"""List and create Google Docs through uncached Google API clients."""

import os

from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.google_api.models import (
    CreateDocumentResponse,
    ListDocumentsResponse,
)


def list_documents(
    query: str = '', limit: int = 20, page_token: str | None = None,
):
    """Run the Google API workflow independently of MCP registration."""
    drive = clients.get_service('drive', 'v3', cached=False)

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


def create_document(title: str, initial_text: str = ''):
    """Run the Google API workflow independently of MCP registration."""
    service = clients.get_service('docs', 'v1', cached=False)
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
