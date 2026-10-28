"""Describe accepted-content views and native proposal inspection."""

from typing import Literal

from pydantic import BaseModel, Field


class SuggestionNotice(BaseModel):
    """Distinguish an absent proposal from unavailable scope detection."""

    view: Literal['without_suggestions'] = 'without_suggestions'
    document_has_pending: bool | None = False
    selected_content_has_pending: bool | None = False
    suggestion_ids: list[str] = Field(default_factory=list)
    suggestion_ids_truncated: bool = False
    detection: Literal['complete', 'partial', 'unavailable'] = 'complete'
    warnings: list[str] = Field(default_factory=list)


class SuggestionLocation(BaseModel):
    """Expose diagnostic native coordinates, never preview write indices."""

    tab_id: str | None = None
    segment_id: str | None = None
    start_index: int | None = None
    end_index: int | None = None
    kind: str
    inherited: bool = False
    uncertain: bool = False


class SuggestionPost(BaseModel):
    """Keep complete native posts only on a bounded detail page."""

    post_id: str | None = None
    content: str = ''
    author: str | None = None
    created: str | None = None
    updated: str | None = None
    deleted: bool = False
    action: str | None = None


class SuggestionDetails(BaseModel):
    """Identify a native thread and whether its known locations match scope."""

    suggestion_id: str
    status: str
    author: str | None = None
    summary: str = ''
    summary_html: str = ''
    summary_truncated: bool = False
    scope_match: Literal['matched', 'unknown']
    locations: list[SuggestionLocation] = Field(default_factory=list)
    locations_truncated: bool = False
    head_post: SuggestionPost | None = None
    reply_count: int = 0
    replies: list[SuggestionPost] = Field(default_factory=list)


class SuggestionsReadResponse(BaseModel):
    """Page selected native thread summaries or one thread's replies."""

    document_id: str
    revision_id: str | None
    tab_id: str | None
    heading_id: str | None = None
    suggestions: list[SuggestionDetails]
    page_kind: Literal['suggestions', 'replies'] = 'suggestions'
    count: int
    total: int
    has_more: bool
    next_page_token: str | None = None
    warnings: list[str] = Field(default_factory=list)
