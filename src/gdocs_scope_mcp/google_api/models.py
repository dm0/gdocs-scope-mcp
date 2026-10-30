"""Models owned by google_api.models."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from gdocs_scope_mcp.contracts import EditFailedResponse, ListingPage


class DocumentListItem(BaseModel):
    """Describe a document found in Drive using its existing field names."""

    model_config = ConfigDict(serialize_by_alias=True)

    id: str
    name: str
    modified_time: Annotated[str | None, Field(alias='modifiedTime')] = None
    web_view_link: Annotated[str | None, Field(alias='webViewLink')] = None


class ListDocumentsResponse(ListingPage):
    """Return a typed document list and the number of returned items."""

    documents: list[DocumentListItem]


class CreateDocumentResponse(BaseModel):
    """Identify a newly created document and provide its browser URL."""

    model_config = ConfigDict(serialize_by_alias=True)

    id: str
    title: str
    web_view_link: Annotated[str, Field(alias='webViewLink')]


class DocumentCreationFailedResponse(EditFailedResponse):
    """Identify a created document after unconfirmed initial insertion."""

    code: Literal['PARTIAL_WRITE', 'WRITE_OUTCOME_UNKNOWN']
    created_document: CreateDocumentResponse
    initial_content: Literal['not_attempted', 'rejected', 'unknown']
