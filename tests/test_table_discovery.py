"""Verify read-only discovery, snapshot references and native cell geometry."""

import asyncio
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup
from fastmcp import Client
from jsonschema import validate

from gdocs_scope_mcp import docs_edit, server, table_read
from gdocs_scope_mcp.text_indices import utf16_length
from gdocs_scope_mcp.tool_errors import ToolFailureError


@pytest.fixture
def table_source(mock_docs, simple_document):
    """Build independent native indices, including nested table structures."""
    def build(specs=None):
        """Insert a table after each supplied native heading."""
        index = 1

        def paragraph(text, heading=None, level=1):
            """Count source positions in UTF-16, not Python characters."""
            nonlocal index
            start = index
            index += utf16_length(text)
            style = {'namedStyleType': 'NORMAL_TEXT'}
            if heading:
                style = {'namedStyleType': f'HEADING_{level}',
                         'headingId': heading}
            return {'startIndex': start, 'endIndex': index, 'paragraph': {
                'paragraphStyle': style, 'elements': [{
                    'startIndex': start, 'endIndex': index,
                    'textRun': {'content': text, 'textStyle': {}},
                }],
            }}

        def table(values):
            """Use structural gaps independently of the Markdown converter."""
            nonlocal index
            start = index
            index += 1
            rows = []
            for texts in values:
                row_start = index
                index += 1
                cells = []
                for text in texts:
                    cell_start = index
                    index += 1
                    if isinstance(text, dict):
                        nested = (text['tables'] if 'tables' in text else
                                  [text['table']])
                        content = [paragraph('Outer\n'),
                                   *[table(values) for values in nested],
                                   paragraph('\n')]
                    else:
                        content = [paragraph(text + '\n')]
                    cells.append({'startIndex': cell_start, 'endIndex': index,
                                  'content': content, 'tableCellStyle': {
                                      'rowSpan': 1, 'columnSpan': 1,
                                  }})
                rows.append({'startIndex': row_start, 'endIndex': index,
                             'tableCells': cells})
            index += 1
            return {'startIndex': start, 'endIndex': index, 'table': {
                'rows': len(rows), 'columns': len(values[0]),
                'tableRows': rows,
            }}

        if specs is None:
            values = [['same😀', ''], ['duplicate', 'soft\u000bbreak']]
            specs = [('parent', 1, values), ('child', 2, values),
                     ('other', 1, [['different']])]
        content = [paragraph('Preamble\n')]
        for heading, level, values in specs:
            if heading is not None:
                content.append(paragraph(heading + '\n', heading, level))
            content.append(table(values))
        content.append(paragraph('Tail\n'))
        native = {**deepcopy(simple_document), 'body': {'content': content}}
        mock_docs.get.return_value.execute.side_effect = lambda: deepcopy(
            native,
        )
        return native
    yield build
    mock_docs.batchUpdate.assert_not_called()


@pytest.fixture
def source(table_source):
    """Provide identical tables in nested scopes and another outside."""
    return table_source()


def call(tool, **arguments):
    """Validate success/error objects against the advertised MCP schema."""
    async def run():
        async with Client(server.mcp) as client:
            description = next(t for t in await client.list_tools()
                               if t.name == tool)
            result = await client.call_tool(tool, arguments,
                                            raise_on_error=False)
            validate(result.structured_content, description.outputSchema)
            return result
    return asyncio.run(run())


@pytest.mark.usefixtures('source')
def test_read_html_references_match_discovery():
    """Add attributes in place, without another mandatory table inventory."""
    read = call('docs_read', doc_id='example')
    listing = call('docs_tables_list', doc_id='example')
    assert not read.is_error and not listing.is_error
    data = read.structured_content
    markup = ''.join(s['markdown'] for s in data['sections'])
    tables = BeautifulSoup(markup, 'html.parser').find_all('table')
    refs = [t['data-mcp-table-ref'] for t in tables]
    assert refs == [t['table_ref']
                    for t in listing.structured_content['tables']]
    assert len(set(refs)) == len(refs)
    assert 'tables' not in read.structured_content
    assert listing.structured_content['snapshot']['scope'] == 'first_tab'


