"""
Expose surgical Google Docs editing tools over MCP.

Exposes Google Docs and Drive operations as MCP tools.

Core abstraction: search-by-text, not by character index.
LLMs describe WHAT they want to change; the server figures out WHERE.
All edits use real batchUpdate — version history, comments, and
suggestions are preserved.

Tools:
  Editing:  docs_get, docs_search_replace, docs_insert_after,
            docs_insert_before, docs_delete_paragraph, docs_append,
            docs_batch_replace
  Comments: native anchored threads, replies, post editing, resolve/reopen
            and deletion
  Manage:   docs_list, docs_create

Auth (in priority order):
  1. GOOGLE_DOCS_MCP_TOKEN env var   — standalone token (auth_setup.py)
  2. GOOGLE_DRIVE_MCP_TOKEN env var  — backward-compatible alias
  3. GOOGLE_DOCS_TOKEN_FILE env var  — legacy gog alias
  4. ~/.google-docs-mcp/token.json   — default standalone location
  5. ~/.google-drive-mcp/token.json  — backward-compatible fallback
  6. GOG_KEYRING_PASSWORD env var    — auto-export from gog CLI

Setup:
  gdocs-scope-mcp-auth --credentials ~/credentials.json
  gdocs-scope-mcp-auth --credentials ~/credentials.json --headless  # no
  browser
  GOOGLE_DOCS_MCP_CLIENT_ID=... GOOGLE_DOCS_MCP_CLIENT_SECRET=...
  gdocs-scope-mcp-auth

Transport: stdio (Claude Desktop / OpenClaw MCP config)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Annotated

from fastmcp import FastMCP
from googleapiclient.discovery import build
from pydantic import BaseModel, Field, TypeAdapter

from . import (
    comments,
    docs_edit,
    entity_edit,
    table_format,
    table_patch,
    table_read,
    table_snapshots,
    table_structure,
)
from .diagnostics import ServerInfo, capture_server_info
from .document_tabs import TabId, TabsResponse
from .entities import (
    DropdownOptions,
    EntityDetails,
    EntityEditResponse,
)
from .models import (
    AddCommentResponse,
    AppendSucceedResponse,
    BatchReplaceResponse,
    CreateDocumentResponse,
    DeleteCommentReplyResponse,
    DeleteCommentResponse,
    DeleteParagraphResponse,
    DocumentOutline,
    DocumentSubset,
    EditCommentResponse,
    EditFailedResponse,
    InsertSucceedResponse,
    ListDocumentsResponse,
    ReadCommentsResponse,
    ReopenCommentResponse,
    ReplaceSucceedResponse,
    ReplyCommentResponse,
    ResolveCommentResponse,
)
from .settings import code_formatting, get_settings
from .table_format import FormatChanges, FormatResponse
from .table_patch import CellPatches, PatchResponse
from .table_read import (
    CellLimit,
    CellPreviewLimit,
    ReadReference,
    TableLimit,
    TableReadResponse,
    TablesListResponse,
)
from .table_snapshots import SnapshotResponse
from .table_structure import StructureOperation, StructureResponse
from .table_tokens import CellAddress, SnapshotFields, SnapshotToken
from .tool_inputs import (
    CodeBlockStyle,
    CodeBlockThemeBackground,
    CommentActionText,
    CommentLimit,
    CommentText,
    ExpectedRevision,
    NonemptyText,
    PositiveInteger,
    ReplacementOccurrence,
    Replacements,
    TableBorders,
)
from .tool_logging import ToolCallLoggingMiddleware, configure_logging

SERVER_INFO = capture_server_info()
TableCells = Annotated[
    list[CellAddress], Field(min_length=1, max_length=100),
]


def _tool_response_schema(success_model: type[BaseModel]) -> dict:
    """Expose success/error objects without FastMCP's result wrapper."""
    schema = TypeAdapter(success_model | EditFailedResponse).json_schema(
        mode='serialization',
    )
    # Both branches are objects. Explicitly stating this prevents FastMCP
    # from treating the union as a non-object result that needs wrapping.
    return {'type': 'object', **schema}


