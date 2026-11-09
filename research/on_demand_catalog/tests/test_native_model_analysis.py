"""Check descriptive intervals and strict native-call grading."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def analysis(monkeypatch):
    """Load the read-only analyzer without starting a client."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    return importlib.import_module('analyze_native_models')


def test_statistics_preserve_sample_variance_and_ceiling_uncertainty(analysis):
    """Ten perfect repetitions still have a nonzero failure uncertainty."""
    summary = analysis.continuous([1, 2, 3])
    assert summary['mean'] == pytest.approx(2)
    assert summary['variance'] == 1
    assert summary['ci95'][0] == pytest.approx(2 - 4.302653 / 3 ** 0.5)
    assert analysis.wilson(10, 10)[0] == pytest.approx(0.7224672)
    assert analysis.continuous([None])['ci95'] is None


def test_native_success_requires_tool_result_and_final_answer(analysis):
    """Reject guessed hex values and deduplicate raw search items."""
    row = {'id': 'case', 'model': 'gpt-6-luna', 'arm': 'deferred',
           'repeat': 0, 'status': 'completed', 'server_calls': [],
           'result': {'messages': ['#0000FF']}}
    items = [
        {'type': 'additional_tools', 'id': 'initial', 'tools': []},
        {'type': 'tool_search_call', 'id': 'search', 'call_id': 'search'},
        {'type': 'tool_search_call', 'id': 'search', 'call_id': 'search'},
        {'type': 'tool_search_output', 'id': 'loaded', 'tools': [
            {'type': 'namespace', 'name': 'mcp__native_probe', 'tools': [
                {'type': 'function', 'name': 'docs_get_color_palette'},
            ]},
        ]},
    ]
    events = [{'method': 'rawResponseItem/completed', 'params': {'item': i}}
              for i in items]
    assert not analysis.summarize(row, events)['success']
    events.append({'method': 'item/completed', 'params': {'item': {
        'type': 'mcpToolCall', 'tool': 'docs_get_color_palette',
        'status': 'completed', 'arguments': {}, 'result': {
            'structuredContent': {'rows': [[{'name': 'blue',
                                             'hex': '#0000FF'}]]}},
    }}})
    summary = analysis.summarize(row, events)
    assert summary['success']
    assert summary['exposure_verified']
    assert summary['search_calls'] == 1
    row['server_calls'].append({'allowed': False})
    assert not analysis.summarize(row, events)['success']
