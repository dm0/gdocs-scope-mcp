"""Verify formatting conflicts and explicit native field masks."""


# Imported pytest fixtures are requested by name in dependent fixtures/tests.
# ruff: noqa: F811

from copy import deepcopy

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp.tables import (
    formatting as table_format,
    reading as table_read,
    snapshots as table_snapshots,
)
from gdocs_scope_mcp.tables.formatting import FormatChanges
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture
def source(table_source, mock_docs):
    """Give every native style property a known, independent initial value."""
    native = table_source([('parent', 1, [['same', 'same'], ['', '']])])
    table = table_at(native)['table']
    table['tableStyle'] = {'tableColumnProperties': [
        {'widthType': 'FIXED_WIDTH',
         'width': {'magnitude': 100, 'unit': 'PT'}},
    ] * 2}
    for row in table['tableRows']:
        row['tableRowStyle'] = {'minRowHeight': {'magnitude': 0, 'unit': 'PT'}}
        for cell in row['tableCells']:
            cell['tableCellStyle'].update({
                'backgroundColor': {}, 'contentAlignment': 'TOP',
                'paddingTop': {'magnitude': 5, 'unit': 'PT'},
                'paddingBottom': {'magnitude': 5, 'unit': 'PT'},
                'paddingLeft': {'magnitude': 5, 'unit': 'PT'},
                'paddingRight': {'magnitude': 5, 'unit': 'PT'},
            })
            for side in ['Top', 'Bottom', 'Left', 'Right']:
                cell['tableCellStyle']['border' + side] = {
                    'color': {'color': {'rgbColor': {'red': 0}}},
                    'width': {'magnitude': 1, 'unit': 'PT'},
                    'dashStyle': 'SOLID',
                }
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'writeControl': {'requiredRevisionId': 'done'}, 'replies': [],
    }
    return native


def table_at(document):
    """Find the single table in the independent fixture."""
    return next(item for item in document['body']['content']
                if 'table' in item)


def cell(source, row=0, column=0):
    """Access a known native fixture cell."""
    return table_at(source)['table']['tableRows'][row]['tableCells'][column]


def baseline(fields, cells=None):
    """Read formatting values and digests through the production path."""
    ref = table_read.tables_list('example').tables[0].table_ref
    base = table_snapshots.snapshot('example', ref, cells or ['A1'], fields)
    return ref, base


def change(ref, base, changes):
    """Run typed formatting against the agent's original baseline."""
    return table_format.format_table('example', ref, base.base_token,
                                      FormatChanges.model_validate(changes))


def reject(code, operation):
    """Require a structured failure and no confirmed committed batch."""
    with pytest.raises(ToolFailureError) as caught:
        operation()
    assert caught.value.failure.code == code
    assert caught.value.failure.committed_batches == 0


@pytest.mark.usefixtures('source')
def test_snapshot_exposes_property_values_without_metadata_writes(mock_docs):
    """Agents can inspect selected style values before choosing new ones."""
    ref, base = baseline(['cell.padding_top', 'column.width',
                          'table.header_rows'])
    assert base.cells[0].formatting['cell.padding_top'][
        'magnitude'] == 5  # noqa: PLR2004
    assert base.cells[0].formatting['column.width']['width'][
        'magnitude'] == 100  # noqa: PLR2004
    assert base.cells[0].formatting['table.header_rows'] == 0
    result = call('docs_table_snapshot', doc_id='example', table_ref=ref,
                  cells=['A1'], fields=['cell.border_right'])
    assert not result.is_error
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_public_atomic_format_and_explicit_masks(mock_docs):
    """Style supported resource kinds without changing text or other fields."""
    ref, base = baseline([
        'cell.background_color', 'cell.padding_top', 'cell.vertical_alignment',
        'paragraph.alignment', 'column.width', 'row.min_height',
        'table.header_rows',
    ], ['A1', 'B2'])
    result = call('docs_table_format', doc_id='example', table_ref=ref,
                  base_token=base.base_token, changes={
                      'cells': [{'address': 'A1',
                                 'background_color': '#123456',
                                 'padding_top': 8,
                                 'vertical_alignment': 'MIDDLE',
                                 'horizontal_alignment': 'CENTER'}],
                      'columns': [{'column': 'B', 'width': 120}],
                      'rows': [{'row': 2, 'min_height': 30}], 'header_rows': 1,
                  })
    assert not result.is_error, result.structured_content
    data = result.structured_content
    assert data['applied_count'] == 4  # noqa: PLR2004
    mock_docs.batchUpdate.assert_called_once()
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert not any('insertText' in r or 'deleteContentRange' in r
                   for r in body['requests'])
    style = next(r['updateTableCellStyle'] for r in body['requests']
                 if 'updateTableCellStyle' in r)
    assert style['fields'] == 'backgroundColor,contentAlignment,paddingTop'
    assert set(style['tableCellStyle']) == {
        'backgroundColor', 'contentAlignment', 'paddingTop',
    }
    alignment = next(r['updateParagraphStyle'] for r in body['requests']
                     if 'updateParagraphStyle' in r)
    assert alignment['fields'] == 'alignment'


