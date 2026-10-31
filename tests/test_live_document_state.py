"""Verify session cleanup and its opt-in boundary without Google access."""

import uuid
from pathlib import Path

import pytest

from .live_document_state import document_session, metadata_cleanup_requests

pytest_plugins = ['pytester']


def test_document_lock_excludes_another_session():
    """A second session cannot erase a document that is already in use."""
    events = []
    doc_id = uuid.uuid4().hex
    with (document_session(doc_id, events.append),
          pytest.raises(RuntimeError, match='Another live test session'),
          document_session(doc_id, events.append)):
        pytest.fail('Concurrent document access was allowed.')
    assert events == ['before', 'after']
    with document_session(doc_id, events.append):
        pass
    assert events == ['before', 'after', 'before', 'after']


@pytest.mark.parametrize('outcome', [
    'success', 'test_failure', 'setup_failure',
    'teardown_failure', 'interruption',
    'offline', 'missing', 'invalid',
])
def test_pytest_session_lifecycle(pytester, monkeypatch, outcome):
    """Exercise real fixture ordering, finalization and offline isolation."""
    doc_id = uuid.uuid4().hex
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', doc_id)
    if outcome == 'missing':
        monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC')
    elif outcome == 'invalid':
        monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', 'https://invalid')
    pytester.makeini('[pytest]\nmarkers = live: live Google tests')
    pytester.makeconftest("""
from pathlib import Path
import pytest
from tests.conftest import (
    live_document_guard, live_document_session, live_test_doc,
)

@pytest.fixture(scope='session')
def live_document_reset():
    def reset(phase):
        with Path('events').open('a') as stream:
            stream.write(phase + '\\n')
        if phase == 'before' and OUTCOME == 'setup_failure':
            raise RuntimeError('Injected initial cleanup failure')
        if phase == 'after' and OUTCOME == 'teardown_failure':
            raise RuntimeError('Injected final cleanup failure')
    return reset
""".replace('OUTCOME', repr(outcome)))
    pytester.makepyfile("""
from pathlib import Path
import pytest

MARKER
def test_first(live_test_doc):
    with Path('events').open('a') as stream:
        stream.write('test-first\\n')
    if OUTCOME == 'interruption':
        raise KeyboardInterrupt

MARKER
def test_second(live_test_doc):
    with Path('events').open('a') as stream:
        stream.write('test-second\\n')
    assert OUTCOME != 'test_failure'
""".replace('MARKER', '' if outcome == 'offline' else '@pytest.mark.live')
                         .replace('OUTCOME', repr(outcome)))
    if outcome == 'interruption':
        # Keep the deliberate interrupt inside the nested pytest process.
        monkeypatch.setenv('PYTHONPATH', str(
            Path(__file__).resolve().parents[1],
        ))
        result = pytester.runpytest_subprocess('-q')
    else:
        result = pytester.runpytest('-q')
    path = pytester.path / 'events'
    events = path.read_text().splitlines() if path.exists() else []
    if outcome == 'missing':
        result.assert_outcomes(skipped=2)
        assert not events
    elif outcome == 'invalid':
        result.assert_outcomes(errors=2)
        assert not events
    elif outcome == 'setup_failure':
        result.assert_outcomes(errors=2)
        assert events == ['before', 'after']
    elif outcome == 'offline':
        result.assert_outcomes(passed=2)
        assert events == ['test-first', 'test-second']
    elif outcome == 'interruption':
        assert result.ret == pytest.ExitCode.INTERRUPTED
        assert events == ['before', 'test-first', 'after']
    elif outcome == 'teardown_failure':
        result.assert_outcomes(passed=2, errors=1)
        assert events == ['before', 'test-first', 'test-second', 'after']
    else:
        result.assert_outcomes(passed=2 if outcome == 'success' else 1,
                               failed=int(outcome == 'test_failure'))
        assert events == ['before', 'test-first', 'test-second', 'after']


def test_cleanup_scopes_ranges_and_preserves_first_root():
    """Delete nested-tab ranges before deleting tabs, retaining the root."""
    child = {'tabProperties': {'tabId': 'child'}, 'documentTab': {
        'namedRanges': {'label': {'namedRanges': [
            {'namedRangeId': 'range'}, {'namedRangeId': 'range'},
        ]}},
    }}
    native = {'tabs': [
        {'tabProperties': {'tabId': 'root'}, 'documentTab': {},
         'childTabs': [child]},
        {'tabProperties': {'tabId': 'other'}, 'documentTab': {}},
    ], 'comments': [
        {'commentId': 'active', 'headPost': {}},
        {'commentId': 'deleted', 'headPost': {'deleted': True}},
    ]}
    assert metadata_cleanup_requests(native) == [
        {'deleteComment': {'commentId': 'active'}},
        {'deleteNamedRange': {'namedRangeId': 'range',
                              'tabsCriteria': {'tabIds': ['child']}}},
        {'deleteTab': {'tabId': 'child'}},
        {'deleteTab': {'tabId': 'other'}},
    ]