mcp = FastMCP(
    name='gdocs-scope-mcp',
    version=SERVER_INFO.package_version,
    middleware=[ToolCallLoggingMiddleware()],
    instructions="""
Surgical Google Docs editing — search by text, never by character index.

ERRORS:
    Failures set isError=true and return {ok:false, code, description,
    suggested_action}. Follow suggested_action; verify document/comment state
    before retrying a failed write.

DOCUMENT TABS:
    Start with docs_get_tree(doc_id): it returns the first tab's headings and
    the complete tabs inventory. For a single-tab document, continue reading
    and editing with tab_id omitted; no separate tab discovery call is needed.
    If several tabs exist, the first tab's outline is already available.
    To switch to another tab, call docs_get_tree with its tab_id for its own
    headings, then pass that same tab_id on subsequent read/edit/table/entity
    calls. docs_tabs_list is optional when only the tab inventory is needed.
    Omitted/null selects the first root tab, not a previously selected tab.
    Explicit missing IDs fail without fallback. Heading IDs, matches,
    named ranges and chip definitions are local to the selected tab. Table
    refs, snapshots and page tokens cannot be reused in another tab. Revision
    IDs remain document-wide. Even native replace-all affects one tab only.
    Drive file and comment-thread operations remain document-wide.
    docs_read returns tab_count; partial=false means the entire selected tab,
    not every document tab. TAB_MISMATCH means the supplied reference and
    selected tab differ: follow its suggested_action to fix the selector or
    obtain a reference in the intended tab. Do not edit opaque tokens.

CONCURRENT EDITS:
    Server setting write_revision_mode selects required (default) or target.
    Required uses requiredRevisionId, up to three validated attempts, and
    rejects changed/deleted/ambiguous targets. Append uses the current end.
    Target sends targetRevisionId from the original read and lets Google merge
    concurrent changes, including overlaps; no local conflict guarantee or
    automatic retry of rejected target revisions. Google controls append order.
    expected_revision_id always enforces a strict required revision and
    disables retries, in either configured mode. Multi-stage table insertion
    always uses required revisions because later stages require known cursors.
    Completed stages and external side effects are not replayed. Unknown write
    outcomes require inspection. committed_batches counts confirmed Docs
    batches. The default guard covers the backend read/write window;
    expected_revision_id can also protect an agent's earlier read.
    Native replace-all retains execution-time matching and accepts no such
    precondition. Native comment batches independently confirm ALL_SAVED;
    failed or unknown comment persistence is never automatically replayed.

DIAGNOSTICS:
    server_info            Read process identity and startup source fingerprint

EDIT RECEIPTS:
    Text edits and comment mutations identify document_id, scope, and
    heading_id.
    at_index is diagnostic only. Text previews have explicit full lengths and
    truncation flags; batch/deletion preview lists contain at most 100 items.
    Use applied/deleted_count for totals, not preview-list lengths. Targeted
    replacements report the complete pre-edit match count in the effective
    scope, including occurrence=1. Native replace-all reports only changes.

EDITING TOOLS:
    Rich insertion accepts reader HTML for bold, italic, underline and aligned
    paragraphs. Heading-ID anchors are metadata, not visible inserted text or
    IDs to reuse. Other wrappers retain child text without unsupported styles;
    this does not provide complete formatting round trips. rich=False keeps
    the original markup literal.
    Smart chips are inline HTML spans in docs_read:
    <span data-mcp-entity="person" data-mcp-id="..."
    data-mcp-email="alice@example.com">Alice</span>.
    All three rich insertion tools recreate native chips from these spans;
    data-mcp-id is not reused. Supported kinds/properties are person/email,
    richLink/URI, dateElement/timestamp and dropdown/definition+option IDs.
    The HTML attributes are data-mcp-email, data-mcp-uri, data-mcp-timestamp,
    data-mcp-definition-id and optional data-mcp-option-id respectively.
    Dates also preserve data-mcp-date-format, data-mcp-time-format,
    data-mcp-time-zone and data-mcp-locale; new dates default to ISO format.
    Labels are resolved by Google, not editable text runs. Dropdown definitions
    must already exist in the selected destination tab. Use docs_get_entity for
    native metadata/options, docs_create_dropdown_definition for new templates,
    and docs_select_dropdown to change only one existing instance.
    Receipts expose inserted_entity_count and one U+FFFC per smart chip.
    Smart-chip writes are revision-guarded without automatic retries. Text
    edits must not cross chip boundaries; paragraph deletion refuses chips.
    Markdown links, recognized bare HTTP(S) URLs, autolinks and HTML a[href]
    become native link styles. Markdown strikethrough and HTML del/s become
    native strikethrough. Both combine with supported inline emphasis and
    apply only to their text ranges.
    Native ordered/unordered lists preserve item paragraphs and homogeneous
    nesting and multiple ordinary paragraphs per item, including continuations
    after nested lists. Continuations have no marker and do not increment
    numbering. Loose lists use 6 pt above paragraphs; tight lists use zero.
    Empty items, custom start numbers, mixed ordered/unordered nesting and
    arbitrary blocks inside items fail before writes. List receipts exclude
    temporary nesting tabs. Reads cannot reconstruct logical item membership
    from indentation alone.
    Markdown images and HTML img[src] insert native inline images using public
    HTTP(S) URLs (PNG/JPEG/GIF; Google's size limits apply). HTML width/height
    accept positive pixel numbers; CSS sizes and responsive sources fail before
    writes. Alt/title are not native metadata. Receipts expose
    inserted_image_count and U+FFFC image placeholders in text/counts.
    Local images require upload_local_images=True. This explicitly permits
    temporary My Drive root files and anyone-with-link reader access; sources
    are deleted after insertion. Check temporary_image_cleanup_pending for
    failed deletions. Do not repeat a successful insertion to clean them up.
    Inline code and fenced/indented code blocks, including HTML code/pre, use
    Roboto Mono by default; inline code defaults to green #188038. The server
    config can override the code font and inline color. Blocks preserve line
    breaks, blank lines and indentation;
    declared languages use Pygments highlighting with the configurable default
    theme. Unknown/absent languages stay plain monospace. Blocks default to
    line spacing 1.0 with theme backgrounds off; both are configurable.
    Inline code is unaffected by block layout settings and works in list items;
    code blocks inside list items fail before writes.
    Optional code_block_style and code_block_theme_background override code
    formatting for this call. Omitted/null values inherit server settings
    (including environment overrides). Explicit False disables the background.

    docs_get_tree          Read hierarchical document tree (headings)
    docs_read              Read document contents (paragraphs + plain)
    docs_tabs_list         Discover top-level and nested document tabs
    docs_tables_list       Discover selected-tab tables and previews
    docs_table_read        Read table/cell pages and geometry
    docs_table_snapshot    Issue/validate selective cell-state expectations
    docs_table_patch       Atomically replace selected Markdown cells
    docs_table_format      Atomically change explicit table style properties
    docs_table_structure   Insert/delete rows, columns or a whole table
    docs_search_replace    Find and replace text (occurrence-targeted or all)
    docs_insert_after      Insert text after a specified paragraph anchor text
    docs_insert_before     Insert text before a specified paragraph anchor text
    docs_delete_paragraph  Delete a paragraph matching the specified anchor
    docs_append            Append paragraph at the end of a document
    docs_batch_replace     Multiple replacements atomically (one API call)

COMMENT TOOLS:
  docs_add_comment       Add comment anchored to specific text
  docs_read_comments     List all comments with anchor/resolve status
  docs_reply_to_comment  Reply to an existing comment
  docs_resolve_comment   Resolve (close) a comment, optionally with reply
  docs_delete_comment    Delete a native comment thread
  docs_reopen_comment    Reopen a native thread
  docs_edit_comment      Edit a head post or reply
  docs_delete_comment_reply Delete an ordinary reply

DOCUMENT MANAGEMENT:
  docs_list              List recent docs (optional search query)
  docs_create            Create a new document

SURGICAL GOOGLE DOCS EDITING WORKFLOW:
  1. Always run 'docs_get_tree' first to inspect the structural outline and
     gather heading IDs and the tabs inventory in one call. With one tab,
     continue without tab_id. With several tabs, reuse the first tab's outline
     or select another tab with docs_get_tree(doc_id, tab_id=...). Use heading
     IDs from that tab and retain its tab_id on subsequent calls. Omitted
     tab_id always selects the first tab; it never remembers earlier choices.
  2. Use 'docs_read' with specific 'heading_ids' to fetch content chunks
     instead of downloading massive documents all at once.
  3. Identify section scopes using the HTML heading ID tags (<a id="...">) and
     choose distinct text phrases within those sections as editing anchors.
  4. docs_search_replace / docs_insert_after / etc. — make targeted edits
  5. docs_get_tree / docs_read — verify changes
  For review: docs_add_comment → docs_read_comments → docs_resolve_comment

All edits preserve version history. Use short, distinctive anchor_text
(a few unique words) for reliable text matching and combine with heading ids
to further reduce the scope.
""".strip(),
)


