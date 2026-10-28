"""Verify structural intent, deletion footprints and atomic retry behavior."""

# Imported pytest fixtures are requested by name.
# ruff: noqa: F811

from copy import deepcopy

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response
from pydantic import TypeAdapter

from gdocs_scope_mcp import table_read, table_snapshots, table_structure
from gdocs_scope_mcp.table_deletion_state import deletion_state
from gdocs_scope_mcp.table_refs import Layout
from gdocs_scope_mcp.table_tokens import decode, digest, encode
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture
def source(table_source, mock_docs):
    """Use duplicate text/tables to expose accidental content retargeting."""
    source = table_source([
        ('parent', 1, [['same', 'same'], ['same', 'same'], ['last', 'last']]),
        (None, 1, [['same', 'same'], ['same', 'same'], ['last', 'last']]),
    ])
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'writeControl': {'requiredRevisionId': 'committed'},
    }
    return source


def native_table(source):
    """Find the first fixture table without relying on source indices."""
    return next(i for i in source['body']['content'] if 'table' in i)


def cell(source, row=0, column=0):
    """Select a known test cell."""
    return native_table(source)['table']['tableRows'][row][
        'tableCells'][column]


def baseline(cells=None, fields=None):
    """Use the same public snapshot path as an MCP agent."""
    ref = table_read.tables_list('example').tables[0].table_ref
    return ref, table_snapshots.snapshot(
        'example', ref, cells or ['A1', 'B1'], fields or ['deletion'],
    )


def apply(ref, base, operation):
    """Validate the discriminated input before running the operation."""
    typed = TypeAdapter(table_structure.StructureOperation).validate_python(
        operation,
    )
    return table_structure.apply_structure(
        'example', ref, base.base_token, typed,
    )


def reject(code, function):
    """Require structured failure with no confirmed writes."""
    with pytest.raises(ToolFailureError) as caught:
        function()
    assert caught.value.failure.code == code
    assert caught.value.failure.committed_batches == 0


@pytest.mark.parametrize(('operation', 'native', 'rows', 'columns'), [
    ({'type': 'insert_rows', 'row': 1, 'position': 'before', 'count': 2},
     'insertTableRow', 5, 2),
    ({'type': 'insert_rows', 'row': 3, 'position': 'after'},
     'insertTableRow', 4, 2),
    ({'type': 'insert_columns', 'column': 'B', 'position': 'after'},
     'insertTableColumn', 3, 3),
    ({'type': 'insert_columns', 'column': 'A', 'position': 'before'},
     'insertTableColumn', 3, 3),
    ({'type': 'delete_rows', 'row': 1}, 'deleteTableRow', 2, 2),
    ({'type': 'delete_columns', 'column': 'A'}, 'deleteTableColumn', 3, 1),
    ({'type': 'delete_table'}, 'deleteContentRange', 0, 0),
])
def test_native_shape_and_one_batch(  # noqa: PLR0917
    source, mock_docs, operation, native, rows, columns,
):
    """Every supported operation is one strict batch with explicit shape."""
    ref, base = baseline(['A1', 'B1', 'A2', 'B2', 'A3', 'B3'])
    original = deepcopy(source)
    result = call('docs_table_structure', doc_id='example', table_ref=ref,
                  base_token=base.base_token, operation=operation)
    assert not result.is_error, result.structured_content
    value = result.structured_content
    assert (value['rows'], value['columns']) == (rows, columns)
    assert value['committed_batches'] == value['attempts'] == 1
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert len(body['requests']) == operation.get('count', 1)
    assert all(set(r) == {native} for r in body['requests'])
    assert source == original
    if rows:
        assert decode(value['table_ref'], 'table', 'example').structure != (
            decode(ref, 'table', 'example').structure)
    else:
        assert value['table_ref'] is None
        bounds = body['requests'][0][native]['range']
        assert bounds['startIndex'] == native_table(source)['startIndex']


def test_deletion_allows_unselected_text_edit(source, mock_docs):
    """A row deletion does not reserve the contents of another row."""
    ref, base = baseline()
    cell(source, 1)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'independent longer text😀\n'
    assert apply(ref, base, {'type': 'delete_rows', 'row': 1}).attempts == 1
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('mutation', ['text', 'style', 'row', 'column',
                                      'object', 'range'])
