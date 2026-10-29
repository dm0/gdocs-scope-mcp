"""Read checked table positions and revision-bound pages without writes."""

# Reuse the existing OAuth boundary without a docs_edit import cycle.
# ruff: noqa: PLC0415
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from gdocs_scope_mcp.contracts import ListingPage
from gdocs_scope_mcp.documents import parsing
from gdocs_scope_mcp.documents.native_models import (
    GoogleDocumentTableCell,
)
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.tables.geometry import (
    _geometry,
    _tables,
)
from gdocs_scope_mcp.tables.references import (
    _check_revision,
    _decode,
    _digest,
    _encode,
    _fail,
    _require_revision,
    _table_token,
    _Token,
)
from gdocs_scope_mcp.tables.refs import Layout
from gdocs_scope_mcp.tables.rendering import _model
from gdocs_scope_mcp.tables.tokens import (
    address,
)

TableLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
CellLimit = Annotated[int, Field(strict=True, ge=1, le=200)]
CellPreviewLimit = Annotated[int, Field(strict=True, ge=1, le=4000)]
ReadReference = Annotated[
    str, Field(strict=True, min_length=1, max_length=8192),
]
PREVIEW_LIMIT = 200
NESTED_REF_LIMIT = 20


















def _read_fetch(doc_id, tab_id=None):
    """Read accepted cells while keeping write/snapshot fetches native."""

    from gdocs_scope_mcp.suggestions.reading import fetch, table_references
    view = fetch(clients.get_service(), doc_id, tab_id)
    _require_revision(view.document)
    _, warnings = table_references(view)
    if warnings:
        _fail('TARGET_CHANGED', 'Pending structural proposals prevent safe '
              'table positions in the accepted-content view.',
              'Read the tab with docs_read and inspect proposals using '
              'docs_suggestions_read before using table references.')
    return view.document














class TableSnapshot(BaseModel):
    """Describe positional refs; pagination still requires this revision."""

    revision_id: str
    scope: Literal['first_tab', 'selected_tab'] = 'first_tab'
    reference_lifetime: Literal['same_structure_only'] = 'same_structure_only'
    tab_id: str | None = None


class TableSummary(BaseModel):
    """Identify and preview one table without duplicating its content."""

    table_ref: str
    reference_lifetime: Literal['same_structure_only'] = 'same_structure_only'
    reference_semantics: Literal['section_position'] = 'section_position'
    section_table_number: int
    heading_id: str | None
    heading_title: str | None
    ancestor_heading_ids: list[str]
    nesting_depth: int
    parent_cell_ref: str | None
    row_count: int
    column_count: int
    has_merged_cells: bool
    geometry_valid: bool
    unsupported_edit_reasons: list[str]
    preview: str
    preview_truncated: bool


class TablesListResponse(ListingPage):
    """Return a revision-bound page of selected-tab table summaries."""

    document_id: str
    tab_id: str | None = None
    snapshot: TableSnapshot
    total_count: int
    selected_headings: list[str] | None
    unknown_heading_ids: list[str]
    tables: list[TableSummary]


class TableCellRead(BaseModel):
    """Preserve physical entries and identify covered merged slots."""

    row: int
    column: int | None
    physical_cell: int
    row_span: int | None
    column_span: int | None
    cell_ref: str | None
    address: str | None
    covered_by: str | None
    simple_text_target: bool = Field(
        description='Structurally eligible for simple text edits; this tool '
        'does not write or promise a future operation will accept the cell.',
    )
    unsupported_edit_reasons: list[str]
    markdown: str
    markdown_char_count: int
    markdown_truncated: bool
    nested_table_refs: list[str]
    nested_table_count: int
    nested_table_refs_truncated: bool


class TableRowRead(BaseModel):
    """A row may continue on another page when its cells exceed the limit."""

    row: int
    complete: bool
    cells: list[TableCellRead]


class TableReadResponse(ListingPage):
    """Page physical cells in native row order with explicit geometry."""

    document_id: str
    tab_id: str | None = None
    snapshot: TableSnapshot
    table: TableSummary
    total_cells: int
    rows: list[TableRowRead]






