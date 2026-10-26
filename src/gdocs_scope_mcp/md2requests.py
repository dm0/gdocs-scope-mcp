"""Convert markdown (with HTML) into google requests"""

import re
from collections.abc import Iterable
from functools import lru_cache
from html import escape
from typing import Literal
from urllib.parse import urlsplit

import mistune
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PageElement
from pydantic import BaseModel, ValidationError, field_validator
from rich.syntax import Syntax

# isort: split
from .code_highlighting import code_shading, code_spans
from .entities import chip_input, insertion_request
from .models import (
    EditFailedResponse,
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentColor,
    GoogleDocumentLink,
    GoogleDocumentNamedStyleType,
    GoogleDocumentOptionalColor,
    GoogleDocumentParagraph,
    GoogleDocumentParagraphStyle,
    GoogleDocumentRgbColor,
    GoogleDocumentTextRun,
    GoogleDocumentTextStyle,
    GoogleDocumentWeightedFontFamily,
)
from .settings import get_code_settings
from .table_insertion import (
    InsertionTable,
    TableInsertionPlan,
    convert_table,
    unsupported_table,
)
from .text_indices import utf16_length
from .tool_errors import ToolFailureError

IMAGE_URI_MAX_BYTES = 2048


class InsertionCodeRun(GoogleDocumentTextRun):
    """Preserve literal block whitespace, including trailing blank lines."""

    @field_validator('content', mode='before')
    @classmethod
    def remove_trailing_newline(cls, value: str) -> str:
        """Keep code newlines; the converter removes one block terminator."""
        return value


class InsertionImage(BaseModel):
    """Describe an image to insert, without inventing a native object ID."""

    type: Literal['image'] = 'image'
    start_index: int
    end_index: int
    uri: str
    object_size: dict

    def __len__(self) -> int:
        """Reserve one UTF-16 index for the native inline object."""
        return 1

    def to_markdown(self, _doc) -> str:
        """Keep the paragraph rendering interface for converter diagnostics."""
        return f'![](<{self.uri}>)'

    def to_text(self, _doc) -> str:
        """Represent the object slot without inventing visible image text."""
        return '\ufffc'


class InsertionChip(BaseModel):
    """Reserve a native entity slot separately from its displayed label."""

    type: Literal['chip'] = 'chip'
    start_index: int
    end_index: int
    request_kind: str
    payload: dict

    def __len__(self) -> int:
        """Reserve one UTF-16 unit for the native smart element."""
        return 1

    def to_markdown(self, _doc) -> str:
        """Keep insertion previews independent of Google-resolved labels."""
        return '\ufffc'

    def to_text(self, _doc) -> str:
        """Represent the native slot without guessing its displayed text."""
        return '\ufffc'


def _image_failure(description: str) -> None:
    """Refuse unsupported images before submitting any document changes."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use an absolute public HTTP(S) PNG, JPEG or GIF URL '
        '(at most 2 kB). HTML dimensions must be positive pixel numbers in '
        'width/height attributes; omit CSS/srcset, or use rich=False.',
    ))


def _convert_image(element: Tag, start: int) -> InsertionImage:
    """Validate an image and convert pixel dimensions to points."""
    uri = str(element.get('src', ''))
    try:
        parsed = urlsplit(uri)
        valid = (
            parsed.scheme.lower() in {'http', 'https'} and parsed.hostname
            and not parsed.username and not parsed.password
            and len(uri.encode('utf-8')) <= IMAGE_URI_MAX_BYTES
            and not re.search(r'[\s\x00-\x1f\x7f]', uri)
        )
    except ValueError:
        valid = False
    if not valid:
        _image_failure('Image src must be an absolute HTTP(S) URL of at '
                       'most 2 kB, without whitespace or credentials.')
    if any(element.get(key) for key in ('style', 'srcset', 'sizes')):
        _image_failure('CSS image styling and responsive image sources are '
                       'unsupported.')
    size = {}
    for dimension in ('width', 'height'):
        if dimension not in element.attrs:
            continue
        value = str(element[dimension]).strip()
        if not re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value):
            _image_failure('Image dimensions must be positive pixel numbers.')
        pixels = float(value.removesuffix('px'))
        if not 0 < pixels < float('inf'):
            _image_failure('Image dimensions must be finite and positive.')
        size[dimension] = {'magnitude': pixels * 0.75, 'unit': 'PT'}
    return InsertionImage(
        start_index=start, end_index=start + 1, uri=uri, object_size=size,
    )


class InsertionParagraph(GoogleDocumentParagraph):
    """Keep insertion-only list metadata separate from API list identities."""

    elements: list[GoogleDocumentTextRun | InsertionImage | InsertionChip]
    bullet_preset: str | None = None
    nesting_level: int = 0
    list_key: int | None = None
    item_key: int | None = None
    continuation: bool = False
    loose_list: bool = False


class DocsHTMLRenderer(mistune.HTMLRenderer):
    """Keep Markdown soft wraps from becoming Google Docs paragraph breaks."""

    def softbreak(self) -> str:
        """Render a soft-wrapped source line as a space, as HTML would."""
        return ' '

    def image(self, text: str, url: str, title: str | None = None) -> str:
        """Preserve file sources for the opt-in upload stage to validate."""
        if url.lower().startswith('file:'):
            # Retain Mistune's alt/title escaping while allowing only this
            # image source through. Links and other protocols stay unchanged.
            placeholder = 'https://gdocs-scope-mcp.invalid/local'
            rendered = super().image(text, placeholder, title)
            return rendered.replace(
                f'src="{placeholder}"', f'src="{escape(url, quote=True)}"', 1,
            )
        return super().image(text, url, title)


def _unsupported_list(description: str) -> None:
    """Reject list forms that cannot yet preserve their structure."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use nonempty items containing ordinary paragraphs '
        'and homogeneous nested lists, with '
        'the same list kind at every nesting level, or use rich=False.',
    ))


