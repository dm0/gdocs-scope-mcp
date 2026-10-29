"""Protect proposal preflight, native coordinates and non-replay semantics."""

# Numeric offsets and native field names are explicit regression contracts.
# ruff: noqa: D103, PLR2004

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from jsonschema import validate
from pydantic import TypeAdapter

from gdocs_scope_mcp import docs_edit, revision_guards, suggestion_writes
from gdocs_scope_mcp.settings import Settings
from gdocs_scope_mcp.suggestion_write_models import ProposalOperation
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_mcp_output_contracts import call_tool
from .test_revision_guards import api_error


def op(**kwargs):
    return TypeAdapter(ProposalOperation).validate_python(kwargs)


@pytest.fixture
def proposal_api(monkeypatch, simple_document):
    """Serve native threads with configurable write outcomes."""
    service = MagicMock()
    state = {'document': deepcopy(simple_document), 'batches': [],
             'response': {'commentUpdateState': 'ALL_SAVED',
                          'suggestionResponses': [
                              {'createdSuggestionIds': ['new', 'second']},
                          ]}, 'error': None, 'verify': True,
             'before_write': None}

    def get(**kwargs):
        request = MagicMock()
        request.uri = 'https://docs.test/v1/documents/example'
        key = ('preview' if kwargs.get('suggestionsViewMode')
               == 'PREVIEW_WITHOUT_SUGGESTIONS' and 'preview' in state
               else 'document')
        request.execute.side_effect = lambda: deepcopy(state[key])
        return request

    def batch(**kwargs):
        request = MagicMock()

        def execute():
            state['batches'].append(deepcopy(kwargs['body']))
            if state['before_write']:
                state['before_write']()
            if state['error']:
                raise state['error']
            if state['verify']:
                threads = state['document'].setdefault('suggestions', [])
                if kwargs['body']['writeControl']['writeMode'] == 'SUGGEST':
                    threads.extend({'suggestionId': sid, 'status': 'OPEN'}
                                   for sid in ('new', 'second'))
                else:
                    for item in kwargs['body']['requests']:
                        kind, payload = next(iter(item.items()))
                        sid = payload['suggestionId']
                        if kind == 'deleteSuggestion':
                            threads[:] = [t for t in threads
                                          if t['suggestionId'] != sid]
                        else:
                            for thread in threads:
                                if thread['suggestionId'] == sid:
                                    thread['status'] = (
                                        'ACCEPTED'
                                        if kind == 'acceptSuggestion'
                                        else 'REJECTED'
                                    )
            return deepcopy(state['response'])

        request.execute.side_effect = execute
        return request

    service.documents().get.side_effect = get
    service.documents().batchUpdate.side_effect = batch
    monkeypatch.setattr(docs_edit, '_get_service', lambda *_args: service)
    state['service'] = service
    return state


def test_replace_uses_suggest_mode_and_returns_every_id(proposal_api):
    result = suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='🦷',
    ), heading_id='parent')
    assert result.changes.created == ['new', 'second']
    assert result.comment_update_state == 'ALL_SAVED'
    batch = proposal_api['batches'][0]
    assert batch['writeControl'] == {
        'writeMode': 'SUGGEST', 'requiredRevisionId': 'revision',
    }
    requests = batch['requests']
    assert requests[0]['insertText']['location']['index'] == 21
    assert requests[1]['deleteContentRange']['range'] == {
        'startIndex': 23, 'endIndex': 36,
    }


@pytest.mark.parametrize(('operation', 'index', 'value'), [
    ('insert_before', 21, 'Proposed\n'),
    ('insert_after', 34, '\nProposed'),
    ('append', 91, '\nProposed'),
])
def test_literal_paragraph_insertions(proposal_api, operation, index, value):
    arguments = {'operation': operation, 'text': 'Proposed', 'rich': False}
    if operation != 'append':
        arguments['anchor'] = 'Target phrase'
    suggestion_writes.suggest('example', op(**arguments))
    request = proposal_api['batches'][0]['requests'][0]['insertText']
    assert request == {'location': {'index': index}, 'text': value}


def test_scoped_append_uses_native_subtree_end(proposal_api):
    suggestion_writes.suggest('example', op(
        operation='append', text='Scoped', rich=False,
    ), heading_id='parent')
    assert proposal_api['batches'][0]['requests'][0]['insertText'][
        'location'
    ]['index'] == 61


def test_delete_preserves_mandatory_final_newline(proposal_api):
    suggestion_writes.suggest('example', op(
        operation='delete_paragraph', anchor='elsewhere',
    ))
    assert proposal_api['batches'][0]['requests'] == [{
        'deleteContentRange': {'range': {'startIndex': 68, 'endIndex': 91}},
    }]