@pytest.mark.usefixtures('source')
def test_detailed_rows_preserve_unicode_and_empty_cells():
    """Keep geometry, cell refs and Unicode without raw indices."""
    listing = table_read.tables_list('example')
    result = call('docs_table_read', doc_id='example',
                  table_ref=listing.tables[0].table_ref)
    assert not result.is_error
    data = result.structured_content
    cells = [c for row in data['rows'] for c in row['cells']]
    assert [c['column'] for c in cells] == [0, 1, 0, 1]
    assert 'same😀' in cells[0]['markdown']
    assert cells[1]['markdown'] == ''
    assert 'soft' in cells[-1]['markdown'] and 'break' in cells[-1]['markdown']
    assert all(c['simple_text_target'] and c['cell_ref'] for c in cells)
    assert data['table']['geometry_valid']
    assert data['total_cells'] == len(cells)
    assert 'startIndex' not in str(data) and 'endIndex' not in str(data)


@pytest.mark.parametrize(('headings', 'expected', 'selected', 'unknown'), [
    (None, ['parent', 'child', 'other'], None, []),
    ([], [], [], []),
    (['parent', 'child', 'parent'], ['parent', 'child'], ['parent'], []),
    (['child'], ['child'], ['child'], []),
    (['missing', 'other', 'missing'], ['other'], ['other'], ['missing']),
])
@pytest.mark.usefixtures('source')
def test_heading_selection_matches_document_reads(
    headings, expected, selected, unknown,
):
    """Collapse selected descendants and preserve mixed unknown diagnostics."""
    result = table_read.tables_list('example', heading_ids=headings)
    assert [t.heading_id for t in result.tables] == expected
    assert result.selected_headings == selected
    assert result.unknown_heading_ids == unknown


@pytest.mark.usefixtures('source')
def test_unknown_heading_is_structured():
    """Reject an unresolved selection instead of reading all tables."""
    result = call('docs_tables_list', doc_id='example',
                  heading_ids=['missing'])
    assert result.is_error
    assert result.structured_content['code'] == 'HEADING_NOT_FOUND'


@pytest.mark.usefixtures('source')
def test_table_and_cell_pagination_are_complete_and_bounded():
    """A wide row can span pages, with explicit incomplete-row metadata."""
    page = table_read.tables_list('example', limit=1)
    refs = [page.tables[0].table_ref]
    while page.has_more:
        page = table_read.tables_list('example', limit=1,
                                      page_token=page.next_page_token)
        refs.extend(t.table_ref for t in page.tables)
    assert len(set(refs)) == len(refs) == 3  # noqa: PLR2004
    page = table_read.table_read('example', refs[0], limit=1)
    cells = []
    while True:
        assert page.count == 1
        assert not page.rows[0].complete
        cells.extend(c.cell_ref for r in page.rows for c in r.cells)
        if not page.has_more:
            break
        page = table_read.table_read('example', refs[0], limit=1,
                                     page_token=page.next_page_token)
    assert len(set(cells)) == len(cells) == 4  # noqa: PLR2004


@pytest.mark.usefixtures('source')
def test_cursor_binds_filter_and_output_options():
    """Never continue a different result using a previously issued cursor."""
    listing = table_read.tables_list('example', limit=1)
    with pytest.raises(ToolFailureError) as caught:
        table_read.tables_list('example', limit=2,
                                page_token=listing.next_page_token)
    assert caught.value.failure.code == 'INVALID_ARGUMENT'
    table_ref = listing.tables[0].table_ref
    cells = table_read.table_read('example', table_ref, limit=1)
    with pytest.raises(ToolFailureError):
        table_read.table_read('example', table_ref, limit=1, max_cell_chars=1,
                              page_token=cells.next_page_token)
    with pytest.raises(ToolFailureError):
        table_read.tables_list('example', heading_ids=['parent'], limit=1,
                                page_token=listing.next_page_token)


def test_revision_change_invalidates_refs_and_cursors(source):
    """Even identical replacement content cannot silently reuse an old path."""
    listing = table_read.tables_list('example', limit=1)
    ref = listing.tables[0].table_ref
    source['revisionId'] = 'changed'
    for operation in [
        lambda: table_read.table_read('example', ref),
        lambda: table_read.tables_list('example', limit=1,
                                       page_token=listing.next_page_token),
    ]:
        with pytest.raises(ToolFailureError) as caught:
            operation()
        assert caught.value.failure.code == 'STALE_REFERENCE'