def _convert_list(
    element: Tag, start: int, *, level: int = 0, list_key: int | None = None,
) -> list[InsertionParagraph]:
    """Preserve logical item membership and paragraph roles in source order."""
    if list_key is None:
        list_key = start
    if element.name == 'ol' and str(element.get('start', '1')) != '1':
        _unsupported_list('Custom ordered-list starting numbers are '
                          'unsupported.')
    result = []
    for item in element.find_all('li', recursive=False):
        if item.find('table') is not None:
            unsupported_table('Tables inside lists are unsupported.')
        if item.find('pre') is not None:
            _unsupported_list('Code blocks inside list items are unsupported.')
        item_key = start
        item_paragraphs = 0
        blocks = []

        def flush(blocks=blocks, item_key=item_key, item=item):
            """Convert a paragraph while preserving its logical item role."""
            nonlocal start, item_paragraphs
            paragraph = InsertionParagraph(
                start_index=start, elements=[],
                paragraph_style=GoogleDocumentParagraphStyle(
                    named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                ),
            )
            extra = _convert_page_elements(blocks, paragraph)
            for part in [paragraph, *extra]:
                if not len(part):
                    continue
                part.list_key = list_key
                part.item_key = item_key
                part.nesting_level = level
                part.continuation = item_paragraphs > 0
                part.loose_list = bool(element.find('p', recursive=False)
                                       or item.find('p', recursive=False))
                part.bullet_preset = (
                    'NUMBERED_DECIMAL_ALPHA_ROMAN' if element.name == 'ol'
                    else 'BULLET_DISC_CIRCLE_SQUARE'
                )
                result.append(part)
                start = part.start_index + len(part)
                item_paragraphs += 1
            blocks.clear()

        for child in item.children:
            if isinstance(child, Tag) and child.name in {'ul', 'ol'}:
                flush()
                if not item_paragraphs:
                    _unsupported_list('List items must start with a nonempty '
                                      'ordinary paragraph.')
                if child.name != element.name:
                    _unsupported_list('Mixed ordered/unordered nesting is '
                                      'not supported in a single list.')
                children = _convert_list(
                    child, start, level=level + 1, list_key=list_key,
                )
                result.extend(children)
                if children:
                    start = children[-1].start_index + len(children[-1])
            elif isinstance(child, Tag) and child.name == 'p':
                flush()
                blocks.append(child)
                flush()
            else:
                if isinstance(child, Tag) and (
                    child.name in {'blockquote', 'div', 'hr', 'input'}
                    or re.fullmatch(r'h\d+', child.name)
                ):
                    _unsupported_list('Only ordinary paragraphs and nested '
                                      'lists are supported inside items.')
                blocks.append(child)
        flush()
        if not item_paragraphs:
            _unsupported_list('List items must contain a nonempty paragraph.')
    return result


@lru_cache
def _md_instance() -> mistune.Markdown:
    md = mistune.create_markdown(
        renderer=DocsHTMLRenderer(escape=False),
        plugins=['strikethrough', 'table', 'url', 'superscript', 'subscript']
    )

    def parse_ext_h(_block, m, state):
        heading = m.group('atx')
        contents = m.group('contents')
        state.append_token(
            {
                'type': 'heading',
                'text': contents,
                'attrs': {'level': len(heading)},
            }
        )
        return m.end() + 1

    md.block.register(
        'extended_headings',
        r'^ {0,3}(?P<atx>#{7,10})\s+(?P<contents>.+)$',
        parse_ext_h,
    )

    return md


