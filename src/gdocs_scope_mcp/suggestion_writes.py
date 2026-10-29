"""Plan native proposals and verify their persistence separately from edits."""

# Reuse authentication and source mapping without a docs_edit import cycle.
# ruff: noqa: PLC0415

from http import HTTPStatus

from googleapiclient.errors import HttpError

from . import comments, suggestions
from .md2requests import markdown_to_requests
from .models import EditFailedResponse
from .revision_guards import depend_on, guarded_edit, remember_snapshot, submit
from .suggestion_index import index_document, scope_ranges
from .suggestion_write_models import (
    SuggestionChanges,
    SuggestionDecision,
    SuggestionsManageResponse,
    SuggestResponse,
)
from .text_indices import utf16_length
from .tool_errors import ToolFailureError

CHANGE_FIELDS = {
    'created': 'createdSuggestionIds',
    'updated': 'updatedSummarySuggestionIds',
    'deleted': 'deletedSuggestionIds',
    'accepted': 'acceptedSuggestionIds',
    'rejected': 'rejectedSuggestionIds',
}


def fail(code, message, committed=0):
    """Direct recovery to current proposal state without replaying writes."""
    raise ToolFailureError(
        EditFailedResponse(
            code=code,
            description=message,
            committed_batches=committed,
            suggested_action='Read docs_read and docs_suggestions_read to '
            'inspect current content and native proposal IDs. Refresh the '
            'tab, heading or anchor. Never blindly replay an uncertain write.',
        )
    )


def saved(response):
    """Require independently persisted threads after the Docs batch."""
    state = response.get('commentUpdateState')
    if state != 'ALL_SAVED':
        fail(
            'PARTIAL_WRITE'
            if state == 'ALL_FAILED_UNKNOWN_REASON'
            else 'WRITE_OUTCOME_UNKNOWN',
            f'Proposal persistence was not confirmed ({state!r}).',
            1,
        )
    values = {}
    for name, field in CHANGE_FIELDS.items():
        ids = [
            sid
            for item in response.get('suggestionResponses', [])
            for sid in item.get(field, [])
        ]
        if any(not isinstance(sid, str) or not sid for sid in ids):
            fail(
                'WRITE_OUTCOME_UNKNOWN', 'Malformed proposal IDs returned.', 1
            )
        values[name] = sorted(set(ids))
    return SuggestionChanges(**values)


def _decide(service, doc_id, action, pending):
    """Keep operation-specific permission guidance after a rejected batch."""
    try:
        return submit(service, doc_id, [
            {action + 'Suggestion': {'suggestionId': sid}} for sid in pending
        ], write_mode='EDIT')
    except HttpError as error:
        if error.resp.status == HTTPStatus.FORBIDDEN:
            requirement = {
                'accept': 'Accepting requires edit access to the document.',
                'reject': 'Rejecting requires edit access or authorship.',
                'delete': 'Deleting requires authorship of each proposal.',
            }[action]
            fail('PERMISSION_DENIED', requirement + ' Google denied the '
                 'batch; also check OAuth scopes and quota permissions.')
        raise


def _safe_paragraph(view, paragraph):
    """Reject complex targets and whole paragraphs affected by proposals."""
    document = view.source
    item = next(
        (
            p
            for p in document['body']['content']
            if p.get('startIndex') == paragraph.start_index
            and p.get('endIndex') == paragraph.end_index
            and 'paragraph' in p
        ),
        None,
    )
    if (
        item is None
        or item['paragraph'].get('bullet')
        or item['paragraph'].get('positionedObjectIds')
        or any(
            'textRun' not in e for e in item['paragraph'].get('elements', [])
        )
    ):
        fail(
            'INVALID_ARGUMENT',
            'Proposals currently target ordinary body '
            'paragraphs, not table cells, lists, objects or native entities.',
        )
    bounds = [(paragraph.start_index, paragraph.end_index)]
    affected = [sid for sid in view.index.locations
                if view.index.relation(
                    sid, document.get('_mcp_tab_id'), bounds,
                ) is not False]
    if view.index.unknown or affected:
        fail(
            'EDIT_CONFLICT',
            'The selected paragraph has pending or '
            'unlocated proposals. Review or decide them before editing it. '
            f'IDs: {affected[:5]!r}; unknown metadata: {view.index.unknown}.',
        )
    depend_on(document, paragraph.start_index, paragraph.end_index)


