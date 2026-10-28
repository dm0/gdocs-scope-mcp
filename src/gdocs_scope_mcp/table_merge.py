"""Validate native merge/unmerge intent and never reconstruct cell contents."""

# Reuse the normal fetch boundary without import cycles.
# ruff: noqa: PLC0415

import logging

from .table_grid import Grid, content_direction, merge_state
from .table_refs import Layout, section
from .table_tokens import coordinates, encode, fail

log = logging.getLogger(__name__)


def _suggestions(value):
    """Detect tracked content/style changes before a destructive transform."""
    if isinstance(value, dict):
        return any((key.startswith('suggested') and bool(child)) or
                   _suggestions(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_suggestions(child) for child in value)
    return False


def _supported(document, grid, heads):
    """Restrict initial transforms to verified normal text paragraphs."""
    if content_direction(document, grid.entry) != 'LEFT_TO_RIGHT':
        fail('INVALID_ARGUMENT', 'Merge/unmerge currently requires an LTR '
             'native section.')
    table = grid.entry.item['table']
    if _suggestions({k: v for k, v in table.items() if k != 'tableRows'}):
        fail('INVALID_ARGUMENT', 'Suggested table changes are unsupported.')
    for head in heads:
        if _suggestions(grid.borders(head)):
            fail('INVALID_ARGUMENT', 'Suggested adjacent borders unsupported.')
        for member in grid.members[head.key]:
            cell = member.native
            if _suggestions(cell) or _suggestions({
                k: v for k, v in table['tableRows'][member.row].items()
                if k != 'tableCells'
            }):
                fail('INVALID_ARGUMENT', 'Suggested cell/row changes present.')
            content = cell.get('content', [])
            if not content:
                fail('INVALID_ARGUMENT', 'Cells must contain paragraphs.')
            for item in content:
                paragraph = item.get('paragraph')
                if (paragraph is None or paragraph.get('bullet') or
                        paragraph.get('positionedObjectIds') or any(
                            'textRun' not in e for e in paragraph.get(
                                'elements', []))):
                    fail('INVALID_ARGUMENT', 'Merge/unmerge supports ordinary '
                         'text paragraphs, without lists, objects or chips.')
                style = paragraph.get('paragraphStyle', {})
                if (style.get('namedStyleType', 'NORMAL_TEXT') != 'NORMAL_TEXT'
                        or style.get('direction') == 'RIGHT_TO_LEFT'):
                    fail('INVALID_ARGUMENT', 'Headings/RTL paragraphs are '
                         'unsupported in merge selections.')
            for group in document.get('namedRanges', {}).values():
                for named in group.get('namedRanges', []):
                    if any(r.get('startIndex', 0) < cell['endIndex'] and
                           cell['startIndex'] < r.get('endIndex', 0)
                           for r in named.get('ranges', [])):
                        fail('INVALID_ARGUMENT', 'Named ranges intersect the '
                             'selection; their movement is unsupported.')


def prepare(document, token, baseline, operation):
    """Protect every complete selected head and build one native request."""
    if token.nested:
        fail('INVALID_ARGUMENT', 'Merge/unmerge requires a top-level table.')
    entry = Layout(document).resolve(token)
    grid = Grid(entry)
    heads = grid.selection(operation.start_cell, operation.end_cell)
    if operation.type == 'merge_cells':
        if len(heads) < 2:  # noqa: PLR2004
            fail('INVALID_ARGUMENT', 'Merge needs two or more distinct cells.')
        changed = heads
    else:
        changed = [h for h in heads if h.row_span > 1 or h.column_span > 1]
        if not changed:
            fail('INVALID_ARGUMENT', 'Selection contains no merged cells.')
    for head in changed:
        if 'merge' not in baseline.cells.get(head.address, {}):
            fail('INVALID_REFERENCE', 'Snapshot needs fields=["merge"] for '
                 'every participating head address, including empty cells.')
        if baseline.cells[head.address]['merge'] != merge_state(
            document, grid, head,
        ):
            fail('EDIT_CONFLICT', 'Participating content, formatting or '
                 'boundary metadata changed.')
    _supported(document, grid, changed)
    r0, c0 = coordinates(operation.start_cell)
    r1, c1 = coordinates(operation.end_cell)
    location = {'index': entry.item['startIndex']}
    if document.get('_mcp_tab_id'):
        location['tabId'] = document['_mcp_tab_id']
    name = ('mergeTableCells' if operation.type == 'merge_cells'
            else 'unmergeTableCells')
    requests = [{name: {'tableRange': {
        'tableCellLocation': {'tableStartLocation': location,
                              'rowIndex': r0, 'columnIndex': c0},
        'rowSpan': r1 - r0 + 1, 'columnSpan': c1 - c0 + 1,
    }}}]
    return requests, [h.address for h in changed]


def refreshed_reference(doc_id, token, revision):
    """Issue an authoritative ref only for the exactly confirmed revision.

    A failed or interleaved post-write read cannot undo the successful batch.
    Return a receipt requesting rediscovery instead of guessing another table,
    failing with zero committed batches, or repeating the transformation.
    """
    from .table_read import _fetch
    try:
        document = _fetch(doc_id)
        if not revision or document['revisionId'] != revision or (
            document.get('_mcp_tab_id') != token.tab
        ):
            return None
        layout = Layout(document)
        entry = layout.sections[tuple(token.section)][token.ordinal]
        if section(entry) != tuple(token.section):
            return None
        Grid(entry)
        return encode(layout.reference(entry))
    except Exception:  # noqa: BLE001
        # This supplementary read must never hide a confirmed committed batch.
        log.warning('edit=docs_table_structure '
                    'status=reference_refresh_failed')
        return None