def test_text_and_other_properties_do_not_conflict(source, mock_docs):
    """Background changes are independent of text, padding and borders."""
    ref, base = baseline(['cell.background_color', 'cell.padding_top'])
    cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
        'content'] = 'concurrent text\n'
    cell(source)['tableCellStyle']['paddingTop']['magnitude'] = 20
    source['revisionId'] = 'concurrent'
    result = change(ref, base, {'cells': [{
        'address': 'A1', 'background_color': '#ff0000',
    }]})
    assert result.attempts == 1
    assert mock_docs.batchUpdate.call_args.kwargs['body']['writeControl'] == {
        'requiredRevisionId': 'concurrent',
    }


def test_same_property_conflicts_before_writing(source, mock_docs):
    """Never overwrite a concurrent change to the requested property."""
    ref, base = baseline(['cell.padding_top'])
    cell(source)['tableCellStyle']['paddingTop']['magnitude'] = 20
    reject('EDIT_CONFLICT', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]}))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('side', ['Top', 'Right', 'Bottom', 'Left'])
def test_different_border_is_compatible(source, mock_docs, side):
    """Unrelated borders on the same cell are separate resources."""
    ref, base = baseline(['cell.background_color'])
    cell(source)['tableCellStyle']['border' + side]['width']['magnitude'] = 3
    assert change(ref, base, {'cells': [{
        'address': 'A1', 'background_color': '#00ff00',
    }]}).committed_batches == 1
    mock_docs.batchUpdate.assert_called_once()


def test_adjacent_shared_edge_conflicts_even_when_own_edge_unchanged(source,
                                                                 mock_docs):
    """The neighbor's opposite edge is part of a border baseline."""
    ref, base = baseline(['cell.border_right'])
    cell(source, column=1)['tableCellStyle']['borderLeft']['width'][
        'magnitude'] = 3
    reject('EDIT_CONFLICT', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'border_right': {'width': 2},
    }]}))
    mock_docs.batchUpdate.assert_not_called()


def test_shared_edge_updates_coalesce(source, mock_docs):
    """Opposite half-edge updates merge only when their components agree."""
    ref, base = baseline(['cell.border_right', 'cell.border_left'],
                          ['A1', 'B1'])
    change(ref, base, {'cells': [
        {'address': 'A1', 'border_right': {'width': 2}},
        {'address': 'B1', 'border_left': {'dash_style': 'DOT'}},
    ]})
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == 1
    style = requests[0]['updateTableCellStyle']
    assert style['fields'] == 'borderRight'
    border = style['tableCellStyle']['borderRight']
    assert border['width']['magnitude'] == 2  # noqa: PLR2004
    assert border['dashStyle'] == 'DOT'
    assert border['color'] == cell(source)['tableCellStyle']['borderRight'][
        'color']