def test_formatting_is_typed_and_uses_text_style_request(proposal_api):
    suggestion_writes.suggest('example', op(
        operation='format_text', find='Target phrase',
        style={'bold': True, 'italic': False},
    ))
    request = proposal_api['batches'][0]['requests'][0]['updateTextStyle']
    assert request['textStyle'] == {'bold': True, 'italic': False}
    assert request['fields'] == 'bold,italic'


@pytest.mark.parametrize('text', [
    '| a | b |\n|---|---|\n|c|d|',
    '- item', '![image](https://example.test/image.png)',
    '<img src="/tmp/local-image.png">',
    '<span data-mcp-entity="person" data-mcp-email="a@example.com">A</span>',
])
def test_unsupported_rich_plans_fail_before_any_write(proposal_api, text):
    with pytest.raises((ToolFailureError, ValueError)):
        suggestion_writes.suggest('example', op(operation='append', text=text))
    assert not proposal_api['batches']


def test_code_markers_are_omitted_with_explicit_warning(proposal_api):
    result = suggestion_writes.suggest('example', op(
        operation='append', text='```python\nx = 1\n```',
    ))
    assert result.warnings
    requests = proposal_api['batches'][0]['requests']
    assert not any('createNamedRange' in r for r in requests)
    assert any('updateTextStyle' in r for r in requests)


@pytest.mark.parametrize('kind', ['suggestedInsertionIds',
                                  'suggestedDeletionIds',
                                  'suggestedTextStyleChanges'])
def test_existing_proposals_on_target_are_rejected(proposal_api, kind):
    run = proposal_api['document']['body']['content'][2]['paragraph'][
        'elements'
    ][0]['textRun']
    run[kind] = {'old': {}} if kind.endswith('Changes') else ['old']
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert not proposal_api['batches']


def test_proposal_elsewhere_does_not_block_target(proposal_api):
    proposal_api['document']['body']['content'][-1]['paragraph']['elements'][
        0
    ]['textRun']['suggestedInsertionIds'] = ['elsewhere']
    result = suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ))
    assert result.ok


@pytest.mark.parametrize('state', [None, 'ALL_FAILED_UNKNOWN_REASON',
                                   'NO_UPDATES_REQUESTED'])
def test_unconfirmed_persistence_is_not_replayed(proposal_api, state):
    proposal_api['response']['commentUpdateState'] = state
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code in {
        'PARTIAL_WRITE', 'WRITE_OUTCOME_UNKNOWN',
    }
    assert len(proposal_api['batches']) == 1


def test_missing_readback_is_unknown_and_not_replayed(proposal_api):
    proposal_api['verify'] = False
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    assert len(proposal_api['batches']) == 1


@pytest.mark.parametrize('error', [
    TimeoutError(), api_error('Unavailable', 503),
])
def test_uncertain_write_is_never_replayed(proposal_api, error):
    proposal_api['error'] = error
    with pytest.raises(ToolFailureError) as caught:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert caught.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    assert len(proposal_api['batches']) == 1


@pytest.mark.parametrize('mode', ['required', 'target'])
def test_revision_policy_and_strict_override(proposal_api, monkeypatch, mode):
    monkeypatch.setattr(revision_guards, 'get_settings',
                        lambda: Settings(write_revision_mode=mode))
    suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ), expected_revision_id='revision')
    assert 'requiredRevisionId' in proposal_api['batches'][0]['writeControl']


@pytest.mark.parametrize('action', ['accept', 'reject', 'delete'])
def test_manage_verifies_each_decision_in_one_batch(proposal_api, action):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': sid, 'status': 'OPEN'} for sid in ('one', 'two')
    ]
    field = {'accept': 'acceptedSuggestionIds',
             'reject': 'rejectedSuggestionIds',
             'delete': 'deletedSuggestionIds'}[action]
    proposal_api['response']['suggestionResponses'] = [{field: ['one', 'two']}]
    result = suggestion_writes.manage('example', action, ['one', 'two'])
    assert [r.outcome for r in result.results] == ['applied', 'applied']
    assert len(proposal_api['batches']) == 1
    assert len(proposal_api['batches'][0]['requests']) == 2
    assert proposal_api['batches'][0]['writeControl']['writeMode'] == 'EDIT'


def test_manage_missing_id_preflights_complete_batch(proposal_api):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'OPEN'},
    ]
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.manage('example', 'accept', ['one', 'missing'])
    assert error.value.failure.code == 'RESOURCE_NOT_FOUND'
    assert not proposal_api['batches']


