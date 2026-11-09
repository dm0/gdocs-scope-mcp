"""Protect audit exclusions and reproduce a synthetic heading-read defect."""

import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace

import pytest

from gdocs_scope_mcp.suggestions.index import scope_ranges

from .test_reduced_study_runner import runner  # noqa: F401
from .test_study_corpus import execution, load_research, scenarios


@pytest.fixture
def audit_module(monkeypatch, runner):  # noqa: F811 - imported pytest fixture
    """Load the audit while retaining explicit research module dependencies."""
    monkeypatch.setitem(sys.modules, 'run_reduced_study', runner)
    monkeypatch.setitem(sys.modules, 'analyze_reduced_study',
                        load_research('analyze_reduced_study'))
    return load_research('audit_reduced_study')


def test_reference_question_requires_observed_anchor(audit_module):
    """Do not excuse a missing resolved-thread search as anchor ambiguity."""
    row = {'case': 'm11', 'clarifications': 1, 'trace': [],
           'turns': [{'messages': ['Should I modify Reference?']}]}
    assert not audit_module.reference_question(row)
    row['trace'] = [{'tool': 'docs_read_comments', 'result': {'comments': [
        {'anchored': True, 'quoted_text': 'Protected reference'},
    ]}}]
    assert audit_module.reference_question(row)
    row['clarifications'] = 0
    assert not audit_module.reference_question(row)


def test_archived_source_verification_requires_exact_bytes(
    audit_module, monkeypatch,
):
    """Keep audit provenance valid after removing live configuration IDs."""
    monkeypatch.setattr(audit_module, 'source_hashes', dict)
    manifest = {'commit': 'f' * 40, 'sources': {
        'study_live.py': hashlib.sha256(b'archived source').hexdigest(),
    }}

    def show(args, **kwargs):
        assert args[:2] == ['git', 'show']
        assert args[2].endswith(':research/tool_consolidation/study_live.py')
        assert kwargs['capture_output'] and kwargs['check']
        return SimpleNamespace(stdout=b'archived source')

    monkeypatch.setattr(audit_module.subprocess, 'run', show)
    assert audit_module.execution_sources_match(manifest)
    manifest['sources']['study_live.py'] = (
        hashlib.sha256(b'changed').hexdigest())
    assert not audit_module.execution_sources_match(manifest)


def test_verbal_action_does_not_become_a_success(audit_module):
    """Correct prose is a distinct construct from a recorded tool action."""
    row = {'status': 'completed', 'case': 'm04', 'level': 'decision',
           'final_success': False, 'trace': [], 'turns': [{'messages': [
               '{"decision":"action","message":"Append bold text"}',
           ]}]}
    assert (audit_module.failure_category(row)
            == 'verbal_action_without_tool_call')
    assert not row['final_success']


def test_recovery_diagnostic_never_relaxes_final_state_or_other_errors(
    audit_module,
):
    """Remove only synthetic read errors and preserve the frozen input."""
    row = {'backend': 'fixture', 'case': 'm05', 'final_success': True,
           'schema_errors': 0, 'semantic_errors': 2, 'recovery_free': False,
           'unnecessary_clarification': False, 'trace': [{
               'tool': 'docs_read', 'schema_valid': True,
               'state_changed': False,
               'result': {'ok': False, 'code': 'TARGET_CHANGED'},
           }]}
    original = deepcopy(row)
    assert audit_module.recovery_diagnostic(row)['semantic_errors'] == 1
    assert not audit_module.recovery_diagnostic(row)['recovery_free']
    row['semantic_errors'] = 1
    assert audit_module.recovery_diagnostic(row)['recovery_free']
    row['final_success'] = False
    assert not audit_module.recovery_diagnostic(row)['recovery_free']
    row['backend'] = 'live'
    assert audit_module.recovery_diagnostic(row) == row
    assert original['semantic_errors'] == 2  # noqa: PLR2004


def test_fixture_clears_heading_identity_from_normal_paragraph():
    """Preserve the real heading while clearing inherited identity on text."""
    fixture = load_research('study_fixture_api').FixtureAPI({
        'tabs': [{'id': 't', 'title': 'T', 'paragraphs': [
            {'text': 'Heading', 'heading_id': 'h', 'level': 'HEADING_1'},
        ]}],
    })
    fixture.apply({'requests': [
        {'insertText': {'location': {'index': 1, 'tabId': 't'},
                        'text': 'Body\n'}},
        {'updateParagraphStyle': {
            'range': {'startIndex': 1, 'endIndex': 6, 'tabId': 't'},
            'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
            'fields': 'namedStyleType',
        }},
    ]})
    tab = fixture.snapshot()['tabs'][0]['documentTab']
    paragraphs = [x['paragraph'] for x in tab['body']['content']]
    assert [p['paragraphStyle'].get('headingId')
            for p in paragraphs] == [None, 'h']
    assert scope_ranges(tab, ['h']) is not None


