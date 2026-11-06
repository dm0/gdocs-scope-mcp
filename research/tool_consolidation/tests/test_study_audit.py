"""Protect audit exclusions and reproduce a synthetic heading-read defect."""

import json
import sys
from copy import deepcopy

import pytest

from gdocs_scope_mcp.suggestions.index import scope_ranges

from .test_reduced_study_runner import runner  # noqa: F401
from .test_study_corpus import load_research


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


def test_fixture_copies_heading_identity_to_normal_paragraph():
    """Expose the invalid duplicate ID hidden by canonical state projection."""
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
    assert [p['paragraphStyle']['headingId'] for p in paragraphs] == ['h', 'h']
    assert scope_ranges(tab, ['h']) is None
    repaired = json.loads(json.dumps(tab))
    repaired['body']['content'][0]['paragraph']['paragraphStyle'].pop('headingId')
    assert scope_ranges(repaired, ['h']) is not None
