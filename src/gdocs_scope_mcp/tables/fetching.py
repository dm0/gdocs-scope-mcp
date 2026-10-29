"""Internal tables.fetching responsibilities."""

from gdocs_scope_mcp.documents import fetching
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.tables.references import _require_revision
from gdocs_scope_mcp.tables.refs import first_tab


def _fetch(doc_id, tab_id=None):
    """Read the selected tab through the normal read-only API boundary."""

    document = first_tab(fetching.get_document(
        clients.get_service(), doc_id, tab_id=tab_id,
    ))
    _require_revision(document)
    return document