def _summary(document, entry, model, layout=None):
    """Create a bounded preview and explicit structural warnings."""
    geometry, valid = _geometry(entry)
    merged = any((isinstance(rs, int) and rs > 1)
                 or (isinstance(cs, int) and cs > 1)
                 for _, _, _, rs, cs, _, _ in geometry)
    nested = any('table' in item for *_, cell in geometry
                 for item in cell.get('content', []))
    reasons = []
    if not valid:
        reasons.append('unverified_geometry')
    if merged:
        reasons.append('merged_cells')
    if nested:
        reasons.append('nested_tables')
    preview = ''
    for *_, cell in geometry:
        text = GoogleDocumentTableCell.model_validate(
            deepcopy(cell),
        ).to_text(model)
        preview += (' | ' if preview else '') + text.rstrip('\n')
        if len(preview) > PREVIEW_LIMIT:
            break
    parent_ref = None
    if entry.parent_cell is not None:
        path, r, c = entry.parent_cell
        parent = next(t for t in _tables(document) if t.path == path)
        if _geometry(parent)[1]:
            parent_ref = _encode(_table_token(document, parent, 'cell',
                                              cell=[r, c], layout=layout))
    token = (layout or Layout(document)).reference(entry)
    return TableSummary(
        table_ref=_encode(token), section_table_number=token.ordinal + 1,
        heading_id=entry.headings[-1][1] if entry.headings else None,
        heading_title=entry.headings[-1][2][:80] if entry.headings else None,
        ancestor_heading_ids=[h[1] for h in entry.headings[:-1]],
        nesting_depth=(len(entry.path) - 1) // 3, parent_cell_ref=parent_ref,
        row_count=entry.item['table'].get('rows', 0),
        column_count=entry.item['table'].get('columns', 0),
        has_merged_cells=merged, geometry_valid=valid,
        unsupported_edit_reasons=reasons, preview=preview[:PREVIEW_LIMIT],
        preview_truncated=len(preview) > PREVIEW_LIMIT,
    )


def _headings(document, requested):
    """Match docs_read's root selection and unknown-heading diagnostics."""
    tree = parsing.parse_document_tree(document)
    if requested is None:
        return None, []
    found = set(requested).intersection(tree.headings)
    unknown = list(dict.fromkeys(
        h for h in requested if h not in tree.headings
    ))
    if requested and not found:
        _fail('HEADING_NOT_FOUND', 'None of the requested heading IDs exist.')
    return [h.id for h in tree.descendants() if h.id in found
            and not found.intersection(h.ancestor_ids)], unknown


def _page(document, kind, options, page_token, entry=None):
    """Bind pagination to its exact snapshot, scope and output bounds."""
    if page_token is None:
        return 0
    token = _decode(page_token, kind, document['documentId'])
    _check_revision(token, document)
    if token.options != _digest(options) or (entry is not None and (
        token.path != entry.path or token.fingerprint != _digest(entry.item)
    )):
        _fail('INVALID_ARGUMENT', 'Continuation parameters do not match.')
    return token.offset


def tables_list(doc_id, heading_ids=None, limit=50, page_token=None, *,
                tab_id=None):
    """Discover tables without returning the surrounding document text."""
    if page_token is not None:
        _decode(page_token, 'tables-page', doc_id)
    document = _read_fetch(doc_id, tab_id=tab_id)
    selected, unknown = _headings(document, heading_ids)
    entries = [t for t in _tables(document) if selected is None
               or set(selected).intersection(h[1] for h in t.headings)]
    options = [heading_ids, limit]
    offset = _page(document, 'tables-page', options, page_token)
    if offset > len(entries):
        _fail('INVALID_ARGUMENT', 'Continuation offset is outside the result.')
    page = entries[offset:offset + limit]
    end = offset + len(page)
    next_token = _encode(_Token(
        kind='tables-page', document=doc_id, revision=document['revisionId'],
        tab=document.get('_mcp_tab_id'),
        offset=end, options=_digest(options),
    )) if end < len(entries) else None
    model = _model(document)
    layout = Layout(document)
    summaries = [_summary(document, t, model, layout) for t in page]
    return TablesListResponse(
        document_id=doc_id, tab_id=document.get('_mcp_tab_id'),
        snapshot=TableSnapshot(
            revision_id=document['revisionId'],
            tab_id=document.get('_mcp_tab_id'),
            scope='selected_tab' if tab_id is not None else 'first_tab',
        ), total_count=len(entries), count=len(page),
        tables=summaries,
        next_page_token=next_token, selected_headings=selected,
        unknown_heading_ids=unknown,
    )


