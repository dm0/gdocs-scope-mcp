"""Exercise deterministic read/write races through the real edit planners."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp import docs_edit, revision_guards
from gdocs_scope_mcp.text_indices import utf16_length
from gdocs_scope_mcp.tool_errors import (
    ToolFailureError,
    failure_from_exception,
)


def api_error(message, status=400):
    """Return a real Google client exception with an explicit reason."""
    return HttpError(Response({'status': str(status)}), json.dumps({
        'error': {'message': message},
    }).encode())


def reindex(document):
    """Rebuild API UTF-16 positions after collaborator paragraph mutations."""
    index = 1
    for item in document['body']['content']:
        item['startIndex'] = index
        for run in item['paragraph']['elements']:
            run['startIndex'] = index
            index += utf16_length(run['textRun']['content'])
            run['endIndex'] = index
        item['endIndex'] = index
    return document


@pytest.fixture
def race_docs(monkeypatch, simple_document):
    """Reject one stale batch after committing a collaborator's chosen edit."""
    service = MagicMock()
    documents = service.documents()
    state = {'document': deepcopy(simple_document), 'writes': [],
             'change': lambda _document: None, 'always': False}
    documents.get.return_value.execute.side_effect = lambda: deepcopy(
        state['document'],
    )

    def write():
        """Enforce guards and record accepted/rejected request plans."""
        body = deepcopy(documents.batchUpdate.call_args.kwargs['body'])
        state['writes'].append(body)
        if len(state['writes']) == 1 or state['always']:
            state['change'](state['document'])
            reindex(state['document'])
            state['document']['revisionId'] = str(len(state['writes']))
            raise api_error('The provided revision ID does not match the '
                            'current revision ID of the document.')
        assert body['writeControl'] == {
            'requiredRevisionId': state['document']['revisionId'],
        }
        return {'replies': [{'createNamedRange': {'namedRangeId': 'anchor'}}]}

    documents.batchUpdate.return_value.execute.side_effect = write
    monkeypatch.setattr(docs_edit, '_get_service', lambda *_args: service)
    monkeypatch.setattr(revision_guards.time, 'sleep', lambda _delay: None)
    state['documents'] = documents
    return state


def change_prefix(document):
    """Shift later targets with a non-BMP insertion in another paragraph."""
    document['body']['content'][0]['paragraph']['elements'][0][
        'textRun']['content'] = 'Collaborator😀 prefix\n'


@pytest.mark.parametrize('operation', ['search', 'batch', 'before', 'after',
                                       'delete', 'comment'])
def test_independent_paragraph_change_replans_utf16(
    operation, race_docs, monkeypatch,
):
    """Retain the scoped target and rebuild its indices from the fresh read."""
    race_docs['change'] = change_prefix
    drive = MagicMock()
    monkeypatch.setattr(docs_edit, 'build', lambda *_a, **_k: drive)
    monkeypatch.setattr(docs_edit, '_load_creds', lambda: None)
    drive.comments().create().execute.return_value = {'id': 'comment'}
    drive.reset_mock()
    calls = {
        'search': lambda: docs_edit.search_replace(
            'test', 'Target phrase', 'new', heading_id='parent',
        ),
        'batch': lambda: docs_edit.batch_replace('test', [
            {'find': 'Target phrase', 'replace': 'new'},
        ]),
        'before': lambda: docs_edit.insert_before(
            'test', 'Target phrase', 'new', heading_id='parent', rich=False,
        ),
        'after': lambda: docs_edit.insert_after(
            'test', 'Target phrase', 'new', heading_id='parent', rich=False,
        ),
        'delete': lambda: docs_edit.delete_paragraph('test', 'Target phrase'),
        'comment': lambda: docs_edit.add_comment(
            'test', 'Review', 'Target phrase',
        ),
    }
    result = calls[operation]()
    assert result['ok'] if isinstance(result, dict) else result.ok
    old, fresh = race_docs['writes']
    old_requests = old['requests']
    new_requests = fresh['requests']
    delta = utf16_length('Collaborator😀 prefix\n') - len('Introduction\n')
    old_op = next(iter(old_requests[0].values()))
    new_op = next(iter(new_requests[0].values()))
    key = 'location' if 'location' in old_op else 'range'
    index_key = 'index' if key == 'location' else 'startIndex'
    assert new_op[key][index_key] - old_op[key][index_key] == delta
    if operation == 'comment':
        drive.comments().create.assert_called_once()