def test_deletion_checks_removed_state(source, mock_docs, mutation):
    """Protect content and formatting/metadata which deletion would remove."""
    target = cell(source)
    if mutation == 'object':
        target['content'][0]['paragraph']['elements'].append({
            'inlineObjectElement': {
                'inlineObjectId': 'image', 'textStyle': {},
            },
        })
        source['inlineObjects'] = {'image': {
            'objectId': 'image', 'inlineObjectProperties': {
                'embeddedObject': {'title': 'Original'},
            },
        }}
    ref, base = baseline()
    if mutation == 'text':
        target['content'][0]['paragraph']['elements'][0]['textRun'][
            'content'] = 'collaborator\n'
    elif mutation == 'style':
        target['tableCellStyle']['paddingTop'] = {'magnitude': 8, 'unit': 'PT'}
    elif mutation == 'row':
        native_table(source)['table']['tableRows'][0]['tableRowStyle'] = {
            'minRowHeight': {'magnitude': 30, 'unit': 'PT'},
        }
    elif mutation == 'column':
        native_table(source)['table']['tableStyle'] = {
            'tableColumnProperties': [{'widthType': 'FIXED_WIDTH'}],
        }
    elif mutation == 'object':
        source['inlineObjects']['image']['inlineObjectProperties'] = {
            'embeddedObject': {'title': 'Changed image'},
        }
    else:
        source['namedRanges'] = {'new': {'namedRanges': [{
            'namedRangeId': 'new', 'name': 'new', 'ranges': [{
                'startIndex': target['startIndex'],
                'endIndex': target['endIndex'],
            }],
        }]}}
    reject('EDIT_CONFLICT', lambda: apply(ref, base, {
        'type': 'delete_rows', 'row': 1,
    }))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_all_removed_cells_need_baseline(mock_docs):
    """A partial row snapshot never authorizes deleting unseen cells."""
    ref, base = baseline(['A1'])
    reject('INVALID_REFERENCE', lambda: apply(ref, base, {
        'type': 'delete_rows', 'row': 1,
    }))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_content_only_is_not_a_deletion_expectation(mock_docs):
    """Deletion needs stronger expectations than a text-only comparison."""
    ref, base = baseline(fields=['content'])
    reject('INVALID_REFERENCE', lambda: apply(ref, base, {
        'type': 'delete_rows', 'row': 1,
    }))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('operation', [
    {}, {'type': 'other'}, {'type': 'delete_rows', 'row': True},
    {'type': 'insert_rows', 'row': 1},
    {'type': 'insert_rows', 'row': 1, 'position': 'before', 'count': 0},
    {'type': 'delete_columns', 'column': 'a'},
    {'type': 'delete_table', 'count': 1},
])
def test_invalid_schema_before_native_reads(mock_docs, operation):
    """Reject unknown or ambiguous operation input through MCP schemas."""
    result = call('docs_table_structure', doc_id='example', table_ref='unused',
                  base_token='unused', operation=operation)
    assert result.is_error
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
@pytest.mark.parametrize('operation', [
    {'type': 'delete_rows', 'row': 1, 'count': 3},
    {'type': 'delete_columns', 'column': 'A', 'count': 2},
    {'type': 'delete_rows', 'row': 3, 'count': 2},
    {'type': 'insert_columns', 'column': 'C', 'position': 'before'},
])
def test_invalid_native_bounds_without_write(mock_docs, operation):
    """An axis deletion cannot silently become whole-table deletion."""
    ref, base = baseline()
    reject('INVALID_ARGUMENT', lambda: apply(ref, base, operation))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('race', ['text', 'overlap', 'structure', 'timeout',
                                  'exhausted'])
def test_race_policy(source, mock_docs, race):
    """Retry only a confirmed rejection and never replace expectations."""
    ref, base = baseline()
    rejection = HttpError(Response({'status': '400'}),
                          b'{"error":{"message":"Revision does not match"}}')
    calls = 0

    def execute():
        """Commit an interleaved native mutation before the stale CAS."""
        nonlocal calls
        calls += 1
        if race == 'timeout':
            raise TimeoutError()
        if calls == 1 or race == 'exhausted':
            if race in {'text', 'overlap'}:
                target = cell(source, int(race == 'text'))
                target['content'][0]['paragraph']['elements'][0]['textRun'][
                    'content'] = 'new text\n'
            elif race == 'structure':
                table = native_table(source)['table']
                table['rows'] += 1
                table['tableRows'].append(deepcopy(table['tableRows'][0]))
            source['revisionId'] = 'fresh'
            raise rejection
        return {'writeControl': {'requiredRevisionId': 'committed'}}

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
    operation = {'type': 'delete_rows', 'row': 1}
    if race == 'text':
        assert apply(ref, base, operation).attempts == 2  # noqa: PLR2004
    else:
        reject({'overlap': 'EDIT_CONFLICT', 'structure': 'TARGET_CHANGED',
                'timeout': 'WRITE_OUTCOME_UNKNOWN',
                'exhausted': 'REVISION_RETRY_EXHAUSTED'}[race],
               lambda: apply(ref, base, operation))
        assert calls == (3 if race == 'exhausted' else 1)


