"""Thin MCP adapters for tables."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from typing import Annotated

from pydantic import Field

from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.tables import (
    formatting as table_format,
    patch as table_patch,
    reading as table_read,
    snapshots as table_snapshots,
    structure as table_structure,
)
from gdocs_scope_mcp.tables.formatting import FormatChanges, FormatResponse
from gdocs_scope_mcp.tables.patch import CellPatches, PatchResponse
from gdocs_scope_mcp.tables.reading import (
    CellLimit,
    CellPreviewLimit,
    ReadReference,
    TableLimit,
    TableReadResponse,
    TablesListResponse,
)
from gdocs_scope_mcp.tables.snapshots import SnapshotResponse
from gdocs_scope_mcp.tables.structure import (
    StructureOperation,
    StructureResponse,
)
from gdocs_scope_mcp.tables.tokens import (
    CellAddress,
    SnapshotFields,
    SnapshotToken,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema

TableCells = Annotated[
    list[CellAddress], Field(min_length=1, max_length=100),
]


def register(mcp):
    """Register tables tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(TablesListResponse),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_tables_list(
        doc_id: str, heading_ids: list[str] | None = None,
        limit: TableLimit = 50, page_token: ReadReference | None = None,
        *, tab_id: TabId | None = None,
    ) -> TablesListResponse:
        """Discover native tables in the selected tab without returning full text.

        Summaries use accepted content without applying pending suggestions.
        TARGET_CHANGED means structural proposals prevent safe native refs;
        inspect docs_read and docs_suggestions_read before retrying.

        Returns compact summaries: opaque table_ref, nearest heading context,
        dimensions, nesting/parent-cell reference, merged geometry warnings and
        a preview of at most 200 Unicode code points. Tables are in preorder,
        including nested tables. heading_ids follows docs_read subtree semantics:
        null=whole selected tab, []=none; unknown IDs are reported.
        All-unknown heading selections fail.

        limit is 1-100 tables (default 50). count is page size, total_count covers
        matching tables. Follow next_page_token with exactly the same arguments.
        Table refs describe the Nth table in its direct heading section. Text/style
        changes preserve refs; count/order/structural changes in that section
        require fresh discovery (TARGET_CHANGED). Swapping structurally identical
        tables retains position meaning, not original object identity. Page tokens
        require the same revision (STALE_REFERENCE). No named ranges or writes.
        tab_id selects a top-level or nested tab; omit it for the first tab.
        """
        return table_read.tables_list(doc_id, heading_ids, limit, page_token,
                                      tab_id=tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(TableReadResponse),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_table_read(
        doc_id: str, table_ref: ReadReference, limit: CellLimit = 100,
        max_cell_chars: CellPreviewLimit = 2000,
        page_token: ReadReference | None = None,
        *, tab_id: TabId | None = None,
    ) -> TableReadResponse:
        """Inspect a table reference from docs_read or docs_tables_list.

        Cell Markdown uses accepted content without applying pending suggestions.
        Structural proposals that prevent verified native refs fail explicitly
        with TARGET_CHANGED. Write planning/snapshots retain native coordinates.

        Returns rows/cells, A1 address, cell_ref, zero-based coordinates and spans,
        physical_cell positions, merged-slot covered_by and unsupported-edit
        reasons. No raw Google indices are returned. Unknown geometry has null
        columns/cell refs; covered placeholders have no independent cell_ref.
        simple_text_target is structural eligibility, not an available write tool.

        limit bounds physical cells, not rows (1-200, default 100). A wide row can
        span pages; rows.complete explicitly reports this. max_cell_chars bounds
        each Markdown preview to 1-4000 Unicode code points (default 2000).
        markdown_char_count and markdown_truncated disclose clipping; a clipped
        preview may cut HTML/code syntax and must not be used as complete content.
        Nested table HTML and nested_table_refs carry table references. At most
        20 immediate child refs are returned per cell; nested_table_count and
        nested_table_refs_truncated disclose omissions. Discover more via the list.

        Follow next_page_token with the same table_ref, limit and max_cell_chars.
        count is cells on this page, total_cells includes physical covered slots.
        Cursors require the same revision. Table refs survive text/style edits;
        changes to the section table structure inventory require fresh discovery.
        Table refs identify section positions, including structurally identical
        replacements/swaps. Use docs_table_snapshot with A1 addresses to check
        selected content/properties. This selected-tab read writes nothing.
        """
        return table_read.table_read(doc_id, table_ref, limit, max_cell_chars,
                                     page_token, tab_id=tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(SnapshotResponse),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_table_snapshot(
        doc_id: str, table_ref: ReadReference, cells: TableCells,
        fields: SnapshotFields | None = None,
        base_token: SnapshotToken | None = None,
        *, tab_id: TabId | None = None,
    ) -> SnapshotResponse:
        """Issue or validate selected-cell expected-state snapshots.

        Accepts 1-100 distinct uppercase A1 addresses, e.g. ["A1", "B2"].
        Validates the table's heading hierarchy, ordinal and structural inventory
        against a fresh read. The position must retain the same table structure;
        row/column/table insertion, deletion or merge requires fresh discovery.
        Snapshots require verified geometry without nested cell tables. Ordinary
        groups require unmerged geometry. fields=["merge"] exclusively supports
        merged tables: select real logical head addresses, never covered slots.
        It protects full native participating state, physical placeholders,
        referenced metadata, enclosing direction, styles and adjacent borders.
        Returns row_span/column_span for each selected cell.
        fields selects content, text_style, paragraph_style, cell_style, structure,
        deletion (full removed-cell state for docs_table_structure)
        or merge, or granular formatting fields:
        cell.background_color/vertical_alignment,
        cell.padding_top/bottom/left/right, cell.border_top/bottom/left/right,
        paragraph.alignment, column.width, row.min_height, table.header_rows.
        Formatting fields use their full dotted names, e.g. cell.padding_top.
        Each shared-border snapshot includes its adjacent opposite side.
        Formatting native values are returned in each cell's formatting object.
        A cell anchors its column, row and table-wide properties respectively.
        Maximum 1000 cell/field pairs per snapshot.
        Defaults to content/text_style/paragraph_style. Only selected cells and
        field groups are checked, so independent cell edits and index shifts pass.

        Omit base_token to issue expectations; pass it later with the same cell set
        and fields to validate. Returns selected cell Markdown (up to 2000 Unicode
        code points each, full lengths/truncation flags), current coordinates,
        renewed base_token,
        revision_id, expires_at (Unix UTC seconds), and validated. Default token
        lifetime is 24 hours, configurable. Tokens are portable checksummed state,
        not signed capabilities; no local key or document bindings are used.
        Expired/corrupt tokens,
        changed/deleted/ambiguous targets and property conflicts fail explicitly.
        Reads/validates only. Use the returned state to prepare docs_table_patch.
        Markdown patches require content and text_style expectations; defaults
        include both. Patches revalidate internally and use strict CAS.
        """
        return table_snapshots.snapshot(
            doc_id, table_ref, cells,
            fields or ['content', 'text_style', 'paragraph_style'], base_token,
            tab_id=tab_id,
        )


    @mcp.tool(
        output_schema=tool_response_schema(PatchResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': True,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_table_patch(
        doc_id: str, table_ref: ReadReference, base_token: SnapshotToken,
        changes: CellPatches,
        *, tab_id: TabId | None = None,
    ) -> PatchResponse:
        """Replace selected Markdown cells in one strictly guarded atomic batch.

        changes is 1-100 objects {address:"A1", markdown:"new **text**"}; an empty
        string clears a cell. Use a docs_table_snapshot base_token containing at
        least content and text_style expectations. Changes can select a subset of
        its cells; every supplied field group is checked for affected cells only.

        Supports inline emphasis, underline, strike, links, inline code, super/sub
        and br soft breaks in single-paragraph unmerged text cells. Blocks, lists,
        images, chips, suggestions and complex targets fail before any write.
        Replaces inline text styles, retaining paragraph/cell properties and the
        mandatory final newline. At most 100000 total Markdown characters and
        1000 native requests; previews are bounded to 200 Unicode code points.

        Rechecks table position/structure and selected state at each attempt,
        recalculates UTF-16 positions and uses requiredRevisionId even when the
        server's general revision mode is target. Up to three attempts after
        confirmed revision races; independent cell edits/index shifts are allowed.
        Overlap returns EDIT_CONFLICT; changed layout returns TARGET_CHANGED;
        exhausted contention returns REVISION_RETRY_EXHAUSTED. An unknown write
        outcome is never retried automatically; inspect the document first.

        Receipts include applied_count, per-cell text previews/full character and
        UTF-16 counts, attempts, committed_batches and resulting revision_id.
        An all-empty-to-empty patch makes no write (committed_batches=0).
        Section-position semantics and identical-table swap limits still apply.
        """
        return table_patch.patch(doc_id, table_ref, base_token, changes,
                                 tab_id=tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(FormatResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': True,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_table_format(
        doc_id: str, table_ref: ReadReference, base_token: SnapshotToken,
        changes: FormatChanges,
        *, tab_id: TabId | None = None,
    ) -> FormatResponse:
        """Apply explicit style changes in one strictly guarded atomic batch.

        changes contains optional cells, columns, rows and header_rows. Cells use
        A1 addresses and background_color (#RRGGBB or transparent), padding_top /
        bottom/left/right in points, vertical_alignment TOP/MIDDLE/BOTTOM,
        horizontal_alignment START/CENTER/END/JUSTIFIED, and
        border_top/bottom/left/right
        objects with color, width in points and dash_style SOLID/DOT/DASH.
        Columns use letters and width (>=5 points or auto); rows use 1-based row
        and min_height in points. header_rows is a count, including 0 to unpin.
        Omitted properties are preserved; explicit nulls/empty updates are invalid.
        Up to 100 cell/row/column/table targets, verified unmerged geometry only.

        Obtain a docs_table_snapshot with matching granular fields first. A cell
        anchors row/column/table fields; include at least one cell in each row or
        column being changed. Only explicitly changed properties are compared;
        unrelated text/styles remain compatible. Borders are atomic shared
        resources: both sides are checked. Partial border components require
        readable matching omitted values; otherwise specify the full border.
        Conflicting updates to the same shared border fail before writing.

        Always requiredRevisionId, up to three revalidated attempts after confirmed
        races, regardless of general revision mode. EDIT_CONFLICT means a changed
        property, TARGET_CHANGED a changed table/layout, REVISION_RETRY_EXHAUSTED
        contention. WRITE_OUTCOME_UNKNOWN is never replayed automatically.
        Receipts identify updated properties, applied target count, attempts and
        resulting revision. No content edits or snapshot/binding metadata writes.
        """
        return table_format.format_table(doc_id, table_ref, base_token, changes,
                                         tab_id=tab_id)


    @mcp.tool(
        output_schema=tool_response_schema(StructureResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': True,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_table_structure(
        doc_id: str, table_ref: ReadReference, base_token: SnapshotToken,
        operation: StructureOperation,
        *, tab_id: TabId | None = None,
    ) -> StructureResponse:
        """Change a checked top-level table's structure in one atomic batch.

        One typed operation per call: insert_rows (row, position before/after,
        count=1), insert_columns (column, position, count=1), delete_rows (row,
        count=1), delete_columns (column, count=1), delete_table, merge_cells or
        unmerge_cells (start_cell, end_cell inclusive logical A1 rectangle).
        Row numbers
        are 1-based, columns uppercase letters; counts are 1-100. References bind
        the structure and insertion boundary, not stale native indices.
        Row/column/table operations require verified unmerged geometry without
        nested tables; at most 100000 logical cells after insertion. Deleting all
        rows/columns requires delete_table.

        Obtain docs_table_snapshot first. Insertions need any cell snapshot and
        do not reserve text/styles. Deletions require fields=["deletion"] covering
        EVERY removed cell (maximum 100 cells). This protects full native cell
        content/styles, referenced objects/list/dropdown metadata, named ranges,
        effective named styles and row/column/table formatting. Other cells may
        change independently. Row/column/table operations still require unmerged
        geometry. Nested tables remain unsupported.

        Merge/unmerge require fields=["merge"] snapshots for every participating
        logical head (up to 100 logical slots), including empty cells. Unmerge
        checks only merged heads; already unmerged cells in its rectangle remain
        independent. Rectangles
        must contain entire existing merged cells. LTR sections and normal text
        paragraphs only; lists, headings, chips/objects, named ranges intersecting
        the selection and tracked suggestions fail before writing. Merge retains
        native paragraph order by head row/column in the upper-left head; empty
        cells add no paragraph. Existing text styles and soft breaks are retained;
        native head/merged-cell formatting rules apply. Unmerge keeps each merged
        cell's whole contents in its own head, creating empty other cells. It does
        not reconstruct the pre-merge contents. Unmerge with no merged cells fails.

        Strict requiredRevisionId even in target mode. Up to three attempts after
        confirmed revision races, always rechecking the original expectations and
        fresh indices. Structure changes in the same section return TARGET_CHANGED;
        changed deleted state returns EDIT_CONFLICT. An unknown write outcome is
        never replayed. Empty rows/columns inherit Google's native formatting.

        Returns the committed revision, updated table_ref and dimensions (null/0
        after deletion), attempts, counts and committed_batches=1. Updated refs
        describe this committed structure; later structural edits can invalidate
        them. All old cell snapshots and section table references are invalidated;
        reread/snapshot before another edit. No post-write mutation stage or hidden
        metadata/bindings are used. Table deletion retains the preceding paragraph.
        Merge/unmerge return affected_cells, result_head_cell and content_policy.
        Their updated ref uses an authoritative read only at the confirmed write
        revision. If that read fails or a collaborator writes first, ok remains
        true with committed_batches=1, table_ref=null and
        reference_refresh_required=true: rediscover/snapshot; do not repeat the
        committed operation. A null ref means deletion only for delete_table.
        """
        return table_structure.apply_structure(
            doc_id, table_ref, base_token, operation, tab_id=tab_id,
        )
