"""Read checked table positions and revision-bound pages without writes."""

# Reuse the existing OAuth boundary without a docs_edit import cycle.
# ruff: noqa: PLC0415

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    EditFailedResponse,
    GoogleDocument,
    GoogleDocumentTableCell,
    ListingPage,
)
from .table_refs import Layout, first_tab
from .table_tokens import (
    Token,
    address,
    decode as decode_position,
    encode as encode_position,
)
from .tool_errors import ToolFailureError

TableLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
CellLimit = Annotated[int, Field(strict=True, ge=1, le=200)]
CellPreviewLimit = Annotated[int, Field(strict=True, ge=1, le=4000)]
ReadReference = Annotated[
    str, Field(strict=True, min_length=1, max_length=8192),
]
PREVIEW_LIMIT = 200
MAX_GRID_AREA = 100_000
NESTED_REF_LIMIT = 20


def _fail(code, description, action=None):
    """Give callers a safe way to reacquire a reference instead of guessing."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action=action or (
            'Read the document or call docs_tables_list and use the returned '
            'reference/page token with unchanged arguments. References are '
            'tab-scoped; page tokens require the same revision. '
            'Structural changes require fresh table refs; do not edit tokens.'
        ),
    ))


def _digest(value):
    """Hash canonical native data or cursor options without a process cache."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
    ).encode()).hexdigest()


class _Token(BaseModel):
    """Validate internal token data; tokens confer no document permissions."""

    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1] = 1
    kind: Literal['table', 'cell', 'tables-page', 'cells-page']
    document: str
    revision: str
    scope: Literal['first_tab', 'selected_tab'] = 'first_tab'
    path: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    cell: list[Annotated[int, Field(ge=0)]] | None = None
    fingerprint: str = ''
    offset: Annotated[int, Field(ge=0)] = 0
    options: str = ''
    tab: str | None = None


def _encode(token):
    """Use versioned, portable opaque references with a corruption checksum."""
    if isinstance(token, Token):
        return encode_position(token)
    payload = token.model_dump(exclude_defaults=True)
    data = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    encoded = base64.urlsafe_b64encode(data).decode().rstrip('=')
    return 'gdt1.' + encoded + '.' + hashlib.sha256(data).hexdigest()[:16]


def _unpack(value):
    """Validate transport encoding separately from document/tool policy."""
    if len(value) > 8192:  # noqa: PLR2004
        raise ValueError('Oversized token')
    prefix, payload, checksum = value.split('.')
    if prefix != 'gdt1':
        raise ValueError('Unsupported token version')
    data = base64.b64decode(payload + '=' * (-len(payload) % 4),
                            altchars=b'-_', validate=True)
    if hashlib.sha256(data).hexdigest()[:16] != checksum:
        raise ValueError('Invalid token checksum')
    return _Token.model_validate_json(data)


def _decode(value, kind, doc_id):
    """Reject malformed, mismatched and wrong-kind tokens before API access."""
    if kind in {'table', 'cell'}:
        return decode_position(value, kind, doc_id)
    try:
        token = _unpack(value)
    except (ValueError, TypeError, ValidationError):
        _fail('INVALID_ARGUMENT', 'Invalid reference or continuation token '
              'for this document/tool.')
    if token.kind != kind or token.document != doc_id:
        _fail('INVALID_ARGUMENT', 'Reference has a different tool/document.')
    return token


def _check_revision(token, document):
    """Reject stale references without reusing an old structural path."""
    from .document_tabs import require_matching_tab
    require_matching_tab(token.tab, document.get('_mcp_tab_id'))
    if token.revision != document['revisionId']:
        _fail('STALE_REFERENCE', 'The reference revision is not current.')


def _fetch(doc_id, tab_id=None):
    """Read the selected tab through the normal read-only API boundary."""
    from . import docs_edit
    document = first_tab(docs_edit._get_document(
        docs_edit._get_service(), doc_id, tab_id=tab_id,
    ))
    _require_revision(document)
    return document


def _read_fetch(doc_id, tab_id=None):
    """Read accepted cells while keeping write/snapshot fetches native."""
    from . import docs_edit
    from .suggestions import fetch, table_references
    view = fetch(docs_edit._get_service(), doc_id, tab_id)
    _require_revision(view.document)
    _, warnings = table_references(view)
    if warnings:
        _fail('TARGET_CHANGED', 'Pending structural proposals prevent safe '
              'table positions in the accepted-content view.',
              'Read the tab with docs_read and inspect proposals using '
              'docs_suggestions_read before using table references.')
    return view.document


def _require_revision(document):
    """Do not issue misleading revision-bound references without metadata."""
    if not isinstance(document.get('revisionId'), str) or not document[
        'revisionId'
    ]:
        _fail('REVISION_UNAVAILABLE', 'Table references require a document '
              'revision, which this read did not return.',
              'Verify edit access: Google returns revision IDs only to '
              'editors. Refresh the document after access is corrected.')


