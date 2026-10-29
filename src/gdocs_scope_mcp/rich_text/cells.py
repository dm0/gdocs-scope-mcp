"""Internal rich_text.cells responsibilities."""

import re
from copy import deepcopy

from bs4 import NavigableString, Tag

from gdocs_scope_mcp.rich_text.models import InsertionTable, TableCell
from gdocs_scope_mcp.rich_text.paragraph_requests import (
    compile_paragraphs as gpars_to_requests,
    paragraph_text as inserted_text_from_requests,
)
from gdocs_scope_mcp.rich_text.paragraphs import parse_html as html_to_gpars
from gdocs_scope_mcp.rich_text.validation import unsupported_table
from gdocs_scope_mcp.text_indices import utf16_length


def shifted_requests(requests: list[dict], offset: int) -> list[dict]:
    """Translate relative cell requests without changing their styles."""
    result = deepcopy(requests)
    for request in result:
        operation = next(iter(request.values()))
        if 'location' in operation:
            operation['location']['index'] += offset
        if 'range' in operation:
            for key in ('startIndex', 'endIndex'):
                operation['range'][key] += offset
    return result


def convert_table(element: Tag, start: int) -> InsertionTable:
    """Validate simple Markdown/HTML tables and prepare every cell offline."""

    if element.find('table') or element.find(['caption', 'colgroup', 'tfoot']):
        unsupported_table('Nested tables, captions and table column/footer '
                          'groups are unsupported.')
    for node in element.descendants:
        if node.find_parent(['td', 'th']) is not None:
            continue
        if isinstance(node, NavigableString) and not node.strip():
            continue
        if isinstance(node, Tag) and node.name in {
            'thead', 'tbody', 'tr', 'td', 'th',
        }:
            continue
        unsupported_table('Table content must be inside rows and cells.')
    rows = element.find_all('tr')
    if (any(row.parent.name not in {'table', 'thead', 'tbody'} for row in rows)
            or any(group.parent is not element
                   for group in element.find_all(['thead', 'tbody']))
            or any(cell.parent.name != 'tr'
                   for cell in element.find_all(['td', 'th']))):
        unsupported_table('Table rows and cells must be directly nested '
                          'inside their table or row group.')
    cells = []
    for row in rows:
        converted = []
        for cell in row.find_all(['td', 'th'], recursive=False):
            if any(str(cell.get(key, '1')) != '1'
                   for key in ('rowspan', 'colspan')):
                unsupported_table('Merged table cells are unsupported.')
            if cell.find(['p', 'div', 'ul', 'ol', 'pre', 'blockquote', 'hr',
                          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8',
                          'h9', 'h10']):
                unsupported_table('Table cells support inline content only.')
            alignment = cell.get('align')
            style = str(cell.get('style', '')).strip()
            if style:
                match = re.fullmatch(
                    r'text-align\s*:\s*(left|center|right)\s*;?', style,
                )
                if match is None:
                    unsupported_table('Only text-align is supported as a '
                                      'table cell CSS style.')
                alignment = match[1]
            if alignment not in {None, 'left', 'center', 'right'}:
                unsupported_table('Unsupported table cell alignment.')
            # Google Docs represents a soft line break as U+000B. Unlike \n,
            # it stays within the cell's single paragraph and survives the
            # text-run validator's removal of paragraph terminators.
            for line_break in cell.find_all('br'):
                line_break.replace_with(NavigableString('\u000b'))
            paragraphs = html_to_gpars(cell.decode_contents(), 0)
            requests = gpars_to_requests(paragraphs, newline_before=False)
            # The native cell already contains its mandatory final newline.
            insertions = [r['insertText'] for r in requests
                          if 'insertText' in r]
            if insertions:
                insertions[-1]['text'] = (
                    insertions[-1]['text'].removesuffix('\n')
                )
            requests = [r for r in requests
                        if 'insertText' not in r or r['insertText']['text']]
            text = inserted_text_from_requests(requests)
            if '\n' in text or '\r' in text:
                unsupported_table('Table cell text must fit a single '
                                  'paragraph; replace raw line breaks with '
                                  'spaces.')
            span = {'startIndex': 0, 'endIndex': max(1, utf16_length(text))}
            if cell.name == 'th':
                requests.append({'updateTextStyle': {
                    'range': span.copy(), 'textStyle': {'bold': True},
                    'fields': 'bold',
                }})
            if alignment is not None:
                requests.append({'updateParagraphStyle': {
                    'range': span.copy(), 'paragraphStyle': {'alignment': {
                        'left': 'START', 'center': 'CENTER', 'right': 'END',
                    }[alignment]}, 'fields': 'alignment',
                }})
            converted.append(TableCell(requests=requests, text=text))
        cells.append(converted)
    if (not cells or not cells[0]
            or any(len(row) != len(cells[0]) for row in cells)):
        unsupported_table('Tables must be nonempty and rectangular.')
    return InsertionTable(start_index=start, cells=cells)
