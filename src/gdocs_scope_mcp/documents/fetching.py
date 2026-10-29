"""Internal documents.fetching operations."""


from gdocs_scope_mcp.documents.tabs import select
from gdocs_scope_mcp.revision_guards import (
    pinned_tab,
    remember_snapshot,
)


def get_document(service, doc_id: str, *, tab_id=None) -> dict:
    """
    Fetch a document with inline suggestions so returned indices stay usable

    for later batchUpdate calls.
    """
    document = service.documents().get(
        documentId=doc_id, includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    ).execute()
    return remember_snapshot(select(
        document, tab_id if tab_id is not None else pinned_tab(),
    ))

