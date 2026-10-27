"""Expose document-bound API probes in explicitly launched test servers."""

import os
import re
import threading

from googleapiclient.errors import HttpError

from gdocs_scope_mcp import docs_edit, table_insertion
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

# This gate is test instrumentation, never production coordination. It lets
# the other STDIO process commit exactly inside an edit's read/write window.
_gate_lock = threading.Lock()
_release = threading.Event()
_gate = {'armed': False, 'ready': False, 'kind': 'read'}
_read = docs_edit._get_document
_submit_table = table_insertion.guarded_submit


def _paused_read(service, doc_id):
    """Pause one environment-selected read after taking its native snapshot."""
    document = _read(service, doc_id)
    with _gate_lock:
        pause = (_gate['armed'] and _gate['kind'] == 'read'
                 and doc_id == _document_id())
        if pause:
            _gate.update(armed=False, ready=True)
    if pause and not _release.wait(30):
        raise TimeoutError('Test read gate was not released within 30 seconds')
    return document


docs_edit._get_document = _paused_read


def _paused_table_submit(service, doc_id, requests, revision, **kwargs):
    """Pause after table creation committed but before its cell lookup."""
    result = _submit_table(service, doc_id, requests, revision, **kwargs)
    with _gate_lock:
        pause = (_gate['armed'] and _gate['kind'] == 'table'
                 and any('insertTable' in r for r in requests)
                 and doc_id == _document_id())
        if pause:
            _gate.update(armed=False, ready=True)
    if pause and not _release.wait(30):
        raise TimeoutError('Test table gate was not released')
    return result


table_insertion.guarded_submit = _paused_table_submit


@mcp.tool
def probe_pause_read() -> dict:
    """Arm the next target-document read in this isolated test process."""
    _document_id()
    with _gate_lock:
        _release.clear()
        _gate.update(armed=True, ready=False, kind='read')
    return {'armed': True}


@mcp.tool
def probe_pause_table_lookup() -> dict:
    """Arm one pause after a table-creation stage in this test process."""
    _document_id()
    with _gate_lock:
        _release.clear()
        _gate.update(armed=True, ready=False, kind='table')
    return {'armed': True}


@mcp.tool
def probe_read_gate() -> dict:
    """Observe synchronization without reading or editing a document."""
    with _gate_lock:
        return dict(_gate)


@mcp.tool
def probe_release_read() -> dict:
    """Release a paused test read; production writes still use revision CAS."""
    with _gate_lock:
        _gate['armed'] = False
        _release.set()
    return {'released': True}
