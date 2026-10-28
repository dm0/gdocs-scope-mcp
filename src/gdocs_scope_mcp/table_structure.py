"""Change table geometry with checked positions and protected deletions."""

# Share the native API boundary without module import cycles.
# ruff: noqa: PLC0415

import logging
import time
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .revision_guards import MAX_ATTEMPTS, RevisionRaceError, submit
from .table_deletion_state import deletion_state
from .table_merge import prepare, refreshed_reference
from .table_refs import Layout
from .table_snapshots import resolve_cells, validate_baseline
from .table_tokens import (
    CellAddress,
    address,
    coordinates,
    decode,
    encode,
    fail,
)

log = logging.getLogger(__name__)
Count = Annotated[int, Field(strict=True, ge=1, le=100)]
Row = Annotated[int, Field(strict=True, ge=1, le=100000)]
Column = Annotated[str, Field(strict=True, pattern=r'^[A-Z]{1,5}$')]


class Operation(BaseModel):
    """Reject unknown properties and coerced structural coordinates."""

    model_config = ConfigDict(strict=True, extra='forbid')


class InsertRows(Operation):
    """Insert empty rows before or after one existing one-based row."""

    type: Literal['insert_rows']
    row: Row
    position: Literal['before', 'after']
    count: Count = 1


class InsertColumns(Operation):
    """Insert empty columns before or after one existing lettered column."""

    type: Literal['insert_columns']
    column: Column
    position: Literal['before', 'after']
    count: Count = 1


class DeleteRows(Operation):
    """Delete consecutive rows beginning at the selected one-based row."""

    type: Literal['delete_rows']
    row: Row
    count: Count = 1


class DeleteColumns(Operation):
    """Delete consecutive columns beginning at the selected column."""

    type: Literal['delete_columns']
    column: Column
    count: Count = 1


class DeleteTable(Operation):
    """Explicitly delete the entire checked table, retaining its paragraph."""

    type: Literal['delete_table']


class MergeCells(Operation):
    """Concatenate complete rectangular cells in native row-major order."""

    type: Literal['merge_cells']
    start_cell: CellAddress
    end_cell: CellAddress


class UnmergeCells(Operation):
    """Split complete merged cells, retaining their contents in their heads."""

    type: Literal['unmerge_cells']
    start_cell: CellAddress
    end_cell: CellAddress


StructureOperation = Annotated[
    InsertRows | InsertColumns | DeleteRows | DeleteColumns | DeleteTable |
    MergeCells | UnmergeCells,
    Field(discriminator='type'),
]


class StructureResponse(BaseModel):
    """Describe the committed shape without reusing old cell snapshots."""

    ok: Literal[True] = True
    document_id: str
    previous_table_ref: str
    table_ref: str | None
    revision_id: str | None
    operation: str
    affected_count: int
    deleted_cell_count: int
    rows: int
    columns: int
    attempts: int
    committed_batches: Literal[1] = 1
    snapshots_invalidated: Literal[True] = True
    section_references_invalidated: Literal[True] = True
    affected_cells: list[str] = Field(default_factory=list)
    result_head_cell: str | None = None
    content_policy: Literal[
        'row_major_paragraphs', 'keep_in_heads',
    ] | None = None
    reference_refresh_required: bool = False


def footprint(entry, operation):
    """Validate the whole operation and select exactly the removed cells."""
    table = entry.item['table']
    rows, columns = table['rows'], table['columns']
    kind = operation.type
    count = getattr(operation, 'count', 1)
    row = operation.row - 1 if hasattr(operation, 'row') else 0
    column = (coordinates(operation.column + '1')[1]
              if hasattr(operation, 'column') else 0)
    if row >= rows or column >= columns:
        fail('INVALID_ARGUMENT', 'Selected row/column is outside the table.')
    if kind == 'delete_rows':
        if row + count > rows or count == rows:
            fail('INVALID_ARGUMENT', 'Invalid row deletion; use delete_table '
                 'to remove every row.')
        selected = [address(r, c) for r in range(row, row + count)
                    for c in range(columns)]
    elif kind == 'delete_columns':
        if column + count > columns or count == columns:
            fail('INVALID_ARGUMENT', 'Invalid column deletion; use '
                 'delete_table to remove every column.')
        selected = [address(r, c) for r in range(rows)
                    for c in range(column, column + count)]
    elif kind == 'delete_table':
        selected = [address(r, c) for r in range(rows)
                    for c in range(columns)]
    else:
        selected = []
        size = ((rows + count) * columns if kind == 'insert_rows'
                else rows * (columns + count))
        if size > 100000:  # noqa: PLR2004
            fail('INVALID_ARGUMENT', 'Result exceeds 100000 logical cells.')
    if len(selected) > 100:  # noqa: PLR2004
        fail('INVALID_ARGUMENT', 'Deletion is limited to 100 cells per call.')
    return selected, row, column


