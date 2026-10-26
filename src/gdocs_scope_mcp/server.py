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
  Comments: docs_add_comment, docs_read_comments, docs_reply_to_comment,
            docs_resolve_comment, docs_delete_comment
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

import json
import logging
import os
import sys

from fastmcp import FastMCP
from googleapiclient.discovery import build
from pydantic import BaseModel, TypeAdapter

from . import docs_edit
from .diagnostics import ServerInfo, capture_server_info
from .models import (
    AddCommentResponse,
    AppendSucceedResponse,
    BatchReplaceResponse,
    CreateDocumentResponse,
    DeleteCommentResponse,
    DeleteParagraphResponse,
    DocumentOutline,
    DocumentSubset,
    EditFailedResponse,
    InsertSucceedResponse,
    ListDocumentsResponse,
    ReadCommentsResponse,
    ReplaceSucceedResponse,
    ReplyCommentResponse,
    ResolveCommentResponse,
)
from .settings import code_formatting, get_settings
from .tool_inputs import (
    CodeBlockStyle,
    CodeBlockThemeBackground,
    NonemptyText,
    PositiveInteger,
    ReplacementOccurrence,
    Replacements,
    TableBorders,
)
from .tool_logging import ToolCallLoggingMiddleware, configure_logging

SERVER_INFO = capture_server_info()


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
    Markdown links, recognized bare HTTP(S) URLs, autolinks and HTML a[href]
    become native link styles. Markdown strikethrough and HTML del/s become
    native strikethrough. Both combine with supported inline emphasis and
    apply only to their text ranges.
    Native ordered/unordered lists preserve item paragraphs and homogeneous
    nesting. Items must be nonempty single paragraphs; custom start numbers,
    mixed ordered/unordered nesting and multi-paragraph items fail before
    writes. List receipts exclude the temporary nesting tabs.
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
  docs_delete_comment    Delete a comment

DOCUMENT MANAGEMENT:
  docs_list              List recent docs (optional search query)
  docs_create            Create a new document