# @mcp.tool
# def docs_full_tree(doc_id: str) -> DocumentTree:
#     """
#     Fetch a Google Doc and return structured representation.

# Use this tool FIRST when encountering a document to locate target sections
# via their heading IDs, avoiding the need to read a massive document all at
#     once.

#     Args:
#         doc_id: Google Doc ID (from the URL: /document/d/{DOC_ID}/edit)
#     """
#     return docs_edit.get_full_tree(doc_id)


@mcp.tool(
    output_schema=_tool_response_schema(ServerInfo),
    title='Server info',
    annotations={
        'readOnlyHint': True,
        'destructiveHint': False,
        'openWorldHint': False,
        'idempotentHint': True,
    },
)
def server_info() -> ServerInfo:
    """Return startup identity and source fingerprint without Google access."""
    return SERVER_INFO


@mcp.tool(
    output_schema=_tool_response_schema(DocumentOutline),
    annotations={
        'readOnlyHint': True,
        'destructiveHint': False,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_get_tree(doc_id: str, *,
                  tab_id: TabId | None = None) -> DocumentOutline:
    """
    Fetch a Google Doc's structural outline as a JSON object.

    The object contains document_id, title, revision_id, and a flat sections
    collection. Each section has id, title, level, and ancestor_ids. Hierarchy
    is represented by ancestor_ids, not nested section objects. Body
    paragraphs are omitted.

    tab_id selects a root or nested tab; omitted selects the first tab.
    Discover IDs with docs_tabs_list. Heading IDs are local to that tab.
    The tabs array lists ALL root and nested tabs with tab_id, title,
    parent_tab_id, depth and sibling index, including the selected tab.
    A single entry means this is the document's only tab. The inventory and
    selected outline come from the same read; sections belong only to tab_id.

    Use this tool FIRST when encountering a document to locate target sections
    via their heading IDs, avoiding the need to read a massive document all at
    once.
    With one tab, continue without tab_id or another discovery call. With
    several tabs, reuse these headings for the first tab, or call this tool
    with another tab_id to obtain that tab's headings before editing it.

    Args:
        doc_id: Google Doc ID (from the URL: /document/d/{DOC_ID}/edit)
    """
    return docs_edit.get_tree(doc_id, tab_id=tab_id)


@mcp.tool(
    output_schema=_tool_response_schema(TabsResponse),
    annotations={'readOnlyHint': True, 'destructiveHint': False,
                 'idempotentHint': True, 'openWorldHint': True},
)
def docs_tabs_list(doc_id: str) -> TabsResponse:
    """List root and nested tabs with IDs, titles, parents and order.

    Pass tab_id to document read/edit, table and entity tools. Omitted tab_id
    means the first document tab. Explicit missing IDs never fall back.
    Tab discovery is read-only; revision IDs remain document-wide.
    """
    return docs_edit.tabs_list(doc_id)


@mcp.tool(
    output_schema=_tool_response_schema(DocumentSubset),
    annotations={
        'readOnlyHint': True,
        'destructiveHint': False,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_read(
    doc_id: str, heading_ids: list[str] | None = None, *,
    tab_id: TabId | None = None,
) -> DocumentSubset | EditFailedResponse:
    """
    Read the selected Google document tab's content converted to Markdown.

    Native people, resource, date and dropdown chips remain identifiable HTML
    spans with data-mcp-entity and data-mcp-id, rather than ordinary labels or
    links. Pass a span to a rich insertion tool to create a native instance.
    Use docs_get_entity for complete properties, source ranges and dropdown
    options. tab_id selects a root or nested tab; omit for the first tab.
    Discover IDs with docs_tabs_list; returned tab_id identifies this view.

    Table HTML includes data-mcp-table-ref, including nested tables. Pass a
    reference to docs_table_read for bounded structured cells and A1 addresses.
    Refs describe checked section positions, not persistent object identity:
    heading ID hierarchy + table ordinal + section table structure inventory.
    Text/style changes preserve refs; structural changes require fresh refs.
    Swapping structurally identical tables preserves position meaning.
    Snapshot checks compare selected cells/fields, allowing independent edits.
    Reads/snapshots create no bindings or files and write no metadata.

    You can read the entire selected tab, or isolate sections by passing
    a list of target heading_ids, including their nested subsections.
    Isolating sections reduces token usage on large files.

    Args:
        doc_id: Google Doc ID from the URL.
        heading_ids: Optional list of heading IDs to fetch.
            Pass null or omit this field to read the whole selected tab.
            An empty list returns no sections. Duplicate IDs and selected
            descendants of selected ancestors are collapsed in document order.

    Returns
    -------
        Document metadata and sections [{heading_id, markdown}], effective
        selected_headings, unknown_heading_ids, partial and tab_count. The
        tab_count includes root and nested tabs; one means the only tab.
        partial=false means the whole selected tab, not all document tabs.
        Call docs_get_tree to choose among other tabs. Whole-tab reads
        include the preamble with heading_id=null. Mixed selections return
        valid content and diagnostics; all-unknown selections fail with
        HEADING_NOT_FOUND. Refresh IDs with docs_get_tree after that error.
        Code reads use configured inline font/color matching, validated block
        markers, and a configurable block-formatting heuristic enabled by
        default. Recognized code omits visual style wrappers and preserves
        literal block whitespace. Only marked blocks retain a language;
        formatting heuristics never guess it. Reading does not create markers.
    """
    if isinstance(heading_ids, str):
        heading_ids = [heading_ids]
    return docs_edit.read(doc_id, heading_ids, tab_id=tab_id)


@mcp.tool(
    output_schema=_tool_response_schema(TablesListResponse),
    annotations={'readOnlyHint': True, 'destructiveHint': False,
                 'idempotentHint': True, 'openWorldHint': True},
)
def docs_tables_list(
    doc_id: str, heading_ids: list[str] | None = None,
    limit: TableLimit = 50, page_token: ReadReference | None = None,
    *, tab_id: TabId | None = None,
) -> TablesListResponse:
    """Discover native tables in the selected tab without returning full text.

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
    output_schema=_tool_response_schema(TableReadResponse),
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
    output_schema=_tool_response_schema(SnapshotResponse),
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
    output_schema=_tool_response_schema(PatchResponse),
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
    output_schema=_tool_response_schema(FormatResponse),
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
    output_schema=_tool_response_schema(StructureResponse),
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


@mcp.tool(
    output_schema=_tool_response_schema(EntityDetails),
    annotations={'readOnlyHint': True, 'destructiveHint': False,
                 'idempotentHint': True, 'openWorldHint': True},
)
def docs_get_entity(
    doc_id: str, entity_id: NonemptyText, tab_id: TabId | None = None,
) -> EntityDetails | EditFailedResponse:
    """Inspect a native smart chip identified by docs_read's data-mcp-id.

    Returns kind, native ID, tab, revision, original UTF-16 source range,
    complete API metadata and the shared dropdown definition/options when
    applicable. Defaults to the first tab. Source indices are diagnostic;
    labels are not editable text runs. Reads do not modify the document.
    """
    return entity_edit.get_entity(doc_id, entity_id, tab_id)


@mcp.tool(
    output_schema=_tool_response_schema(EntityEditResponse),
    annotations={'readOnlyHint': False, 'destructiveHint': False,
                 'idempotentHint': False, 'openWorldHint': True},
)
def docs_create_dropdown_definition(
    doc_id: str, title: NonemptyText, options: DropdownOptions,
    tab_id: TabId | None = None,
) -> EntityEditResponse | EditFailedResponse:
    """Create a reusable native dropdown definition with 2-50 typed options.

    Options have display_value and optional #RRGGBB foreground_color and
    background_color. Returns dropdown_definition with definition/option IDs.
    Does not insert an instance or change existing definitions. Defaults to
    the first tab. Use the returned IDs in smart-chip HTML for the insertion
    tools. Writes are revision-guarded; inspect state after unknown outcomes
    before retrying, since creating another definition is not idempotent.
    """
    return entity_edit.create_dropdown_definition(
        doc_id, title, options, tab_id,
    )


@mcp.tool(
    output_schema=_tool_response_schema(EntityEditResponse),
    annotations={'readOnlyHint': False, 'destructiveHint': False,
                 'idempotentHint': False, 'openWorldHint': True},
)
def docs_select_dropdown(
    doc_id: str, entity_id: NonemptyText, option_id: NonemptyText,
    tab_id: TabId | None = None, expected_option_id: str | None = None,
) -> EntityEditResponse | EditFailedResponse:
    """Select an existing option on one native dropdown instance by ID.

    Does not change the shared definition or other instances. Obtain IDs
    from docs_read and docs_get_entity. expected_option_id optionally refuses
    an intervening selection change. Defaults to the first tab. Writes use
    the freshly read revision; concurrent changes fail without blind retries.
    Inspect state after ambiguous transport failures before retrying a write.
    """
    return entity_edit.select_dropdown(
        doc_id, entity_id, option_id, tab_id, expected_option_id,
    )


@mcp.tool(
    output_schema=_tool_response_schema(ReplaceSucceedResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': True,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
# Preserve the public positional calling convention.
def docs_search_replace(  # noqa: PLR0917
    doc_id: str,
    find: NonemptyText,
    replace: str,
    occurrence: ReplacementOccurrence = 1,
    heading_id: str | None = None,
    regex: bool = False,
    *, tab_id: TabId | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> ReplaceSucceedResponse | EditFailedResponse:
    """
    Find text and replace.

    Uses configured write_revision_mode: required validates targets with up to
    three attempts; target delegates concurrent/overlapping edits to Google.
    expected_revision_id forces a strict required revision without retries.
    Unknown writes and rejected target revisions are not replayed.

    Preserves history using batchUpdate.
    Replace-all (occurrence=0) is only supported if regex=False and heading_id
    is None.

    Args:
        doc_id:     Google Doc ID
        find:       Text to search for (or regex pattern if regex=True)
        replace:    Text to replace it with
        occurrence: Occurrence number to replace, 1-based (default 1 = first).
                    Use 2 for the second, etc. Use 0 to replace ALL
                    occurrences. Replace all is only supported in non regular
                    expression mode (regex=False) and heading_id is None.
        heading_id: Restrict search and replacement to this heading and its
                    subheadings. Use docs_get_tree to find heading IDs.
        regex:      If True, treat `find` as a Python regular expression

    Returns
    -------
        A structured object with ok, replaced (up to 80 characters), at_index,
        occurrences_found, and occurrences_changed. Targeted replacements
        populate at_index and occurrences_found; replace-all populates
        occurrences_changed. Unused index/count fields are null.
        Includes document_id, scope, heading_id, applied (changes),
        replaced_char_count (Unicode code points), and preview_truncated.
        occurrences_found_complete is True for every targeted replacement;
        occurrences_found counts all pre-edit matches in the effective scope,
        while applied=1, including when replace is empty (deletion).
        Native replace-all has occurrences_found=null and completeness=False;
        replaced previews the search string.
        Targeted matching is case-insensitive; native literal replace-all
        is case-sensitive. at_index is diagnostic only.
    """
    return docs_edit.search_replace(
        doc_id, find, replace, occurrence, heading_id, regex,
        expected_revision_id=expected_revision_id, tab_id=tab_id,
    )


@mcp.tool(
    output_schema=_tool_response_schema(InsertSucceedResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_insert_after(
    doc_id: str,
    anchor: NonemptyText,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, tab_id: TabId | None = None,
    upload_local_images: bool = False, table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert a new paragraph immediately after the paragraph containing `anchor`.

    Configured required mode validates an unchanged, unique anchor with up to
    three attempts; target lets Google merge overlapping changes without local
    conflict checks or retries. expected_revision_id forces strict required.
    Table stages always use required; completed stages/unknown writes are not
    replayed. Inspect partial results.

    The anchor is matched case-insensitively as a substring of the paragraph.

    The search can be scoped to the specified heading and nested subheadings.

    Rich formatting is ON by default. Set rich=False to insert literal text.

    Converts Markdown paragraphs and # / ## / ### / ... headings, with
    **bold**, *italic*, and ***bold italic*** inline styles. Heading mapping:
    # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on. Native homogeneous
    lists, rectangular Markdown/HTML tables, Markdown images and HTML img[src]
    are supported. Tables preserve inline formatting, br line breaks and
    column alignment;
    merged/nested tables and block content in cells are unsupported. Tables
    use multiple revision-guarded batches; failures may leave partial content.
    Read before retrying. Images require public HTTP(S) PNG/JPEG/GIF URLs;
    alt/title metadata is not preserved. HTML width/height accept pixel
    numbers.
    Inline code and blocks default to Roboto Mono, with inline color #188038;
    font/color are configurable on the server. Blocks preserve literal
    whitespace. Declared languages use Pygments (theme default); highlighting
    is configurable on the server. Unknown/absent languages stay plain.
    HTML code/pre are supported; blocks inside list items are unsupported.

    Args:
        doc_id: Google Doc ID
        anchor: A unique, distinctive string of text within the target
            paragraph. Choose a longer phrase to avoid accidental matches.
        text:   Text to insert as the new paragraph
        heading_id: Narrow down search to this heading and subheadings
        rich:   If True (default), convert Markdown using the shared converter
        upload_local_images: Allow absolute local image paths/file URLs.
            Uploads to My Drive root, temporarily grants anyone-with-link
            read access, inserts, then deletes sources. Defaults to False.
            Ignored with rich=False. See temporary_image_cleanup_pending.
        table_borders: Show borders on new tables (default True).
            False hides outer and internal borders. Ignored with rich=False.
        code_block_style: Pygments theme, e.g. default or monokai.
            Omitted/null inherits config/environment. Ignored with rich=False.
        code_block_theme_background: Apply paragraph theme background.
            Omitted/null inherits server config/environment; False disables it.
            Ignored with rich=False.

    Returns
    -------
        A receipt with document_id, scope, heading_id, ok, anchor,
        insert_position, diagnostic at_index, rich, and inserted_text.
        inserted_text is a preview of up to 200 Unicode code points;
        inserted_image_count counts native images; previews use U+FFFC per
        image. inserted_char_count includes placeholders and paragraph breaks;
        preview_truncated signals omitted text. The anchor preview is at most
        80 code points, with anchor_char_count and anchor_preview_truncated.
    """
    with code_formatting(style=code_block_style,
                         theme_background=code_block_theme_background):
        return docs_edit.insert_after(
            doc_id, anchor, text, heading_id=heading_id, rich=rich,
            upload_local_images=upload_local_images,
            table_borders=table_borders,
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        )


@mcp.tool(
    output_schema=_tool_response_schema(InsertSucceedResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_insert_before(
    doc_id: str,
    anchor: NonemptyText,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, tab_id: TabId | None = None,
    upload_local_images: bool = False, table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert a new paragraph immediately before the paragraph containing

    `anchor`.

    Configured required mode validates an unchanged, unique anchor with up to
    three attempts; target lets Google merge overlapping changes without local
    conflict checks or retries. expected_revision_id forces strict required.
    Table stages always use required; completed stages/unknown writes are not
    replayed. Inspect partial results.

    The anchor is matched case-insensitively as a substring of the paragraph.

    The search can be scoped to the specified heading and nested subheadings.

    Rich formatting is ON by default. Set rich=False to insert literal text.

    Converts Markdown paragraphs and # / ## / ### / ... headings, with
    **bold**, *italic*, and ***bold italic*** inline styles. Heading mapping:
    # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on. Native homogeneous
    lists, rectangular Markdown/HTML tables, Markdown images and HTML img[src]
    are supported. Tables preserve inline formatting, br line breaks and
    column alignment;
    merged/nested tables and block content in cells are unsupported. Tables
    use multiple revision-guarded batches; failures may leave partial content.
    Read before retrying. Images require public HTTP(S) PNG/JPEG/GIF URLs;
    alt/title metadata is not preserved. HTML width/height accept pixel
    numbers.
    Inline code and blocks default to Roboto Mono, with inline color #188038;
    font/color are configurable on the server. Blocks preserve literal
    whitespace. Declared languages use Pygments (theme default); highlighting
    is configurable on the server. Unknown/absent languages stay plain.
    HTML code/pre are supported; blocks inside list items are unsupported.

    Args:
        doc_id: Google Doc ID
        anchor: Text to search for to find the target paragraph
        text:   Text to insert as the new paragraph
        heading_id: Narrow down search to this heading and subheadings
        rich:   If True (default), convert Markdown using the shared converter
        upload_local_images: Allow absolute local image paths/file URLs.
            Uploads to My Drive root, temporarily grants anyone-with-link
            read access, inserts, then deletes sources. Defaults to False.
            Ignored with rich=False. See temporary_image_cleanup_pending.
        table_borders: Show borders on new tables (default True).
            False hides outer and internal borders. Ignored with rich=False.
        code_block_style: Pygments theme, e.g. default or monokai.
            Omitted/null inherits config/environment. Ignored with rich=False.
        code_block_theme_background: Apply paragraph theme background.
            Omitted/null inherits server config/environment; False disables it.
            Ignored with rich=False.

    Returns
    -------
        A receipt with document_id, scope, heading_id, ok, anchor,
        insert_position, diagnostic at_index, rich, and inserted_text.
        inserted_text is a preview of up to 200 Unicode code points;
        inserted_image_count counts native images; previews use U+FFFC per
        image. inserted_char_count includes placeholders and paragraph breaks;
        preview_truncated signals omitted text. The anchor preview is at most
        80 code points, with anchor_char_count and anchor_preview_truncated.
    """
    with code_formatting(style=code_block_style,
                         theme_background=code_block_theme_background):
        return docs_edit.insert_before(
            doc_id, anchor, text, heading_id=heading_id, rich=rich,
            upload_local_images=upload_local_images,
            table_borders=table_borders,
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        )


@mcp.tool(
    output_schema=_tool_response_schema(DeleteParagraphResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': True,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_delete_paragraph(
    doc_id: str, anchor: NonemptyText,
    *, tab_id: TabId | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> DeleteParagraphResponse:
    """
    Delete the paragraph(s) containing `anchor` text.

    Configured required mode validates original targets/styles with up to three
    attempts. Target lets Google merge overlapping changes without local
    conflict checks or retries. expected_revision_id forces strict required.
    Unknown writes and rejected target revisions are not replayed.

    Deletes ALL paragraphs that contain the anchor string (case-insensitive).
    If the anchor matches only one paragraph, only that paragraph is deleted.
    The required final Body newline remains as an empty paragraph. Clearing
    final paragraph content counts as one deletion; an already-empty final
    paragraph is skipped and is not counted.

    Args:
        doc_id: Google Doc ID
        anchor: Text to search for in paragraphs to delete

    Returns
    -------
        A structured object with ok, deleted_count, and deleted (paragraph
        previews up to 80 characters each, in reverse document order).
        Includes document_id, scope, and heading_id. At most 100 previews are
        returned, with aligned deleted_char_counts (full display-text Unicode
        code-point lengths excluding trailing newlines) and
        deleted_preview_truncated flags. deleted_truncated signals omitted
        previews; deleted_count includes all removed/cleared paragraphs.
    """
    return DeleteParagraphResponse.model_validate(
        docs_edit.delete_paragraph(
            doc_id, anchor, expected_revision_id=expected_revision_id,
            tab_id=tab_id,
        ),
    )


@mcp.tool(
    output_schema=_tool_response_schema(AppendSucceedResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_append(
    doc_id: str, text: str, rich: bool = True, *,
    tab_id: TabId | None = None,
    upload_local_images: bool = False,
    table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> AppendSucceedResponse:
    """
    Append Markdown paragraphs or literal text at the end of a Google Doc.

    Configured required mode replans at the current end (up to three attempts).
    Target lets Google merge concurrent appends and choose their order, without
    local retries. expected_revision_id forces strict required without retries.
    Table stages always use required; completed stages and unknown writes are
    not replayed. Inspect partial failures.

    A paragraph break is added before the appended content automatically.
    With rich=True, separate Markdown paragraphs with blank lines. Headings
    map as follows: # is TITLE, ## is SUBTITLE, ### is HEADING_1, and so on.
    Bold, italic, combined emphasis and native homogeneous lists are supported.
    Markdown images and HTML img[src] create native images from public HTTP(S)
    PNG/JPEG/GIF URLs. HTML width/height accept pixel numbers; alt/title
    metadata is not preserved. CSS/responsive images are unsupported.
    Rectangular Markdown/HTML tables preserve inline formatting, br breaks,
    empty cells and column alignment. Merged/nested tables and block content
    are unsupported. Tables use multiple revision-guarded batches; failures may
    leave partial content. Read the document before retrying.

    Inline code and blocks default to Roboto Mono, with inline color #188038;
    font/color are configurable on the server. Blocks preserve literal
    whitespace. Declared languages use Pygments (theme default); highlighting
    is configurable on the server. Unknown/absent languages stay plain.
    HTML code/pre are supported; blocks inside list items are unsupported.

    With rich=False, preserve Markdown delimiters and line breaks literally.

    Args:
        doc_id: Google Doc ID
        text: Markdown or literal content to append, according to rich.
        rich: Parse Markdown if True (default); insert literal text if False.
        upload_local_images: Allow absolute local image paths/file URLs.
            Uploads to My Drive root, temporarily grants anyone-with-link
            read access, inserts, then deletes sources. Defaults to False.
            Ignored with rich=False. See temporary_image_cleanup_pending.
        table_borders: Show borders on new tables (default True).
            False hides outer and internal borders. Ignored with rich=False.
        code_block_style: Pygments theme, e.g. default or monokai.
            Omitted/null inherits config/environment. Ignored with rich=False.
        code_block_theme_background: Apply paragraph theme background.
            Omitted/null inherits server config/environment; False disables it.
            Ignored with rich=False.

    Returns
    -------
        A structured receipt with document_id, rich, diagnostic at_index,
        appended (plain-text preview up to 200 Unicode code points),
        inserted_image_count, inserted_char_count (including paragraph breaks
        and U+FFFC per native image), preview_truncated,
        and ok=True. Read the document to verify formatting.
        scope is document_end and heading_id is null.
    """
    with code_formatting(style=code_block_style,
                         theme_background=code_block_theme_background):
        return docs_edit.append(
            doc_id, text, rich=rich, upload_local_images=upload_local_images,
            table_borders=table_borders,
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        )


@mcp.tool(
    output_schema=_tool_response_schema(BatchReplaceResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': True,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_batch_replace(
    doc_id: str, replacements: Replacements,
    *, tab_id: TabId | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> BatchReplaceResponse:
    """
    Apply multiple find→replace operations atomically in a single batchUpdate.

    Configured required mode validates original targets/styles with up to three
    attempts. Target delegates merging, including overlaps, to Google without
    local conflict checks or retries. expected_revision_id forces strict
    required. Unknown writes and rejected target revisions are not replayed.

    All replacements are applied in one API call (end-of-document first to
    preserve index validity). Either ALL changes succeed, or none do.

    Args:
        doc_id:           Google Doc ID
        replacements: Nonempty array of typed replacement objects, e.g.:
                          [{"find": "Q1", "replace": "Q2"},
                            {"find": "draft", "replace": "final", "occurrence":
                            0}]

                          Each item: {"find": str, "replace": str,
                                      "occurrence": int (default 1, 0=all),
                                      "regex": bool (default false)}
                          find must be nonempty; replace="" deletes text.
                          Types are strict; unknown fields, negative
                          occurrences and invalid regex patterns are rejected
                          before API access. occurrence=0 supports literal
                          and regex replace-all within this batch tool.

    Returns
    -------
        A structured object with ok, applied (count), and changes in document
        order. Each change has replaced, with (replacement text), and at_index.
        Includes document_id, scope, heading_id, and changes_truncated. Only
        the first 100 change previews are returned; applied counts all edits.
        Each change bounds replaced to 80 and with to 200 Unicode code points,
        with full replaced_char_count/replacement_char_count and
        preview_truncated/replacement_preview_truncated flags. Indices are
        diagnostic only.
    """
    return BatchReplaceResponse.model_validate(
        docs_edit.batch_replace(
            doc_id, [replacement.model_dump() for replacement in replacements],
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        ),
    )


@mcp.tool(
    output_schema=_tool_response_schema(AddCommentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_add_comment(
    doc_id: str, comment: CommentText, anchor_text: NonemptyText,
    occurrence: PositiveInteger = 1, *, tab_id: TabId | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> AddCommentResponse:
    """
    Create a native comment anchored to exact text in the selected tab.

    occurrence selects a 1-based match; use 2, 3, etc. for repeated text.
    Matching uses native UTF-16 source positions across text runs, not rendered
    Markdown offsets. comment is plain text, at most 2048 UTF-8 bytes. Native
    anchoring supplies the quote; no quote is appended to your comment body.
    Uses configured required/target revision policy; expected_revision_id
    forces strict required. Confirmed revision races may be replanned; unknown
    write outcomes and unsuccessful commentUpdateState are never replayed.
    Returns native comment_id, post_id, anchor_id and confirmed ALL_SAVED.
    No named range, bookmark, Apps Script bridge or script scopes are needed.

    Args:
        occurrence: Which occurrence to anchor (default 1 = first).
            Use 2, 3, etc. when the same text appears more than once.
    """
    result = docs_edit.add_comment(
        doc_id, comment, anchor_text, occurrence,
        expected_revision_id=expected_revision_id, tab_id=tab_id,
    )
    return AddCommentResponse.model_validate(result)


@mcp.tool(
    output_schema=_tool_response_schema(ReplyCommentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_reply_to_comment(
    doc_id: str, comment_id: NonemptyText, reply: CommentText, *,
    expected_revision_id: ExpectedRevision | None = None,
) -> ReplyCommentResponse:
    """
    Reply to a native comment ID from docs_read_comments, in any tab.

    Plain text must be nonempty and at most 2048 UTF-8 bytes. Uses the normal
    revision policy; expected_revision_id forces required without retries.
    Reports success only after commentUpdateState=ALL_SAVED. reply_id is the
    native post ID; inspect replies with docs_read_comments(comment_id=...).
    Unknown outcomes are never automatically replayed.
    """
    return ReplyCommentResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'reply', reply,
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(ResolveCommentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_resolve_comment(
    doc_id: str, comment_id: NonemptyText, reply: CommentActionText = '', *,
    expected_revision_id: ExpectedRevision | None = None,
) -> ResolveCommentResponse:
    """
    Resolve a native thread with one RESOLVE action post.

    Optional closing text (at most 2048 UTF-8 bytes) is included in that same
    post; empty reply sends only the action. IDs work document-wide across
    tabs. Uses the normal revision policy and checks commentUpdateState.
    Unknown or failed persistence is never automatically replayed.
    """
    return ResolveCommentResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'resolve', reply,
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(DeleteCommentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': True,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_delete_comment(
    doc_id: str, comment_id: NonemptyText, *,
    expected_revision_id: ExpectedRevision | None = None,
) -> DeleteCommentResponse:
    """
    Delete a native thread; Google requires the head post's author.

    The ID is document-wide, including threads on nested tabs. Uses the
    normal revision policy and requires ALL_SAVED. Deleting a missing thread
    returns RESOURCE_NOT_FOUND. Inspect state after an unknown outcome.
    """
    return DeleteCommentResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'delete',
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(ReadCommentsResponse),
    annotations={
        'readOnlyHint': True,
        'destructiveHint': False,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_read_comments(
    doc_id: str, include_resolved: bool = False,
    page_token: NonemptyText | None = None, *, limit: CommentLimit = 100,
    comment_id: NonemptyText | None = None,
) -> ReadCommentsResponse:
    """
    Read native comment summaries across ALL document tabs, without writes.

    Default mode returns up to limit thread summaries (1-100) with native ID,
    head_post_id, text, author, quote, anchor_id, tab_id and diagnostic ranges,
    resolved/deleted flags and reply_count. Reply bodies are omitted here.
    include_resolved also includes deleted heads. Existing visible native
    threads remain usable; legacy Drive cursors must be discarded.

    Supply comment_id to inspect one thread, including resolved threads, and
    page its replies by limit. Its head/anchor metadata is repeated in the
    single comments entry; replies expose post_id, content, author and actions.
    page_kind identifies threads/replies. count is returned thread entries,
    including one in reply mode. Follow next_page_token with identical args.
    Tokens bind complete comment/anchor state, not only the body revision;
    changes return STALE_REFERENCE. Each page fetches current native metadata
    using COMMENTS_VIEW_MODE_INCLUDED and SUGGESTIONS_INLINE. The API has no
    server-side comment pagination; pagination bounds MCP output only.
    Comments require permission to view them; no Drive/Apps Script fallback.
    """
    return comments.read(doc_id, include_resolved, page_token, limit=limit,
                         comment_id=comment_id)


@mcp.tool(
    output_schema=_tool_response_schema(ReopenCommentResponse),
    annotations={'readOnlyHint': False, 'destructiveHint': False,
                 'idempotentHint': False, 'openWorldHint': True},
)
def docs_reopen_comment(
    doc_id: str, comment_id: NonemptyText, reply: CommentActionText = '', *,
    expected_revision_id: ExpectedRevision | None = None,
) -> ReopenCommentResponse:
    """
    Reopen a native thread with one REOPEN post and optional plain text.

    Uses document-wide comment IDs and the normal revision policy. Success
    requires ALL_SAVED. Unknown outcomes are never automatically replayed.
    """
    return ReopenCommentResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'reopen', reply,
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(EditCommentResponse),
    annotations={'readOnlyHint': False, 'destructiveHint': True,
                 'idempotentHint': True, 'openWorldHint': True},
)
def docs_edit_comment(
    doc_id: str, comment_id: NonemptyText, content: CommentText, *,
    post_id: NonemptyText | None = None,
    expected_revision_id: ExpectedRevision | None = None,
) -> EditCommentResponse:
    """
    Edit a native head post, or a reply selected with post_id.

    Omit post_id for the thread's head post. Get reply IDs by reading
    docs_read_comments(comment_id=...). Google permits only the post's author
    to edit it. content is plain text, 1-2048 UTF-8 bytes. Uses the normal
    revision policy; success requires ALL_SAVED. Document revisions protect
    the body snapshot; they are not per-post optimistic concurrency tokens.
    """
    return EditCommentResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'edit', content, post_id,
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(DeleteCommentReplyResponse),
    annotations={'readOnlyHint': False, 'destructiveHint': True,
                 'idempotentHint': True, 'openWorldHint': True},
)
def docs_delete_comment_reply(
    doc_id: str, comment_id: NonemptyText, reply_id: NonemptyText, *,
    expected_revision_id: ExpectedRevision | None = None,
) -> DeleteCommentReplyResponse:
    """
    Delete one ordinary native reply by its post/reply ID.

    Google permits only its author to delete it. Head posts, action posts
    and assignment posts are not eligible; use docs_delete_comment for a
    whole thread. Uses the normal revision policy and requires ALL_SAVED.
    """
    return DeleteCommentReplyResponse.model_validate(comments.mutate(
        doc_id, comment_id, 'delete_reply', post_id=reply_id,
        expected_revision_id=expected_revision_id,
    ))


@mcp.tool(
    output_schema=_tool_response_schema(ListDocumentsResponse),
    annotations={
        'readOnlyHint': True,
        'destructiveHint': False,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_list(
    query: str = '', limit: PositiveInteger = 20,
    page_token: NonemptyText | None = None,
) -> ListDocumentsResponse:
    """
    List Google Docs from Drive, optionally filtered by a search query.

    Args:
        query: Optional search terms (searches title and content)
        limit: Positive per-page maximum (default 20, above 100 capped).
        page_token: Opaque token from the previous response. Omit for page one;
            preserve query, limit and shared-drive settings across pages.

    Returns
    -------
        A structured object with count, documents, next_page_token and
        has_more. Each document has id,
        name, modifiedTime, and webViewLink. Count covers this response only;
        not a total. Follow next_page_token until null. Each call fetches one
        page; has_more is API continuation, not an estimate of remaining items.
    """
    creds = docs_edit._load_creds()
    drive = build('drive', 'v3', credentials=creds)

    use_drive = (
        os.environ.get('GOOGLE_DOCS_USE_DRIVE', 'false').lower() == 'true'
    )
    drive_id = os.environ.get('GOOGLE_DOCS_DRIVE_ID', None)
    drive_kwargs: dict[str, str | bool] = {}
    if drive_id is not None:
        use_drive = True
        drive_kwargs = {
            **drive_kwargs,
            'corpora': 'drive',
            'driveId': drive_id,
        }
    if use_drive:
        drive_kwargs = {
            **drive_kwargs,
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True,
        }

    q = 'mimeType="application/vnd.google-apps.document" and trashed=false'
    if query:
        q += f' and fullText contains "{query}"'

    results = (
        drive.files()
        .list(
            q=q,
            pageSize=min(limit, 100),
            fields='nextPageToken,files(id, name, modifiedTime, webViewLink)',
            orderBy='modifiedTime desc',
            pageToken=page_token,
            **drive_kwargs,
        )
        .execute()
    )

    files = results.get('files', [])
    return ListDocumentsResponse(
        count=len(files), documents=files,
        next_page_token=results.get('nextPageToken') or None,
    )


@mcp.tool(
    output_schema=_tool_response_schema(CreateDocumentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': False,
        'idempotentHint': False,
        'openWorldHint': True,
    },
)
def docs_create(title: str, initial_text: str = '') -> CreateDocumentResponse:
    """
    Create a new Google Doc with an optional initial paragraph of text.

    Args:
        title:        Document title
        initial_text: Optional first paragraph content

    Returns
    -------
        A structured object with id, title, and webViewLink.
    """
    creds = docs_edit._load_creds()
    service = build('docs', 'v1', credentials=creds)
    doc = service.documents().create(body={'title': title}).execute()
    doc_id = doc['documentId']

    if initial_text:
        service.documents().batchUpdate(
            documentId=doc_id,
            body={
                'requests': [
                    {
                        'insertText': {
                            'location': {'index': 1},
                            'text': initial_text,
                        }
                    }
                ]
            },
        ).execute()

    return CreateDocumentResponse(
        id=doc_id,
        title=title,
        webViewLink=f'https://docs.google.com/document/d/{doc_id}/edit',
    )


def main():
    """Run the command-line entry point for this module."""
    configure_logging()
    get_settings()
    # Our logger has its own handler; this default is for third-party loggers.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