def plan(document, table_token, operation):
    """Plan native requests and the new structural reference before writing."""
    simulated = deepcopy(document)
    layout = Layout(simulated)
    entry = layout.resolve(table_token)
    selected, row, column = footprint(entry, operation)
    # Also verify merged/nested geometry for insertions, which remove no cells.
    resolve_cells(simulated, table_token, selected or ['A1'])
    if table_token.nested:
        fail('INVALID_ARGUMENT', 'Structural operations require a top-level '
             'table; nested-table editing is unsupported.')
    location = {'index': entry.item['startIndex']}
    if document.get('_mcp_tab_id'):
        location['tabId'] = document['_mcp_tab_id']
    cell_location = {'tableStartLocation': location, 'rowIndex': row,
                     'columnIndex': column}
    kind, table = operation.type, entry.item['table']
    count = getattr(operation, 'count', 1)
    if kind == 'delete_table':
        bounds = {'startIndex': entry.item['startIndex'],
                  'endIndex': entry.item['endIndex']}
        if document.get('_mcp_tab_id'):
            bounds['tabId'] = document['_mcp_tab_id']
        return [{'deleteContentRange': {'range': bounds}}], None, 0, 0
    axis = 'rows' if hasattr(operation, 'row') else 'columns'
    index = row if axis == 'rows' else column
    insert = kind.startswith('insert_')
    native = ('insert' if insert else 'delete') + (
        'TableRow' if axis == 'rows' else 'TableColumn')
    body = {'tableCellLocation': cell_location}
    if insert:
        after = operation.position == 'after'
        body['insertBelow' if axis == 'rows' else 'insertRight'] = after
        index += int(after)
        empty = {'tableCellStyle': {'rowSpan': 1, 'columnSpan': 1},
                 'content': []}
        if axis == 'rows':
            table['tableRows'][index:index] = [
                {'tableCells': [deepcopy(empty)
                                for _ in range(table['columns'])]}
                for _ in range(count)
            ]
        else:
            for item in table['tableRows']:
                item['tableCells'][index:index] = [
                    deepcopy(empty) for _ in range(count)
                ]
        table[axis] += count
    else:
        if axis == 'rows':
            del table['tableRows'][index:index + count]
        else:
            for item in table['tableRows']:
                del item['tableCells'][index:index + count]
        table[axis] -= count
    # Shape hashes ignore native indices/content/styles. No post-write read
    # can accidentally identify another table after a collaborator's edit.
    new_layout = Layout(simulated)
    reference = encode(new_layout.reference(
        new_layout.by_path[tuple(entry.path)],
    ))
    return [{native: deepcopy(body)} for _ in range(count)], reference, (
        table['rows']), table['columns']


def apply_structure(doc_id, table_ref, base_token, operation):
    """Recheck the original footprint and commit one strictly guarded batch."""
    from . import docs_edit
    from .table_read import _fetch
    token = decode(table_ref, 'table', doc_id)
    baseline = decode(base_token, 'base', doc_id)
    validate_baseline(token, baseline, [], baseline.fields, subset=True)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        validate_baseline(token, baseline, [], baseline.fields, subset=True)
        document = _fetch(doc_id)
        entry = Layout(document).resolve(token)
        merging = isinstance(operation, (MergeCells, UnmergeCells))
        changed = []
        if merging:
            requests, changed = prepare(document, token, baseline, operation)
            updated, selected = None, []
            rows, columns = (entry.item['table'][key]
                             for key in ('rows', 'columns'))
        else:
            selected, _, _ = footprint(entry, operation)
            available = resolve_cells(document, token, selected or ['A1'])
            for a in selected:
                if 'deletion' not in baseline.cells.get(a, {}):
                    fail('INVALID_REFERENCE', 'Snapshot needs deletion '
                         'expectations for every removed cell.')
                r, c, _ = available[a]
                if baseline.cells[a]['deletion'] != deletion_state(
                    document, entry, r, c,
                ):
                    fail('EDIT_CONFLICT', 'Removed content/metadata changed.')
            requests, updated, rows, columns = plan(document, token, operation)
        try:
            result = submit(docs_edit._get_service(), doc_id, requests,
                            document['revisionId'], force_required=True)
        except RevisionRaceError:
            if attempt == MAX_ATTEMPTS:
                break
            log.info('edit=docs_table_structure status=revision_retry '
                     'attempt=%s', attempt)
            time.sleep(0.05 * (2 ** (attempt - 1)))
            continue
        revision = result.get('writeControl', {}).get('requiredRevisionId')
        if merging:
            updated = refreshed_reference(doc_id, token, revision)
        return StructureResponse(
            document_id=doc_id, previous_table_ref=table_ref,
            table_ref=updated, revision_id=revision, operation=operation.type,
            affected_count=(len(changed) if merging else
                            getattr(operation, 'count', 1)),
            deleted_cell_count=len(selected), rows=rows, columns=columns,
            attempts=attempt,
            affected_cells=changed,
            result_head_cell=(operation.start_cell if isinstance(
                operation, MergeCells,
            ) else None),
            content_policy=('row_major_paragraphs' if isinstance(
                operation, MergeCells,
            ) else 'keep_in_heads' if merging else None),
            reference_refresh_required=merging and updated is None,
        )
    return fail('REVISION_RETRY_EXHAUSTED', 'The structural batch lost three '
                'strict revision races; retry later with the same baseline '
                'if still valid.')