def test_already_matching_decision_is_read_only(proposal_api):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'ACCEPTED'},
    ]
    result = suggestion_writes.manage('example', 'accept', ['one'])
    assert result.results[0].outcome == 'already_decided'
    assert result.comment_update_state is None
    assert not proposal_api['batches']


@pytest.mark.parametrize('arguments', [
    {'operation': {'operation': 'replace', 'find': '', 'text': 'new'}},
    {'operation': {'operation': 'replace', 'find': 'old', 'text': 'new',
                   'occurrence': 0}},
    {'operation': {'operation': 'format_text', 'find': 'old', 'style': {}}},
    {'operation': {'operation': 'format_text', 'find': 'old',
                   'style': {'bold': 'true'}}},
    {'operation': {'operation': 'append', 'text': 'new', 'extra': True}},
])
def test_mcp_validation_precedes_api(proposal_api, arguments):
    tool, result = call_tool(
        'docs_suggest', {'doc_id': 'example', **arguments},
        raise_on_error=False,
    )
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert tool.inputSchema
    proposal_api['service'].documents().get.assert_not_called()


@pytest.mark.usefixtures('proposal_api')
def test_mcp_proposal_receipt_contract():
    tool, result = call_tool('docs_suggest', {
        'doc_id': 'example',
        'operation': {'operation': 'replace',
                      'find': 'Target phrase', 'text': 'replacement'},
    })
    validate(result.structured_content, tool.outputSchema)
    assert result.structured_content['changes']['created'] == ['new', 'second']
    assert not tool.annotations.readOnlyHint
    assert not tool.annotations.idempotentHint


def test_mcp_management_receipt_contract(proposal_api):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'OPEN'},
    ]
    proposal_api['response']['suggestionResponses'] = [
        {'acceptedSuggestionIds': ['one']},
    ]
    tool, result = call_tool('docs_suggestions_manage', {
        'doc_id': 'example', 'action': 'accept', 'suggestion_ids': ['one'],
    })
    validate(result.structured_content, tool.outputSchema)
    assert result.structured_content['results'][0]['status'] == 'ACCEPTED'
    assert tool.annotations.destructiveHint


@pytest.mark.parametrize('action', ['accept', 'reject', 'delete'])
def test_manage_readback_failure_is_not_replayed(proposal_api, action):
    proposal_api['verify'] = False
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'OPEN'},
    ]
    field = {'accept': 'acceptedSuggestionIds',
             'reject': 'rejectedSuggestionIds',
             'delete': 'deletedSuggestionIds'}[action]
    proposal_api['response']['suggestionResponses'] = [{field: ['one']}]
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.manage('example', action, ['one'])
    assert error.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    assert len(proposal_api['batches']) == 1


def test_target_mode_uses_target_revision(proposal_api, monkeypatch):
    monkeypatch.setattr(revision_guards, 'get_settings',
                        lambda: Settings(write_revision_mode='target'))
    suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ))
    assert proposal_api['batches'][0]['writeControl'] == {
        'targetRevisionId': 'revision', 'writeMode': 'SUGGEST',
    }


def test_target_revision_rejection_is_not_replayed(proposal_api, monkeypatch):
    monkeypatch.setattr(revision_guards, 'get_settings',
                        lambda: Settings(write_revision_mode='target'))
    proposal_api['error'] = api_error('revision is too old')
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'TARGET_REVISION_REJECTED'
    assert len(proposal_api['batches']) == 1


def test_exhausted_required_races_retain_suggest_mode(proposal_api):
    proposal_api['error'] = api_error('revision does not match')
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'REVISION_RETRY_EXHAUSTED'
    assert len(proposal_api['batches']) == 3
    assert all(b['writeControl']['writeMode'] == 'SUGGEST'
               for b in proposal_api['batches'])


def test_new_overlapping_proposal_during_retry_is_not_retargeted(proposal_api):
    def change_target():
        proposal_api['document']['body']['content'][2]['paragraph'][
            'elements'
        ][0]['textRun']['suggestedDeletionIds'] = ['other-editor']
    proposal_api['before_write'] = change_target
    proposal_api['error'] = api_error('revision does not match')
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert len(proposal_api['batches']) == 1


def test_required_retry_allows_unrelated_paragraph_change(proposal_api):
    def change_other():
        if len(proposal_api['batches']) == 1:
            proposal_api['document']['body']['content'][0]['paragraph'][
                'elements'
            ][0]['textRun']['textStyle']['italic'] = True
            proposal_api['error'] = api_error('revision does not match')
        else:
            proposal_api['error'] = None
    proposal_api['before_write'] = change_other
    result = suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ))
    assert result.ok
    assert len(proposal_api['batches']) == 2