def test_index_shifts_do_not_change_deletion_state(source, mock_docs):
    """Absolute index shifts are compatible even with protected ranges."""
    ref, base = baseline()

    def shift(value):
        """Move every native index without changing native cell content."""
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {'startIndex', 'endIndex'}:
                    value[key] += 7
                else:
                    shift(child)
        elif isinstance(value, list):
            for child in value:
                shift(child)

    old = native_table(source)['startIndex']
    shift(source)
    apply(ref, base, {'type': 'delete_rows', 'row': 1})
    request = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]
    assert request['deleteTableRow']['tableCellLocation'][
        'tableStartLocation']['index'] == old + 7


def test_new_reference_matches_predicted_shape(source):
    """Returned guards include the changed same-section table inventory."""
    ref, base = baseline()
    result = apply(ref, base, {'type': 'insert_rows', 'row': 1,
                               'position': 'before'})
    table = native_table(source)['table']
    table['rows'] += 1
    table['tableRows'].insert(0, deepcopy(table['tableRows'][0]))
    fresh = Layout(source)
    assert encode(fresh.reference(fresh.entries[0])) == result.table_ref
    assert digest(ref) != digest(result.table_ref)


def test_insertion_does_not_reserve_snapshot_content(source):
    """An insertion changes geometry without discarding edited cell text."""
    ref, base = baseline(fields=['content'])
    cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'new collaborator text\n'
    assert apply(ref, base, {'type': 'insert_rows', 'row': 1,
                             'position': 'after'}).committed_batches == 1


def test_nested_footnote_object_metadata_is_guarded(source):
    """The image referenced inside a removed footnote is also protected."""
    cell(source)['content'][0]['paragraph']['elements'].append({
        'footnoteReference': {'footnoteId': 'note'},
    })
    source['footnotes'] = {'note': {'content': [{
        'paragraph': {'elements': [
            {'inlineObjectElement': {'inlineObjectId': 'image'}},
        ]},
    }]}}
    source['inlineObjects'] = {'image': {'title': 'Original'}}
    entry = Layout(source).entries[0]
    original = deletion_state(source, entry, 0, 0)
    source['inlineObjects']['image']['title'] = 'Changed'
    assert deletion_state(source, entry, 0, 0) != original


def test_deletion_checks_neighbor_border(source, mock_docs):
    """The surviving side of a removed shared edge is a dependency."""
    ref, base = baseline()
    cell(source, 1)['tableCellStyle']['borderTop'] = {
        'width': {'magnitude': 2, 'unit': 'PT'},
    }
    reject('EDIT_CONFLICT', lambda: apply(ref, base, {
        'type': 'delete_rows', 'row': 1,
    }))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('geometry', ['merged', 'nested'])
def test_unsupported_geometry_fails_before_writing(source, mock_docs,
                                                   geometry):
    """Never interpret physical merged cells as ordinary row coordinates."""
    if geometry == 'merged':
        cell(source)['tableCellStyle']['rowSpan'] = 2
    else:
        cell(source)['content'].append(deepcopy(native_table(source)))
    # Build refs directly because unsupported native geometry may not render.
    layout = Layout(source)
    ref = encode(layout.reference(layout.entries[0]))
    token = decode(ref, 'table', 'example').model_copy(update={
        'kind': 'base', 'expires': 9999999999, 'fields': ['content'],
        'cells': {'A1': {'content': digest('unused')}},
    })
    reject('INVALID_ARGUMENT', lambda: table_structure.apply_structure(
        'example', ref, encode(token), table_structure.InsertRows(
            type='insert_rows', row=1, position='after',
        ),
    ))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_expired_structure_baseline_without_read(mock_docs):
    """Expiry is checked before touching the native API."""
    ref, base = baseline()
    token = decode(base.base_token, 'base', 'example')
    base.base_token = encode(token.model_copy(update={'expires': 1}))
    mock_docs.get.reset_mock()
    reject('SNAPSHOT_EXPIRED', lambda: apply(ref, base, {
        'type': 'insert_rows', 'row': 1, 'position': 'after',
    }))
    mock_docs.get.assert_not_called()
