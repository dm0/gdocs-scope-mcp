"""Thin MCP adapters for comments."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp import comments
from gdocs_scope_mcp.comment_models import (
    AddCommentResponse,
    DeleteCommentReplyResponse,
    DeleteCommentResponse,
    EditCommentResponse,
    ReadCommentsResponse,
    ReopenCommentResponse,
    ReplyCommentResponse,
    ResolveCommentResponse,
)
from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.tool_inputs import (
    CommentActionText,
    CommentLimit,
    CommentText,
    ExpectedRevision,
    NonemptyText,
    PositiveInteger,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp):
    """Register comments tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(AddCommentResponse),
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
        result = comments.add_comment(
            doc_id, comment, anchor_text, occurrence,
            expected_revision_id=expected_revision_id, tab_id=tab_id,
        )
        return AddCommentResponse.model_validate(result)


    @mcp.tool(
        output_schema=tool_response_schema(ReplyCommentResponse),
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
        output_schema=tool_response_schema(ResolveCommentResponse),
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
        output_schema=tool_response_schema(DeleteCommentResponse),
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
        output_schema=tool_response_schema(ReadCommentsResponse),
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
        output_schema=tool_response_schema(ReopenCommentResponse),
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
        output_schema=tool_response_schema(EditCommentResponse),
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
        output_schema=tool_response_schema(DeleteCommentReplyResponse),
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