def test_manage_never_accepts_changed_summary_during_retry(proposal_api):
    thread = {'suggestionId': 'one', 'status': 'OPEN',
              'summaryText': 'original'}
    proposal_api['document']['suggestions'] = [thread]
    proposal_api['before_write'] = lambda: thread.update(summaryText='changed')
    proposal_api['error'] = api_error('revision does not match')
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.manage('example', 'accept', ['one'])
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert len(proposal_api['batches']) == 1


@pytest.mark.parametrize('ids', [['one', 'one'], ['one', 'closed']])
def test_manage_preflight_does_not_send_partial_decisions(proposal_api, ids):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'OPEN'},
        {'suggestionId': 'closed', 'status': 'REJECTED'},
    ]
    with pytest.raises(ToolFailureError):
        suggestion_writes.manage('example', 'accept', ids)
    assert not proposal_api['batches']


@pytest.mark.parametrize('revision', [None, 'old'])
def test_missing_or_stale_revision_never_writes(proposal_api, revision):
    proposal_api['document']['revisionId'] = revision
    with pytest.raises(ToolFailureError):
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ), expected_revision_id='revision')
    assert not proposal_api['batches']


def test_native_tab_selection_is_attached_to_every_request(proposal_api):
    native = proposal_api['document']
    body = native.pop('body')
    native['tabs'] = [{
        'tabProperties': {'tabId': 'chosen', 'title': 'Chosen', 'index': 0},
        'documentTab': {'body': body},
    }]
    result = suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ), tab_id='chosen')
    assert result.tab_id == 'chosen'
    requests = proposal_api['batches'][0]['requests']
    assert requests[0]['insertText']['location']['tabId'] == 'chosen'
    assert requests[1]['deleteContentRange']['range']['tabId'] == 'chosen'


@pytest.mark.parametrize(('action', 'permission'), [
    ('accept', 'edit access'),
    ('reject', 'authorship'), ('delete', 'authorship'),
])
def test_decision_permission_errors_remain_specific(
    proposal_api, action, permission,
):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'one', 'status': 'OPEN'},
    ]
    proposal_api['error'] = api_error('Forbidden', 403)
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.manage('example', action, ['one'])
    assert error.value.failure.code == 'PERMISSION_DENIED'
    assert permission in error.value.failure.description
    assert len(proposal_api['batches']) == 1


def test_deletion_guards_next_paragraph_when_removing_break(proposal_api):
    proposal_api['document']['body']['content'][3]['paragraph']['elements'][
        0
    ]['textRun']['suggestedDeletionIds'] = ['neighbor-proposal']
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='delete_paragraph', anchor='Target phrase',
        ))
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert not proposal_api['batches']


@pytest.mark.parametrize('operation', ['replace', 'format_text'])
def test_text_operations_preserve_paragraph_terminator(
    proposal_api, operation,
):
    arguments = {'operation': operation, 'find': 'Target phrase\n'}
    arguments.update({'text': 'replacement'} if operation == 'replace'
                     else {'style': {'bold': True}})
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(**arguments))
    assert error.value.failure.code == 'INVALID_ARGUMENT'
    assert not proposal_api['batches']


def test_proposal_before_target_keeps_native_indices(proposal_api):
    proposal_api['preview'] = deepcopy(proposal_api['document'])
    content = proposal_api['document']['body']['content']
    first = content[0]
    first['endIndex'] += 2
    for item in content:
        if item is not first:
            item['startIndex'] += 2
            item['endIndex'] += 2
        for element in item['paragraph']['elements']:
            element['startIndex'] += 2
            element['endIndex'] += 2
    first['paragraph']['elements'].insert(0, {
        'startIndex': 1, 'endIndex': 3,
        'textRun': {'content': 'XX', 'textStyle': {},
                    'suggestedInsertionIds': ['prefix']},
    })
    suggestion_writes.suggest('example', op(
        operation='replace', find='Target phrase', text='new',
    ))
    index = proposal_api['batches'][0]['requests'][0]['insertText'][
        'location'
    ]['index']
    assert index == 23
    assert index != proposal_api['preview']['body']['content'][2]['startIndex']


def test_unlocated_open_thread_requires_explicit_review(proposal_api):
    proposal_api['document']['suggestions'] = [
        {'suggestionId': 'unlocated', 'status': 'OPEN'},
    ]
    with pytest.raises(ToolFailureError) as error:
        suggestion_writes.suggest('example', op(
            operation='replace', find='Target phrase', text='new',
        ))
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert 'unlocated' in error.value.failure.description
    assert not proposal_api['batches']
