"""Internal rich_text.paragraph_requests responsibilities."""

import re

from gdocs_scope_mcp.code_reading import block_marker
from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.native_models import (
    GoogleDocumentTextRun,
)
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.rich_text.models import (
    InsertionChip,
    InsertionCodeRun,
    InsertionImage,
    InsertionParagraph,
    InsertionTable,
)
from gdocs_scope_mcp.settings import get_code_settings
from gdocs_scope_mcp.text_indices import utf16_length


def _mixed_list_requests(paragraphs: list[tuple]) -> list[dict]:
    """Replace mixed subtrees without renumbering their enclosing lists."""
    components = {}
    for start, end, paragraph in paragraphs:
        path = paragraph.list_component_path
        for length in range(1, len(path) + 1):
            components.setdefault(path[:length], []).append(
                (start, end, paragraph),
            )
    requests = []
    # Ancestors must be formatted before descendants. Each replacement has
    # zero net text length, so all subsequent component coordinates stay valid.
    for rows in components.values():
        left, right = rows[0][0], rows[-1][1]
        requests.append({'deleteParagraphBullets': {'range': {
            'startIndex': left, 'endIndex': right,
        }}})
        tabs = 0
        for start, _, paragraph in reversed(rows):
            depth = paragraph.nesting_level
            tabs += depth
            requests.append({'insertText': {
                'location': {'index': start}, 'text': '\t' * depth,
            }})
        # Google normalizes a newly created list's first nesting level to 0.
        # A temporary root preserves absolute native depths after its removal.
        # Keep all requests, including removal, in the same atomic batch.
        root = 'ROOT\n'
        requests.append({'insertText': {
            'location': {'index': left}, 'text': root,
        }})
        span = {'startIndex': left, 'endIndex': right + tabs + len(root)}
        zero = {'magnitude': 0, 'unit': 'PT'}
        requests.append({'updateParagraphStyle': {
            'range': span,
            'paragraphStyle': {'indentStart': zero, 'indentFirstLine': zero,
                               'indentEnd': zero},
            'fields': 'indentStart,indentFirstLine,indentEnd',
        }})
        requests.append({'createParagraphBullets': {
            'range': span, 'bulletPreset': rows[0][2].bullet_preset,
        }})
        requests.append({'deleteContentRange': {'range': {
            'startIndex': left, 'endIndex': left + len(root),
        }}})
    return requests