SURGICAL GOOGLE DOCS EDITING WORKFLOW:
  1. Always run 'docs_get_tree' first to inspect the structural outline and
     gather heading IDs.
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
def docs_get_tree(doc_id: str) -> DocumentOutline:
    """
    Fetch a Google Doc's structural outline as a JSON object.

    The object contains document_id, title, revision_id, and a flat sections
    collection. Each section has id, title, level, and ancestor_ids. Hierarchy
    is represented by ancestor_ids, not nested section objects. Body
    paragraphs are omitted.

    Use this tool FIRST when encountering a document to locate target sections
    via their heading IDs, avoiding the need to read a massive document all at
    once.

    Args:
        doc_id: Google Doc ID (from the URL: /document/d/{DOC_ID}/edit)
    """
    return docs_edit.get_tree(doc_id)


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
    doc_id: str, heading_ids: list[str] | None = None
) -> DocumentSubset | EditFailedResponse:
    """
    Read a Google document's content converted to Markdown.

    You can read the entire document, or isolate specific sections by passing
    a list of target heading_ids, including their nested subsections.
    Isolating sections reduces token usage on large files.

    Args:
        doc_id: Google Doc ID from the URL.
        heading_ids: Optional list of heading IDs to fetch.
            Pass null or omit this field entirely to read the whole document.
            An empty list returns no sections. Duplicate IDs and selected
            descendants of selected ancestors are collapsed in document order.

    Returns
    -------
        Document metadata and sections [{heading_id, markdown}], effective
        selected_headings, unknown_heading_ids, and partial. Whole reads
        include the preamble with heading_id=null. Mixed selections return
        valid content and diagnostics; all-unknown selections fail with
        HEADING_NOT_FOUND. Refresh IDs with docs_get_tree after that error.
    """
    if isinstance(heading_ids, str):
        heading_ids = [heading_ids]
    return docs_edit.read(doc_id, heading_ids)


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
) -> ReplaceSucceedResponse | EditFailedResponse:
    """
    Find text and replace.

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
        doc_id, find, replace, occurrence, heading_id, regex
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
    *, upload_local_images: bool = False, table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert a new paragraph immediately after the paragraph containing `anchor`.

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
    *, upload_local_images: bool = False, table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert a new paragraph immediately before the paragraph containing

    `anchor`.

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
) -> DeleteParagraphResponse:
    """
    Delete the paragraph(s) containing `anchor` text.

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
        docs_edit.delete_paragraph(doc_id, anchor),
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
    upload_local_images: bool = False,
    table_borders: TableBorders = True,
    code_block_style: CodeBlockStyle | None = None,
    code_block_theme_background: CodeBlockThemeBackground | None = None,
) -> AppendSucceedResponse:
    """
    Append Markdown paragraphs or literal text at the end of a Google Doc.

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
) -> BatchReplaceResponse:
    """
    Apply multiple find→replace operations atomically in a single batchUpdate.

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
# Preserve the public positional calling convention.
def docs_add_comment(  # noqa: PLR0917
    doc_id: str,
    comment: str,
    anchor_text: NonemptyText,
    occurrence: PositiveInteger = 1,
    include_anchor_text: bool = True,
    bookmark_jump: bool = False,
) -> AddCommentResponse:
    """
    Add a comment anchored to specific text in a Google Doc.

    NOTE: The current implementation uses the Drive comments API plus a Docs
    named range. In the Docs UI this still shows as "Original content deleted"
    rather than a proper inline comment highlight. The comments ARE readable
    via
    docs_read_comments and the Docs 💬 panel.

    The next path to investigate is Apps Script automation. The OAuth token
    must
    include the script.* scopes, and the Google account must also have the Apps
    Script API enabled at https://script.google.com/home/usersettings before
    remote Apps Script project creation/execution will work.

    By default the tool also appends the matched anchor text into the comment
    body so the user can understand what was targeted even though the Docs UI
    does not render a proper inline highlight with the current API path.

    When bookmark_jump=True, the tool also uses a persistent Apps Script bridge
    (configured via GOOGLE_DOCS_MCP_APPS_SCRIPT_ID) to create a bookmark at the
    target text, then appends a #bookmark jump URL into the comment body.

    Args:
        doc_id:      Google Doc ID (from the URL: /document/d/{DOC_ID}/edit)
        comment:     The comment text to post
        anchor_text: Exact text in the document to attach the comment to.
                     Use a short, unique phrase (a few words) for reliable
                     matching.
        occurrence: Which occurrence of anchor_text to use (default 1 = first).
            Use 2, 3, etc. if the text appears multiple times.
        include_anchor_text: If True (default), append the matched anchor text
                     excerpt into the comment body for human readability.
        bookmark_jump: If True, create an Apps Script bookmark and append a
                     jump URL into the comment body. Requires the Apps Script
                     bridge env var setup documented in the README.

    Returns
    -------
        A structured object with ok, comment_id, anchored_to (matched text),
        at_index, named_range_id, comment_content, and optional bookmark_id,
        bookmark_url, and apps_script_id (null when bookmarks are disabled).
        Includes document_id, scope=document, and heading_id=null.
    """
    result = docs_edit.add_comment(
        doc_id,
        comment,
        anchor_text,
        occurrence,
        include_anchor_text=include_anchor_text,
        bookmark_jump=bookmark_jump,
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
    doc_id: str, comment_id: str, reply: str
) -> ReplyCommentResponse:
    """
    Reply to an existing comment on a Google Doc.

    Args:
        doc_id:     Google Doc ID
        comment_id: ID of the comment to reply to (from docs_read_comments)
        reply:      Reply text to post

    Returns
    -------
        A structured object with ok, reply_id, comment_id, and content.
        Includes document_id, scope=comment, and heading_id=null.
    """
    creds = docs_edit._load_creds()
    drive = build('drive', 'v3', credentials=creds)
    result = (
        drive.replies()
        .create(
            fileId=doc_id,
            commentId=comment_id,
            body={'content': reply},
            fields='id,content,createdTime',
        )
        .execute()
    )
    return ReplyCommentResponse(
        document_id=doc_id,
        reply_id=result.get('id'),
        comment_id=comment_id,
        content=result.get('content'),
    )


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
    doc_id: str, comment_id: str, reply: str = ''
) -> ResolveCommentResponse:
    """
    Resolve a comment by creating a reply with the resolve action.

    An optional closing message is included in that same reply. Without a
    message, only the resolve action is sent; no text content is required.

    Args:
        doc_id:     Google Doc ID
        comment_id: ID of the comment to resolve (from docs_read_comments)
        reply: Optional closing text to include in the resolving reply.

    Returns
    -------
        A structured object with ok, comment_id, and resolved=True.
        Includes document_id, scope=comment, and heading_id=null.
    """
    creds = docs_edit._load_creds()
    drive = build('drive', 'v3', credentials=creds)

    body = {'action': 'resolve'}
    if reply:
        body['content'] = reply
    drive.replies().create(
        fileId=doc_id,
        commentId=comment_id,
        body=body,
        fields='id',
    ).execute()
    return ResolveCommentResponse(document_id=doc_id, comment_id=comment_id)


