"""Convert markdown (with HTML) into google requests"""

import re
from collections.abc import Iterable
from functools import lru_cache

import mistune
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString, PageElement
from rich.syntax import Syntax

# isort: split
from .models import (
    EditFailedResponse,
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentLink,
    GoogleDocumentNamedStyleType,
    GoogleDocumentParagraph,
    GoogleDocumentParagraphStyle,
    GoogleDocumentTextRun,
    GoogleDocumentTextStyle,
)
from .tool_errors import ToolFailureError


class InsertionParagraph(GoogleDocumentParagraph):
    """Keep insertion-only list metadata separate from API list identities."""

    bullet_preset: str | None = None
    nesting_level: int = 0
    list_key: int | None = None


class DocsHTMLRenderer(mistune.HTMLRenderer):
    """Keep Markdown soft wraps from becoming Google Docs paragraph breaks."""

    def softbreak(self) -> str:
        """Render a soft-wrapped source line as a space, as HTML would."""
        return ' '


def _unsupported_list(description: str) -> None:
    """Reject list forms that cannot yet preserve their structure."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use nonempty, single-paragraph list items with '
        'the same list kind at every nesting level, or use rich=False.',
    ))


def _convert_list(
    element: Tag, start: int, *, level: int = 0, list_key: int | None = None,
) -> list[InsertionParagraph]:
    """Flatten a homogeneous list tree into item paragraphs in source order."""
    if list_key is None:
        list_key = start
    if element.name == 'ol' and str(element.get('start', '1')) != '1':
        _unsupported_list('Custom ordered-list starting numbers are '
                          'unsupported.')
    result = []
    for item in element.find_all('li', recursive=False):
        paragraph = InsertionParagraph(
            start_index=start, elements=[], list_key=list_key,
            nesting_level=level,
            bullet_preset=(
                'NUMBERED_DECIMAL_ALPHA_ROMAN' if element.name == 'ol'
                else 'BULLET_DISC_CIRCLE_SQUARE'
            ),
            paragraph_style=GoogleDocumentParagraphStyle(
                named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
            ),
        )
        blocks = []
        nested = []
        for child in item.children:
            if isinstance(child, Tag) and child.name in {'ul', 'ol'}:
                if child.name != element.name:
                    _unsupported_list('Mixed ordered/unordered nesting is '
                                      'not supported in a single list.')
                nested.append(child)
            else:
                if nested and str(child).strip():
                    _unsupported_list('Text after a nested list is '
                                      'unsupported.')
                blocks.append(child)
        extra = _convert_page_elements(blocks, paragraph)
        nonempty = [p for p in [paragraph, *extra] if len(p)]
        if len(nonempty) != 1:
            _unsupported_list('Each list item must contain one nonempty '
                              'paragraph.')
        paragraph = nonempty[0]
        paragraph.list_key = list_key
        paragraph.nesting_level = level
        paragraph.bullet_preset = (
            'NUMBERED_DECIMAL_ALPHA_ROMAN' if element.name == 'ol'
            else 'BULLET_DISC_CIRCLE_SQUARE'
        )
        result.append(paragraph)
        start = paragraph.start_index + len(paragraph)
        for child in nested:
            children = _convert_list(
                child, start, level=level + 1, list_key=list_key,
            )
            result.extend(children)
            if children:
                start = children[-1].start_index + len(children[-1])
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
) -> list[InsertionParagraph]:
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


def html_to_gpars(html: str, start: int = 0) -> list[InsertionParagraph]:
    """Convert HTML nodes into indexed Google Docs paragraphs."""
    bs = BeautifulSoup(html, 'html.parser')
    current_index = start
    paragraphs: list[InsertionParagraph] = [
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
    paragraphs: list[InsertionParagraph], *, newline_before: bool = True
):
    """Build requests with breaks before or after inserted paragraphs."""
    requests = []
    list_ranges = []
    paragraph_ranges = []
    offset = 0
    for p in paragraphs:
        if not len(p):
            continue
        text_style_requests = []
        insert_index = p.start_index + offset
        text = '\n' if newline_before else ''
        if newline_before:
            offset += 1
        content_start = p.start_index + offset
        indent = p.nesting_level if p.bullet_preset else 0
        text += '\t' * indent
        offset += indent
        for element in p.elements:
            if isinstance(element, GoogleDocumentTextRun):
                text += element.content
                style = element.text_style.model_dump(
                    mode='json',
                    by_alias=True,
                    exclude_defaults=True,
                    exclude_unset=True,
                )
                if not len(style):
                    continue
                text_style_requests.append(
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
        requests.append(
            {'insertText': {'location': {'index': insert_index}, 'text': text}}
        )
        style = p.paragraph_style.model_dump(
            mode='json',
            by_alias=True,
            exclude_defaults=True,
            exclude_unset=True,
        )
        requests.append(
            {
                'updateParagraphStyle': {
                    'range': {
                        'startIndex': p.start_index + offset,
                        'endIndex': p.end_index + offset,
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
                })
        if not newline_before:
            offset += 1
    if list_ranges:
        requests.append({'deleteParagraphBullets': {'range': {
            'startIndex': paragraph_ranges[0][0],
            'endIndex': paragraph_ranges[-1][1],
        }}})
        requests.extend({'createParagraphBullets': {
            'range': {'startIndex': item['start'], 'endIndex': item['end']},
            'bulletPreset': item['preset'],
        }} for item in reversed(list_ranges))
    return requests


def inserted_text_from_requests(requests: list[dict]) -> str:
    """Return inserted text after list operations remove nesting tabs."""
    insertions = [r['insertText'] for r in requests if 'insertText' in r]
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
):
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
