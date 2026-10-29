"""Verify section positions, A1 addressing and selective expected states."""

# Imported pytest fixtures are requested by name in tests.
# ruff: noqa: F811
from copy import deepcopy

import pytest

from gdocs_scope_mcp.tables import (
    reading as table_read,
    snapshots as table_snapshots,
    tokens as table_tokens,
)
from gdocs_scope_mcp.tables.refs import Layout, first_tab
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture(autouse=True)
def read_only(mock_docs):
    """Keep all identity/snapshot operations free of document writes."""
    yield
    mock_docs.batchUpdate.assert_not_called()


@pytest.fixture
def source(table_source):
    """Use two identical tables in one section and another in a child."""
    return table_source([('parent', 1, [['same😀', ''], ['same😀', '']]),
                         (None, 0, [['same😀', ''], ['same😀', '']]),
                         ('child', 2, [['child']])])


def tables(source):
    """Enumerate native top-level tables independently of reference code."""
    return [x for x in source['body']['content'] if 'table' in x]


def cell(source, row=0, column=0, table=0):
    """Access a known native fixture position."""
    return tables(source)[table]['table']['tableRows'][row]['tableCells'][
        column]


def ref(table=0):
    """Read a positional ref from the public discovery implementation."""
    return table_read.tables_list('example').tables[table].table_ref


def snapshot(table_ref, cells=None, fields=None, base=None):
    """Select explicit properties at A1 positions in one checked table."""
    return table_snapshots.snapshot('example', table_ref, cells or ['A1'],
                                    fields or ['content'], base)


def reject(code, operation):
    """Require structured recovery guidance instead of a raw exception."""
    with pytest.raises(ToolFailureError) as caught:
        operation()
    assert caught.value.failure.code == code
    assert caught.value.failure.suggested_action


def test_identical_tables_use_section_positions(source):
    """Duplicate structure/content does not make a positional target vague."""
    first, second = ref(), ref(1)
    assert first != second
    assert [t.section_table_number for t in table_read.tables_list(
        'example').tables] == [1, 2, 1]
    token = table_tokens.decode(second, 'table', 'example')
    assert token.section == ['parent'] and token.ordinal == 1
    assert Layout(source).resolve(token).item is tables(source)[1]
    detail = table_read.table_read('example', second)
    assert [c.address for r in detail.rows for c in r.cells] == [
        'A1', 'B1', 'A2', 'B2',
    ]
    assert detail.table.reference_semantics == 'section_position'


def test_index_shifts_title_text_and_neighbors_preserve_refs(source):
    """Ignore revisions, indices and unrelated text/style."""
    reference = ref(1)
    base = snapshot(reference)
    source['revisionId'] = 'changed'
    cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'a different table\n'
    cell(source, table=1, column=1)['tableCellStyle']['paddingTop'] = {
        'magnitude': 12, 'unit': 'PT',
    }
    source['body']['content'][1]['paragraph']['elements'][0]['textRun'][
        'content'] = 'Renamed heading\n'
    source['body']['content'].insert(0, deepcopy(source['body']['content'][0]))
    assert ref(1) == reference
    assert snapshot(reference, base=base.base_token).validated


@pytest.mark.parametrize('change', ['insert_table', 'delete_table',
                                   'row', 'column', 'merge', 'heading',
                                   'ancestry', 'nested'])
def test_structural_changes_in_direct_section_invalidate(source, change):
    """Never continue through a changed section table inventory."""
    reference = ref(1)
    first = tables(source)[0]
    if change == 'insert_table':
        source['body']['content'].insert(2, deepcopy(first))
    elif change == 'delete_table':
        source['body']['content'].remove(first)
    elif change == 'row':
        first['table']['rows'] += 1
    elif change == 'column':
        first['table']['columns'] += 1
    elif change == 'merge':
        cell(source)['tableCellStyle']['columnSpan'] = 2
    elif change == 'heading':
        source['body']['content'][1]['paragraph']['paragraphStyle'][
            'headingId'] = 'new-heading-id'
    elif change == 'ancestry':
        heading = deepcopy(source['body']['content'][1])
        heading['paragraph']['paragraphStyle']['headingId'] = 'ancestor'
        source['body']['content'].insert(1, heading)
        source['body']['content'][2]['paragraph']['paragraphStyle'][
            'namedStyleType'] = 'HEADING_2'
    else:
        cell(source)['content'].append(deepcopy(tables(source)[2]))
    reject('TARGET_CHANGED', lambda: table_read.table_read(
        'example', reference,
    ))


