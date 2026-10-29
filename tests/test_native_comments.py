"""Verify native comment persistence, permissions and pagination."""


from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp import auth_setup, revision_guards
from gdocs_scope_mcp.google_api import credentials as google_credentials

from .native_comment_fixtures import comment_thread, wire_native_comments
from .test_table_discovery import call


@pytest.fixture
def native_api(mock_docs, simple_document):
    """Give thread anchors to both a root tab and a nested tab."""
    wire_native_comments(mock_docs, simple_document)
    body = deepcopy(simple_document['body'])
    simple_document['tabs'] = [
        {
            'tabProperties': {'tabId': 'first', 'title': 'Main'},
            'documentTab': {
                'body': body,
                'commentAnchors': {
                    'anchor-comment-id': {
                        'ranges': [
                            {'startIndex': 1, 'endIndex': 8},
                        ]
                    },
                },
            },
            'childTabs': [
                {
                    'tabProperties': {'tabId': 'nested', 'title': 'Child'},
                    'documentTab': {
                        'body': deepcopy(body),
                        'commentAnchors': {
                            'anchor-nested-id': {
                                'ranges': [
                                    {'startIndex': 4, 'endIndex': 16},
                                ]
                            },
                        },
                    },
                }
            ],
        }
    ]
    simple_document['comments'].append(comment_thread('nested-id'))
    return mock_docs, simple_document


def test_native_read_joins_threads_and_anchors_without_writes(native_api):
    """Map a nested anchor correctly and omit reply bodies in listings."""
    api, _ = native_api
    result = call('docs_read_comments', doc_id='example')
    assert not result.is_error
    data = result.structured_content
    assert data['page_kind'] == 'threads'
    assert [t['tab_id'] for t in data['comments']] == ['first', 'nested']
    assert all(
        t['anchored'] and t['reply_count'] == 1 and not t['replies']
        for t in data['comments']
    )
    assert data['comments'][1]['ranges'] == [
        {
            'tab_id': 'nested',
            'segment_id': None,
            'start_index': 4,
            'end_index': 16,
        }
    ]
    assert parse_qs(urlsplit(api.get.return_value.uri).query)[
        'commentsViewMode'
    ] == ['COMMENTS_VIEW_MODE_INCLUDED']
    api.get.assert_called_once_with(
        documentId='example',
        includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    )
    api.batchUpdate.assert_not_called()


@pytest.mark.parametrize(
    'operation,extra,name',
    [
        ('docs_reply_to_comment', {'reply': 'Reply'}, 'addCommentReply'),
        ('docs_resolve_comment', {}, 'addCommentReply'),
        ('docs_reopen_comment', {'reply': 'Reopen'}, 'addCommentReply'),
        ('docs_edit_comment', {'content': 'Edited'}, 'updateCommentPost'),
        (
            'docs_edit_comment',
            {'content': 'Edited', 'post_id': 'reply-id'},
            'updateCommentPost',
        ),
        (
            'docs_delete_comment_reply',
            {'reply_id': 'reply-id'},
            'deleteCommentReply',
        ),
        ('docs_delete_comment', {}, 'deleteComment'),
    ],
)
def test_native_id_mutations_are_document_wide(
    native_api, operation, extra, name
):
    """A comment on a child tab needs no hidden selection or Drive request."""
    api, _ = native_api
    result = call(operation, doc_id='example', comment_id='nested-id', **extra)
    assert not result.is_error, result.structured_content
    data = result.structured_content
    assert data['tab_id'] == 'nested'
    assert data['comment_update_state'] == 'ALL_SAVED'
    api.batchUpdate.assert_called_once()
    body = api.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert list(body['requests'][0]) == [name]
    assert body['requests'][0][name]['commentId'] == 'nested-id'


@pytest.mark.parametrize(
    'state,code',
    [
        ('ALL_FAILED_UNKNOWN_REASON', 'PARTIAL_WRITE'),
        (None, 'WRITE_OUTCOME_UNKNOWN'),
        ('NO_UPDATES_REQUESTED', 'WRITE_OUTCOME_UNKNOWN'),
        ('COMMENT_UPDATE_STATE_UNSPECIFIED', 'WRITE_OUTCOME_UNKNOWN'),
    ],
)
@pytest.mark.parametrize('creation', [False, True])
def test_unconfirmed_persistence_never_claims_success_or_replays(
    native_api,
    state,
    code,
    creation,
):
    """An HTTP-successful batch can still fail to persist its comment."""
    api, _ = native_api
    api.batchUpdate.return_value.execute.side_effect = None
    api.batchUpdate.return_value.execute.return_value = {
        'commentUpdateState': state,
    }
    tool = 'docs_add_comment' if creation else 'docs_resolve_comment'
    args = (
        {'comment': 'Review', 'anchor_text': 'Target phrase'}
        if creation
        else {'comment_id': 'comment-id'}
    )
    result = call(tool, doc_id='example', **args)
    assert result.is_error
    assert result.structured_content['code'] == code
    assert result.structured_content['committed_batches'] == 1
    api.batchUpdate.assert_called_once()