def _insert(text, index, rich, *, before=False):
    """Compile once without image staging; reject unsupported whole plans."""
    if not rich:
        value = text + '\n' if before else '\n' + text
        return [
            {'insertText': {'location': {'index': index}, 'text': value}}
        ], []
    requests = markdown_to_requests(text, index, newline_before=not before)
    allowed = {
        'insertText',
        'updateTextStyle',
        'updateParagraphStyle',
        'createNamedRange',
    }
    if not isinstance(requests, list) or any(
        len(r) != 1 or not set(r) <= allowed for r in requests
    ):
        fail(
            'INVALID_ARGUMENT',
            'Suggested rich insertions support paragraphs '
            'and text formatting only; tables, lists, images and chips are '
            'not supported. Nothing was uploaded or written.',
        )
    markers = any('createNamedRange' in r for r in requests)
    # Native named ranges cannot be suggested. Never add them in direct mode.
    requests = [r for r in requests if 'createNamedRange' not in r]
    if not any('insertText' in r for r in requests):
        fail('INVALID_ARGUMENT', 'The insertion contains no supported text.')
    warnings = [
        'Code-block named-range markers were omitted because Google '
        'cannot suggest named ranges. Code formatting is retained.'
    ]
    return requests, warnings if markers else []


def _plan(view, operation, heading_id):
    """Resolve literal anchors on native indices within an accepted scope."""
    from . import docs_edit

    document = view.source
    ranges = scope_ranges(document, [heading_id] if heading_id else None)
    if ranges is None:
        fail(
            'HEADING_NOT_FOUND',
            'The heading scope has no safe native mapping.',
        )
    tree = docs_edit._parse_document_tree(document)
    if operation.operation == 'append':
        end = ranges[0][1]
        item = next(
            (
                p
                for p in reversed(document['body']['content'])
                if p.get('startIndex', 0) < end and 'paragraph' in p
            ),
            None,
        )
        if item is None or item['endIndex'] != end:
            fail(
                'INVALID_ARGUMENT', 'The scope must end with a body paragraph.'
            )
        matches = tree.find_all('\n', True)
        paragraph = next(
            (
                m.paragraph
                for m in reversed(matches)
                if m.paragraph.start_index == item['startIndex']
            ),
            None,
        )
        if paragraph is None:
            fail('INVALID_ARGUMENT', 'The last paragraph cannot be mapped.')
        _safe_paragraph(view, paragraph)
        return _insert(operation.text, paragraph.end_index - 1, operation.rich)
    needle = getattr(operation, 'find', None) or operation.anchor
    matches = [
        m
        for m in tree.find_all(needle, True)
        if any(a <= m.paragraph.start_index < b for a, b in ranges)
    ]
    if not matches:
        fail('TEXT_NOT_FOUND', 'No literal case-sensitive anchor was found.')
    if operation.occurrence > len(matches):
        fail('OCCURRENCE_NOT_FOUND', 'The requested occurrence was not found.')
    match = matches[operation.occurrence - 1]
    paragraph = match.paragraph
    _safe_paragraph(view, paragraph)
    if operation.operation in {'insert_before', 'insert_after'}:
        before = operation.operation == 'insert_before'
        index = paragraph.start_index if before else paragraph.end_index - 1
        return _insert(operation.text, index, operation.rich, before=before)
    if operation.operation == 'delete_paragraph':
        terminal = document['body']['content'][-1]['endIndex'] - 1
        start, end = paragraph.start_index, min(paragraph.end_index, terminal)
        if start >= end:
            fail('INVALID_ARGUMENT', 'The final paragraph is already empty.')
    else:
        start, end = docs_edit._full_text_range_to_doc_indices(
            match.start_index,
            match.end_index,
            paragraph.text,
            paragraph.text_map,
        )
    target = {'startIndex': start, 'endIndex': end}
    if operation.operation == 'format_text':
        style = operation.style.model_dump(exclude_none=True)
        return [
            {
                'updateTextStyle': {
                    'range': target,
                    'textStyle': style,
                    'fields': ','.join(style),
                }
            }
        ], []
    requests = []
    if operation.operation == 'replace' and operation.text:
        if operation.text == needle:
            fail('INVALID_ARGUMENT', 'Replacement text is unchanged.')
        requests.append(
            {
                'insertText': {
                    'location': {'index': start},
                    'text': operation.text,
                }
            }
        )
        offset = utf16_length(operation.text)
        target = {'startIndex': start + offset, 'endIndex': end + offset}
    requests.append({'deleteContentRange': {'range': target}})
    return requests, []


