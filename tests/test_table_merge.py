"""Check merged-grid ownership, selective guards and committed receipts."""

# Imported pytest fixtures are requested by name.
# ruff: noqa: F811
import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response
from pydantic import TypeAdapter

from gdocs_scope_mcp.tables import (
    reading as table_read,
    snapshots as table_snapshots,
    structure as table_structure,
)
from gdocs_scope_mcp.tables.grid import Grid
from gdocs_scope_mcp.tables.refs import Layout
from gdocs_scope_mcp.tables.tokens import decode, encode
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture
def source(table_source, mock_docs):
    """Provide independent native geometry with unique and duplicate cells."""
    native = table_source([('parent', 1, [
        ['A1', 'B1', 'same', 'same'], ['A2', '', 'C2', 'D2'],
        ['Outside', 'B3', 'C3', 'D3'],
    ])])
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'writeControl': {'requiredRevisionId': 'committed'},
    }
    return native


def table(source):
    """Locate the fixture's only table without hardcoded native indices."""
    return next(i['table'] for i in source['body']['content'] if 'table' in i)


def cell(source, row=0, column=0):
    """Access the known full-width physical representation."""
    return table(source)['tableRows'][row]['tableCells'][column]


def merged(source, *, height=1, width=2, compact=False):
    """Construct a valid merged head and optionally omit covered entries."""
    cell(source)['tableCellStyle'].update(rowSpan=height, columnSpan=width)
    for r in range(height):
        for c in range(width):
            if r == c == 0:
                continue
            run = cell(source, r, c)['content'][0]['paragraph']['elements'][0]
            run['textRun']['content'] = '\n'
    if compact:
        for r in range(height):
            del table(source)['tableRows'][r]['tableCells'][
                int(r == 0):width]


def baseline(addresses=None, fields=None):
    """Prepare native expectations through the normal snapshot path."""
    ref = table_read.tables_list('example').tables[0].table_ref
    base = table_snapshots.snapshot('example', ref, addresses or ['A1', 'B1'],
                                    fields or ['merge'])
    return ref, base


def apply(ref, base, *, kind='merge_cells', start='A1', end='B1'):
    """Run the same typed structural operation exposed through MCP."""
    adapter = TypeAdapter(table_structure.StructureOperation)
    operation = adapter.validate_python(
        {'type': kind, 'start_cell': start, 'end_cell': end},
    )
    return table_structure.apply_structure('example', ref, base.base_token,
                                            operation)


def reject(code, function):
    """Require a structured pre-write rejection."""
    with pytest.raises(ToolFailureError) as caught:
        function()
    assert caught.value.failure.code == code
    assert caught.value.failure.committed_batches == 0


@pytest.mark.parametrize('compact', [False, True])
@pytest.mark.parametrize('height', [1, 2])
def test_head_snapshots_in_verified_merged_tables(source, mock_docs, compact,
                                                 height):
    """Resolve real heads and retain their logical spans without writes."""
    merged(source, height=height, compact=compact)
    _, base = baseline(['A1', 'C1'])
    assert base.cells[0].row_span == height
    assert base.cells[0].column_span == 2  # noqa: PLR2004
    assert base.cells[1].column == 2  # noqa: PLR2004
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('compact', [False, True])
def test_covered_address_is_never_retargeted(source, mock_docs, compact):
    """Require the head address even when a covered physical entry exists."""
    merged(source, compact=compact)
    reject('INVALID_ARGUMENT', lambda: baseline(['B1']))
    mock_docs.batchUpdate.assert_not_called()