def test_other_section_structure_does_not_invalidate(source):
    """A child section has its own structural inventory."""
    reference = ref()
    tables(source)[2]['table']['columns'] += 1
    assert snapshot(reference)


def test_same_shape_swaps_have_explicit_position_semantics(source):
    """A structure hash cannot prove native object identity or edit history."""
    first, second = tables(source)[:2]
    second['table']['tableRows'][0]['tableCells'][0]['content'][0][
        'paragraph']['elements'][0]['textRun']['content'] = 'other\n'
    reference = ref()
    base = snapshot(reference)
    body = source['body']['content']
    a, b = body.index(first), body.index(second)
    body[a], body[b] = second, first
    assert ref() == reference
    assert snapshot(reference)  # The first position still has this structure.
    reject('EDIT_CONFLICT', lambda: snapshot(reference, base=base.base_token))


@pytest.mark.parametrize('field', ['content', 'text_style', 'paragraph_style',
                                  'cell_style', 'structure'])
def test_only_selected_cell_properties_are_checked(source, field):
    """Independent cells remain editable even in identical tables."""
    reference = ref()
    base = snapshot(reference, fields=[field])
    neighbor = cell(source, column=1)
    neighbor['content'][0]['paragraph']['elements'][0]['textRun'].update(
        content='independent\n', textStyle={'bold': True},
    )
    neighbor['tableCellStyle']['paddingTop'] = {
        'magnitude': 10, 'unit': 'PT',
    }
    assert snapshot(reference, fields=[field], base=base.base_token).validated
    target = cell(source)
    p = target['content'][0]['paragraph']
    if field == 'content':
        p['elements'][0]['textRun']['content'] = 'overlap\n'
    elif field == 'text_style':
        p['elements'][0]['textRun']['textStyle']['bold'] = True
    elif field == 'paragraph_style':
        p['paragraphStyle']['alignment'] = 'CENTER'
    elif field == 'cell_style':
        target['tableCellStyle']['paddingTop'] = {
            'magnitude': 20, 'unit': 'PT',
        }
    else:
        p['elements'].append({'textRun': {'content': '', 'textStyle': {}}})
    reject('EDIT_CONFLICT', lambda: snapshot(
        reference, fields=[field], base=base.base_token,
    ))


def test_content_only_allows_style_splits_and_clear_refill(source):
    """Plain content expectations ignore run splitting and formatting."""
    reference = ref()
    base = snapshot(reference)
    p = cell(source)['content'][0]['paragraph']
    p['elements'] = [{'textRun': {'content': 'same',
                                  'textStyle': {'bold': True}}},
                     {'textRun': {'content': '😀\n', 'textStyle': {}}}]
    assert snapshot(reference, base=base.base_token).validated
    p['elements'] = [{'textRun': {'content': '\n', 'textStyle': {}}}]
    reject('EDIT_CONFLICT', lambda: snapshot(reference, base=base.base_token))
    assert snapshot(reference)


def test_snapshot_expiry_scope_and_cell_set(source, monkeypatch):  # noqa: ARG001
    """Reject expired tokens and mismatched table/cell/property sets."""
    reference = ref()
    base = snapshot(reference)
    reject('INVALID_REFERENCE', lambda: snapshot(
        ref(1), base=base.base_token,
    ))
    reject('INVALID_REFERENCE', lambda: snapshot(
        reference, ['B1'], base=base.base_token,
    ))
    reject('INVALID_REFERENCE', lambda: snapshot(
        reference, fields=['cell_style'], base=base.base_token,
    ))
    reject('INVALID_ARGUMENT', lambda: snapshot(reference, ['A1', 'A1']))
    reject('INVALID_ARGUMENT', lambda: snapshot(reference, ['Z99']))
    monkeypatch.setattr(table_snapshots.time, 'time', lambda: base.expires_at)
    reject('SNAPSHOT_EXPIRED', lambda: snapshot(
        reference, base=base.base_token,
    ))


def test_cross_document_kind_corruption_and_tab_scope(source, mock_docs):
    """Reject wrong tokens before Google access and changed tabs on resolve."""
    reference = ref()
    mock_docs.get.reset_mock()
    reject('INVALID_ARGUMENT', lambda: table_read.table_read(
        'other', reference,
    ))
    reject('INVALID_ARGUMENT', lambda: snapshot(reference[:-8] + '00000000'))
    mock_docs.get.assert_not_called()
    source['tabs'] = [{'tabProperties': {'tabId': 'new-tab'},
                       'documentTab': {'body': source['body']}}]
    reject('TAB_MISMATCH', lambda: snapshot(reference))
    assert first_tab(source)['_mcp_tab_id'] == 'new-tab'