@mcp.tool(
    output_schema=_tool_response_schema(DeleteCommentResponse),
    annotations={
        'readOnlyHint': False,
        'destructiveHint': True,
        'idempotentHint': True,
        'openWorldHint': True,
    },
)
def docs_delete_comment(doc_id: str, comment_id: str) -> DeleteCommentResponse:
    """
    Delete a comment from a Google Doc.

    Args:
        doc_id:     Google Doc ID
        comment_id: ID of the comment to delete

    Returns
    -------
        A structured object with ok and comment_id.
        Includes document_id, scope=comment, and heading_id=null.
    """
    creds = docs_edit._load_creds()
    drive = build('drive', 'v3', credentials=creds)
    drive.comments().delete(fileId=doc_id, commentId=comment_id).execute()
    return DeleteCommentResponse(document_id=doc_id, comment_id=comment_id)


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
    page_token: NonemptyText | None = None,
) -> ReadCommentsResponse:
    """
    Read a page of up to 100 comments on a Google Doc.

    Returns each comment with its content, author, anchor status, and whether
    it's resolved or deleted. Useful for auditing what comments exist and
    whether they are properly anchored to text.

    Args:
        doc_id:           Google Doc ID
        include_resolved: Include resolved/deleted comments (default False)
        page_token: Opaque token from the previous response. Omit for page one;
            preserve doc_id and include_resolved when requesting later pages.

    Returns
    -------
        A structured object with count, comments, next_page_token and has_more.
        Each comment has id,
        content, author, anchored, named_range_id, quoted_text, resolved,
        deleted, and created. Count includes only returned items after
        filtering, not a document-wide total. Follow next_page_token until
        null, even on empty filtered pages; each call fetches only one page.
    """
    creds = docs_edit._load_creds()
    drive = build('drive', 'v3', credentials=creds)

    resp = (
        drive.comments()
        .list(
            fileId=doc_id,
            fields='nextPageToken,comments(id,content,anchor,resolved,deleted,'
            'author,createdTime,quotedFileContent)',
            pageSize=100,
            pageToken=page_token,
        )
        .execute()
    )

    results = []
    for c in resp.get('comments', []):
        if not include_resolved and (c.get('deleted') or c.get('resolved')):
            continue
        anchor = c.get('anchor') or ''
        named_range_id = None
        if anchor:
            try:
                a = json.loads(anchor)
                for part in a.get('a', []):
                    if part.get('t') == 'r':
                        named_range_id = part.get('v')
            # This boundary intentionally handles all errors without
            # propagating.
            except Exception:  # noqa: BLE001
                pass
        results.append(
            {
                'id': c['id'],
                'content': c.get('content', ''),
                'author': c.get('author', {}).get('displayName', '?'),
                'anchored': bool(anchor),
                'named_range_id': named_range_id,
                'quoted_text': (c.get('quotedFileContent') or {}).get(
                    'value', ''
                ),
                'resolved': c.get('resolved', False),
                'deleted': c.get('deleted', False),
                'created': c.get('createdTime', ''),
            }
        )

    return ReadCommentsResponse(
        count=len(results), comments=results,
        next_page_token=resp.get('nextPageToken') or None,
    )


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