def test_merge_snapshot_renews_only_original_selected_state(source, mock_docs):
    """Validate a merged head without reserving another cell's text."""
    merged(source, height=2, compact=True)
    ref, base = baseline(['A1'])
    table(source)['tableRows'][2]['tableCells'][0]['content'][0][
        'paragraph']['elements'][0]['textRun']['content'] = 'outside\n'
    renewed = table_snapshots.snapshot('example', ref, ['A1'], ['merge'],
                                        base.base_token)
    assert renewed.validated
    cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'changed head\n'
    reject('EDIT_CONFLICT', lambda: table_snapshots.snapshot(
        'example', ref, ['A1'], ['merge'], renewed.base_token,
    ))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_merge_field_cannot_mix_with_other_groups(mock_docs):
    """Do not imply ordinary per-cell group semantics on covered geometry."""
    ref, _ = baseline()
    mock_docs.get.reset_mock()
    reject('INVALID_ARGUMENT', lambda: table_snapshots.snapshot(
        'example', ref, ['A1'], ['merge', 'content'],
    ))
    mock_docs.get.assert_not_called()


@pytest.mark.parametrize('invalid', ['covered_space', 'boolean_span'])
def test_uncertain_merged_geometry_is_rejected(source, mock_docs, invalid):
    """Do not discard hidden whitespace or coerce malformed native spans."""
    merged(source)
    if invalid == 'covered_space':
        run = cell(source, 0, 1)['content'][0]['paragraph']['elements'][0]
        run['textRun']['content'] = ' \n'
    else:
        cell(source)['tableCellStyle']['rowSpan'] = True
    reject('INVALID_ARGUMENT', lambda: baseline(['A1']))
    mock_docs.batchUpdate.assert_not_called()


def test_partial_merged_rectangle_rejected(source, mock_docs):
    """Never ask Google to expand a partial selection to unknown cells."""
    merged(source, height=2)
    ref, base = baseline(['A1'])
    reject('INVALID_ARGUMENT', lambda: apply(ref, base, kind='unmerge_cells',
                                            end='B1'))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('compact', [False, True])
def test_existing_merged_heads_can_join_a_complete_rectangle(source, mock_docs,
                                                            compact):
    """An existing merge contributes one head and its complete native state."""
    merged(source, compact=compact)
    ref, base = baseline(['A1', 'C1', 'D1'])
    result = apply(ref, base, end='D1')
    assert result.affected_cells == ['A1', 'C1', 'D1']
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert body['requests'][0]['mergeTableCells']['tableRange'][
        'columnSpan'] == 4  # noqa: PLR2004


def test_logical_coordinates_not_physical_indices(source, mock_docs):
    """A compact row's physical cell 1 still means logical column C."""
    merged(source, compact=True)
    ref, base = baseline(['C1', 'D1'])
    apply(ref, base, start='C1', end='D1')
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    location = body['requests'][0]['mergeTableCells']['tableRange'][
        'tableCellLocation']
    assert location['columnIndex'] == 2  # noqa: PLR2004


@pytest.mark.usefixtures('source')
def test_public_discriminated_input_and_atomic_request(mock_docs):
    """Expose typed merge intent without hand-built text replacement calls."""
    ref, base = baseline()
    result = call('docs_table_structure', doc_id='example', table_ref=ref,
                  base_token=base.base_token, operation={
                      'type': 'merge_cells', 'start_cell': 'A1',
                      'end_cell': 'B1',
                  })
    assert not result.is_error, result.structured_content
    data = result.structured_content
    assert data['content_policy'] == 'row_major_paragraphs'
    assert data['result_head_cell'] == 'A1'
    assert data['deleted_cell_count'] == 0
    assert data['committed_batches'] == data['attempts'] == 1
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == 1
    assert set(requests[0]) == {'mergeTableCells'}


@pytest.mark.parametrize('mutation', ['inside', 'style', 'placeholder',
                                      'neighbor', 'row', 'section'])
