"""Thin MCP adapters for files."""

# Preserve the exact public descriptions after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp.google_api import files
from gdocs_scope_mcp.google_api.models import (
    CreateDocumentResponse,
    ListDocumentsResponse,
)
from gdocs_scope_mcp.tool_inputs import (
    NonemptyText,
    PositiveInteger,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp):
    """Register files tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(ListDocumentsResponse),
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
        return files.list_documents(query, limit, page_token)


    @mcp.tool(
        output_schema=tool_response_schema(CreateDocumentResponse),
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
        return files.create_document(title, initial_text)

