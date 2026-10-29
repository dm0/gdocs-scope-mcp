"""Read accepted-content projections and inspect native suggestion threads."""

# Authentication and tree parsing are shared lazily with the edit backend.
# ruff: noqa: PLC0415

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, NoReturn

from googleapiclient.errors import HttpError
from pydantic import Field

from . import comments
from .document_tabs import select
from .errors import ToolFailureError
from .models import EditFailedResponse
from .suggestion_index import (
    STYLE_LEVELS,
    ProposalIndex,
    index_document,
    scope_ranges,
)
from .suggestion_models import (
    SuggestionDetails,
    SuggestionPost,
    SuggestionsReadResponse,
)

SuggestionId = Annotated[
    str, Field(strict=True, min_length=1, max_length=2048)
]
SuggestionLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
SuggestionCursor = Annotated[str, Field(strict=True, max_length=8192)]
SUMMARY_LIMIT = 2000
LOCATION_LIMIT = 100


def fail(code, description) -> NoReturn:
    """Report read failures without treating a projection as a saved change."""
    raise ToolFailureError(
        EditFailedResponse(
            code=code,
            description=description,
            suggested_action='Refresh docs_get_tree or docs_suggestions_read. '
            'Use current heading/tab/suggestion IDs. Preview indices are not '
            'native write indices; no suggestion was accepted or rejected.',
        )
    )


@dataclass
class ReadView:
    """Keep one coherent native snapshot and its accepted-content view."""

    native: dict
    source: dict
    document: dict
    index: ProposalIndex
    unavailable: bool = False
    projected: bool = False


def fetch(service, doc_id, tab_id=None, *, threads=False):
    """Pair projections by revision; skip extra calls without proposals."""

    def get(view):
        return (
            service.documents()
            .get(
                documentId=doc_id,
                includeTabsContent=True,
                suggestionsViewMode=view,
            )
            .execute()
        )

    for _attempt in range(3):
        try:
            native = (
                comments.fetch(service, doc_id)
                if threads
                else get('SUGGESTIONS_INLINE')
            )
        except HttpError as error:
            if error.resp.status != HTTPStatus.FORBIDDEN or threads:
                raise
            projected = get('PREVIEW_WITHOUT_SUGGESTIONS')
            selected = select(projected, tab_id)
            return ReadView(
                projected,
                selected,
                selected,
                ProposalIndex(),
                unavailable=True,
                projected=True,
            )
        source = select(native, tab_id)
        index = index_document(native)
        if not index.locations and not index.unknown:
            return ReadView(native, source, source, index)
        projected = get('PREVIEW_WITHOUT_SUGGESTIONS')
        revision = native.get('revisionId')
        if revision and projected.get('revisionId') != revision:
            continue
        document = select(projected, source.get('_mcp_tab_id'))
        if not revision:
            # Without revision IDs there is no proof these two reads match.
            return ReadView(
                native,
                document,
                document,
                ProposalIndex(),
                unavailable=True,
                projected=True,
            )
        source = _heading_mapping(source, document)
        return ReadView(native, source, document, index, projected=True)
    fail(
        'EDIT_CONFLICT',
        'The document changed between suggestion and '
        'accepted-content reads on three consecutive attempts.',
    )


def _heading_mapping(source, document):
    """Exclude hidden proposed headings from accepted subtree boundaries."""

    def headings(value):
        result = {}
        for item in value.get('body', {}).get('content', []):
            paragraph = item.get('paragraph', {})
            style = paragraph.get('paragraphStyle', {})
            identity = style.get('headingId')
            if identity is None:
                continue
            text = ''.join(
                run.get('textRun', {}).get('content', '')
                for run in paragraph.get('elements', [])
                if not run.get('textRun', {}).get('suggestedInsertionIds')
            )
            result[identity] = (
                STYLE_LEVELS.get(style.get('namedStyleType'), 100),
                text,
            )
        return result

    native, projected = headings(source), headings(document)
    return {
        **source,
        '_mcp_heading_levels': {
            sid: value[0] for sid, value in projected.items()
        },
        '_mcp_unsafe_headings': {
            sid for sid, value in projected.items() if native.get(sid) != value
        },
    }


def table_references(view):
    """Expose projected table refs only when native meaning is unchanged."""
    from .table_read import reference_map

    if not view.document.get('revisionId'):
        return {}, ['Table references require edit access and a revision ID.']
    projected = reference_map(view.document)
    if not view.projected:
        return projected, []
    if view.unavailable:
        return {}, [
            'Table references omitted: native suggestion structure '
            'could not be checked.'
        ] if projected else []
    native = set(reference_map(view.source).values())
    safe = {index: ref for index, ref in projected.items() if ref in native}
    warnings = [
        'Some table references were omitted because pending '
        'structural proposals change their native scope or position.'
    ]
    return safe, warnings if len(safe) != len(projected) else []