def test_merged_state_dependencies_reject_overlap(source, mock_docs, mutation):
    """Include physical placeholders and both sides of shared borders."""
    merged(source)
    ref, base = baseline(['A1'])
    if mutation == 'inside':
        cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
            'content'] = 'new content\n'
    elif mutation == 'style':
        cell(source)['tableCellStyle']['backgroundColor'] = {'color': {
            'rgbColor': {'red': 1},
        }}
    elif mutation == 'placeholder':
        cell(source, 0, 1)['tableCellStyle']['paddingTop'] = {
            'magnitude': 20, 'unit': 'PT',
        }
    elif mutation == 'neighbor':
        cell(source, 0, 2)['tableCellStyle']['borderLeft'] = {
            'width': {'magnitude': 2, 'unit': 'PT'},
        }
    elif mutation == 'row':
        table(source)['tableRows'][0]['tableRowStyle'] = {'tableHeader': True}
    else:
        source['body']['content'].insert(0, {'startIndex': 0, 'sectionBreak': {
            'sectionStyle': {'contentDirection': 'RIGHT_TO_LEFT'},
        }})
    reject('EDIT_CONFLICT', lambda: apply(ref, base, kind='unmerge_cells'))
    mock_docs.batchUpdate.assert_not_called()


def test_outside_content_change_is_compatible(source, mock_docs):
    """A text-only edit outside the rectangle does not reserve this merge."""
    ref, base = baseline()
    cell(source, 2)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'independent\n'
    assert apply(ref, base).committed_batches == 1
    mock_docs.batchUpdate.assert_called_once()


def test_unmerge_ignores_unchanged_heads_inside_rectangle(source, mock_docs):
    """Unmerged cells in an unmerge range are not transformation targets."""
    merged(source)
    ref, base = baseline(['A1'])
    cell(source, 0, 2)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'independent C1\n'
    result = apply(ref, base, kind='unmerge_cells', end='D1')
    assert result.affected_cells == ['A1']
    assert result.committed_batches == 1
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('unsupported', ['list', 'object', 'heading',
                                        'suggestion', 'named_range', 'rtl'])
def test_unsupported_initial_transform_fails_before_write(source, mock_docs,
                                                         unsupported):
    """Do not transform content or metadata without verified semantics."""
    if unsupported == 'list':
        cell(source)['content'][0]['paragraph']['bullet'] = {'listId': 'list'}
        source['lists'] = {'list': {'listProperties': {'nestingLevels': [
            {'glyphSymbol': '•', 'bulletAlignment': 'START'},
        ]}}}
    elif unsupported == 'object':
        cell(source)['content'][0]['paragraph']['elements'][0] = {
            'startIndex': cell(source)['startIndex'] + 1,
            'endIndex': cell(source)['endIndex'],
            'horizontalRule': {'textStyle': {}},
        }
    elif unsupported == 'heading':
        cell(source)['content'][0]['paragraph']['paragraphStyle'][
            'namedStyleType'] = 'HEADING_1'
    elif unsupported == 'suggestion':
        cell(source)['suggestedInsertionIds'] = ['pending']
    elif unsupported == 'named_range':
        source['namedRanges'] = {'code': {'namedRanges': [{
            'namedRangeId': 'range', 'name': 'code', 'ranges': [{
                'startIndex': cell(source)['startIndex'],
                'endIndex': cell(source)['endIndex'],
            }],
        }]}}
    else:
        source['body']['content'].insert(0, {'startIndex': 0, 'sectionBreak': {
            'sectionStyle': {'contentDirection': 'RIGHT_TO_LEFT'},
        }})
    # Bypass display-model requirements for deliberately unsupported payloads.
    layout = Layout(source)
    ref = encode(layout.reference(layout.entries[0]))
    from gdocs_scope_mcp.tables.grid import merge_state  # noqa: PLC0415
    grid = Grid(layout.entries[0])
    token = decode(ref, 'table', 'example').model_copy(update={
        'kind': 'base', 'expires': 9999999999, 'fields': ['merge'],
        'cells': {a: {'merge': merge_state(source, grid, grid.cell(a))}
                  for a in ['A1', 'B1']},
    })
    reject('INVALID_ARGUMENT', lambda: table_structure.apply_structure(
        'example', ref, encode(token), table_structure.MergeCells(
            type='merge_cells', start_cell='A1', end_cell='B1',
        ),
    ))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