def markdown_to_html(markdown: str) -> str:
    """Render the supported Markdown syntax as HTML."""
    html = _md_instance()(markdown)
    assert isinstance(html, str), f'Expected a string, got {type(html)}'
    return html


def _collect_styles(
    element: PageElement, stop: PageElement
) -> GoogleDocumentTextStyle:
    style = GoogleDocumentTextStyle()
    parent = element.parent
    while parent and parent != stop:
        if parent.name in ['b', 'strong']:
            style.bold = True
        if parent.name in ['i', 'em']:
            style.italic = True
        if parent.name == 'u':
            style.underline = True
        if parent.name in ['s', 'del']:
            style.strikethrough = True
        if parent.name == 'code':
            settings = get_code_settings()
            style.weighted_font_family = GoogleDocumentWeightedFontFamily(
                font_family=settings.code_font_family,
            )
            color = settings.inline_code_color.removeprefix('#')
            style.foreground_color = GoogleDocumentOptionalColor(
                color=GoogleDocumentColor(rgb_color=GoogleDocumentRgbColor(
                    red=int(color[:2], 16) / 255,
                    green=int(color[2:4], 16) / 255,
                    blue=int(color[4:], 16) / 255,
                )),
            )
        if parent.name == 'a' and parent.get('href'):
            style.link = GoogleDocumentLink(url=parent['href'])
        if parent.name == 'sup':
            style.baseline_offset = GoogleDocumentBaselineOffset.SUPERSCRIPT
        if parent.name == 'sub':
            style.baseline_offset = GoogleDocumentBaselineOffset.SUBSCRIPT
        parent = parent.parent
    return style


def _convert_page_elements(
    elements: Iterable[PageElement], paragraph: InsertionParagraph
) -> list[InsertionParagraph | InsertionTable]:
    added = []
    last = paragraph
    for element in elements:
        if isinstance(element, NavigableString):
            content = str(element)
            start_index = last.start_index + len(last)
            text_run = GoogleDocumentTextRun(
                content=content,
                start_index=start_index,
                text_style=_collect_styles(element, element),
            )
            if not len(text_run):
                continue
            end_index = start_index + len(text_run)
            text_run.end_index = end_index
            last.elements.append(text_run)
            last.end_index = end_index
            continue
        if isinstance(element, Tag):
            if element.has_attr('data-mcp-entity'):
                try:
                    entity = chip_input(element.attrs)
                except (ValidationError, ValueError, KeyError):
                    raise ToolFailureError(EditFailedResponse(
                        code='INVALID_ARGUMENT',
                        description='Invalid smart-chip HTML attributes.',
                        suggested_action='Use the data-mcp-entity and '
                        'identity properties emitted by docs_read; labels '
                        'alone cannot define a native chip.',
                    )) from None
                if element.find(attrs={'data-mcp-entity': True}):
                    raise ToolFailureError(EditFailedResponse(
                        code='INVALID_ARGUMENT',
                        description='Nested smart-chip HTML is unsupported.',
                        suggested_action='Use separate inline smart chips.',
                    ))
                kind, payload = insertion_request(entity)
                start = last.start_index + len(last)
                last.elements.append(InsertionChip(
                    start_index=start, end_index=start + 1,
                    request_kind=kind, payload=payload,
                ))
                last.end_index = start + 1
                continue
            if element.name == 'table':
                start = last.start_index + len(last)
                added.append(convert_table(element, start))
                last = InsertionParagraph(
                    start_index=start, end_index=start, elements=[],
                    paragraph_style=GoogleDocumentParagraphStyle(),
                )
                added.append(last)
                continue
            if element.name == 'pre':
                # Mistune adds one terminal newline to a fenced block. The
                # surrounding paragraph break represents that terminator;
                # all other whitespace must survive unchanged.
                content = element.get_text().removesuffix('\n')
                start = last.start_index + len(last)
                code = element.find('code')
                classes = code.get('class', []) if code else []
                language = next((name.removeprefix('language-')
                                 for name in classes
                                 if name.startswith('language-')), None)
                runs = []
                end = start
                for value, style in code_spans(content, language):
                    run = InsertionCodeRun(
                        start_index=end, end_index=end + utf16_length(value),
                        content=value, text_style=style,
                    )
                    runs.append(run)
                    end = run.end_index
                last = InsertionParagraph(
                    start_index=start, end_index=end, elements=runs,
                    paragraph_style=GoogleDocumentParagraphStyle(
                        named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                        line_spacing=(
                            get_code_settings().code_block_line_spacing * 100
                        ),
                        shading=code_shading(run.text_style for run in runs),
                    ),
                )
                added.append(last)
                continue
            if element.name == 'img':
                start = last.start_index + len(last)
                last.elements.append(_convert_image(element, start))
                last.end_index = start + 1
                continue
            if element.name == 'picture':
                _image_failure('HTML picture/source selection is unsupported; '
                               'use a single img with src.')
            if element.name in {'ul', 'ol'}:
                added.extend(_convert_list(
                    element, last.start_index + len(last),
                ))
                last = added[-1] if added else paragraph
                continue
            if element.name == 'p':
                align = GoogleDocumentAlignment.ALIGNMENT_UNSPECIFIED

                if (
                    element.has_attr('style')
                    and 'text-align' in element['style']
                ):
                    if 'center' in element['style']:
                        align = GoogleDocumentAlignment.CENTER
                    elif 'right' in element['style']:
                        align = GoogleDocumentAlignment.END
                    elif 'justify' in element['style']:
                        align = GoogleDocumentAlignment.JUSTIFIED

                added.append(
                    InsertionParagraph(
                        start_index=last.start_index + len(last),
                        elements=[],
                        paragraph_style=GoogleDocumentParagraphStyle(
                            named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                            alignment=align,
                        ),
                    )
                )
            elif match := re.match(r'h(?P<level>\d+)', element.name):
                # FIXME: Implement
                added.append(
                    InsertionParagraph(
                        start_index=last.start_index + len(last),
                        elements=[],
                        paragraph_style=GoogleDocumentParagraphStyle(
                            named_style_type=GoogleDocumentNamedStyleType.from_level(
                                int(match['level'])
                            )
                        ),
                    )
                )
            # FIXME: Implement other supported elements
            last = added[-1] if added else paragraph
            added.extend(_convert_page_elements(element.children, last))
            continue
        # Unsupported element kind
        # TODO: Log this
        print(f'Skipped: {element}')
        continue
    return added