def test_snapshot_mcp_contract_and_read_only_schema(source):  # noqa: ARG001
    """Expose direct typed responses and default dependencies over MCP."""
    result = call('docs_table_snapshot', doc_id='example', table_ref=ref(),
                  cells=['A1', 'B2'])
    assert not result.is_error
    data = result.structured_content
    assert data['fields'] == ['content', 'paragraph_style', 'text_style']
    assert [c['address'] for c in data['cells']] == ['A1', 'B2']
    assert data['cells'][0]['markdown'] == 'same😀'


@pytest.mark.parametrize('cells', [
    [], ['a1'], ['A0'], ['A1:B2'], ['A1'] * 101,
])
def test_address_input_validation_precedes_google(mock_docs, cells):
    """Accept bounded lists of individual uppercase A1 addresses."""
    result = call('docs_table_snapshot', doc_id='example', table_ref='unused',
                  cells=cells)
    assert result.is_error
    mock_docs.get.assert_not_called()


@pytest.mark.parametrize(('column', 'expected'), [(0, 'A1'), (25, 'Z1'),
                                                (26, 'AA1'), (701, 'ZZ1'),
                                                (702, 'AAA1')])
def test_multi_letter_column_addresses(column, expected):
    """Use standard base-26 column labels without an arbitrary Z limit."""
    assert table_tokens.address(0, column) == expected


def test_nested_position_ignores_parent_paragraph_shifts(table_source):
    """Locate nested tables by structure rather than paragraph indices."""
    nested = {'tables': [[['one']], [['two']]]}
    native = table_source([('parent', 1, [[nested]])])
    listing = table_read.tables_list('example')
    reference = listing.tables[2].table_ref
    base = snapshot(reference)
    content = cell(native)['content']
    content.insert(1, deepcopy(content[0]))
    assert snapshot(reference, base=base.base_token).validated
    assert snapshot(reference).cells[0].markdown == 'two'


def test_selected_preview_is_bounded_but_hash_covers_full_text(source):
    """Changes beyond the visible preview still invalidate expectations."""
    p = cell(source)['content'][0]['paragraph']
    p['elements'][0]['textRun']['content'] = '😀' * 2100 + '\n'
    reference = ref()
    base = snapshot(reference)
    assert len(base.cells[0].markdown) == 2000  # noqa: PLR2004
    assert base.cells[0].markdown_truncated
    assert base.cells[0].markdown_char_count == 2100  # noqa: PLR2004
    p['elements'][0]['textRun']['content'] = '😀' * 2100 + 'tail\n'
    reject('EDIT_CONFLICT', lambda: snapshot(reference, base=base.base_token))


@pytest.mark.parametrize('kind', ['bullet', 'list', 'named_style'])
def test_referenced_paragraph_dependencies(source, kind):
    """Track inherited selected styles without unrelated list dependencies."""
    paragraph = cell(source)['content'][0]['paragraph']
    paragraph['bullet'] = {'listId': 'selected', 'nestingLevel': 0,
                           'textStyle': {}}
    source['lists'] = {'selected': {'listProperties': {
        'nestingLevels': [{'glyphSymbol': '●'}, {'glyphSymbol': '○'}],
    }}}
    source['namedStyles'] = {'styles': [
        {'namedStyleType': 'NORMAL_TEXT', 'textStyle': {}},
    ]}
    reference = ref()
    base = snapshot(reference, fields=['paragraph_style'])
    source['lists']['other'] = {'listProperties': {
        'nestingLevels': [{'glyphSymbol': '■'}],
    }}
    assert snapshot(reference, fields=['paragraph_style'],
                    base=base.base_token).validated
    if kind == 'bullet':
        paragraph['bullet']['nestingLevel'] = 1
    elif kind == 'list':
        source['lists']['selected']['listProperties']['nestingLevels'][0][
            'glyphSymbol'] = '■'
    else:
        source['namedStyles']['styles'][0]['textStyle']['bold'] = True
    reject('EDIT_CONFLICT', lambda: snapshot(
        reference, fields=['paragraph_style'], base=base.base_token,
    ))


def test_page_cursor_still_requires_exact_revision(source):
    """Position refs survive cell edits; page cursors require one snapshot."""
    reference = ref()
    page = table_read.table_read('example', reference, limit=1)
    source['revisionId'] = 'new'
    assert snapshot(reference)
    reject('STALE_REFERENCE', lambda: table_read.table_read(
        'example', reference, limit=1, page_token=page.next_page_token,
    ))