@pytest.mark.parametrize(
    'operation,extra',
    [
        ('docs_resolve_comment', {'comment_id': 'comment-id'}),
        (
            'docs_add_comment',
            {'comment': 'Review', 'anchor_text': 'Target phrase'},
        ),
    ],
)
def test_unknown_network_write_is_not_replayed(native_api, operation, extra):
    """A lost reply does not justify posting a duplicate comment/action."""
    api, _ = native_api
    api.batchUpdate.return_value.execute.side_effect = TimeoutError()
    result = call(operation, doc_id='example', **extra)
    assert result.is_error
    assert result.structured_content['code'] == 'WRITE_OUTCOME_UNKNOWN'
    api.batchUpdate.assert_called_once()


def test_existing_orphan_thread_is_readable_and_not_reanchored(native_api):
    """An old API/UI thread without a current anchor retains its native ID."""
    api, source = native_api
    source['comments'].append(comment_thread('orphan', resolved=True))
    result = call(
        'docs_read_comments', doc_id='example', include_resolved=True
    )
    orphan = next(
        c for c in result.structured_content['comments'] if c['id'] == 'orphan'
    )
    assert not orphan['anchored'] and orphan['tab_id'] is None
    assert orphan['ranges'] == [] and orphan['resolved']
    api.batchUpdate.assert_not_called()


def test_thread_and_reply_pagination_are_state_bound(native_api):
    """A changed comment invalidates a cursor even with the same revision."""
    api, source = native_api
    first = call('docs_read_comments', doc_id='example', limit=1)
    token = first.structured_content['next_page_token']
    second = call(
        'docs_read_comments', doc_id='example', limit=1, page_token=token
    )
    assert second.structured_content['comments'][0]['id'] == 'nested-id'
    assert not second.structured_content['has_more']
    source['comments'][0]['headPost']['content'] = 'Concurrent comment edit'
    stale = call(
        'docs_read_comments', doc_id='example', limit=1, page_token=token
    )
    assert (
        stale.is_error
        and stale.structured_content['code'] == 'STALE_REFERENCE'
    )
    source['comments'][0]['replies'].append(
        {'postId': 'second-reply', 'content': 'Second'}
    )
    reply_page = call(
        'docs_read_comments',
        doc_id='example',
        comment_id='comment-id',
        limit=1,
    )
    assert reply_page.structured_content['page_kind'] == 'replies'
    expected_replies = 2
    assert reply_page.structured_content['comments'][0]['reply_count'] == (
        expected_replies
    )
    reply_page = call(
        'docs_read_comments',
        doc_id='example',
        comment_id='comment-id',
        limit=1,
        page_token=reply_page.structured_content['next_page_token'],
    )
    assert (
        reply_page.structured_content['comments'][0]['replies'][0]['post_id']
        == 'second-reply'
    )
    assert not reply_page.structured_content['has_more']
    api.batchUpdate.assert_not_called()


@pytest.mark.parametrize('text', ['', '😀' * 513, 'Ж' * 1025, '\ud800'])
def test_invalid_native_comment_text_fails_before_api(mock_docs, text):
    """Enforce the API's UTF-8 limit rather than Python character counts."""
    result = call(
        'docs_add_comment',
        doc_id='example',
        comment=text,
        anchor_text='Target phrase',
    )
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('text', ['a' * 2048, '😀' * 512, 'Ж' * 1024])
@pytest.mark.usefixtures('native_api')
def test_exact_utf8_boundary_is_accepted(text):
    """All three strings contain exactly 2048 UTF-8 bytes."""
    result = call(
        'docs_add_comment',
        doc_id='example',
        comment=text,
        anchor_text='Target phrase',
    )
    assert not result.is_error
    assert result.structured_content['comment_content'] == text


@pytest.mark.parametrize('stage', ['read', 'write'])
def test_permission_failures_never_fall_back_to_drive(native_api, stage):
    """Forced comment inclusion exposes access denial instead of empty data."""
    api, _ = native_api
    error = HttpError(
        Response({'status': '403'}),
        b'{"error":{"message":"Permission denied"}}',
    )
    request = api.get if stage == 'read' else api.batchUpdate
    request.return_value.execute.side_effect = error
    result = call(
        'docs_reply_to_comment',
        doc_id='example',
        comment_id='comment-id',
        reply='Reply',
    )
    assert result.is_error
    assert result.structured_content['code'] == 'PERMISSION_DENIED'
    if stage == 'read':
        api.batchUpdate.assert_not_called()