@pytest.mark.usefixtures('source')
def test_conflicting_shared_edge_updates_are_rejected(mock_docs):
    """Do not rely on Google's border update ordering to choose a winner."""
    ref, base = baseline(['cell.border_right', 'cell.border_left'],
                          ['A1', 'B1'])
    reject('INVALID_ARGUMENT', lambda: change(ref, base, {'cells': [
        {'address': 'A1', 'border_right': {'width': 2}},
        {'address': 'B1', 'border_left': {'width': 3}},
    ]}))
    mock_docs.batchUpdate.assert_not_called()


def test_unknown_inherited_border_requires_full_values(source, mock_docs):
    """Do not invent inherited color/dash values for partial writes."""
    for column in range(2):
        cell(source, column=column)['tableCellStyle'].pop(
            'borderRight' if column == 0 else 'borderLeft',
        )
    ref, base = baseline(['cell.border_right'])
    reject('INVALID_ARGUMENT', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'border_right': {'width': 2},
    }]}))
    mock_docs.batchUpdate.assert_not_called()
    assert change(ref, base, {'cells': [{'address': 'A1', 'border_right': {
        'width': 2, 'color': '#000000', 'dash_style': 'SOLID',
    }}]}).committed_batches == 1


@pytest.mark.usefixtures('source')
def test_wrong_snapshot_fields_do_not_trigger_reads(mock_docs):
    """A broad cell_style hash is insufficient for property-level updates."""
    ref, base = baseline(['cell_style'])
    mock_docs.get.reset_mock()
    reject('INVALID_REFERENCE', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]}))
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('changes', [
    {}, {'cells': []}, {'cells': [{'address': 'A1'}]},
    {'cells': [{'address': 'A1', 'padding_top': None}]},
    {'cells': [{'address': 'A1', 'padding_top': -1}]},
    {'cells': [{'address': 'A1', 'padding_top': True}]},
    {'cells': [{'address': 'A1', 'background_color': 'red'}]},
    {'cells': [{'address': 'A1', 'vertical_alignment': 'CENTER'}]},
    {'cells': [{'address': 'A1', 'border_top': {}}]},
    {'cells': [{'address': 'A1', 'border_top': {'dash_style': 'DASHED'}}]},
    {'columns': [{'column': 'a', 'width': 40}]},
    {'columns': [{'column': 'A', 'width': 4}]},
    {'rows': [{'row': 0, 'min_height': 20}]}, {'header_rows': True},
    {'header_rows': None}, {'unknown': 1},
    {'cells': [{'address': 'A1', 'padding_top': 2}] * 2},
])
def test_invalid_typed_styles_fail_before_google_reads(mock_docs, changes):
    """Reject empty, ambiguous, out-of-range and malformed typed values."""
    result = call('docs_table_format', doc_id='example', table_ref='unused',
                  base_token='unused', changes=changes)
    assert result.is_error
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


def test_formatting_race_revalidates_properties(source, mock_docs):
    """A text-only race can be retried without refreshing the baseline."""
    ref, base = baseline(['cell.padding_top'])
    rejection = HttpError(Response({'status': '400'}),
                          b'{"error":{"message":"Revision does not match"}}')
    calls = 0

    def execute():
        """Commit an independent text change before rejecting the first CAS."""
        nonlocal calls
        calls += 1
        if calls == 1:
            cell(source)['content'][0]['paragraph']['elements'][0]['textRun'][
                'content'] = 'new text\n'
            source['revisionId'] = 'new'
            raise rejection
        return {'writeControl': {'requiredRevisionId': 'done'}}

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
    result = change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]})
    assert result.attempts == 2  # noqa: PLR2004
    assert calls == 2  # noqa: PLR2004


@pytest.mark.usefixtures('source')
def test_unknown_style_write_is_never_replayed(mock_docs):
    """A timeout can hide a committed batch; inspect instead of retrying."""
    ref, base = baseline(['cell.padding_top'])
    mock_docs.batchUpdate.return_value.execute.side_effect = TimeoutError()
    reject('WRITE_OUTCOME_UNKNOWN', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]}))
    assert mock_docs.batchUpdate.call_count == 1