def html_to_gpars(
    html: str, start: int = 0,
) -> list[InsertionParagraph | InsertionTable]:
    """Convert HTML into indexed paragraphs and structural table plans."""
    bs = BeautifulSoup(html, 'html.parser')
    current_index = start
    paragraphs: list[InsertionParagraph | InsertionTable] = [
        InsertionParagraph(
            start_index=current_index,
            elements=[],
            paragraph_style=GoogleDocumentParagraphStyle(
                named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT
            ),
        )
    ]

    paragraphs.extend(_convert_page_elements(bs.contents, paragraphs[-1]))
    return paragraphs


def gpars_to_requests(
    paragraphs: list[InsertionParagraph | InsertionTable], *,
    newline_before: bool = True,
) -> list[dict] | TableInsertionPlan:
    """Build requests with breaks before or after inserted paragraphs."""
    if any(isinstance(p, InsertionTable) for p in paragraphs):
        return TableInsertionPlan(
            blocks=paragraphs, start=paragraphs[0].start_index,
            newline_before=newline_before,
        )
    requests = []
    list_ranges = []
    paragraph_ranges = []
    font_style_requests = []
    code_paragraph_style_requests = []
    offset = 0
    for p in paragraphs:
        if not len(p):
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
    return requests


def inserted_text_from_requests(
    requests: list[dict] | TableInsertionPlan,
) -> str:
    """Render final text, using U+FFFC for each native image or smart chip."""
    if isinstance(requests, TableInsertionPlan):
        return requests.text()
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


def markdown_to_requests(
    markdown: str, start: int = 0, *, newline_before: bool = True
) -> list[dict] | TableInsertionPlan:
    """Convert Markdown with breaks suited to the insertion side."""
    html = markdown_to_html(markdown)
    gpars = html_to_gpars(html, start)
    return gpars_to_requests(gpars, newline_before=newline_before)


if __name__ == '__main__':
    import argparse

    import rich

    console = rich.get_console()

    parser = argparse.ArgumentParser()
    parser.add_argument('md')

    args = parser.parse_args()

    console.print('HTML:')
    html = markdown_to_html(args.md)
    console.print(Syntax(html, 'html'))

    console.print('PARAGRAPHS:')
    gpars = html_to_gpars(html)
    for r in gpars:
        console.print(
            r.model_dump(
                mode='json',
                exclude_defaults=True,
                exclude_unset=True,
                by_alias=True,
            )
        )

    console.print('MD:')
    md = ''.join([r.to_markdown(None) for r in gpars])
    console.print(Syntax(md, 'md'))

    console.print('REQUESTS:')
    requests = gpars_to_requests(gpars)
    for r in requests:
        console.print(r)
