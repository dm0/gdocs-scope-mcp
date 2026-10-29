"""Models owned by comment_models."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
)

from gdocs_scope_mcp.contracts import DocumentEditReceipt, ListingPage


class CommentMutationReceipt(DocumentEditReceipt):
    """Confirm native comment persistence separately from Docs HTTP success."""

    ok: Literal[True] = True
    comment_id: str
    revision_id: str | None = None
    comment_update_state: Literal['ALL_SAVED'] = 'ALL_SAVED'



class AddCommentResponse(CommentMutationReceipt):
    """Report a native anchored comment without auxiliary metadata writes."""

    post_id: str
    anchor_id: str | None
    anchored_to: str
    at_index: Annotated[int, Field(description='Google Docs API anchor index; '
                                 'diagnostic only')]
    comment_content: str



class ReplyCommentResponse(CommentMutationReceipt):
    """Identify a newly posted comment reply."""

    ok: Literal[True] = True
    scope: Literal['comment'] = 'comment'
    reply_id: str
    comment_id: str
    content: str | None



class ResolveCommentResponse(CommentMutationReceipt):
    """Confirm resolution of a document comment."""

    ok: Literal[True] = True
    scope: Literal['comment'] = 'comment'
    comment_id: str
    resolved: Literal[True] = True
    reply_id: str



class ReopenCommentResponse(CommentMutationReceipt):
    """Confirm reopening through a native action post."""

    scope: Literal['comment'] = 'comment'
    resolved: Literal[False] = False
    reply_id: str



class EditCommentResponse(CommentMutationReceipt):
    """Identify the edited head/reply post and confirmed plain text."""

    scope: Literal['comment'] = 'comment'
    post_id: str
    content: str



class DeleteCommentReplyResponse(CommentMutationReceipt):
    """Identify a deleted ordinary reply; action posts cannot be deleted."""

    scope: Literal['comment'] = 'comment'
    reply_id: str



class DeleteCommentResponse(CommentMutationReceipt):
    """Identify the deleted comment."""

    ok: Literal[True] = True
    scope: Literal['comment'] = 'comment'
    comment_id: str



class CommentRange(BaseModel):
    """Return native anchor bounds for inspection, never as edit selectors."""

    tab_id: str
    segment_id: str | None = None
    start_index: int | None = None
    end_index: int | None = None



class CommentPost(BaseModel):
    """Expose a native reply ID, plain text and action metadata."""

    post_id: str
    content: str
    author: str
    deleted: bool = False
    created: str = ''
    updated: str = ''
    action: str | None = None



class DocumentComment(BaseModel):
    """Expose comment text, anchor metadata, author, and resolution state."""

    id: str
    content: str
    author: str
    anchored: bool
    anchor_id: str | None
    tab_id: str | None
    ranges: list[CommentRange]
    head_post_id: str | None
    reply_count: int
    replies: list[CommentPost] = Field(default_factory=list)
    quoted_text: str
    resolved: bool
    deleted: bool
    created: str



class ReadCommentsResponse(ListingPage):
    """Return comments from the fetched page with a count of included items."""

    comments: list[DocumentComment]
    document_id: str
    revision_id: str | None
    page_kind: Literal['threads', 'replies'] = 'threads'

