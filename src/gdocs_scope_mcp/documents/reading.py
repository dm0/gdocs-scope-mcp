"""Internal documents.reading operations."""


from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents import fetching, parsing
from gdocs_scope_mcp.documents.models import (
    DocumentOutline,
    DocumentReadSection,
    DocumentSubset,
    DocumentTree,
)
from gdocs_scope_mcp.documents.tabs import discover
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.suggestions.index import (
    scope_ranges as suggestion_scope_ranges,
)
from gdocs_scope_mcp.suggestions.reading import (
    fetch as read_view,
    table_references,
)


def tabs_list(doc_id):
    """Discover root and nested tabs without modifying the document."""
    document = clients.get_service('docs', 'v1').documents().get(
        documentId=doc_id, includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    ).execute()
    return discover(document)


def read(
    doc_id: str, heading_ids: list[str] | None = None,
    *, tab_id: str | None = None,
) -> DocumentSubset | EditFailedResponse:
    """
    Read Google document or its parts including all nested headings.
    """
    service = clients.get_service('docs', 'v1')
    view = read_view(service, doc_id, tab_id)
    doc = view.document
    doc['table_refs'], table_warnings = table_references(view)
    google_doc = parsing.parse_document_tree(doc)

    if heading_ids is None:
        roots = google_doc.sections
        selected = None
        unknown = []
    else:
        requested = set(heading_ids)
        resolved = requested.intersection(google_doc.headings)
        unknown = list(dict.fromkeys(
            item for item in heading_ids if item not in google_doc.headings
        ))
        if heading_ids and not resolved:
            return EditFailedResponse(
                code='HEADING_NOT_FOUND',
                description='None of the requested heading IDs were found.',
                suggested_action='Call docs_get_tree to refresh heading IDs, '
                'then retry with IDs from the current outline.',
            )
        roots = [
            item for item in google_doc.descendants()
            if item.id in resolved
            and not resolved.intersection(item.ancestor_ids)
        ]
        selected = [item.id for item in roots]

    if selected and suggestion_scope_ranges(view.source, selected) is None:
        return EditFailedResponse(
            code='TARGET_CHANGED',
            description='Pending heading changes prevent safe mapping of '
            'this accepted heading selection to native source.',
            suggested_action='Read the whole tab without heading_ids, or '
            'review the heading proposals with docs_suggestions_read first.',
        )
    notice = view.index.notice(view.source, selected,
                               unavailable=view.unavailable)
    notice.warnings.extend(table_warnings)
    return DocumentSubset(
        suggestions=notice,
        tab_count=len(doc.get('_mcp_tabs', [])),
        sections=[
            DocumentReadSection(
                heading_id=item.id or None, markdown=item.subtree_markdown(),
            ) for item in roots
        ],
        unknown_heading_ids=unknown,
        selected_headings=selected,
        partial=heading_ids is not None,
        title=google_doc.title,
        revision_id=google_doc.revision_id,
        document_id=google_doc.document_id,
        tab_id=doc.get('_mcp_tab_id'), tab_title=doc.get('_mcp_tab_title'),
    )


def get_tree(doc_id: str, *, tab_id=None) -> DocumentOutline:
    """
    Fetch a Google Doc and return structured representation.
    """
    service = clients.get_service('docs', 'v1')
    view = read_view(service, doc_id, tab_id)
    doc = view.document

    tree = parsing.parse_document_tree(doc)
    flat_items = list(tree.descendants())

    return DocumentOutline(
        suggestions=view.index.notice(
            view.source, unavailable=view.unavailable,
        ),
        sections=flat_items,
        tabs=doc.get('_mcp_tabs', []),
        title=tree.title,
        revision_id=tree.revision_id,
        document_id=tree.document_id,
        tab_id=doc.get('_mcp_tab_id'), tab_title=doc.get('_mcp_tab_title'),
    )


def get_full_tree(doc_id: str, *, tab_id=None) -> DocumentTree:
    """
    Fetch a Google Doc and return structured representation.
    """
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)

    return parsing.parse_document_tree(doc)