def test_alignment_inheritance_and_paragraph_split(source, mock_docs):
    """Track effective alignment while allowing compatible paragraph splits."""
    source['namedStyles'] = {'styles': [{
        'namedStyleType': 'NORMAL_TEXT',
        'paragraphStyle': {'alignment': 'START'},
    }]}
    ref, base = baseline(['paragraph.alignment'])
    cell(source)['content'].append(deepcopy(cell(source)['content'][0]))
    assert change(ref, base, {'cells': [{
        'address': 'A1', 'horizontal_alignment': 'CENTER',
    }]}).attempts == 1
    mock_docs.batchUpdate.reset_mock()
    source['namedStyles']['styles'][0]['paragraphStyle']['alignment'] = 'END'
    reject('EDIT_CONFLICT', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'horizontal_alignment': 'CENTER',
    }]}))
    mock_docs.batchUpdate.assert_not_called()


def test_different_edges_remain_independent(source, mock_docs):
    """Updating a top border does not reserve the right border."""
    ref, base = baseline(['cell.border_top', 'cell.border_right'])
    cell(source)['tableCellStyle']['borderRight']['width']['magnitude'] = 3
    assert change(ref, base, {'cells': [{
        'address': 'A1', 'border_top': {'width': 2},
    }]}).committed_batches == 1
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[0]['updateTableCellStyle']['fields'] == 'borderTop'


@pytest.mark.parametrize(('field', 'changes', 'native_key'), [
    ('column.width', {'columns': [{'column': 'A', 'width': 120}]}, 'column'),
    ('row.min_height', {'rows': [{'row': 1, 'min_height': 30}]}, 'row'),
    ('table.header_rows', {'header_rows': 1}, 'header'),
])
def test_resource_overlap_conflicts(source, mock_docs, field, changes,
                                    native_key):
    """Column, row and table-wide expectations guard their own resource."""
    ref, base = baseline([field])
    table = table_at(source)['table']
    if native_key == 'column':
        table['tableStyle']['tableColumnProperties'][0]['width'][
            'magnitude'] = 200
    elif native_key == 'row':
        table['tableRows'][0]['tableRowStyle']['minRowHeight'][
            'magnitude'] = 40
    else:
        table['tableRows'][0]['tableRowStyle']['tableHeader'] = True
    reject('EDIT_CONFLICT', lambda: change(ref, base, changes))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_formatting_contention_has_three_attempt_cap(mock_docs):
    """Repeated confirmed races stop without an unbounded write loop."""
    ref, base = baseline(['cell.padding_top'])
    mock_docs.batchUpdate.return_value.execute.side_effect = HttpError(
        Response({'status': '400'}),
        b'{"error":{"message":"Revision does not match"}}',
    )
    reject('REVISION_RETRY_EXHAUSTED', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]}))
    assert mock_docs.batchUpdate.call_count == 3  # noqa: PLR2004


def test_retry_detects_new_property_overlap(source, mock_docs):
    """Never replace the original expectations with state from a retry."""
    ref, base = baseline(['cell.padding_top'])

    def execute():
        """Change the guarded property just before the first CAS loses."""
        cell(source)['tableCellStyle']['paddingTop']['magnitude'] = 40
        raise HttpError(Response({'status': '400'}),
                        b'{"error":{"message":"Revision does not match"}}')

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
    reject('EDIT_CONFLICT', lambda: change(ref, base, {'cells': [{
        'address': 'A1', 'padding_top': 8,
    }]}))
    assert mock_docs.batchUpdate.call_count == 1


@pytest.mark.usefixtures('source')
def test_snapshot_pair_budget_rejects_before_google_read(mock_docs):
    """Bound token growth even for large selections of granular fields."""
    ref, _ = baseline(['content'])
    mock_docs.get.reset_mock()
    fields = ['cell.' + name for name in table_format.CELL_FIELDS]
    fields.append('paragraph.alignment')
    reject('INVALID_ARGUMENT', lambda: table_snapshots.snapshot(
        'example', ref, [f'A{row}' for row in range(1, 101)], fields,
    ))
    mock_docs.get.assert_not_called()
