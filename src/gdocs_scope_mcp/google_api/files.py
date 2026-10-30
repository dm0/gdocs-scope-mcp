"""List and create Google Docs through uncached Google API clients."""

from http import HTTPStatus

from googleapiclient.errors import HttpError

from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.google_api.models import (
    CreateDocumentResponse,
    DocumentCreationFailedResponse,
    ListDocumentsResponse,
)
from gdocs_scope_mcp.settings import optional_env


def _query_literal(value: str) -> str:
    """Quote a Drive query value, escaping backslashes before apostrophes."""
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def list_documents(
    query: str = '', limit: int = 20, page_token: str | None = None,
):
    """Run the Google API workflow independently of MCP registration."""
    configured = optional_env('GDOCS_SCOPE_MCP_USE_DRIVE') or 'false'
    if configured.lower() not in {'true', 'false'}:
        raise ValueError('GDOCS_SCOPE_MCP_USE_DRIVE must be true or false')
    use_drive = configured.lower() == 'true'
    drive_id = optional_env('GDOCS_SCOPE_MCP_DRIVE_ID')
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
        q += f' and fullText contains {_query_literal(query)}'

    drive = clients.get_service('drive', 'v3', cached=False)
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


def create_document(title: str, initial_text: str = ''):
    """Run the Google API workflow independently of MCP registration."""
    service = clients.get_service('docs', 'v1', cached=False)
    doc = service.documents().create(body={'title': title}).execute()
    doc_id = doc['documentId']
    created = CreateDocumentResponse(
        id=doc_id,
        title=title,
        webViewLink=f'https://docs.google.com/document/d/{doc_id}/edit',
    )

    if initial_text:
        submitted = False
        try:
            request = service.documents().batchUpdate(
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
            )
            submitted = True
            request.execute()
        except Exception as error:
            # A timeout or service error does not prove that insertion failed.
            # Only explicit request/access/quota rejections confirm no write.
            rejected = isinstance(error, HttpError) and error.resp.status in {
                HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND,
                HTTPStatus.CONFLICT, HTTPStatus.PRECONDITION_FAILED,
                HTTPStatus.TOO_MANY_REQUESTS,
            }
            outcome = (
                'not_attempted' if not submitted else
                'rejected' if rejected else 'unknown'
            )
            raise ToolFailureError(DocumentCreationFailedResponse(
                code=('WRITE_OUTCOME_UNKNOWN' if outcome == 'unknown'
                      else 'PARTIAL_WRITE'),
                description='The document was created, but initial content '
                'insertion was not confirmed.',
                suggested_action='Do not repeat docs_create. Inspect the '
                'created document using created_document.id before adding '
                'any missing text to that same document.',
                created_document=created,
                initial_content=outcome,
            )) from error

    return created