def _text(item):
    """Read source heading text without exposing indices or Markdown markup."""
    return ''.join(e.get('textRun', {}).get('content', '')
                   for e in item.get('paragraph', {}).get('elements', []))


@dataclass
class _Table:
    """Keep a native structural path private to the current snapshot."""

    item: dict
    path: list[int]
    headings: list[tuple[int, str, str]]
    parent_cell: tuple[list[int], int, int] | None = None


def _tables(document):
    """Walk tables in preorder, retaining nesting paths and heading scope."""
    def walk(content, path, inherited, parent=None):
        """Use independent heading stacks inside cells, retaining ancestry."""
        headings = list(inherited)
        for index, item in enumerate(content):
            style = item.get('paragraph', {}).get('paragraphStyle', {})
            heading = style.get('headingId')
            if heading:
                kind = style.get('namedStyleType', '')
                level = int(kind[-1]) if kind.startswith('HEADING_') else 0
                headings = [h for h in headings if h[0] < level]
                headings.append((level, heading, _text(item).rstrip('\n')))
            if 'table' not in item:
                continue
            current = [*path, index]
            yield _Table(item, current, list(headings), parent)
            for r, row in enumerate(item['table'].get('tableRows', [])):
                for c, cell in enumerate(row.get('tableCells', [])):
                    yield from walk(cell.get('content', []),
                                    [*current, r, c], headings,
                                    (current, r, c))
    return list(walk(document.get('body', {}).get('content', []), [], []))


def _table_token(document, entry, kind='table', *, layout=None, **updates):
    """Describe a checked position or an exact-revision page cursor."""
    if kind in {'table', 'cell'}:
        cell = updates.get('cell')
        cell_address = None
        if cell is not None:
            geometry, valid = _geometry(entry)
            value = next(x for x in geometry if x[:2] == tuple(cell))
            if not valid:
                _fail('INVALID_ARGUMENT', 'Cell geometry is not verified.')
            cell_address = address(value[0], value[2])
        return (layout or Layout(document)).reference(
            entry, kind=kind, address=cell_address,
        )
    return _Token(kind=kind, document=document['documentId'],
                  revision=document['revisionId'], path=entry.path,
                  tab=document.get('_mcp_tab_id'),
                  fingerprint=_digest(entry.item), **updates)


def reference_map(document):
    """Supply HTML table references without any document writes."""
    entries = _tables(document)
    if entries:
        _require_revision(document)
    layout = Layout(document)
    return {entry.item['startIndex']: _encode(layout.reference(entry))
            for entry in entries}


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


def _geometry(entry):
    """Map spans conservatively, preserving API placeholder entries."""
    table = entry.item['table']
    height, width = table.get('rows', 0), table.get('columns', 0)
    rows = table.get('tableRows', [])
    valid = (len(rows) == height and height > 0 and width > 0
             and height * width <= MAX_GRID_AREA)
    if not valid:
        return [(r, c, c, cell.get('tableCellStyle', {}).get('rowSpan'),
                 cell.get('tableCellStyle', {}).get('columnSpan'), None, cell)
                for r, row in enumerate(rows)
                for c, cell in enumerate(row.get('tableCells', []))], False
    occupied = {}
    result = []
    for r, row in enumerate(rows):
        cells = row.get('tableCells', [])
        explicit = len(cells) == width
        cursor = 0
        for physical, cell in enumerate(cells):
            if explicit:
                c = physical
            else:
                while (r, cursor) in occupied:
                    cursor += 1
                c = cursor
            style = cell.get('tableCellStyle', {})
            rs, cs = style.get('rowSpan'), style.get('columnSpan')
            owner = occupied.get((r, c)) if explicit else None
            result.append((r, physical, c, rs, cs, owner, cell))
            if not all(isinstance(n, int) and n > 0 for n in (rs, cs)):
                valid = False
                continue
            if owner is not None:
                # A covered physical slot must not introduce another span.
                nonempty = any(_text(item).strip() or 'table' in item
                               or any('textRun' not in e for e in
                                      item.get('paragraph', {}).get(
                                          'elements', []))
                               for item in cell.get('content', []))
                if rs != 1 or cs != 1 or nonempty:
                    valid = False
                continue
            if (r + rs > height or c + cs > width
                    or rs * cs > MAX_GRID_AREA):
                valid = False
                continue
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    if (rr, cc) in occupied:
                        valid = False
                    occupied[rr, cc] = (r, physical)
            cursor = c + cs
    valid = valid and len(occupied) == height * width
    return result, valid


def _model(document):
    """Render shared Markdown while leaving the native snapshot untouched."""
    return GoogleDocument.model_validate(deepcopy({
        **document, 'table_refs': reference_map(document),
    }))


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
    from .docs_edit import _parse_document_tree
    tree = _parse_document_tree(document)
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