def test_rendered_answer_diagnostic_retains_raw_text_and_scope(audit_module):
    """Retain strict tasks, extra text and unauthorized-read constraints."""
    row = {'case': 'm18', 'status': 'completed', 'level': 'end_to_end',
           'final_success': False, 'first_action_correct': True,
           'schema_errors': 0, 'semantic_errors': 0, 'trace': [],
           'turns': [{'messages': [json.dumps({
               'decision': 'noop', 'message': 'Batch&#58; WH&#45;7294&#45;Z',
           })]}]}
    assert audit_module.rendered_answer_diagnostic(row)['final_success']
    assert not row['final_success']
    row['trace'] = [{'tool': 'docs_read', 'state_changed': False,
                     'arguments': {}}]
    assert not audit_module.rendered_answer_diagnostic(row)['final_success']
    row['trace'][0]['arguments']['heading_ids'] = ['h.delivery']
    assert audit_module.rendered_answer_diagnostic(row)['final_success']
    row['turns'][0]['messages'] = [json.dumps({
        'decision': 'noop', 'message': 'Batch&#58; WH&#45;7294&#45;Z extra',
    })]
    assert not audit_module.rendered_answer_diagnostic(row)['final_success']


@pytest.mark.parametrize('case_id,headings', [
    ('m05', ['h.exercises', 'h.reading']),
    ('m16', ['h.reviews', 'h.notes']),
])
def test_plain_gold_equivalent_write_retains_readable_heading_selection(
    tmp_path, case_id, headings,
):
    """Keep scoped reads available after rich=False actor trajectories."""
    case = next(c for c in scenarios.MAIN if c['id'] == case_id)

    async def run():
        async with execution.fixture_backend(
            case, 'baseline', tmp_path / case_id,
        ) as (backend, _identity):
            for original in case['oracle']:
                call = deepcopy(original)
                call['arguments']['rich'] = False
                assert (await backend.call(call)).get('ok') is not False
            native = await backend.snapshot()
            body = native['tabs'][0]['documentTab']['body']['content']
            styles = [x['paragraph']['paragraphStyle'] for x in body]
            counts = Counter(s.get('headingId') for s in styles)
            assert not any(s.get('namedStyleType') == 'NORMAL_TEXT'
                           and s.get('headingId') in headings for s in styles)
            assert all(counts[h] == 1 for h in headings)
            result = await backend.call({
                'tool': 'docs_read', 'arguments': {
                    'doc_id': backend.document_id, 'heading_ids': headings,
                },
            })
            assert result.get('ok') is not False
            assert len(result['sections']) == len(headings)
            whole = await backend.call({
                'tool': 'docs_read',
                'arguments': {'doc_id': backend.document_id},
            })
            assert whole.get('ok') is not False

    asyncio.run(run())


@pytest.mark.live
@pytest.mark.parametrize('case_id,headings', [
    ('m05', ['h.exercises', 'h.reading']),
    ('m16', ['h.reviews', 'h.notes']),
])
def test_native_plain_insert_retains_readable_heading_selection(
    tmp_path, monkeypatch, case_id, headings,
):
    """Check the failing synthetic continuation on owned native documents."""
    monkeypatch.setitem(sys.modules, 'study_execution', execution)
    live = load_research('study_live')
    if os.environ.get('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER') is None:
        pytest.skip('Explicit authorized test-folder opt-in is required.')
    case = next(c for c in scenarios.MAIN if c['id'] == case_id)

    async def run():
        async with live.live_backend(
            case, 'baseline', tmp_path / case_id, reference_mode=True,
        ) as (backend, _identity):
            for original in case['oracle']:
                call = deepcopy(original)
                call['arguments']['rich'] = False
                receipt = await backend.call(backend.actual_call(
                    call, 'baseline',
                ))
                assert receipt.get('ok') is not False
            inverse = {alias: native for native, alias
                       in backend.aliases['headings'].items()}
            response = await backend.call({
                'tool': 'docs_read', 'arguments': {
                    'doc_id': backend.document_id,
                    'heading_ids': [inverse[h] for h in headings],
                },
            })
            assert response.get('ok') is not False
            assert len(response['sections']) == len(headings)

    asyncio.run(run())