@pytest.mark.parametrize('mode', ['text', 'style', 'deleted', 'new_match',
                                  'duplicate'])
def test_changed_or_ambiguous_targets_are_never_retargeted(mode, race_docs):
    """A matching query on a fresh snapshot is not sufficient identity."""
    if mode == 'duplicate':
        document = race_docs['document']
        document['body']['content'].insert(
            3, deepcopy(document['body']['content'][2]),
        )
        reindex(document)

    def change(document):
        """Overlap the target or introduce a misleading earlier match."""
        target = document['body']['content'][2]['paragraph']['elements'][0]
        if mode == 'text':
            target['textRun']['content'] = 'Target phrase changed\n'
        elif mode == 'style':
            target['textRun']['textStyle'] = {'bold': True}
        elif mode == 'deleted':
            document['body']['content'].pop(2)
        elif mode == 'new_match':
            document['body']['content'][0]['paragraph']['elements'][0][
                'textRun']['content'] = 'Earlier Target phrase\n'
        else:
            change_prefix(document)
    race_docs['change'] = change
    with pytest.raises(ToolFailureError) as error:
        docs_edit.search_replace('test', 'Target phrase', 'replacement')
    assert error.value.failure.code in {
        'EDIT_CONFLICT', 'TARGET_AMBIGUOUS', 'TARGET_DELETED',
    }
    if mode == 'duplicate':
        assert error.value.failure.code == 'TARGET_AMBIGUOUS'
    assert len(race_docs['writes']) == 1


def test_append_replans_at_current_end(race_docs):
    """Rebase concurrent appends at the new document end."""
    def change(document):
        """Append collaborator content to the current final paragraph."""
        document['body']['content'][-1]['paragraph']['elements'][0][
            'textRun']['content'] += 'concurrent😀\n'
    race_docs['change'] = change
    result = docs_edit.append('test', 'ours', rich=False)
    assert result.at_index == race_docs['document']['body']['content'][-1][
        'endIndex'] - 1
    assert len(race_docs['writes']) == 2  # noqa: PLR2004
    request = race_docs['writes'][1]['requests'][0]['insertText']
    assert request['text'] == '\nours'


def test_retry_exhaustion_is_bounded(race_docs):
    """Three confirmed rejections do not turn into an unbounded retry loop."""
    race_docs['always'] = True
    race_docs['change'] = change_prefix
    with pytest.raises(ToolFailureError) as error:
        docs_edit.search_replace('test', 'Target phrase', 'new')
    assert error.value.failure.code == 'REVISION_RETRY_EXHAUSTED'
    assert len(race_docs['writes']) == revision_guards.MAX_ATTEMPTS


@pytest.mark.parametrize('error', [TimeoutError('lost response'),
                                  api_error('upstream failure', 503)])
def test_unknown_outcome_is_not_retried(error, race_docs):
    """A request can commit before its response is lost; never replay it."""
    race_docs['documents'].batchUpdate.return_value.execute.side_effect = error
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.append('test', 'possibly already inserted', rich=False)
    assert caught.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    assert race_docs['documents'].batchUpdate.call_count == 1
    assert failure_from_exception(caught.value, 'docs_append').code == (
        'WRITE_OUTCOME_UNKNOWN'
    )


def test_invalid_request_is_not_a_revision_retry(race_docs):
    """Ordinary HTTP 400 input failures must not be classified as races."""
    race_docs['documents'].batchUpdate.return_value.execute.side_effect = (
        api_error('Invalid insertion location.'),
    )
    with pytest.raises(HttpError):
        docs_edit.append('test', 'invalid', rich=False)
    assert race_docs['documents'].batchUpdate.call_count == 1


def test_native_replace_all_keeps_execution_time_matching(mock_docs):
    """Native replace-all retains its no-read semantics and atomic request."""
    docs_edit.search_replace('test', 'old', 'new', occurrence=0)
    mock_docs.get.assert_not_called()
    assert 'writeControl' not in mock_docs.batchUpdate.call_args.kwargs['body']


