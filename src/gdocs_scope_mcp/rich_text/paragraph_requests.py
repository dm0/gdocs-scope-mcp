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
                content_start, content_end, indent, p.continuation,
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
            for start, end, depth, continuation in item['paragraphs']:
                final_start = start - removed
                removed += depth
                if not continuation:
                    continue
                span = {'startIndex': final_start, 'endIndex': end - removed}
                requests.append({'deleteParagraphBullets': {'range': span}})
                indent = {'magnitude': 36 * (depth + 1), 'unit': 'PT'}
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
    insertions = []
    for request in requests:
        kind, payload = next(iter(request.items()))
        if kind == 'insertText':
            insertions.append(payload)
        elif kind in {'insertInlineImage', 'insertPerson', 'insertRichLink',
                      'insertDate', 'insertDropdown'}:
            insertions.append({'location': payload['location'],
                               'text': '\ufffc'})
    if not insertions:
        return ''
    start = insertions[0]['location']['index']
    buffer = ''.join(item['text'] for item in insertions).encode('utf-16-le')
    for request in requests:
        if 'createParagraphBullets' not in request:
            continue
        span = request['createParagraphBullets']['range']
        left = (span['startIndex'] - start) * 2
        right = (span['endIndex'] - start) * 2
        text = buffer[left:right].decode('utf-16-le')
        text = re.sub(r'(?m)^\t+', '', text)
        buffer = buffer[:left] + text.encode('utf-16-le') + buffer[right:]
    return buffer.decode('utf-16-le')
