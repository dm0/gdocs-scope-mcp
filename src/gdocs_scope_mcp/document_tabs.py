"""Discover document tabs and keep every selected view and write scoped."""

from copy import deepcopy
from typing import Annotated

from pydantic import BaseModel, Field

from .models import EditFailedResponse
from .tool_errors import ToolFailureError

MAX_TAB_ID_LENGTH = 256

TabId = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=MAX_TAB_ID_LENGTH,
        pattern=r'^\S+$',
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
        return {**document, '_mcp_tab_id': None, '_mcp_tab_title': None}
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
    }


class TabInfo(BaseModel):
    """Expose a flat hierarchy suitable for explicit agent selection."""

    tab_id: str
    title: str
    parent_tab_id: str | None
    depth: int
    index: int


class TabsResponse(BaseModel):
    """List tab metadata without returning body contents or writing state."""

    document_id: str
    title: str
    revision_id: str | None = None
    default_tab_id: str | None
    tabs: list[TabInfo]


def discover(document):
    """Build hierarchy metadata; legacy responses expose no invented tab ID."""
    select(document)
    tabs = [
        TabInfo(
            tab_id=tab['tabProperties']['tabId'],
            title=tab['tabProperties'].get('title', ''),
            parent_tab_id=parent,
            depth=depth,
            index=tab['tabProperties'].get('index', index),
        )
        for tab, parent, depth, index in walk(document.get('tabs', []))
    ]
    return TabsResponse(
        document_id=document['documentId'],
        title=document.get('title', ''),
        revision_id=document.get('revisionId'),
        tabs=tabs,
        default_tab_id=tabs[0].tab_id if tabs else None,
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
