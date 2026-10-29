"""Thin MCP adapters for suggestions."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.suggestions import (
    reading as suggestions,
    writing as suggestion_writes,
)
from gdocs_scope_mcp.suggestions.models import SuggestionsReadResponse
from gdocs_scope_mcp.suggestions.reading import (
    SuggestionCursor,
    SuggestionId,
    SuggestionLimit,
)
from gdocs_scope_mcp.suggestions.write_models import (
    ProposalOperation,
    SuggestionAction,
    SuggestionIds,
    SuggestionsManageResponse,
    SuggestResponse,
)
from gdocs_scope_mcp.tool_inputs import (
    ExpectedRevision,
    NonemptyText,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp):
    """Register suggestions tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(SuggestionsReadResponse),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': True},
    )
    def docs_suggestions_read(
        doc_id: str, *, tab_id: TabId | None = None,
        heading_id: NonemptyText | None = None,
        suggestion_id: SuggestionId | None = None,
        include_closed: bool = False, limit: SuggestionLimit = 50,
        page_token: SuggestionCursor | None = None,
    ) -> SuggestionsReadResponse:
        """Inspect native proposals separately from accepted-content reads.

        Omitted tab_id selects the first tab; heading_id selects an accepted
        heading subtree. Ordinary docs_read/docs_get_tree omit proposed insertions
        and retain proposed deletions without accepting/rejecting anything.
        This tool lists OPEN/unknown proposals by default. include_closed also
        returns decided threads; an explicit suggestion_id includes its status
        regardless of include_closed and pages its replies with a complete head.
        Summaries and diagnostic native ranges identify proposals, not editable
        source text or preview coordinates. Unknown locations are returned with
        scope_match=unknown rather than assigned to a tab/heading by their summary.
        Closed threads can lose their source ranges. Lists omit posts/reply bodies;
        summaries and locations are bounded with truncation flags. Use detail to
        read complete posts. page_token requires unchanged arguments and native
        thread/document state; restart without it after STALE_REFERENCE.
        No proposals or comments are created, accepted, rejected or deleted.
        """
        return suggestions.read(
            doc_id, tab_id=tab_id, heading_id=heading_id,
            suggestion_id=suggestion_id, include_closed=include_closed,
            limit=limit, page_token=page_token,
        )


    @mcp.tool(
        output_schema=tool_response_schema(SuggestResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_suggest(
        doc_id: str, operation: ProposalOperation, *,
        tab_id: TabId | None = None, heading_id: NonemptyText | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> SuggestResponse:
        """Propose one native change, leaving accepted content unchanged.

        Choose replace (literal find/text), insert_before/insert_after
        (anchor/text), append (text), delete_paragraph (anchor) or format_text
        (find/style).
        Literal anchors are case-sensitive; occurrence is 1-based, never all.
        Inserts add separate paragraphs; replace text is literal. Rich insertions
        support Markdown paragraphs, headings and text formatting; tables, lists,
        images and chips are rejected before writes or uploads. Code formatting
        is supported, but named-range code markers are omitted with a warning.
        format_text accepts bold, italic, underline and strikethrough booleans.
        Only ordinary body paragraphs are supported. Existing proposals affecting
        the target paragraph or unknown locations cause EDIT_CONFLICT; proposals
        elsewhere are allowed. Do not use preview indices or proposal summaries
        as anchors. Omitted tab_id means the first tab; heading_id scopes anchors
        and append to its accepted subtree. Normal required/target revision policy
        applies; expected_revision_id enforces strict required revision matching.
        Receipts require ALL_SAVED and native thread readback and list all returned
        created/affected IDs. Unknown outcomes are never replayed automatically.
        Inspect with docs_suggestions_read and decide with docs_suggestions_manage.
        Existing edit tools continue making direct edits.
        """
        return suggestion_writes.suggest(
            doc_id, operation, tab_id=tab_id, heading_id=heading_id,
            expected_revision_id=expected_revision_id,
        )


    @mcp.tool(
        output_schema=tool_response_schema(SuggestionsManageResponse),
        annotations={'readOnlyHint': False, 'destructiveHint': True,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_suggestions_manage(
        doc_id: str, action: SuggestionAction, suggestion_ids: SuggestionIds, *,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> SuggestionsManageResponse:
        """Accept, reject or delete up to 50 explicit native proposal IDs.

        IDs from docs_suggestions_read or docs_suggest are document-wide; no tab
        selection is needed. The complete batch is preflighted: duplicate, missing,
        deleted, unknown or differently decided IDs cause no decisions to be sent.
        Already accepted/rejected IDs matching the requested decision are reported
        as already_decided. Pending IDs are submitted together in one guarded
        batch. Results require ALL_SAVED, matching native IDs and readback.
        Partial or uncertain outcomes are never automatically replayed. A required
        revision retry rejects changed proposal state; configured target mode uses
        Google's collaboration semantics. expected_revision_id forces strict mode.
        Accept requires edit access; reject requires edit access or authorship;
        delete requires authorship and removes the proposal, including its pending
        changes. Another user's permissions are never inferred from display names.
        Reply writing and editing generated summaries are not supported.
        """
        return suggestion_writes.manage(
            doc_id, action, suggestion_ids,
            expected_revision_id=expected_revision_id,
        )

