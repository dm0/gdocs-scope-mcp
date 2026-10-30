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
  1. GDOCS_SCOPE_MCP_TOKEN env var   — standalone token (auth_setup.py)
  2. $XDG_CONFIG_HOME/gdocs-scope-mcp/token.json (default root: ~/.config)
  3. ~/.google-docs-mcp/token.json   — legacy-file fallback
  4. ~/.google-drive-mcp/token.json  — legacy-file fallback
  5. GOG_KEYRING_PASSWORD env var    — auto-export from gog CLI

Setup:
  gdocs-scope-mcp-auth --credentials ~/credentials.json
  gdocs-scope-mcp-auth --credentials ~/credentials.json --headless  # no
  browser
  GDOCS_SCOPE_MCP_CLIENT_ID=... GDOCS_SCOPE_MCP_CLIENT_SECRET=...
  gdocs-scope-mcp-auth

Transport: stdio (Claude Desktop / OpenClaw MCP config)
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from gdocs_scope_mcp.diagnostics import capture_server_info
from gdocs_scope_mcp.settings import get_settings
from gdocs_scope_mcp.tool_logging import (
    ToolCallLoggingMiddleware,
    configure_logging,
)
from gdocs_scope_mcp.tools import (
    comments,
    diagnostics,
    documents,
    entities,
    files,
    suggestions,
    tables,
)

SERVER_INFO = capture_server_info()




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

SUGGESTIONS:
    docs_get_tree and docs_read show accepted content: pending insertions are
    hidden, pending deletions retained, and proposed formatting is not applied.
    This view does not accept or reject anything. Their suggestions metadata
    reports document_has_pending and selected_content_has_pending (null means
    unknown), relevant IDs and detection warnings. General named-style effects
    may be unknown. Without proposals, ordinary reading needs no extra call.
    unavailable_heading_ids flags accepted selectors that cannot be mapped
    safely to native headings; read the whole tab instead of using them.
    Use docs_suggestions_read to inspect native IDs, status, summaries, source
    ranges and replies separately. Scope is first tab by default. Existing
    editing tools still perform direct edits from native inline coordinates.
    Preview coordinates must never drive a write. Pending structural changes
    may prevent safe table references; inspect suggestions.warnings when an
    HTML table lacks data-mcp-table-ref. Proposal-writing tools are separate
    future work; this reading tool performs no mutations.

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
    Native ordered/unordered lists preserve homogeneous and mixed nesting and
    multiple ordinary paragraphs per item, including continuations
    after nested lists. Continuations have no marker and do not increment
    numbering. Loose lists use 6 pt above paragraphs; tight lists use zero.
    Empty items, custom start numbers and
    arbitrary blocks inside items fail before writes. List receipts exclude
    temporary nesting tabs and root paragraphs. Mixed subtrees use separate
    native list IDs while parent numbering continues. Reads cannot reconstruct
    logical item membership from indentation alone.
    Reads emit contiguous lists as nested HTML ol/ul/li groups, preserving
    marker kinds and nesting for rich reinsertion. Unmarked paragraphs end
    groups; native IDs and custom numbering are not preserved by copying.
    Markdown images and HTML img[src] insert native inline images using public
    HTTP(S) URLs (PNG/JPEG/GIF; Google's size limits apply). HTML width/height
    accept positive pixel numbers; CSS sizes and responsive sources fail before
    writes. Without either dimension, images fill the available paragraph
    width in single-column paged body paragraphs/lists; Google preserves aspect
    ratio. Table cells, pageless/multi-column or unresolved layouts retain
    Google's default sizing. Explicit width or height takes precedence.
    Alt/title are not native metadata. Receipts expose
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


































































diagnostics.register(mcp, lambda: SERVER_INFO)
documents.register_discovery(mcp)
suggestions.register(mcp)
documents.register_reading(mcp)
tables.register(mcp)
entities.register(mcp)
documents.register_editing(mcp)
comments.register(mcp)
files.register(mcp)

def main():
    """Run the command-line entry point for this module."""
    configure_logging()
    get_settings()
    # Our logger has its own handler; this default is for third-party loggers.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
