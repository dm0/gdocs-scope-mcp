"""Models owned by contracts."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    PlainSerializer,
    computed_field,
)


class EditFailedResponse(BaseModel):
    """A tool failure with a stable code and recovery guidance."""

    ok: Literal[False] = False
    code: Literal[
        'HEADING_NOT_FOUND',
        'TEXT_NOT_FOUND',
        'OCCURRENCE_NOT_FOUND',
        'EMPTY_DOCUMENT',
        'INVALID_ARGUMENT',
        'AUTHENTICATION_REQUIRED',
        'PERMISSION_DENIED',
        'RESOURCE_NOT_FOUND',
        'RATE_LIMITED',
        'QUOTA_EXCEEDED',
        'TEMPORARILY_UNAVAILABLE',
        'AUTH_CONFIGURATION_ERROR',
        'GOOGLE_API_ERROR',
        'INTERNAL_ERROR',
        'EDIT_CONFLICT',
        'TARGET_AMBIGUOUS',
        'TARGET_DELETED',
        'REVISION_RETRY_EXHAUSTED',
        'REVISION_UNAVAILABLE',
        'WRITE_OUTCOME_UNKNOWN',
        'PARTIAL_WRITE',
        'TARGET_REVISION_REJECTED',
        'STALE_REFERENCE',
        'TARGET_CHANGED',
        'TAB_MISMATCH',
        'INVALID_REFERENCE',
        'SNAPSHOT_EXPIRED',
    ]
    description: Annotated[str, Field(description='Failure description')]
    suggested_action: Annotated[
        str, Field(description='Suggested action to resolve the failure')
    ]
    committed_batches: int = Field(
        default=0, description='Confirmed completed Docs batches before '
        'failure; an unknown pending write may also have committed.',
    )


SHORT_PREVIEW_LIMIT = 80


TEXT_PREVIEW_LIMIT = 200


RECEIPT_ITEM_LIMIT = 100


TruncatedStr80 = Annotated[
    str,
    PlainSerializer(
        lambda v: v[:SHORT_PREVIEW_LIMIT] if v else v, return_type=str
    ),
    Field(json_schema_extra={'maxLength': SHORT_PREVIEW_LIMIT}),
]


TruncatedStr200 = Annotated[
    str,
    PlainSerializer(
        lambda v: v[:TEXT_PREVIEW_LIMIT] if v else v, return_type=str
    ),
    Field(json_schema_extra={'maxLength': TEXT_PREVIEW_LIMIT}),
]


class DocumentEditReceipt(BaseModel):
    """Identify the document and effective scope of a successful edit."""

    document_id: Annotated[str, Field(description='Edited Google Doc ID')]
    tab_id: str | None = None
    scope: Literal[
        'document', 'heading_subtree', 'document_end', 'comment'
    ] = 'document'
    heading_id: Annotated[
        str | None, Field(description='Effective heading subtree ID, or null '
                          'when the operation is not heading-scoped')
    ] = None


APPEND_PREVIEW_LIMIT = TEXT_PREVIEW_LIMIT


class ListingPage(BaseModel):
    """Describe one API page without implying a collection-wide total."""

    count: int = Field(
        ge=0, description='Items returned on this page after filtering; '
        'not the total number of items in the collection.',
    )
    next_page_token: str | None = Field(
        default=None, description='Opaque continuation token; null on the '
        'terminal page. Reuse with the same query and filters.',
    )

    @computed_field(description='Whether the API returned a continuation '
                    'token, even if this page contains no visible items.')
    @property
    def has_more(self) -> bool:
        """Derive continuation from the API token rather than item count."""
        return bool(self.next_page_token)
