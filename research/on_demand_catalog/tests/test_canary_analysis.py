"""Keep callback availability distinct from observable tool search."""

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

from .test_probe_client import probe


def test_success_without_search_events_is_not_a_search_trace(monkeypatch):
    """A successful deferred call cannot manufacture discovery telemetry."""
    monkeypatch.setitem(sys.modules, 'probe_client', probe)
    path = Path(__file__).parents[1] / 'analyze_canaries.py'
    spec = importlib.util.spec_from_file_location('canary_analysis', path)
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)
    row = {
        'id': 'synthetic', 'model': 'test', 'arm': 'deferred',
        'status': 'completed', 'effective_model': 'test',
        'effective_effort': 'medium', 'actor_reaped': True, 'mcp_reaped': True,
        'result': {'calls': [{
            'tool': 'docs_get_color_palette', 'arguments': {},
            'result': {'rows': [[{'name': 'blue', 'hex': '#0000FF'}]]},
        }], 'messages': ['Blue is #0000FF.']},
    }
    events = [{'method': 'item/tool/call', 'params': {
        'namespace': 'gdocs', 'tool': 'docs_get_color_palette',
        'arguments': {},
    }}]
    actual = analysis.summarize(row, events)
    assert actual['palette_callback_valid']
    assert actual['answer_contains_returned_blue']
    assert actual['explicit_search_items'] == []
    assert actual['explicit_search_methods'] == []
    repeated = deepcopy(row)
    repeated['result']['calls'] *= 2
    retried = analysis.summarize(repeated, events * 2)
    assert retried['palette_callback_valid']
    assert retried['redundant_palette_reads'] == 1
    events.append({'method': 'item/completed', 'params': {
        'item': {'type': 'toolSearchCall', 'query': 'colors'},
    }})
    assert len(analysis.summarize(row, events)['explicit_search_items']) == 1