@pytest.mark.parametrize('operation', [
    {'type': 'merge_cells', 'start_cell': 'a1', 'end_cell': 'B1'},
    {'type': 'merge_cells', 'start_cell': 'A1'},
    {'type': 'unmerge_cells', 'start_cell': 'A1', 'end_cell': 'B1',
     'count': 1},
])
def test_malformed_input_rejected_before_reads(mock_docs, operation):
    """The schema advertises strict complete A1 range selectors."""
    mock_docs.get.reset_mock()
    result = call('docs_table_structure', doc_id='example', table_ref='unused',
                  base_token='unused', operation=operation)
    assert result.is_error
    mock_docs.get.assert_not_called()


@pytest.mark.usefixtures('source')
@pytest.mark.parametrize(('kind', 'start', 'end'), [
    ('merge_cells', 'A1', 'A1'), ('merge_cells', 'B1', 'A1'),
    ('merge_cells', 'A1', 'A101'), ('merge_cells', 'A1', 'Z1'),
    ('unmerge_cells', 'A1', 'B1'),
])
def test_invalid_selection_without_writes(mock_docs, kind, start, end):
    """Reject reversed, out-of-bounds, oversized and no-op rectangles."""
    ref, base = baseline()
    reject('INVALID_ARGUMENT', lambda: apply(ref, base, kind=kind, start=start,
                                            end=end))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_all_head_expectations_required(mock_docs):
    """Do not merge an unseen empty or nonempty neighboring head."""
    ref, base = baseline(['A1'])
    reject('INVALID_REFERENCE', lambda: apply(ref, base))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('fault', ['race', 'overlap', 'exhausted', 'timeout'])
def test_shared_revision_policy(source, mock_docs, fault):
    """Replan only confirmed CAS rejection, with the original head state."""
    ref, base = baseline()
    calls = 0

    def execute():
        """Commit a collaborator's mutation in the read/write window."""
        nonlocal calls
        calls += 1
        if fault == 'timeout':
            raise TimeoutError()
        if calls == 1 or fault == 'exhausted':
            target = cell(source, 2 if fault == 'race' else 0)
            target['content'][0]['paragraph']['elements'][0]['textRun'][
                'content'] = 'collaborator\n'
            if fault == 'exhausted':
                # Pure contention must not mutate a guarded cell.
                target['content'][0]['paragraph']['elements'][0]['textRun'][
                    'content'] = 'A1\n'
            source['revisionId'] = 'new'
            raise HttpError(Response({'status': '400'}),
                            b'{"error":{"message":"Revision does not match"}}')
        return {'writeControl': {'requiredRevisionId': 'committed'}}

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
    if fault == 'race':
        assert apply(ref, base).attempts == 2  # noqa: PLR2004
    else:
        reject({'overlap': 'EDIT_CONFLICT',
                'exhausted': 'REVISION_RETRY_EXHAUSTED',
                'timeout': 'WRITE_OUTCOME_UNKNOWN'}[fault],
               lambda: apply(ref, base))
        assert calls == (3 if fault == 'exhausted' else 1)


@pytest.mark.parametrize('followup', ['current', 'changed', 'failed'])
def test_confirmed_commit_survives_post_read_race(source, mock_docs, followup):
    """A receipt never guesses a new reference or loses a confirmed batch."""
    ref, base = baseline()

    def execute():
        """Emulate the native geometry change and a later collaborator."""
        merged(source)
        source['revisionId'] = ('committed' if followup == 'current' else
                                'later')
        if followup == 'failed':
            mock_docs.get.return_value.execute.side_effect = TimeoutError()
        return {'writeControl': {'requiredRevisionId': 'committed'}}

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
    result = apply(ref, base)
    assert result.ok and result.committed_batches == 1
    if followup == 'current':
        assert result.table_ref == table_read.tables_list('example').tables[
            0].table_ref
        assert not result.reference_refresh_required
    else:
        assert result.table_ref is None
        assert result.reference_refresh_required
    mock_docs.batchUpdate.assert_called_once()
