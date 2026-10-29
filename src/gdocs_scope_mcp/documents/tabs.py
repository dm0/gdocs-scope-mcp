"""Discover document tabs and keep every selected view and write scoped."""


from copy import deepcopy
from typing import Annotated

from pydantic import BaseModel, Field

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.models import TabInfo
from gdocs_scope_mcp.errors import ToolFailureError

MAX_TAB_ID_LENGTH = 256

TabId = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=MAX_TAB_ID_LENGTH,
        pattern=r'^\S+$',
        description='Tab ID from docs_get_tree.tabs or docs_tabs_list. '
        'Omit or pass null for the first root tab; no selector is needed '
        'for a single-tab document. Root and nested IDs are supported. '
        'When switching to another tab, pass its ID on subsequent calls. '
        'Explicit missing IDs fail without fallback.',
    ),
]


def fail(description, code='RESOURCE_NOT_FOUND'):
    """Never substitute another tab for a missing or ambiguous selection."""
    raise ToolFailureError(
        EditFailedResponse(
            code=code,
            description=description,
            suggested_action='Call docs_tabs_list to refresh tab IDs. '
            'Choose the intended tab and refresh its references.',
        )
    )


def walk(tabs, parent=None, depth=0):
    """Yield root and nested tabs in document order with actual parents."""
    for index, tab in enumerate(tabs):
        yield tab, parent, depth, index
        yield from walk(
            tab.get('childTabs', []), tab['tabProperties']['tabId'], depth + 1
        )


def require_matching_tab(expected, actual):
    """Explain a tab mismatch without suggesting the layout changed."""
    if expected == actual:
        return
    action = (f'Repeat this call with tab_id={expected!r}. '
              if expected is not None else
              'Refresh the reference from the intended tab. ')
    raise ToolFailureError(EditFailedResponse(
        code='TAB_MISMATCH',
        description=f'The reference belongs to tab_id={expected!r}, '
        f'but this call selected tab_id={actual!r}. '
        'An omitted tab_id selects the first root tab.',
        suggested_action=action + 'If you intended the currently selected '
        'tab, call docs_tables_list in that tab and use its references. '
        'Do not modify reference or snapshot tokens.',
    ))


def select(document, tab_id=None):
    """Return one tab's native body/metadata, retaining shared identity."""
    if tab_id is not None and (
        not isinstance(tab_id, str)
        or not tab_id
        or len(tab_id) > MAX_TAB_ID_LENGTH
        or any(c.isspace() for c in tab_id)
    ):
        fail(
            'tab_id must be a nonempty ID without whitespace.',
            'INVALID_ARGUMENT',
        )
    if '_mcp_tab_id' in document:
        if tab_id is not None and document['_mcp_tab_id'] != tab_id:
            fail('Selected snapshot belongs to a different tab.')
        return document
    tabs = list(walk(document.get('tabs', [])))
    if not tabs:
        if tab_id is not None:
            fail('Requested tab was not found.')
        return {**document, '_mcp_tab_id': None, '_mcp_tab_title': None,
                '_mcp_tabs': []}
    ids = [t['tabProperties']['tabId'] for t, *_ in tabs]
    if len(set(ids)) != len(ids):
        fail(
            'Duplicate native tab IDs make selection ambiguous.',
            'GOOGLE_API_ERROR',
        )
    chosen = (
        next(
            (t for t, *_ in tabs if t['tabProperties']['tabId'] == tab_id),
            None,
        )
        if tab_id is not None
        else tabs[0][0]
    )
    if chosen is None:
        fail('Requested tab was not found.')
    shared = {
        k: document[k]
        for k in (
            'documentId',
            'title',
            'revisionId',
            'documentStyle',
            'suggestedDocumentStyleChanges',
            'suggestionsViewMode',
            'commentsViewMode',
        )
        if k in document
    }
    return {
        **shared,
        **chosen['documentTab'],
        '_mcp_tab_id': chosen['tabProperties']['tabId'],
        '_mcp_tab_title': chosen['tabProperties'].get('title', ''),
        '_mcp_tabs': [TabInfo(
            tab_id=tab['tabProperties']['tabId'],
            title=tab['tabProperties'].get('title', ''),
            parent_tab_id=parent, depth=depth,
            index=tab['tabProperties'].get('index', index),
        ).model_dump() for tab, parent, depth, index in tabs],
    }


class TabsResponse(BaseModel):
    """List tab metadata without returning body contents or writing state."""

    document_id: str
    title: str
    revision_id: str | None = None
    default_tab_id: str | None
    tabs: list[TabInfo]


def discover(document):
    """Build hierarchy metadata; legacy responses expose no invented tab ID."""
    tabs = select(document).get('_mcp_tabs', [])
    return TabsResponse(
        document_id=document['documentId'],
        title=document.get('title', ''),
        revision_id=document.get('revisionId'),
        tabs=tabs,
        default_tab_id=tabs[0]['tab_id'] if tabs else None,
    )


def scope_requests(requests, tab_id):
    """Attach the selected tab only at native locations/ranges/criteria."""
    if tab_id is None:
        return requests
    result = deepcopy(requests)

    def locate(value):
        """Handle nested table locations as well as ordinary text ranges."""
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    'location',
                    'range',
                    'tableStartLocation',
                    'endOfSegmentLocation',
                } and isinstance(child, dict):
                    if child.get('tabId', tab_id) != tab_id:
                        fail(
                            'Native request targets a different tab.',
                            'INVALID_ARGUMENT',
                        )
                    child['tabId'] = tab_id
                else:
                    locate(child)
        elif isinstance(value, list):
            for child in value:
                locate(child)

    for request in result:
        name, payload = next(iter(request.items()))
        if name in {
            'replaceAllText',
            'deleteNamedRange',
            'replaceNamedRangeContent',
        }:
            if payload.get('tabsCriteria', {'tabIds': [tab_id]}) != {
                'tabIds': [tab_id],
            }:
                fail(
                    'Native request targets different tabs.',
                    'INVALID_ARGUMENT',
                )
            payload['tabsCriteria'] = {'tabIds': [tab_id]}
        else:
            locate(payload)
    return result
