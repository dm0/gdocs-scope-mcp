"""Expose document-bound API probes in explicitly launched test servers."""

import json
import os
import re
import threading
from pathlib import Path

from googleapiclient.errors import HttpError

from gdocs_scope_mcp import (
    docs_edit,
    table_format,
    table_insertion,
    table_patch,
    table_structure,
)
from gdocs_scope_mcp.server import mcp
from gdocs_scope_mcp.tool_logging import configure_logging

ALLOWED = {
    'addDocumentTab', 'deleteTab',
    'createNamedRange', 'deleteNamedRange', 'insertText',
    'deleteContentRange', 'insertTableRow', 'deleteTableRow',
    'insertTableColumn', 'deleteTableColumn', 'mergeTableCells',
    'unmergeTableCells', 'updateTextStyle', 'updateParagraphStyle',
    'updateTableCellStyle',
    'updateTableColumnProperties', 'updateTableRowStyle', 'pinTableHeaderRows',
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
def probe_tabs_document() -> dict:
    """Read every tab only in the explicitly authorized test document."""
    return docs_edit._get_service().documents().get(
        documentId=_document_id(), includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    ).execute()


@mcp.tool
def probe_export_pdf() -> dict:
    """Export only the environment-authorized document for local visual QA."""
    doc_id = _document_id()
    data = docs_edit._get_service('drive', 'v3').files().export(
        fileId=doc_id, mimeType='application/pdf',
    ).execute()
    if not isinstance(data, bytes) or not data.startswith(b'%PDF'):
        raise ValueError('Expected a native PDF export')
    path = Path('/tmp/gdocs-scope-mcp-table-format-preview.pdf')
    path.write_bytes(data)
    return {'path': str(path), 'byte_count': len(data)}


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
        return {'accepted': False, 'http_status': error.resp.status,
                'message': json.loads(error.content).get('error', {}).get(
                    'message', 'Request rejected',
                )}
    return {'accepted': True, 'response': result}


configure_logging()

# This gate is test instrumentation, never production coordination. It lets
# the other STDIO process commit exactly inside an edit's read/write window.
_gate_lock = threading.Lock()
_release = threading.Event()
_gate = {'armed': False, 'ready': False, 'kind': 'read'}
_read = docs_edit._get_document
_submit_table = table_insertion.guarded_submit
_submit_patch = table_patch.submit
_patch_fault = {'armed': False}
_submit_format = table_format.submit
_format_fault = {'armed': False}
_submit_structure = table_structure.submit
_structure_fault = {'armed': False}


def _paused_read(service, doc_id, **kwargs):
    """Pause one environment-selected read after taking its native snapshot."""
    document = _read(service, doc_id, **kwargs)
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


def _with_fault(submit, fault, service, doc_id, requests, *args, **kwargs):
    """Inject one invalid request into an explicitly armed native batch."""
    with _gate_lock:
        fail = fault['armed']
        fault['armed'] = False
    if fail:
        requests = [*requests, {'deleteContentRange': {'range': {
            'startIndex': 0, 'endIndex': 999999999,
        }}}]
    return submit(service, doc_id, requests, *args, **kwargs)


def _atomic_failure(service, doc_id, requests, *args, **kwargs):
    """Inject one invalid request into an explicitly armed patch batch."""
    return _with_fault(_submit_patch, _patch_fault, service, doc_id, requests,
                       *args, **kwargs)


def _format_failure(service, doc_id, requests, *args, **kwargs):
    """Inject one invalid request into an armed formatting batch."""
    return _with_fault(
        _submit_format, _format_fault, service, doc_id, requests,
        *args, **kwargs,
    )


table_patch.submit = _atomic_failure
table_format.submit = _format_failure


def _structure_failure(service, doc_id, requests, *args, **kwargs):
    """Inject an invalid request into one armed structural batch."""
    result = _with_fault(
        _submit_structure, _structure_fault, service, doc_id, requests,
        *args, **kwargs,
    )
    with _gate_lock:
        pause = (_gate['armed'] and _gate['kind'] == 'structure'
                 and doc_id == _document_id())
        if pause:
            _gate.update(armed=False, ready=True)
    if pause and not _release.wait(30):
        raise TimeoutError('Test structure receipt gate was not released')
    return result


table_structure.submit = _structure_failure


@mcp.tool
def probe_fail_next_structure() -> dict:
    """Arm a single structural atomic-failure check in this test server."""
    _document_id()
    with _gate_lock:
        _structure_fault['armed'] = True
    return {'armed': True}


@mcp.tool
def probe_fail_next_patch() -> dict:
    """Arm a single native atomic-failure check in this test-only server."""
    _document_id()
    with _gate_lock:
        _patch_fault['armed'] = True
    return {'armed': True}


@mcp.tool
def probe_fail_next_format() -> dict:
    """Arm a single native formatting atomic-failure check."""
    _document_id()
    with _gate_lock:
        _format_fault['armed'] = True
    return {'armed': True}


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
def probe_pause_structure_receipt() -> dict:
    """Pause after one structural commit, before its reference readback."""
    _document_id()
    with _gate_lock:
        _release.clear()
        _gate.update(armed=True, ready=False, kind='structure')
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