def test_obsolete_options_and_drive_cursors_are_rejected(native_api):
    """Migration is explicit; no silent compatibility fallback is used."""
    api, _ = native_api
    for option in ['bookmark_jump', 'include_anchor_text']:
        result = call(
            'docs_add_comment',
            doc_id='example',
            comment='Comment',
            anchor_text='Target phrase',
            **{option: True},
        )
        assert result.is_error
    cursor = call(
        'docs_read_comments', doc_id='example', page_token='drive-token'
    )
    assert cursor.is_error
    assert cursor.structured_content['code'] == 'INVALID_ARGUMENT'
    api.batchUpdate.assert_not_called()


def test_native_comments_need_no_script_scopes():
    """Retain Docs/Drive access without requesting new script grants."""
    assert not any('/auth/script.' in scope for scope in auth_setup.SCOPES)
    assert 'https://www.googleapis.com/auth/documents' in auth_setup.SCOPES
    assert 'https://www.googleapis.com/auth/drive' in auth_setup.SCOPES


@pytest.mark.parametrize('mode,key', [
    ('required', 'requiredRevisionId'), ('target', 'targetRevisionId'),
])
def test_comment_mutations_preserve_revision_modes(native_api, monkeypatch,
                                                   mode, key):
    """The native migration retains the configured revision policy."""
    api, _ = native_api
    monkeypatch.setattr(revision_guards, 'get_settings', lambda: (
        SimpleNamespace(write_revision_mode=mode)
    ))
    result = call('docs_reply_to_comment', doc_id='example',
                  comment_id='nested-id', reply='Reply')
    assert not result.is_error
    assert api.batchUpdate.call_args.kwargs['body']['writeControl'] == {
        key: 'revision',
    }
    api.batchUpdate.reset_mock()
    result = call('docs_reply_to_comment', doc_id='example',
                  comment_id='nested-id', reply='Reply',
                  expected_revision_id='revision')
    assert not result.is_error
    assert api.batchUpdate.call_args.kwargs['body']['writeControl'] == {
        'requiredRevisionId': 'revision',
    }


def test_missing_revision_allows_read_but_not_unprotected_write(native_api):
    """Comment-only access does not silently disable revision guards."""
    api, document = native_api
    document.pop('revisionId')
    read = call('docs_read_comments', doc_id='example')
    assert not read.is_error and read.structured_content['revision_id'] is None
    write = call('docs_reply_to_comment', doc_id='example',
                 comment_id='comment-id', reply='Reply')
    assert write.is_error
    assert write.structured_content['code'] == 'REVISION_UNAVAILABLE'
    api.batchUpdate.assert_not_called()


@pytest.mark.parametrize('creation', [True, False])
def test_missing_new_ids_do_not_authorize_replay(native_api, creation):
    """ALL_SAVED without new identity is an unknown result, not success."""
    api, _ = native_api
    api.batchUpdate.return_value.execute.side_effect = None
    api.batchUpdate.return_value.execute.return_value = {
        'commentUpdateState': 'ALL_SAVED', 'replies': [{}],
    }
    if creation:
        result = call('docs_add_comment', doc_id='example', comment='Note',
                      anchor_text='Target phrase')
    else:
        result = call('docs_reply_to_comment', doc_id='example',
                      comment_id='comment-id', reply='Reply')
    assert result.is_error
    assert result.structured_content['code'] == 'WRITE_OUTCOME_UNKNOWN'
    assert result.structured_content['committed_batches'] == 1
    api.batchUpdate.assert_called_once()


def test_existing_token_with_script_scopes_still_loads(monkeypatch):
    """Existing tokens are accepted without modifying old grants."""
    old = {'client_id': 'client', 'client_secret': 'secret',
           'refresh_token': 'refresh', 'email': 'old@example.com',
           'scopes': ['https://www.googleapis.com/auth/documents',
                      'https://www.googleapis.com/auth/script.projects']}
    before = deepcopy(old)
    credentials = MagicMock()
    constructor = MagicMock(return_value=credentials)
    monkeypatch.setattr(google_credentials, 'load_token', lambda: old)
    monkeypatch.setattr(google_credentials, 'Credentials', constructor)
    monkeypatch.setattr(google_credentials, 'Request', lambda: None)
    assert google_credentials.load_credentials() is credentials
    assert old == before
    assert constructor.call_args.kwargs['scopes'] == old['scopes']
    credentials.refresh.assert_called_once()