def _post(value):
    return SuggestionPost(
        post_id=value.get('postId'),
        content=value.get('content', ''),
        author=value.get('author', {}).get('displayName'),
        created=value.get('createTime'),
        updated=value.get('updateTime'),
        deleted=value.get('deleted', False),
        action=value.get('suggestionAction'),
    )


def read(
    doc_id,
    *,
    tab_id=None,
    heading_id=None,
    suggestion_id=None,
    include_closed=False,
    limit=50,
    page_token=None,
):
    """Page scoped threads or one thread's head and bounded replies."""
    from . import docs_edit

    view = fetch(docs_edit._get_service(), doc_id, tab_id, threads=True)
    if heading_id is not None:
        tree = docs_edit._parse_document_tree(view.document)
        if heading_id not in tree.headings:
            fail(
                'HEADING_NOT_FOUND',
                'The heading is absent from the accepted-content outline.',
            )
    ranges = scope_ranges(view.source, [heading_id] if heading_id else None)
    if ranges is None:
        fail(
            'TARGET_CHANGED',
            'Pending heading changes prevent safe mapping '
            'of this accepted heading scope. Read the whole tab instead.',
        )
    threads = {
        t['suggestionId']: t for t in view.native.get('suggestions', [])
    }
    # Do not silently hide a pending native ID if thread metadata is missing.
    for sid in view.index.locations:
        threads.setdefault(sid, {'suggestionId': sid, 'status': 'UNKNOWN'})
    selected = []
    for sid, thread in sorted(threads.items()):
        if suggestion_id is not None and sid != suggestion_id:
            continue
        if (
            suggestion_id is None
            and not include_closed
            and thread.get('status') not in {'OPEN', 'UNKNOWN'}
        ):
            continue
        match = view.index.relation(
            sid, view.source.get('_mcp_tab_id'), ranges
        )
        if heading_id is None and any(
            loc.tab_id in {None, view.source.get('_mcp_tab_id')}
            and loc.segment_id is not None
            for loc in view.index.locations.get(sid, [])
        ):
            match = True
        if match is False:
            continue
        selected.append((sid, thread, match))
    if suggestion_id is not None and not selected:
        fail(
            'RESOURCE_NOT_FOUND', 'The suggestion was not found in this scope.'
        )
    state = comments.digest(
        [view.native, heading_id, tab_id, suggestion_id, include_closed, limit]
    )
    expected = {'suggestions_state': state, 'document': doc_id}
    try:
        offset = comments.page_offset(page_token, expected)
    except ToolFailureError as error:
        fail(
            error.failure.code,
            'Invalid or stale suggestion cursor. '
            'Restart docs_suggestions_read without page_token and keep '
            'document, tab, heading, ID, status and limit filters unchanged.',
        )
    if suggestion_id is None:
        page = selected[offset : offset + limit]
        total = len(selected)
    else:
        page = selected
        total = len(page[0][1].get('replies', []))
    items = []
    for sid, thread, match in page:
        locations = view.index.locations.get(sid, [])
        summary = thread.get('summaryText', '')
        html = thread.get('summaryHtml', '')
        head = thread.get('headPost', {})
        items.append(
            SuggestionDetails(
                suggestion_id=sid,
                status=thread.get('status', 'UNKNOWN'),
                author=head.get('author', {}).get('displayName'),
                summary=summary[:SUMMARY_LIMIT],
                summary_html=html[:SUMMARY_LIMIT],
                summary_truncated=len(summary) > SUMMARY_LIMIT
                or len(html) > SUMMARY_LIMIT,
                scope_match='matched' if match else 'unknown',
                locations=locations[:LOCATION_LIMIT],
                locations_truncated=len(locations) > LOCATION_LIMIT,
                head_post=_post(head) if suggestion_id is not None else None,
                reply_count=len(thread.get('replies', [])),
                replies=[
                    _post(post)
                    for post in thread.get('replies', [])[
                        offset : offset + limit
                    ]
                ]
                if suggestion_id is not None
                else [],
            )
        )
    more = offset + limit < total
    return SuggestionsReadResponse(
        document_id=doc_id,
        revision_id=view.document.get('revisionId'),
        tab_id=view.document.get('_mcp_tab_id'),
        heading_id=heading_id,
        suggestions=items,
        page_kind='replies' if suggestion_id else 'suggestions',
        count=len(items),
        total=total,
        has_more=more,
        next_page_token=comments.cursor(expected, offset + limit)
        if more
        else None,
        warnings=[
            'Unlocated or closed threads are included with unknown '
            'scope; their summaries do not establish source ranges.'
        ]
        if any(item.scope_match == 'unknown' for item in items)
        else [],
    )
