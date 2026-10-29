"""Define typed, bounded native proposal operations and verified receipts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from .suggestions import SuggestionId
from .tool_inputs import NonemptyText, PositiveInteger


class Operation(BaseModel):
    """Reject unknown fields and coercion before planning a proposal."""

    model_config = ConfigDict(strict=True, extra='forbid')


class ReplaceProposal(Operation):
    """Replace one literal case-sensitive match with literal text."""

    operation: Literal['replace']
    find: NonemptyText
    text: str
    occurrence: PositiveInteger = 1


class InsertProposal(Operation):
    """Insert paragraphs before or after one anchor's paragraph."""

    operation: Literal['insert_before', 'insert_after']
    anchor: NonemptyText
    text: NonemptyText
    occurrence: PositiveInteger = 1
    rich: bool = True


class AppendProposal(Operation):
    """Append paragraphs within the selected tab or heading subtree."""

    operation: Literal['append']
    text: NonemptyText
    rich: bool = True


class DeleteProposal(Operation):
    """Delete one anchor's paragraph, retaining the final body newline."""

    operation: Literal['delete_paragraph']
    anchor: NonemptyText
    occurrence: PositiveInteger = 1


class TextFormatting(Operation):
    """Allow only explicitly supported text style flags."""

    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strikethrough: bool | None = None

    @model_validator(mode='after')
    def require_changes(self) -> Self:
        """Reject an empty formatting proposal, including explicit nulls."""
        if not self.model_dump(exclude_none=True):
            raise ValueError('At least one text style flag is required')
        return self


class FormatProposal(Operation):
    """Suggest text formatting on one literal case-sensitive match."""

    operation: Literal['format_text']
    find: NonemptyText
    occurrence: PositiveInteger = 1
    style: TextFormatting


ProposalOperation = Annotated[
    ReplaceProposal
    | InsertProposal
    | AppendProposal
    | DeleteProposal
    | FormatProposal,
    Field(discriminator='operation'),
]
SuggestionIds = Annotated[
    list[SuggestionId],
    Field(strict=True, min_length=1, max_length=50),
]
SuggestionAction = Literal['accept', 'reject', 'delete']


class SuggestionChanges(BaseModel):
    """Expose native IDs without assuming one suggestion per API request."""

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    accepted: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class SuggestResponse(BaseModel):
    """Confirm a saved, read-back proposal and its source tab."""

    ok: Literal[True] = True
    document_id: str
    tab_id: str | None
    heading_id: str | None = None
    operation: str
    revision_id: str | None
    comment_update_state: Literal['ALL_SAVED'] = 'ALL_SAVED'
    changes: SuggestionChanges
    warnings: list[str] = Field(default_factory=list)


class SuggestionDecision(BaseModel):
    """Describe one verified native decision or an already matching state."""

    suggestion_id: str
    action: SuggestionAction
    outcome: Literal['applied', 'already_decided']
    status: Literal['ACCEPTED', 'REJECTED', 'DELETED']


class SuggestionsManageResponse(BaseModel):
    """Return per-ID outcomes after a single preflighted decision batch."""

    ok: Literal[True] = True
    document_id: str
    revision_id: str | None
    comment_update_state: Literal['ALL_SAVED'] | None
    results: list[SuggestionDecision]
    changes: SuggestionChanges
