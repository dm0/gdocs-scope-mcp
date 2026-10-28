"""Read native comment threads and confirm independently persisted writes."""

# Reuse authentication lazily without a docs_edit import cycle.
# ruff: noqa: PLC0415

import base64
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .document_tabs import walk
from .models import EditFailedResponse, ReadCommentsResponse
from .revision_guards import guarded_edit, remember_snapshot, submit
from .tool_errors import ToolFailureError


def fail(code, description, committed=0):
    """Never suggest replaying a comment with an unconfirmed save outcome."""
    raise ToolFailureError(
        EditFailedResponse(
            code=code,
            description=description,
            committed_batches=committed,
            suggested_action='Read current threads with docs_read_comments '
            'and posts before retrying. Use native comment/post IDs from that '
            'read. Discard Drive cursors. Do not blindly replay writes.',
        )
    )


def saved(response):
    """Check persistence even when the batchUpdate HTTP request succeeded."""
    state = response.get('commentUpdateState')
    if state == 'ALL_FAILED_UNKNOWN_REASON':
        fail(
            'PARTIAL_WRITE',
            'The Docs batch completed, but comment updates '
            'failed to save (commentUpdateState=ALL_FAILED_UNKNOWN_REASON). '
            'No automatic replay was performed.',
            1,
        )
    if state != 'ALL_SAVED':
        fail(
            'WRITE_OUTCOME_UNKNOWN',
            'The Docs batch completed without '
            f'confirmed comment persistence (commentUpdateState={state!r}). '
            'No automatic replay was performed.',
            1,
        )
    return response


def created(response, name, field):
    """Do not invent IDs if Google confirms persistence but omits identity."""
    payload = (
        next(
            (
                reply.get(name)
                for reply in response.get('replies', [])
                if name in reply
            ),
            {},
        )
        or {}
    )
    value = payload.get(field) or {}
    required = ('commentId',) if field == 'commentThread' else ('postId',)
    if not isinstance(value, dict) or not all(
        isinstance(value.get(key), str) and value[key] for key in required
    ):
        fail(
            'WRITE_OUTCOME_UNKNOWN',
            'Google reported ALL_SAVED but omitted '
            'the new native comment/post ID. Inspect threads before retry.',
            1,
        )
    return value


def fetch(service, doc_id):
    """
    Include comments using the authenticated client's ordinary request.

    Older installed discovery schemas lack commentsViewMode. Adding the
    documented query to HttpRequest.uri avoids replacing the client, changing
    dependencies, or downloading discovery metadata on every comment read.
    """
    request = service.documents().get(
        documentId=doc_id,
        includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    )
    parts = urlsplit(request.uri)
    query = dict(parse_qsl(parts.query))
    query['commentsViewMode'] = 'COMMENTS_VIEW_MODE_INCLUDED'
    request.uri = urlunsplit(parts._replace(query=urlencode(query)))
    return request.execute()


def anchors(document):
    """Resolve native anchors across all root and child tabs."""
    result = {}
    for tab, *_ in walk(document.get('tabs', [])):
        tab_id = tab['tabProperties']['tabId']
        for anchor_id, anchor in (
            tab['documentTab']
            .get(
                'commentAnchors',
                {},
            )
            .items()
        ):
            result.setdefault(anchor_id, []).extend(
                {
                    'tab_id': tab_id,
                    'segment_id': value.get('segmentId'),
                    'start_index': value.get('startIndex'),
                    'end_index': value.get('endIndex'),
                }
                for value in anchor.get('ranges', [])
            )
    return result


def tab_for(thread, anchor_map):
    """Do not guess a tab when its anchor is missing or spans several tabs."""
    ids = {r['tab_id'] for r in anchor_map.get(thread.get('anchorId'), [])}
    return next(iter(ids)) if len(ids) == 1 else None


def post(value):
    """Map native posts without treating resolved/action posts as content."""
    return {
        'post_id': value['postId'],
        'content': value.get('content', ''),
        'author': value.get('author', {}).get('displayName', '?'),
        'deleted': value.get('deleted', False),
        'created': value.get('createTime', ''),
        'updated': value.get('updateTime', ''),
        'action': value.get('commentAction'),
    }


def thread_summary(thread, anchor_map):
    """Keep listing small; replies are fetched by selecting one thread."""
    head = thread.get('headPost', {})
    ranges = anchor_map.get(thread.get('anchorId'), [])
    return {
        'id': thread['commentId'],
        'content': head.get('content', ''),
        'author': head.get('author', {}).get('displayName', '?'),
        'anchored': bool(ranges),
        'anchor_id': thread.get('anchorId'),
        'tab_id': tab_for(thread, anchor_map),
        'ranges': ranges,
        'head_post_id': head.get('postId'),
        'reply_count': len(thread.get('replies', [])),
        'quoted_text': thread.get('plainTextQuote', ''),
        'resolved': thread.get('status') == 'RESOLVED',
        'deleted': head.get('deleted', False),
        'created': head.get('createTime', ''),
    }


