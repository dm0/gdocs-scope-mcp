"""Validate operation-specific expectations at checked table/cell positions."""

# Share the native read boundary without an import cycle.
# ruff: noqa: PLC0415
import time
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from gdocs_scope_mcp.documents.native_models import GoogleDocumentTableCell
from gdocs_scope_mcp.settings import get_settings
from gdocs_scope_mcp.tables.deletion_state import deletion_state
from gdocs_scope_mcp.tables.grid import Grid, merge_state
from gdocs_scope_mcp.tables.refs import Layout
from gdocs_scope_mcp.tables.style_state import property_state, property_value
from gdocs_scope_mcp.tables.tokens import address, decode, digest, encode, fail


def cell_state(document, cell):
    """Separate content/styles from absolute cell positions."""
    from gdocs_scope_mcp.revision_guards import _normalized
    content, text_styles, paragraph_styles, shape = [], [], [], []
    kinds, list_ids = set(), set()
    for item in cell.get('content', []):
        paragraph = item.get('paragraph', {})
        values, styles, elements = [], [], []
        for element in paragraph.get('elements', []):
            normalized = _normalized(element)
            run = normalized.get('textRun')
            if run is not None:
                text = run.get('content', '')
                if values and isinstance(values[-1], str):
                    values[-1] += text
                else:
                    values.append(text)
                styles.append([len(text.encode('utf-16-le')) // 2,
                               run.get('textStyle', {})])
                elements.append('text')
            else:
                values.append(normalized)
                elements.append(sorted(normalized))
        content.append(values)
        text_styles.append(styles)
        bullet = paragraph.get('bullet')
        paragraph_styles.append([paragraph.get('paragraphStyle', {}), bullet])
        if bullet and bullet.get('listId'):
            list_ids.add(bullet['listId'])
        kinds.add(paragraph.get('paragraphStyle', {}).get('namedStyleType',
                                                          'NORMAL_TEXT'))
        shape.append(elements)
    styles = document.get('namedStyles', {}).get('styles', [])
    named_styles = [s for s in styles if s.get('namedStyleType') in kinds]
    list_styles = {i: document.get('lists', {}).get(i) for i in list_ids}
    return {'content': digest(content),
            'text_style': digest([text_styles, named_styles]),
            'paragraph_style': digest([paragraph_styles, named_styles,
                                       list_styles]),
            'cell_style': digest(cell.get('tableCellStyle', {})),
            'structure': digest([shape, cell.get('tableCellStyle', {}).get(
                'rowSpan'), cell.get('tableCellStyle', {}).get('columnSpan')])}


class CellLocation(BaseModel):
    """Report addresses alongside zero-based diagnostic coordinates."""

    address: str
    row: int
    column: int
    markdown: str
    markdown_char_count: int
    markdown_truncated: bool
    formatting: dict[str, Any] = Field(default_factory=dict)
    row_span: int = 1
    column_span: int = 1


class SnapshotResponse(BaseModel):
    """Issue or validate expectations for selected positional cells."""

    document_id: str
    tab_id: str | None = None
    table_ref: str
    revision_id: str
    base_token: str
    expires_at: int
    fields: list[str]
    cells: list[CellLocation]
    validated: bool


def validate_baseline(table, baseline, cells, fields, *, subset=False):
    """Validate expected scope/expiry before any native read or write."""
    if baseline.expires <= int(time.time()):
        fail('SNAPSHOT_EXPIRED', 'The selected-cell snapshot has expired.')
    original = baseline.model_copy(update={
        'kind': 'table', 'expires': 0, 'fields': [], 'cells': {},
    })
    selected = set(cells)
    matches = (selected <= set(baseline.cells) if subset else
               selected == set(baseline.cells))
    if original != table or baseline.fields != fields or not matches:
        fail('INVALID_REFERENCE', 'Snapshot table/cells/fields differ.')


def resolve_cells(document, table, selected, *, merged=False):
    """Resolve current positions only after checking structural guards."""
    from gdocs_scope_mcp.tables.geometry import _geometry
    entry = Layout(document).resolve(table)
    if merged:
        grid = Grid(entry)
        return {a: (head.row, head.column, head.native) for a in selected
                for head in [grid.cell(a)]}
    geometry, valid = _geometry(entry)
    if (not valid or any(rs != 1 or cs != 1 for _, _, _, rs, cs, _, _ in
                         geometry) or any('table' in child
                         for *_, cell in geometry
                         for child in cell.get('content', []))):
        fail('INVALID_ARGUMENT', 'Cell snapshots/patches require verified '
             'unmerged geometry without nested tables in cells.')
    available = {address(r, c): (r, c, cell)
                 for r, _, c, _, _, _, cell in geometry}
    if not set(selected) <= set(available):
        fail('INVALID_ARGUMENT', 'Selected address is outside the table.')
    return {key: available[key] for key in selected}


