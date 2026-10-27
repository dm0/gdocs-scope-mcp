"""Expose document-bound API probes in explicitly launched test servers."""

import os
import re

from googleapiclient.errors import HttpError

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.server import mcp
from gdocs_scope_mcp.tool_logging import configure_logging

ALLOWED = {
    'createNamedRange', 'deleteNamedRange', 'insertText',
    'deleteContentRange', 'insertTableRow', 'deleteTableRow',
    'insertTableColumn', 'deleteTableColumn', 'mergeTableCells',
    'unmergeTableCells', 'updateTextStyle',
}


def _document_id() -> str:
    """Reject missing or URL-shaped targets before constructing API clients."""
    doc_id = os.environ.get('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', doc_id):
        raise ValueError('Set GDOCS_SCOPE_MCP_LIVE_TEST_DOC to a test Doc ID')
    return doc_id


@mcp.tool
def probe_document() -> dict:
    """Read the single environment-selected document with native indices."""
    doc_id = _document_id()
    return docs_edit._get_document(docs_edit._get_service(), doc_id)


@mcp.tool
def probe_batch(requests: list[dict], write_control: dict) -> dict:
    """Observe expected HTTP 400s without hiding authentication failures."""
    doc_id = _document_id()
    if not requests or any(len(r) != 1 or not set(r) <= ALLOWED
                           for r in requests):
        raise ValueError('Only table/identity probe operations allowed')
    if (len(write_control) != 1 or not set(write_control) <= {
        'requiredRevisionId', 'targetRevisionId',
    }):
        raise ValueError('Exactly one revision precondition required')
    try:
        result = docs_edit._get_service().documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests, 'writeControl': write_control},
        ).execute()
    except HttpError as error:
        if error.resp.status != 400:  # noqa: PLR2004
            raise
        return {'accepted': False, 'http_status': error.resp.status}
    return {'accepted': True, 'response': result}


configure_logging()
