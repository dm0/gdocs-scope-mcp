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
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentLink,
    GoogleDocumentNamedStyleType,
    GoogleDocumentParagraph,
    GoogleDocumentParagraphStyle,
    GoogleDocumentTextRun,
    GoogleDocumentTextStyle,
)


@lru_cache
def _md_instance() -> mistune.Markdown:
    md = mistune.create_markdown(
        escape=False,
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
    elements: Iterable[PageElement], paragraph: GoogleDocumentParagraph
) -> list[GoogleDocumentParagraph]:
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
                    GoogleDocumentParagraph(
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
                    GoogleDocumentParagraph(
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


def html_to_gpars(html: str, start: int = 0) -> list[GoogleDocumentParagraph]:
    """Convert HTML nodes into indexed Google Docs paragraphs."""
    bs = BeautifulSoup(html, 'html.parser')
    current_index = start
    paragraphs: list[GoogleDocumentParagraph] = [
        GoogleDocumentParagraph(
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
    paragraphs: list[GoogleDocumentParagraph], *, newline_before: bool = True
):
    """Build requests with breaks before or after inserted paragraphs."""
    requests = []
    offset = 0
    for p in paragraphs:
        if not len(p):
            continue
        text_style_requests = []
        insert_index = p.start_index + offset
        text = '\n' if newline_before else ''
        if newline_before:
            offset += 1
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
        if not newline_before:
            offset += 1
    return requests


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