def table_read(doc_id, table_ref, limit=100, max_cell_chars=2000,
               page_token=None, *, tab_id=None):
    """Read bounded cell pages without creating persistent bindings."""
    token = _decode(table_ref, 'table', doc_id)
    if page_token is not None:
        _decode(page_token, 'cells-page', doc_id)
    document = _read_fetch(doc_id, tab_id=tab_id)
    layout = Layout(document)
    entries = layout.entries
    entry = layout.resolve(token)
    options = [table_ref, limit, max_cell_chars]
    offset = _page(document, 'cells-page', options, page_token, entry)
    geometry, valid = _geometry(entry)
    merged_table = any((isinstance(rs, int) and rs > 1)
                       or (isinstance(cs, int) and cs > 1)
                       for _, _, _, rs, cs, _, _ in geometry)
    if offset > len(geometry):
        _fail('INVALID_ARGUMENT', 'Continuation offset is outside the table.')
    page = geometry[offset:offset + limit]
    end = offset + len(page)
    model = _model(document)
    addresses = {(r, p): address(r, c) for r, p, c, *_ in geometry} if (
        valid
    ) else {}
    rows = {}
    for r, physical, c, rs, cs, owner, cell in page:
        is_covered = owner is not None and owner != (r, physical)
        cell_ref = _encode(layout.reference(
            entry, kind='cell', address=addresses[r, physical],
        )) if valid else None
        covered_by = (_encode(layout.reference(
            entry, kind='cell', address=addresses[owner],
        ))
                      if is_covered and valid else None)
        content = cell.get('content', [])
        nested = [t for t in entries
                  if t.parent_cell == (entry.path, r, physical)]
        reasons = []
        if not valid:
            reasons.append('unverified_geometry')
        if merged_table:
            reasons.append('merged_table')
        if is_covered:
            reasons.append('covered_slot')
        if rs != 1 or cs != 1:
            reasons.append('merged_cell')
        if nested:
            reasons.append('nested_table')
        if (len(content) != 1 or 'paragraph' not in content[0]):
            reasons.append('complex_cell_content')
        if any('textRun' not in e for item in content
               for e in item.get('paragraph', {}).get('elements', [])):
            reasons.append('non_text_elements')
        markdown = GoogleDocumentTableCell.model_validate(
            deepcopy(cell),
        ).to_markdown(model)
        # Strip only the outer td wrapper; preserve nested tables and styles.
        markdown = markdown[markdown.index('>') + 1:-len('</td>')]
        record = TableCellRead(
            row=r, column=c if valid else None, physical_cell=physical,
            row_span=rs, column_span=cs,
            cell_ref=None if is_covered else cell_ref,
            address=address(r, c) if valid and not is_covered else None,
            covered_by=covered_by, simple_text_target=not reasons,
            unsupported_edit_reasons=reasons,
            markdown=markdown[:max_cell_chars],
            markdown_char_count=len(markdown),
            markdown_truncated=len(markdown) > max_cell_chars,
            nested_table_refs=[_encode(layout.reference(t))
                               for t in nested[:NESTED_REF_LIMIT]],
            nested_table_count=len(nested),
            nested_table_refs_truncated=len(nested) > NESTED_REF_LIMIT,
        )
        rows.setdefault(r, []).append(record)
    next_token = _encode(_table_token(
        document, entry, 'cells-page', offset=end, options=_digest(options),
    )) if end < len(geometry) else None
    return TableReadResponse(
        document_id=doc_id, tab_id=document.get('_mcp_tab_id'),
        snapshot=TableSnapshot(
            revision_id=document['revisionId'],
            tab_id=document.get('_mcp_tab_id'),
            scope='selected_tab' if tab_id is not None else 'first_tab',
        ), table=_summary(document, entry, model, layout),
        total_cells=len(geometry),
        count=len(page), next_page_token=next_token,
        rows=[TableRowRead(
            row=r, cells=cells,
            complete=len(cells) == len(entry.item['table']['tableRows'][r][
                'tableCells']),
        ) for r, cells in rows.items()],
    )