def test_table_fingerprint_detects_changed_path_at_same_revision(source):
    """Validate the snapshot as well as the opaque structural path."""
    ref = table_read.tables_list('example').tables[0].table_ref
    row = source['body']['content'][2]['table']['tableRows'][0]
    run = row['tableCells'][0]['content'][0]['paragraph']['elements'][0]
    run['textRun']['content'] = 'new\n'
    with pytest.raises(ToolFailureError) as caught:
        table_read.table_read('example', ref)
    assert caught.value.failure.code == 'STALE_REFERENCE'


@pytest.mark.parametrize('bad', ['bad', 'gdt1.bad.00', 'x' * 8193])
def test_invalid_reference_never_reads_document(mock_docs, bad):
    """Reject corrupt input at the MCP boundary without Google access."""
    result = call('docs_table_read', doc_id='example', table_ref=bad)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()


@pytest.mark.usefixtures('source')
def test_cross_document_and_wrong_kind_tokens_are_rejected(mock_docs):
    """References are not interchangeable with cell refs or page cursors."""
    listing = table_read.tables_list('example', limit=1)
    mock_docs.get.reset_mock()
    for ref, doc_id in [(listing.tables[0].table_ref, 'other'),
                        (listing.next_page_token, 'example')]:
        with pytest.raises(ToolFailureError) as caught:
            table_read.table_read(doc_id, ref)
        assert caught.value.failure.code == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()


def test_nested_tables_have_distinct_html_and_parent_cell_refs(table_source):
    """Nested paths work without flattening child tables into their parent."""
    native = table_source([('parent', 1, [[{'table': [['deep😀']]}]])])
    listing = table_read.tables_list('example')
    assert [t.nesting_depth for t in listing.tables] == [0, 1]
    parent, child = listing.tables
    details = table_read.table_read('example', parent.table_ref)
    cell = details.rows[0].cells[0]
    assert child.parent_cell_ref == cell.cell_ref
    assert cell.nested_table_refs == [child.table_ref]
    assert child.table_ref in cell.markdown
    assert not cell.simple_text_target
    assert 'nested_table' in cell.unsupported_edit_reasons
    assert 'deep😀' in table_read.table_read('example', child.table_ref).rows[
        0].cells[0].markdown
    before = deepcopy(native)
    read = docs_edit.read('example')
    markup = ''.join(s.markdown for s in read.sections)
    assert len(BeautifulSoup(markup, 'html.parser').find_all('table')) == 2  # noqa: PLR2004
    assert native == before


@pytest.mark.parametrize('compressed', [False, True])
@pytest.mark.parametrize('vertical', [False, True])
def test_merged_geometry_handles_placeholders_and_compressed_rows(
    table_source, compressed, vertical,
):
    """Read heads and covered slots without inventing editable cells."""
    native = table_source([('parent', 1, [['head', ''], ['', 'tail']])])
    table = native['body']['content'][2]['table']
    rows = table['tableRows']
    first = rows[0]['tableCells'][0]
    first['tableCellStyle']['rowSpan' if vertical else 'columnSpan'] = 2
    if not vertical:
        rows[1]['tableCells'][0]['content'][0]['paragraph']['elements'][0][
            'textRun']['content'] = 'bottom\n'
    if compressed:
        rows[1 if vertical else 0]['tableCells'].pop(0 if vertical else 1)
    listing = table_read.tables_list('example')
    assert listing.tables[0].geometry_valid
    assert listing.tables[0].has_merged_cells
    data = table_read.table_read('example', listing.tables[0].table_ref)
    cells = [c for row in data.rows for c in row.cells]
    assert not cells[0].simple_text_target
    covered = [c for c in cells if c.covered_by]
    assert bool(covered) is not compressed
    assert all(c.cell_ref is None and not c.simple_text_target
               for c in covered)
    if vertical:
        assert data.rows[-1].cells[-1].column == 1