@guarded_edit
def suggest(
    doc_id,
    operation,
    *,
    tab_id=None,
    heading_id=None,
    expected_revision_id=None,  # noqa: ARG001 - decorator
):
    """Submit exactly one preflighted suggest batch and read back its IDs."""
    from . import docs_edit

    service = docs_edit._get_service()
    view = suggestions.fetch(service, doc_id, tab_id, threads=True)
    if view.unavailable or not view.source.get('revisionId'):
        fail(
            'REVISION_UNAVAILABLE',
            'Native proposal source cannot be verified.',
        )
    remember_snapshot(view.source)
    requests, warnings = _plan(view, operation, heading_id)
    changes = saved(submit(service, doc_id, requests, write_mode='SUGGEST'))
    ids = set(changes.created) | set(changes.updated)
    if not ids or changes.deleted or changes.accepted or changes.rejected:
        fail(
            'WRITE_OUTCOME_UNKNOWN',
            'The proposal returned no usable IDs or '
            'unexpected decisions. Inspect current proposals.',
            1,
        )
    after = comments.fetch(service, doc_id)
    threads = {t['suggestionId']: t for t in after.get('suggestions', [])}
    if any(
        sid not in threads or threads[sid].get('status') != 'OPEN'
        for sid in ids
    ):
        fail(
            'WRITE_OUTCOME_UNKNOWN',
            'Saved open proposals could not be '
            'verified by reading their native threads.',
            1,
        )
    return SuggestResponse(
        document_id=doc_id,
        tab_id=view.source.get('_mcp_tab_id'),
        heading_id=heading_id,
        operation=operation.operation,
        revision_id=after.get('revisionId'),
        changes=changes,
        warnings=warnings,
    )


def manage(doc_id, action, suggestion_ids, *, expected_revision_id=None):
    """Preflight all IDs, apply one decision batch, and verify each ID."""
    from . import docs_edit

    if len(set(suggestion_ids)) != len(suggestion_ids):
        fail('INVALID_ARGUMENT', 'Suggestion IDs must be unique.')
    baseline = None

    @guarded_edit
    def apply(*, expected_revision_id=None):  # noqa: ARG001 - decorator
        nonlocal baseline
        service = docs_edit._get_service()
        document = comments.fetch(service, doc_id)
        remember_snapshot(
            {'documentId': doc_id, 'revisionId': document.get('revisionId')}
        )
        threads = {
            t['suggestionId']: t for t in document.get('suggestions', [])
        }
        selected = [threads.get(sid) for sid in suggestion_ids]
        if any(
            t is None or t.get('headPost', {}).get('deleted') for t in selected
        ):
            fail(
                'RESOURCE_NOT_FOUND',
                'A selected proposal is missing/deleted; '
                'the complete batch was rejected before writing.',
            )
        state = comments.digest(
            [
                selected,
                {
                    sid: [loc.model_dump() for loc in locations]
                    for sid, locations in index_document(
                        document
                    ).locations.items()
                    if sid in suggestion_ids
                },
            ]
        )
        if baseline is not None and state != baseline:
            fail('EDIT_CONFLICT', 'A selected proposal changed during retry.')
        baseline = state
        desired = {
            'accept': 'ACCEPTED',
            'reject': 'REJECTED',
            'delete': 'DELETED',
        }[action]
        pending, results = [], []
        for sid, thread in zip(suggestion_ids, selected):
            status = thread.get('status')
            if status not in {'OPEN', desired}:
                fail(
                    'EDIT_CONFLICT',
                    'A selected proposal is already decided '
                    'differently or has unknown status. No decisions sent.',
                )
            if status == 'OPEN':
                pending.append(sid)
            results.append(
                SuggestionDecision(
                    suggestion_id=sid,
                    action=action,
                    status=desired,
                    outcome='applied'
                    if status == 'OPEN'
                    else 'already_decided',
                )
            )
        changes = SuggestionChanges()
        if pending:
            changes = saved(_decide(service, doc_id, action, pending))
            if not set(pending) <= set(
                getattr(
                    changes,
                    {
                        'accept': 'accepted',
                        'reject': 'rejected',
                        'delete': 'deleted',
                    }[action],
                )
            ):
                fail(
                    'WRITE_OUTCOME_UNKNOWN', 'Google omitted decision IDs.', 1
                )
            document = comments.fetch(service, doc_id)
            threads = {
                t['suggestionId']: t for t in document.get('suggestions', [])
            }
            remaining = index_document(document).locations
            for sid in pending:
                thread = threads.get(sid)
                verified = (
                    (
                        sid not in remaining
                        and (
                            thread is None
                            or thread.get('headPost', {}).get('deleted')
                            or thread.get('status') == 'DELETED'
                        )
                    )
                    if action == 'delete'
                    else (
                        thread is not None
                        and thread.get('status') == desired
                        and sid not in remaining
                    )
                )
                if not verified:
                    fail(
                        'WRITE_OUTCOME_UNKNOWN',
                        'A saved decision could not '
                        'be verified by reading native proposal state.',
                        1,
                    )
        return SuggestionsManageResponse(
            document_id=doc_id,
            revision_id=document.get('revisionId'),
            comment_update_state='ALL_SAVED' if pending else None,
            results=results,
            changes=changes,
        )

    return apply(expected_revision_id=expected_revision_id)