def validate_states(document, baseline, available):
    """Compare only affected cells and the baseline's explicit field groups."""
    entry = (Layout(document).resolve(baseline)
             if any('.' in f or f in {'deletion', 'merge'}
                    for f in baseline.fields)
             else None)
    grid = Grid(entry) if 'merge' in baseline.fields else None
    for selected, (row, column, cell) in available.items():
        state = cell_state(document, cell)
        if entry is not None:
            state.update({f: property_state(entry, row, column, f, document)
                          for f in baseline.fields if '.' in f})
        if 'deletion' in baseline.fields:
            state['deletion'] = deletion_state(document, entry, row, column)
        if grid is not None:
            state['merge'] = merge_state(document, grid, grid.cell(selected))
        expected = baseline.cells[selected]
        if (set(expected) != set(baseline.fields) or
                any(expected[field] != state[field]
                    for field in baseline.fields)):
            fail('EDIT_CONFLICT', 'Selected content or properties changed.')


def snapshot(doc_id, table_ref, cells, fields, base_token=None, *,
             tab_id=None):
    """Resolve a checked position and validate selected dependencies."""
    from gdocs_scope_mcp.tables.fetching import _fetch
    from gdocs_scope_mcp.tables.rendering import _model
    table = decode(table_ref, 'table', doc_id)
    requested = sorted(set(fields))
    if 'merge' in requested and requested != ['merge']:
        fail('INVALID_ARGUMENT', 'Use fields=["merge"] separately from other '
             'snapshot groups.')
    if len(cells) * len(requested) > 1000:  # noqa: PLR2004
        fail('INVALID_ARGUMENT', 'At most 1000 cell/field pairs per snapshot.')
    baseline = decode(base_token, 'base', doc_id) if base_token else None
    if len(set(cells)) != len(cells):
        fail('INVALID_ARGUMENT', 'Duplicate cell addresses are not allowed.')
    if baseline is not None:
        validate_baseline(table, baseline, cells, requested)
    document = _fetch(doc_id, tab_id=tab_id)
    available = resolve_cells(document, table, cells,
                              merged=requested == ['merge'])
    if baseline is not None:
        validate_states(document, baseline, available)
    model = _model(document)
    entry = (Layout(document).resolve(table)
             if any('.' in f or f in {'deletion', 'merge'} for f in requested)
             else None)
    grid = Grid(entry) if requested == ['merge'] else None
    states, locations = {}, []
    for selected in cells:
        r, c, cell = available[selected]
        state = cell_state(document, cell)
        formatting = {}
        if entry is not None:
            formatting = {f: property_value(entry, r, c, f, document)
                          for f in requested if '.' in f}
            state.update({f: property_state(entry, r, c, f, document)
                          for f in formatting})
        if 'deletion' in requested:
            state['deletion'] = deletion_state(document, entry, r, c)
        if grid is not None:
            state['merge'] = merge_state(document, grid, grid.cell(selected))
        states[selected] = {field: state[field] for field in requested}
        markup = GoogleDocumentTableCell.model_validate(
            deepcopy(cell),
        ).to_markdown(model)
        markup = markup[markup.index('>') + 1:-len('</td>')]
        locations.append(CellLocation(
            address=selected, row=r, column=c, markdown=markup[:2000],
            markdown_char_count=len(markup),
            markdown_truncated=len(markup) > 2000,  # noqa: PLR2004
            formatting=formatting,
            row_span=cell.get('tableCellStyle', {}).get('rowSpan', 1),
            column_span=cell.get('tableCellStyle', {}).get('columnSpan', 1),
        ))
    issued = table.model_copy(update={
        'kind': 'base', 'fields': requested, 'cells': states,
        'expires': (int(time.time()) +
                    get_settings().table_snapshot_ttl_seconds),
    })
    return SnapshotResponse(
        document_id=doc_id, tab_id=document.get('_mcp_tab_id'),
        table_ref=table_ref,
        revision_id=document['revisionId'], base_token=encode(issued),
        expires_at=issued.expires, fields=requested, cells=locations,
        validated=baseline is not None,
    )
