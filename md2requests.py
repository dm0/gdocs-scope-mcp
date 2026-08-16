"""Convert markdown (with HTML) into google requests"""
from typing import Iterable
import re
from bs4.element import PageElement, NavigableString

from functools import lru_cache

import mistune
from bs4 import BeautifulSoup, Tag

# isort: split
from models import GoogleDocumentParagraph, GoogleDocumentParagraphStyle, GoogleDocumentNamedStyleType, GoogleDocumentTextStyle, GoogleDocumentBaselineOffset, GoogleDocumentTextRun, GoogleDocumentAlignment


@lru_cache
def _md_instance() -> mistune.Markdown:
    md = mistune.create_markdown(plugins=[
        'strikethrough',
        'table',
        'url',
        'superscript',
        'subscript'
    ])

    def parse_ext_h(block, m, state):
        heading = m.group('atx')
        contents = m.group('contents')
        state.append_token({
            'type': 'heading',
            'text': contents,
            'attrs': {'level': len(heading)}
        })
        return m.end() + 1

    md.block.register(
        'extended_headings',
        r'^ {0,3}(?P<atx>#{7,10})\s+(?P<contents>.+)$',
        parse_ext_h
    )

    return md


def markdown_to_html(markdown: str) -> str:
    html = _md_instance()(markdown)
    assert isinstance(html, str), f'Expected a string, got {type(html)}'
    return html


def _collect_styles(element: PageElement, stop: PageElement) -> GoogleDocumentTextStyle:
    style = GoogleDocumentTextStyle()
    parent = element.parent
    while parent and parent != stop:
        if parent.name in ['b', 'strong']:
            style.bold = True
        if parent.name in ['i', 'em']:
            style.italic = True
        if parent.name == 'u':
            style.underline = True
        if parent.name == 's':
            style.strikethrough = True
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
            paragraph.elements.append(GoogleDocumentTextRun(
                content=content,
                start_index=last.start_index + len(last),
                text_style=_collect_styles(element, element)
            ))
            continue
        if isinstance(element, Tag):
            if element.name == 'p':
                align = GoogleDocumentAlignment.START

                if element.has_attr('style') and 'text-align' in element['style']:
                    if 'center' in element['style']:
                        align = GoogleDocumentAlignment.CENTER
                    elif 'right' in element['style']:
                        align = GoogleDocumentAlignment.END
                    elif 'justify' in element['style']:
                        align = GoogleDocumentAlignment.JUSTIFIED

                added.append(GoogleDocumentParagraph(
                    start_index=last.start_index + len(last),
                    elements=[],
                    paragraph_style=GoogleDocumentParagraphStyle(
                        named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT,
                        alignment=align
                    )
                ))
            elif match := re.match(r'h(?P<level>\d+)', element.name):
                # FIXME: Implement
                added.append(GoogleDocumentParagraph(
                    start_index=last.start_index + len(last),
                    elements=[],
                    paragraph_style=GoogleDocumentParagraphStyle(
                        named_style_type=GoogleDocumentNamedStyleType.from_level(int(match['level']))
                    )
                ))
            # FIXME: Implement other supported elements
            last = added[-1] if added else paragraph
            added.extend(_convert_page_elements(
                element.children,
                last
            ))
            continue
        # Unsupported element kind
        # TODO: Log this
        print(f'Skipped: {element}')
        continue
    return added


def html_to_requests(html: str, start: int = 1):
    bs = BeautifulSoup(html, 'html.parser')
    requests = []
    current_index = start
    block_start = current_index
    paragraphs: list[GoogleDocumentParagraph] = [
        GoogleDocumentParagraph(
            start_index=current_index,
            elements=[],
            paragraph_style=GoogleDocumentParagraphStyle(
                named_style_type=GoogleDocumentNamedStyleType.NORMAL_TEXT)
        )
    ]

    paragraphs.extend(_convert_page_elements(bs.contents, paragraphs[-1]))
    return [p for p in paragraphs if len(p)]

    # Iterate through top-level block elements
    for element in bs.contents:
        if element.name in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            block_start = current_index

            # 1. Process all inline elements inside this block to extract raw text
            block_text = ""
            inline_runs = [] # Keep track of style locations relative to block_text

            for child in element.descendants:
                if isinstance(child, str):
                    # Track where this text run will land in absolute coordinates
                    run_start = current_index + len(block_text)
                    block_text += child
                    run_end = current_index + len(block_text)

                    # Inspect parents up to the block element to collect inline styles
                    styles = {}
                    parent = child.parent
                    while parent and parent != element:
                        if parent.name in ['b', 'strong']: styles['bold'] = True
                        if parent.name in ['i', 'em']: styles['italic'] = True
                        if parent.name == 'u': styles['underline'] = True
                        if parent.name == 's': styles['strikethrough'] = True
                        if parent.name == 'sup': styles['baselineOffset'] = 'SUPERSCRIPT'
                        if parent.name == 'sub': styles['baselineOffset'] = 'SUBSCRIPT'
                        parent = parent.parent

                    if styles:
                        inline_runs.append({'start': run_start, 'end': run_end, 'styles': styles})

            # Google Docs blocks must end with a newline character
            block_text += "\n"

            # 2. Generate Text Insertion Request
            requests.append({
                "insertText": {
                    "location": {"index": block_start},
                    "text": block_text
                }
            })

            # 3. Generate TextStyle Requests for the inline formatting
            for run in inline_runs:
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": run['start'], "endIndex": run['end']},
                        "textStyle": run['styles'],
                        "fields": ",".join(run['styles'].keys())
                    }
                })

            # 4. Generate Paragraph Style Requests (Alignment & Heading Level)
            p_style = {}
            if element.name.startswith('h'):
                p_style['namedStyleType'] = f"HEADING_{element.name[1]}"

            if element.has_attr('style') and 'text-align' in element['style']:
                if 'center' in element['style']: p_style['alignment'] = 'CENTER'
                elif 'right' in element['style']: p_style['alignment'] = 'END'
                elif 'justify' in element['style']: p_style['alignment'] = 'JUSTIFIED'

            if p_style:
                requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": block_start, "endIndex": block_start + len(block_text)},
                        "paragraphStyle": p_style,
                        "fields": ",".join(p_style.keys())
                    }
                })

            # Update global index tracker
            current_index += len(block_text)

        elif element.name == 'table':
            # Fallback to your Table processing logic here
            # (Requires the separate fetch-and-reverse-fill step discussed previously)
            pass

    return requests

def markdown_to_requests(markdown: str, start: int = 1):
    html = markdown_to_html(markdown)
    return html_to_requests(html, start)


if __name__ == '__main__':
    import argparse
    import rich

    console = rich.get_console()

    parser = argparse.ArgumentParser()
    parser.add_argument('md')

    args = parser.parse_args()

    console.print('HTML:')
    html = markdown_to_html(args.md)
    console.print(html)

    console.print('REQUESTS:')
    requests = html_to_requests(html)
    console.print(requests)

    console.print('MD:')
    for r in requests:
        console.print(r.to_markdown(None))
