"""Verify table source ranges independently of display markup."""

from copy import deepcopy

import pytest

from gdocs_scope_mcp import docs_edit


def cell_paragraphs(document):
    """Return raw source paragraphs in table row/cell order."""
    table = document['body']['content'][2]['table']
    return [
        paragraph for row in table['tableRows']
        for cell in row['tableCells'] for paragraph in cell['content']
    ]


def source_buffer(document):
    """Place source runs into UTF-16 bytes, retaining structural gaps."""
    buffer = bytearray(b'\0\0' * document['body']['content'][-1]['endIndex'])

    def place(items):
        for item in items:
            if 'paragraph' in item:
                for element in item['paragraph']['elements']:
                    content = element['textRun']['content'].encode('utf-16-le')
                    start = element['startIndex'] * 2
                    buffer[start:start + len(content)] = content
            elif 'table' in item:
                for row in item['table']['tableRows']:
                    for cell in row['tableCells']:
                        place(cell['content'])

    place(document['body']['content'])
    return bytes(buffer)


@pytest.mark.parametrize('cell_number', range(5))
@pytest.mark.parametrize('operation', ['replace', 'before', 'after'])
@pytest.mark.parametrize('rich', [False, True])
def test_table_edits_use_original_paragraph_ranges(
    table_document, mock_docs, *, cell_number, operation, rich,
):
    """Use cell paragraph bounds without changing neighbouring source."""
    source = cell_paragraphs(table_document)[cell_number]
    text = source['paragraph']['elements'][0]['textRun']['content']
    anchor = text.strip()
    original = source_buffer(table_document)
    if operation == 'replace':
        result = docs_edit.search_replace(
            'example', anchor, 'Changed', heading_id='owner',
        )
        at = source['startIndex']
        inserted = 'Changed'
    else:
        result = getattr(docs_edit, f'insert_{operation}')(
            'example', anchor, 'Changed', heading_id='owner', rich=rich,
        )
        at = (
            source['startIndex'] if operation == 'before'
            else source['endIndex'] - 1
        )
        inserted = 'Changed\n' if operation == 'before' else '\nChanged'
    assert result.ok is True
    assert result.at_index == at
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    insertion = requests[0]['insertText']
    assert insertion == {'location': {'index': at}, 'text': inserted}
    if operation == 'replace':
        replaced_units = len(anchor.encode('utf-16-le')) // 2
        assert requests[1]['deleteContentRange']['range'] == {
            'startIndex': at + len(inserted),
            'endIndex': at + len(inserted) + replaced_units,
        }
    remaining = original
    for request in requests:
        if 'insertText' in request:
            insertion = request['insertText']
            index = insertion['location']['index'] * 2
            remaining = (
                remaining[:index] + insertion['text'].encode('utf-16-le')
                + remaining[index:]
            )
            continue
        span = next(iter(request.values()))['range']
        # Formatting and deletion stay inside this cell's shifted paragraph.
        assert source['startIndex'] <= span['startIndex'] <= span['endIndex']
        assert span['endIndex'] <= source['endIndex'] + len(inserted)
        if 'deleteContentRange' in request:
            remaining = (
                remaining[:span['startIndex'] * 2]
                + remaining[span['endIndex'] * 2:]
            )
    old_units = (
        len(anchor.encode('utf-16-le')) // 2 if operation == 'replace' else 0
    )
    assert remaining == (
        original[:at * 2] + inserted.encode('utf-16-le')
        + original[(at + old_units) * 2:]
    )


def test_table_rendering_does_not_extend_preceding_paragraph(table_document):
    """Keep one HTML table and separate editable source paragraphs."""
    expected = deepcopy(table_document)
    tree = docs_edit._parse_document_tree(table_document)
    owner = tree.headings['owner']
    before = owner.paragraphs[1]
    source = expected['body']['content'][1]
    assert before.text == 'Before table\n'
    assert before.start_index == source['startIndex']
    assert before.end_index == source['endIndex']
    assert owner.markdown.count('<table>') == 1
    assert owner.markdown.count('First😀') == 1
    assert [p.text for p in owner.paragraphs[2:-1]] == [
        item['paragraph']['elements'][0]['textRun']['content']
        for item in cell_paragraphs(expected)
    ]
    assert tree.headings['other'].find_first('First') is None


@pytest.mark.parametrize('operation', ['insert_before', 'insert_after'])
def test_insert_around_body_paragraph_before_table(
    table_document, mock_docs, operation,
):
    """A body anchor immediately before a table retains its own bounds."""
    source = table_document['body']['content'][1]
    result = getattr(docs_edit, operation)(
        'example', 'Before table', 'Inserted', rich=False,
    )
    assert result.ok is True
    assert result.at_index == (
        source['startIndex'] if operation == 'insert_before'
        else source['endIndex'] - 1
    )
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('find', ['Cell tail.*Second', 'First😀 | Second'])
@pytest.mark.usefixtures('table_document')
def test_table_matches_cannot_cross_cells(mock_docs, find):
    """Do not interpret rendered cell separators as contiguous source text."""
    result = docs_edit.search_replace(
        'example', find, 'X', regex=True, heading_id='owner',
    )
    assert result.ok is False
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('replacement', ['X', ''])
@pytest.mark.usefixtures('table_document')
def test_table_cell_terminal_newline_is_protected(
    mock_docs, replacement,
):
    """Refuse replacements that would remove the cell's required terminator."""
    result = docs_edit.search_replace(
        'example', r'(?<=tail)\W+', replacement,
        regex=True, heading_id='owner',
    )
    assert result.ok is False
    assert result.code == 'INVALID_ARGUMENT'
    assert result.suggested_action
    mock_docs.batchUpdate.assert_not_called()


def test_table_internal_paragraph_newline_can_be_replaced(
    table_document, mock_docs,
):
    """Allow merging paragraphs within a cell, preserving its terminator."""
    result = docs_edit.search_replace(
        'example', r'First😀\n', 'X', regex=True, heading_id='owner',
    )
    assert result.ok is True
    assert result.replaced == 'First😀\n'
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    row = table_document['body']['content'][2]['table']['tableRows'][0]
    cell = row['tableCells'][0]
    assert requests[1]['deleteContentRange']['range']['endIndex'] < (
        cell['endIndex']
    )