def compile_paragraphs(
    paragraphs: list[InsertionParagraph | InsertionTable], *,
    newline_before: bool = True,
) -> list[dict]:
    """Build requests with breaks before or after inserted paragraphs."""
    requests = []
    list_ranges = []
    paragraph_ranges = []
    font_style_requests = []
    code_paragraph_style_requests = []
    code_markers = []
    removed_tabs = []
    offset = 0
    for p in paragraphs:
        if not len(p) and not p.code_block:
            continue
        text_style_requests = []
        images = []
        insert_index = p.start_index + offset
        text = '\n' if newline_before else ''
        if newline_before:
            offset += 1
        content_start = p.start_index + offset
        indent = p.nesting_level if p.bullet_preset else 0
        text += '\t' * indent
        offset += indent
        for element in p.elements:
            if isinstance(element, (InsertionImage, InsertionChip)):
                images.append((utf16_length(text), element))
                # A planning placeholder only; never send it as insertText.
                text += '\ufffc'
                continue
            if isinstance(element, GoogleDocumentTextRun):
                text += element.content
                style = element.text_style.model_dump(
                    mode='json',
                    by_alias=True,
                    exclude_defaults=True,
                    exclude_unset=True,
                )
                if (isinstance(element, InsertionCodeRun)
                        and element.text_style.foreground_color is not None):
                    # Theme styles must also clear inherited emphasis when
                    # the lexer marks a token as plain text.
                    for flag in ('bold', 'italic', 'underline'):
                        style[flag] = getattr(element.text_style, flag)
                if not len(style):
                    continue
                target = (font_style_requests if 'weightedFontFamily' in style
                          else text_style_requests)
                target.append(
                    {
                        'updateTextStyle': {
                            'range': {
                                'startIndex': element.start_index + offset,
                                'endIndex': element.end_index + offset,
                            },
                            'textStyle': style,
                            'fields': ','.join(style.keys()),
                        }
                    }
                )
        if not newline_before:
            text += '\n'
        # Insert text and objects in source order. All ranges below include
        # the one index occupied by each image, so styles never drift.
        buffer = text.encode('utf-16-le')
        cursor = 0
        for position, image in images:
            chunk = buffer[cursor * 2:position * 2].decode('utf-16-le')
            if chunk:
                requests.append({'insertText': {
                    'location': {'index': insert_index + cursor},
                    'text': chunk,
                }})
            location = {'index': insert_index + position}
            if isinstance(image, InsertionChip):
                requests.append({image.request_kind: {
                    **image.payload, 'location': location,
                }})
            else:
                image_request = {'location': location, 'uri': image.uri}
                if image.object_size:
                    image_request['objectSize'] = image.object_size
                requests.append({'insertInlineImage': image_request})
            cursor = position + 1
        chunk = buffer[cursor * 2:].decode('utf-16-le')
        if chunk:
            requests.append({'insertText': {
                'location': {'index': insert_index + cursor}, 'text': chunk,
            }})
        style = p.paragraph_style.model_dump(
            mode='json',
            by_alias=True,
            exclude_defaults=True,
            exclude_unset=True,
        )
        if p.bullet_preset:
            style.update({
                'spaceAbove': {'magnitude': 6 if p.loose_list else 0,
                               'unit': 'PT'},
                'spaceBelow': {'magnitude': 0, 'unit': 'PT'},
            })
        paragraph_requests = (code_paragraph_style_requests
                              if p.paragraph_style.line_spacing is not None
                              else requests)
        paragraph_end = p.end_index + offset
        if (p.paragraph_style.line_spacing is not None and p.elements
                and p.elements[-1].content.endswith('\n')):
            # The block terminator belongs to its final empty paragraph.
            # Include it to format trailing blank lines without touching prose.
            paragraph_end += 1
        paragraph_requests.append(
            {
                'updateParagraphStyle': {
                    'range': {
                        'startIndex': p.start_index + offset,
                        'endIndex': paragraph_end,
                    },
                    'paragraphStyle': style,
                    'fields': ','.join(style.keys()),
                }
            }
        )
        requests.extend(text_style_requests)
        content_end = p.end_index + offset
        if p.code_block and get_code_settings().code_block_named_ranges:
            code_markers.append((p.code_language, content_start,
                                 max(content_start + 1, content_end)))
        if indent:
            removed_tabs.extend(range(content_start, content_start + indent))
        paragraph_ranges.append((content_start, content_end))
        if p.bullet_preset:
            if list_ranges and list_ranges[-1]['key'] == p.list_key:
                list_ranges[-1]['end'] = content_end
            else:
                list_ranges.append({
                    'key': p.list_key, 'start': content_start,
                    'end': content_end, 'preset': p.bullet_preset,
                    'paragraphs': [],
                })
            list_ranges[-1]['paragraphs'].append((
                content_start, content_end, p,
            ))
        if not newline_before:
            offset += 1
    # Apply code spacing/fonts after all insertions, so subsequent prose
    # cannot inherit formatting from a code paragraph we just formatted.
    requests.extend(code_paragraph_style_requests)
    requests.extend(font_style_requests)
    if list_ranges:
        requests.append({'deleteParagraphBullets': {'range': {
            'startIndex': paragraph_ranges[0][0],
            'endIndex': paragraph_ranges[-1][1],
        }}})
        for item in reversed(list_ranges):
            requests.append({'createParagraphBullets': {
                'range': {'startIndex': item['start'],
                          'endIndex': item['end']},
                'bulletPreset': item['preset'],
            }})
            removed = 0
            final_paragraphs = []
            for start, end, p in item['paragraphs']:
                final_start = start - removed
                removed += p.nesting_level
                final_paragraphs.append((final_start, end - removed, p))
            requests.extend(_mixed_list_requests(final_paragraphs))
            for start, end, p in final_paragraphs:
                if not p.continuation:
                    continue
                span = {'startIndex': start, 'endIndex': end}
                requests.append({'deleteParagraphBullets': {'range': span}})
                indent = {'magnitude': 36 * (p.nesting_level + 1),
                          'unit': 'PT'}
                requests.append({'updateParagraphStyle': {
                    'range': span,
                    'paragraphStyle': {'indentStart': indent,
                                       'indentFirstLine': indent},
                    'fields': 'indentStart,indentFirstLine',
                }})
    for language, start, end in code_markers:
        final_start = start - sum(p < start for p in removed_tabs)
        final_end = end - sum(p < end for p in removed_tabs)
        try:
            requests.append(block_marker(language, final_start, final_end))
        except ValueError:
            raise ToolFailureError(EditFailedResponse(
                code='INVALID_ARGUMENT',
                description='Code language label exceeds the named-range '
                'metadata limit.',
                suggested_action='Use a shorter language label.',
            )) from None
    return requests


def paragraph_text(
    requests: list[dict],
) -> str:
    """Render final text, using U+FFFC for each native image or smart chip."""
    start = None
    buffer = b''
    for request in requests:
        kind, payload = next(iter(request.items()))
        if kind in {'insertText', 'insertInlineImage', 'insertPerson',
                    'insertRichLink', 'insertDate', 'insertDropdown'}:
            index = payload['location']['index']
            if start is None:
                start = index
            at = (index - start) * 2
            text = payload['text'] if kind == 'insertText' else '\ufffc'
            buffer = buffer[:at] + text.encode('utf-16-le') + buffer[at:]
            continue
        if start is None or kind not in {
            'createParagraphBullets', 'deleteContentRange',
        }:
            continue
        span = payload['range']
        left = (span['startIndex'] - start) * 2
        right = (span['endIndex'] - start) * 2
        if kind == 'deleteContentRange':
            buffer = buffer[:left] + buffer[right:]
            continue
        text = buffer[left:right].decode('utf-16-le')
        text = re.sub(r'(?m)^\t+', '', text)
        buffer = buffer[:left] + text.encode('utf-16-le') + buffer[right:]
    return buffer.decode('utf-16-le')