def test_target_deletion_is_structured(race_docs):
    """A vanished unique target is reported distinctly from a new lookup."""
    race_docs['change'] = lambda doc: doc['body']['content'].pop(0)
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.insert_before('test', 'Introduction', 'new', rich=False)
    assert caught.value.failure.code == 'TARGET_DELETED'


def test_tree_parsing_preserves_snapshot(simple_document):
    """Model flattening must not destroy the native dependency snapshot."""
    before = deepcopy(simple_document)
    docs_edit._parse_document_tree(simple_document)
    assert simple_document == before


def test_read_without_revision_fails_before_write(race_docs):
    """Missing revision metadata never enables an unguarded indexed write."""
    del race_docs['document']['revisionId']
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.append('test', 'new', rich=False)
    assert caught.value.failure.code == 'REVISION_UNAVAILABLE'
    race_docs['documents'].batchUpdate.assert_not_called()


def test_explicit_stale_revision_rejects_before_write(race_docs):
    """Optionally protect the agent's earlier document read."""
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.append('test', 'new', expected_revision_id='agent-old')
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    race_docs['documents'].batchUpdate.assert_not_called()


def test_explicit_revision_disables_rebasing(race_docs):
    """A strict revision precondition cannot be silently weakened on retry."""
    race_docs['change'] = change_prefix
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.append('test', 'new', expected_revision_id='revision')
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    assert len(race_docs['writes']) == 1


def test_native_replace_all_rejects_explicit_revision(race_docs):
    """Keep native execution-time semantics explicit, never ignore a guard."""
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.search_replace('test', 'old', 'new', occurrence=0,
                                 expected_revision_id='revision')
    assert caught.value.failure.code == 'INVALID_ARGUMENT'
    race_docs['documents'].batchUpdate.assert_not_called()


def test_multi_target_batch_replans_as_one_atomic_write(race_docs):
    """A retry validates every target before submitting one complete batch."""
    race_docs['change'] = change_prefix
    result = docs_edit.batch_replace('test', [
        {'find': 'Target phrase', 'replace': 'first'},
        {'find': 'elsewhere', 'replace': 'second'},
    ])
    assert result['applied'] == 2  # noqa: PLR2004
    assert len(race_docs['writes']) == 2  # noqa: PLR2004
    requests = race_docs['writes'][-1]['requests']
    values = [r['insertText']['text'] for r in requests if 'insertText' in r]
    assert values == ['second', 'first']


def test_one_conflicting_batch_target_prevents_all_replacements(race_docs):
    """An unchanged first target cannot cause a partially accepted batch."""
    def change(document):
        """Overlap only the second requested target."""
        document['body']['content'][-1]['paragraph']['elements'][0][
            'textRun']['textStyle'] = {'italic': True}
    race_docs['change'] = change
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.batch_replace('test', [
            {'find': 'Target phrase', 'replace': 'first'},
            {'find': 'elsewhere', 'replace': 'second'},
        ])
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    assert len(race_docs['writes']) == 1


def test_new_delete_all_match_does_not_expand_target_set(race_docs):
    """A collaborator cannot accidentally add another paragraph to deletion."""
    def change(document):
        """Make an independent paragraph newly satisfy the original query."""
        document['body']['content'][0]['paragraph']['elements'][0][
            'textRun']['content'] = 'Target phrase newly added\n'
    race_docs['change'] = change
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.delete_paragraph('test', 'Target phrase')
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    assert len(race_docs['writes']) == 1


def test_lost_comment_response_does_not_repeat_anchor_or_comment(
    mock_docs, monkeypatch,
):
    """The comment side effect may commit after its anchor succeeds."""
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'createNamedRange': {'namedRangeId': 'anchor'}}],
    }
    drive = MagicMock()
    drive.comments().create.return_value.execute.side_effect = TimeoutError()
    monkeypatch.setattr(docs_edit, 'build', lambda *_a, **_k: drive)
    monkeypatch.setattr(docs_edit, '_load_creds', lambda: None)
    with pytest.raises(ToolFailureError) as caught:
        docs_edit.add_comment('test', 'review', 'Target phrase')
    assert caught.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    assert caught.value.failure.committed_batches == 1
    mock_docs.batchUpdate.assert_called_once()
    drive.comments().create.assert_called_once()