def test_unknown_geometry_is_readable_without_cell_handles(table_source):
    """Preserve data and warn rather than flattening unsupported geometry."""
    native = table_source([('parent', 1, [['value']])])
    del native['body']['content'][2]['table']['tableRows'][0]['tableCells'][0][
        'tableCellStyle']['rowSpan']
    listing = table_read.tables_list('example')
    assert not listing.tables[0].geometry_valid
    detail = table_read.table_read('example', listing.tables[0].table_ref)
    cell = detail.rows[0].cells[0]
    assert cell.column is None and cell.cell_ref is None
    assert not cell.simple_text_target
    assert 'value' in cell.markdown


def test_many_nested_tables_have_bounded_refs_and_discovery(table_source):
    """Expose child counts without an unbounded list inside a cell."""
    count = table_read.NESTED_REF_LIMIT + 1
    table_source([('parent', 1, [[{'tables': [[['deep']]] * count}]])])
    listing = table_read.tables_list('example')
    detail = table_read.table_read('example', listing.tables[0].table_ref)
    cell = detail.rows[0].cells[0]
    assert len(cell.nested_table_refs) == table_read.NESTED_REF_LIMIT
    assert cell.nested_table_count == count
    assert cell.nested_table_refs_truncated
    assert sum(t.parent_cell_ref == cell.cell_ref for t in listing.tables) == (
        count
    )


def test_preamble_table_has_no_invented_heading_context(table_source):
    """Keep tables before headings discoverable without a synthetic section."""
    table_source([(None, 0, [['intro table']]),
                  ('parent', 1, [['scoped table']])])
    listing = table_read.tables_list('example')
    assert listing.tables[0].heading_id is None
    assert listing.tables[0].heading_title is None
    assert listing.tables[0].ancestor_heading_ids == []
    scoped = table_read.tables_list('example', heading_ids=['parent'])
    assert [t.table_ref for t in scoped.tables] == [
        listing.tables[1].table_ref,
    ]


def test_bounded_unicode_markdown_discloses_truncation(table_source):
    """Count preview bounds in Unicode code points, independently of UTF-16."""
    table_source([('parent', 1, [['😀' * 250]])])
    table = table_read.tables_list('example').tables[0]
    assert table.preview_truncated and len(table.preview) == 200  # noqa: PLR2004
    data = table_read.table_read('example', table.table_ref, max_cell_chars=3)
    cell = data.rows[0].cells[0]
    assert cell.markdown == '😀😀😀'
    assert cell.markdown_char_count == 250  # noqa: PLR2004
    assert cell.markdown_truncated


def test_revision_metadata_is_required(source):
    """Fail clearly when a read-only viewer cannot obtain a Docs revision."""
    del source['revisionId']
    result = call('docs_tables_list', doc_id='example')
    assert result.is_error
    assert result.structured_content['code'] == 'REVISION_UNAVAILABLE'


def test_empty_discovery_returns_a_terminal_page(mock_docs):  # noqa: ARG001
    """A document without tables is a successful empty result."""
    result = call('docs_tables_list', doc_id='example')
    assert not result.is_error
    data = result.structured_content
    assert data['tables'] == [] and data['count'] == 0
    assert data['total_count'] == 0 and not data['has_more']


def test_conflicting_covered_content_marks_geometry_unknown(table_source):
    """Never erase nonempty placeholder data under a guessed merge head."""
    native = table_source([('parent', 1, [['head', 'retained']])])
    row = native['body']['content'][2]['table']['tableRows'][0]
    row['tableCells'][0]['tableCellStyle']['columnSpan'] = 2
    listing = table_read.tables_list('example')
    assert not listing.tables[0].geometry_valid
    read = table_read.table_read('example', listing.tables[0].table_ref)
    assert 'retained' in read.rows[0].cells[1].markdown
    assert all(c.cell_ref is None and c.column is None
               for c in read.rows[0].cells)


@pytest.mark.parametrize('arguments', [{'limit': 0}, {'limit': 201},
                                        {'max_cell_chars': 4001},
                                        {'max_cell_chars': True}])
def test_invalid_page_bounds_fail_before_api_access(mock_docs, arguments):
    """Reject oversized pages and invalid types before a Google read."""
    result = call('docs_table_read', doc_id='example', table_ref='unused',
                  **arguments)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