def digest(value):
    """Comments can change independently of body revisions; bind full state."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(',', ':'),
        ).encode()
    ).hexdigest()


def _unpack_page(token):
    """Validate cursor transport without interpreting server-side policy."""
    if len(token) > 8192:  # noqa: PLR2004
        raise ValueError('Oversized cursor')
    prefix, encoded, checksum = token.split('.')
    data = base64.b64decode(
        encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True
    )
    payload = json.loads(data)
    if prefix != 'gcc1' or digest(payload) != checksum:
        raise ValueError('Invalid checksum or old Drive token')
    offset = payload.pop('offset')
    if type(offset) is not int or offset < 0:
        raise ValueError('Invalid offset')
    return payload, offset


def page_offset(token, expected):
    """Reject stale, corrupt and differently filtered native cursors."""
    if token is None:
        return 0
    try:
        payload, offset = _unpack_page(token)
    except (ValueError, TypeError, KeyError, RecursionError):
        fail(
            'INVALID_ARGUMENT',
            'Invalid native comment continuation token. '
            'Restart without page_token; old Drive tokens are unsupported.',
        )
    if payload != expected:
        fail(
            'STALE_REFERENCE',
            'Comment state or pagination arguments changed. '
            'Restart without page_token; comments are not revision-cached.',
        )
    return offset


def cursor(expected, offset):
    """Encode portable, unprivileged cursor state rather than server memory."""
    value = {**expected, 'offset': offset}
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return (
        'gcc1.'
        + base64.urlsafe_b64encode(data).decode().rstrip('=')
        + '.'
        + digest(value)
    )


def read(
    doc_id,
    include_resolved=False,
    page_token=None,
    *,
    limit=100,
    comment_id=None,
):
    """Page document-wide thread summaries, or replies in a selected thread."""
    from . import docs_edit

    document = fetch(docs_edit._get_service(), doc_id)
    anchor_map = anchors(document)
    threads = sorted(
        document.get('comments', []),
        key=lambda t: (
            t.get('headPost', {}).get('createTime', ''),
            t['commentId'],
        ),
    )
    expected = {
        'document': doc_id,
        'include_resolved': include_resolved,
        'limit': limit,
        'comment_id': comment_id,
        'state': digest([threads, anchor_map]),
    }
    offset = page_offset(page_token, expected)
    if comment_id is None:
        visible = [
            t
            for t in threads
            if include_resolved
            or (
                t.get('status') != 'RESOLVED'
                and not t.get('headPost', {}).get('deleted')
            )
        ]
        items = visible[offset : offset + limit]
        summaries = [thread_summary(t, anchor_map) for t in items]
        total = len(visible)
    else:
        selected = next(
            (t for t in threads if t['commentId'] == comment_id), None
        )
        if selected is None:
            fail('RESOURCE_NOT_FOUND', 'Native comment thread was not found.')
        replies = selected.get('replies', [])
        total = len(replies)
        summaries = [thread_summary(selected, anchor_map)]
        summaries[0]['replies'] = [
            post(p) for p in replies[offset : offset + limit]
        ]
    next_offset = offset + limit
    return ReadCommentsResponse(
        document_id=doc_id,
        revision_id=document.get('revisionId'),
        comments=summaries,
        count=len(summaries),
        page_kind='replies' if comment_id is not None else 'threads',
        next_page_token=(
            cursor(expected, next_offset) if next_offset < total else None
        ),
    )


@guarded_edit
def mutate(
    doc_id,
    comment_id,
    operation,
    content='',
    post_id=None,
    *,
    expected_revision_id=None,  # noqa: ARG001 - decorator
):
    """Apply one ID-addressed mutation with the normal revision policy."""
    from . import docs_edit

    service = docs_edit._get_service()
    document = fetch(service, doc_id)
    # ID-addressed comments are document-wide. No first-tab body is targeted.
    remember_snapshot(
        {'documentId': doc_id, 'revisionId': document.get('revisionId')}
    )
    thread = next(
        (
            t
            for t in document.get('comments', [])
            if t['commentId'] == comment_id
        ),
        None,
    )
    if thread is None:
        fail('RESOURCE_NOT_FOUND', 'Native comment thread was not found.')
    base = {'commentId': comment_id}
    if operation in {'reply', 'resolve', 'reopen'}:
        value = {}
        if content:
            value['content'] = content
        if operation != 'reply':
            value['commentAction'] = operation.upper()
        request = {'addCommentReply': {**base, 'post': value}}
    elif operation == 'delete':
        request = {'deleteComment': base}
    else:
        posts = [thread.get('headPost', {}), *thread.get('replies', [])]
        post_id = post_id or thread.get('headPost', {}).get('postId')
        target = next((p for p in posts if p.get('postId') == post_id), None)
        if target is None or target.get('deleted'):
            fail(
                'RESOURCE_NOT_FOUND',
                'Native post was not found in this thread.',
            )
        if operation == 'delete_reply' and (
            target is thread.get('headPost')
            or target.get('commentAction') in {'RESOLVE', 'REOPEN'}
            or target.get('assigneeEmail')
        ):
            fail(
                'INVALID_ARGUMENT', 'Only ordinary reply posts can be deleted.'
            )
        name = (
            'updateCommentPost'
            if operation == 'edit'
            else 'deleteCommentReply'
        )
        request = {name: {**base, 'postId': post_id}}
        if operation == 'edit':
            request[name]['content'] = content
    response = saved(submit(service, doc_id, [request]))
    result = {
        'ok': True, 'document_id': doc_id,
        'comment_id': comment_id,
        'tab_id': tab_for(thread, anchors(document)),
        'revision_id': response.get('writeControl', {}).get(
            'requiredRevisionId'
        )
        or response.get('writeControl', {}).get('targetRevisionId'),
        'comment_update_state': 'ALL_SAVED',
    }
    if operation in {'reply', 'resolve', 'reopen'}:
        added = created(response, 'addCommentReply', 'post')
        result['reply_id'] = added['postId']
        if operation == 'reply':
            result['content'] = added.get('content', content)
    elif operation == 'edit':
        result.update(post_id=post_id, content=content)
    elif operation == 'delete_reply':
        result['reply_id'] = post_id
    return result
