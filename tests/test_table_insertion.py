"""Exercise table plans against an independent UTF-16 structural buffer."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.image_uploads import rich_insertion_requests
from gdocs_scope_mcp.md2requests import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.table_insertion import InsertionTable, TableInsertionPlan
from gdocs_scope_mcp.tool_errors import ToolFailureError

MARKDOWN = ('| **Name** | Value |\n| :--- | ---: |\n'
            '| 😀[link](https://example.com) | |\n'
            '| `code` | ~~end~~ |')


class NativeBuffer:
    """Model structural slots independently with variable gaps."""

    def __init__(self, prefix='before😀', suffix='after', *, gap=1):
        self.buffer = (prefix + suffix + '\n').encode('utf-16-le')
        self.start = len(prefix.encode('utf-16-le')) // 2
        self.gap = gap
        self.tables = []
        self.batches = []
        self.styles = []
        self.table_styles = []
        self.revision = 0
        self.service = MagicMock()
        documents = self.service.documents.return_value
        documents.get.return_value.execute.side_effect = self.document
        documents.batchUpdate.side_effect = self.update

    def index(self, marker):
        """Locate a structural marker using its UTF-16 byte position."""
        return self.buffer.index(marker.encode('utf-16-le')) // 2

    def document(self):
        """Expose the native cells at their current buffer positions."""
        content = []
        for table in self.tables:
            rows = []
            for row in table['cells']:
                cells = []
                for opening, closing in row:
                    start = self.index(opening) + len(opening)
                    end = self.index(closing)
                    text = self.buffer[start * 2:end * 2].decode('utf-16-le')
                    cells.append({'content': [{
                        'startIndex': start, 'endIndex': end,
                        'paragraph': {'elements': [{'textRun': {
                            'content': text,
                        }}]},
                    }]})
                rows.append({'tableCells': cells})
            content.append({
                'startIndex': self.index(table['open']),
                'endIndex': self.index(table['close']) + 1,
                'table': {'tableRows': rows},
            })
        return {'body': {'content': content}, 'revisionId': str(self.revision)}

    def update(self, *, body, **kwargs):
        """Apply insertions and verify style bounds at submission time."""
        assert kwargs['documentId'] == 'test'
        assert body['writeControl']['requiredRevisionId'] == str(self.revision)
        self.batches.append(deepcopy(body['requests']))
        for request in body['requests']:
            if 'insertTable' in request:
                assert len(body['requests']) == 1
                operation = request['insertTable']
                seed = 0x2500 + len(self.tables) * 128
                opening, closing = chr(seed), chr(seed + 1)
                table = {'open': opening, 'close': closing, 'cells': []}
                structure = '\n' + opening
                for row_index in range(operation['rows']):
                    structure += chr(seed + 2) * self.gap
                    row = []
                    for column in range(operation['columns']):
                        number = 4 + (row_index * operation['columns']
                                      + column) * 2
                        left = chr(seed + number)
                        right = chr(seed + number + 1)
                        row.append((left * self.gap, right))
                        structure += left * self.gap + '\n' + right
                    table['cells'].append(row)
                structure += closing
                self.tables.append(table)
                self.insert(operation['location']['index'], structure)
            elif 'updateTableCellStyle' in request:
                operation = request['updateTableCellStyle']
                assert any(self.index(table['open'])
                           == operation['tableStartLocation']['index']
                           for table in self.tables)
                self.table_styles.append(deepcopy(operation))
            elif 'insertText' in request or 'insertInlineImage' in request:
                operation = next(iter(request.values()))
                self.insert(operation['location']['index'],
                            operation.get('text', '\ufffc'))
            else:
                operation = next(iter(request.values()))
                span = operation['range']
                assert 0 <= span['startIndex'] < span['endIndex']
                assert span['endIndex'] <= len(self.buffer) // 2
                self.styles.append((request, self.buffer[
                    span['startIndex'] * 2:span['endIndex'] * 2
                ].decode('utf-16-le')))
        self.revision += 1
        response = MagicMock()
        response.execute.return_value = {
            'writeControl': {'requiredRevisionId': str(self.revision)},
        }
        return response

    def insert(self, index, text):
        """Insert at a UTF-16 boundary and reject split surrogate pairs."""
        byte = index * 2
        self.buffer[:byte].decode('utf-16-le')
        self.buffer[byte:].decode('utf-16-le')
        self.buffer = (self.buffer[:byte] + text.encode('utf-16-le')
                       + self.buffer[byte:])


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('gap', [1, 3])
def test_native_positions_styles_and_surrounding_content(newline_before, gap):
    """Use API cell indices, preserving empty cells and neighbouring text."""
    native = NativeBuffer(gap=gap)
    source = f'Intro😀\n\n{MARKDOWN}\n\nOutro'
    plan = markdown_to_requests(source, native.start,
                                newline_before=newline_before)
    plan.execute(native.service, 'test')
    result = native.document()
    table = result['body']['content'][0]['table']
    values = [[cell['content'][0]['paragraph']['elements'][0][
        'textRun']['content'] for cell in row['tableCells']]
        for row in table['tableRows']]
    assert values == [['Name\n', 'Value\n'], ['😀link\n', '\n'],
                      ['code\n', 'end\n']]
    assert native.buffer.startswith('before😀'.encode('utf-16-le'))
    assert native.buffer.endswith('after\n'.encode('utf-16-le'))
    assert any(text == 'link' and 'updateTextStyle' in request
               and request['updateTextStyle']['textStyle'].get('link')
               for request, text in native.styles)
    assert any(text == 'code' and request.get('updateTextStyle', {}).get(
        'textStyle', {}).get('weightedFontFamily')
        for request, text in native.styles)
    assert any(text == 'end' and request.get('updateTextStyle', {}).get(
        'textStyle', {}).get('strikethrough')
        for request, text in native.styles)
    preview = inserted_text_from_requests(plan)
    assert 'Name\nValue\n😀link\n\ncode\nend\n' in preview
    assert 'Intro😀' in preview and 'Outro' in preview


@pytest.mark.parametrize('newline_before', [False, True])
def test_adjacent_tables_empty_cells_and_eof(newline_before):
    """Insert multiple tables and stop before the protected body newline."""
    native = NativeBuffer(suffix='')
    table = '| A | B |\n| --- | --- |\n| | |'
    plan = markdown_to_requests(f'{table}\n\n{table}', native.start,
                                newline_before=newline_before)
    plan.execute(native.service, 'test')
    expected_tables = 2
    assert len(native.tables) == expected_tables
    assert native.buffer.endswith('\n'.encode('utf-16-le'))


@pytest.mark.parametrize('markup', [
    '<table></table>',
    '<table><tr><td>A</td><td>B</td></tr><tr><td>C</td></tr></table>',
    '<table><tr><td colspan="2">A</td></tr></table>',
    '<table><tr><td rowspan="2">A</td></tr></table>',
    '<table><tr><td><table><tr><td>A</td></tr></table></td></tr></table>',
    '<table><tr><td><ul><li>A</li></ul></td></tr></table>',
    '<table><tr><td><pre>code</pre></td></tr></table>',
    '<table><tr><td style="background:red">A</td></tr></table>',
    '<table><tr><td align="justify">A</td></tr></table>',
    '<table>lost text<tr><td>A</td></tr></table>',
    '<table><tr><td>A</td></tr><td>lost cell</td></table>',
    '<table><tr><td>A\nb</td></tr></table>',
    '<ul><li>A<table><tr><td>B</td></tr></table></li></ul>',
])
def test_unsupported_tables_fail_before_writes(markup, mock_docs):
    """Reject unsupported structure before any table or text is inserted."""
    with pytest.raises(ToolFailureError):
        docs_edit.append('test', markup)
    mock_docs.batchUpdate.assert_not_called()


def test_declared_alignment_and_header_ranges():
    """Keep Markdown alignment in all cells, including empty headers."""
    plan = markdown_to_requests('| | B | C |\n| :-- | :-: | --: |\n|a|b|c|')
    assert isinstance(plan, TableInsertionPlan)
    table = next(b for b in plan.blocks if isinstance(b, InsertionTable))
    for row in table.cells:
        pairs = zip(row, ['START', 'CENTER', 'END'], strict=True)
        for cell, expected in pairs:
            alignments = [r['updateParagraphStyle']['paragraphStyle'][
                'alignment'] for r in cell.requests
                if 'alignment' in r.get('updateParagraphStyle', {}).get(
                    'paragraphStyle', {})]
            assert alignments == [expected]


def test_failure_reports_partial_result_without_retries():
    """A later failure must not invite duplicating already inserted text."""
    native = NativeBuffer()
    original = native.document

    def concurrent_read():
        result = original()
        if native.tables:
            result['revisionId'] = 'concurrent'
        return result

    native.service.documents().get.return_value.execute.side_effect = (
        concurrent_read
    )
    plan = markdown_to_requests(MARKDOWN, native.start)
    with pytest.raises(ToolFailureError) as failure:
        plan.execute(native.service, 'test')
    assert 'Earlier stages' in failure.value.failure.description
    assert 'before retrying' in failure.value.failure.suggested_action
    assert len(native.batches) == 1


@pytest.mark.parametrize('operation', [
    'append', 'insert_before', 'insert_after',
])
def test_literal_tables_stay_literal(operation, mock_docs):
    """The new table planner must never run for rich=False."""
    args = ('test', MARKDOWN) if operation == 'append' else (
        'test', 'Introduction', MARKDOWN,
    )
    result = getattr(docs_edit, operation)(*args, rich=False)
    assert result.ok
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == 1
    assert MARKDOWN in requests[0]['insertText']['text']


def test_inline_images_use_native_cell_positions():
    """Image slots occupy one UTF-16 index within their intended cell."""
    native = NativeBuffer(gap=3)
    plan = markdown_to_requests(
        '| A | B |\n| --- | --- |\n'
        '| 😀![x](https://example.com/x.png)**tail** | next |', native.start,
    )
    plan.execute(native.service, 'test')
    styles = [text for request, text in native.styles
              if request.get('updateTextStyle', {}).get('textStyle', {}).get(
                  'bold')]
    assert 'tail' in styles
    assert '😀\ufffctail' in native.buffer.decode('utf-16-le')


def test_temporary_images_in_body_and_cells_share_source(tmp_path, image_png):
    """Stage once and replace every planned source before table execution."""
    path = tmp_path / 'source.png'
    path.write_bytes(image_png)
    drive = MagicMock()
    drive.files().create.return_value.execute.return_value = {'id': 'temp'}
    drive.permissions().create.return_value.execute.return_value = {'id': 'p'}
    uri = 'https://example.com/staged.png'
    drive.files().get.return_value.execute.return_value = {
        'webContentLink': uri,
    }
    source = f'![image]({path})'
    text = f'{source}\n\n| A | B |\n| --- | --- |\n|{source}|{source}|'
    with rich_insertion_requests(text, 1, upload_local_images=True,
                                 drive_factory=lambda: drive) as prepared:
        requests = prepared.requests.iter_requests()
        images = [r['insertInlineImage'] for r in requests
                  if 'insertInlineImage' in r]
        assert [image['uri'] for image in images] == [uri, uri, uri]
        drive.files().delete.assert_not_called()
    drive.files().create.assert_called_once()
    drive.files().delete.assert_called_once_with(fileId='temp')


def test_html_table_preserves_inline_styles_and_alignment():
    """Simple HTML tables use the same native planner as Markdown tables."""
    plan = markdown_to_requests(
        '<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr>'
        '<td><u>under</u></td><td style="text-align: center;">'
        '<a href="https://example.com">link</a></td></tr></tbody></table>',
    )
    native = NativeBuffer()
    plan.start = native.start
    plan.execute(native.service, 'test')
    assert any(text == 'under' and request.get('updateTextStyle', {}).get(
        'textStyle', {}).get('underline')
        for request, text in native.styles)
    assert any(text == 'link' and request.get('updateParagraphStyle', {}).get(
        'paragraphStyle', {}).get('alignment') == 'CENTER'
        for request, text in native.styles)


@pytest.mark.parametrize('tag', ['<br>', '<br/>', '<br />', '<BR>'])
@pytest.mark.parametrize('html', [False, True])
def test_cell_soft_breaks_preserve_whitespace_styles_and_indices(tag, html):
    """Keep edge/repeated breaks and styled emoji within the intended cell."""
    content = f'{tag}<b>😀bold</b>{tag}{tag}<i>next</i>{tag}'
    markup = (
        f'<table><tr><td>{content}</td><td>adjacent</td></tr></table>'
        if html else f'| A | B |\n| --- | --- |\n| {content} | adjacent |'
    )
    native = NativeBuffer(gap=3)
    plan = markdown_to_requests(markup, native.start)
    plan.execute(native.service, 'test')
    table = native.document()['body']['content'][0]['table']
    row = table['tableRows'][-1]['tableCells']
    values = [cell['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] for cell in row]
    assert values == ['\u000b😀bold\u000b\u000bnext\u000b\n', 'adjacent\n']
    assert any(text == '😀bold' and request.get('updateTextStyle', {}).get(
        'textStyle', {}).get('bold') for request, text in native.styles)
    assert any(text == 'next' and request.get('updateTextStyle', {}).get(
        'textStyle', {}).get('italic') for request, text in native.styles)
    preview = inserted_text_from_requests(plan)
    assert '\n😀bold\n\nnext\n\n' in preview
    assert '\u000b' not in preview


@pytest.mark.parametrize('borders', [False, True])
@pytest.mark.parametrize('empty', [False, True])
def test_borders_apply_to_all_new_tables_only(borders, empty):
    """Set outer/internal borders even when tables contain no text requests."""
    markup = ('<table><tr><td></td></tr></table>' if empty else MARKDOWN)
    native = NativeBuffer()
    plan = markdown_to_requests(markup + '\n\n' + markup, native.start)
    plan.execute(native.service, 'test', table_borders=borders)
    assert len(native.table_styles) == len(native.tables)
    sides = {'borderTop', 'borderBottom', 'borderLeft', 'borderRight'}
    for operation in native.table_styles:
        assert set(operation['fields'].split(',')) == sides
        assert set(operation['tableCellStyle']) == sides
        for border in operation['tableCellStyle'].values():
            assert border['width'] == {
                'magnitude': 1 if borders else 0, 'unit': 'PT',
            }
