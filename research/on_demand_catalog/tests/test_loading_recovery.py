"""Validate isolated profile interventions before real diagnostic calls."""

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def recovery(monkeypatch):
    """Import research-only diagnostics without creating a thread."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    return importlib.import_module('native_loading_recovery')


@pytest.mark.parametrize('profile', [
    'function-lite', 'function-full', 'model-default',
    'code-native', 'code-local',
])
def test_profiles_change_only_loading_between_arms(recovery, profile):
    """Both arms preserve the same routing, reasoning and backend metadata."""
    models = [{'slug': 'gpt-6.1-sol', 'supports_search_tool': True,
               'tool_mode': 'code_mode_only', 'use_responses_lite': True}]
    eager = recovery.metadata(models, profile, 'eager')['models'][0]
    deferred = recovery.metadata(models, profile, 'deferred')['models'][0]
    assert eager.pop('supports_search_tool') is False
    assert deferred.pop('supports_search_tool') is True
    assert eager == deferred
    assert models[0]['supports_search_tool'] is True
    if profile.startswith('code-') or profile == 'model-default':
        assert eager['tool_mode'] == 'code_mode_only'
    else:
        assert 'tool_mode' not in eager


def test_code_profile_removes_only_conflicting_disables(recovery,
                                                       monkeypatch, tmp_path):
    """Native approvals and unrelated capability restrictions are retained."""
    monkeypatch.setattr(recovery, 'command', lambda *_: [
        'codex', 'app-server', '--disable', 'shell_tool', '--disable',
        'code_mode', '--disable', 'code_mode_only', '--disable', 'apps',
    ])
    result = recovery.native_command(tmp_path, 'code-local')
    assert result[:6] == ['codex', 'app-server', '--disable', 'shell_tool',
                          '--disable', 'apps']
    assert 'features.code_mode_tool_search=true' in result
    assert 'features.code_mode_only=true' in result


def test_replay_preserves_observed_search_shape(recovery):
    """The regression fixture must not normalize away the real failure."""
    del recovery
    replay = importlib.import_module('search_format_replay')
    item = replay.search_item(True)
    assert item['type'] == 'function_call'
    assert item['namespace'] == 'tool_search'
    assert item['name'] == 'tool_search_tool'
    assert json.loads(item['arguments']) == {'query': 'docs_get_color_palette',
                                            'limit': 1}
    canonical = replay.search_item(False)
    assert canonical['type'] == 'tool_search_call'
    assert canonical['arguments'] == json.loads(item['arguments'])


def test_ordinary_routing_does_not_force_feature_settings(recovery,
                                                        monkeypatch, tmp_path):
    """Restore normal model metadata without enabling experimental features."""
    monkeypatch.setattr(recovery, 'command', lambda *_: [
        'codex', '--disable', 'code_mode', '--disable', 'code_mode_only',
        '--disable', 'shell_tool',
    ])
    command = recovery.native_command(tmp_path, 'model-default')
    assert command[:3] == ['codex', '--disable', 'shell_tool']
    assert not any('features.' in part for part in command)


def test_ordinary_schedule_and_schema_observation(recovery):
    """Observe full code-mode declarations instead of top-level functions."""
    del recovery
    study = importlib.import_module('ordinary_loading_study')
    jobs = study.schedule(10)
    expected_sessions = 60
    assert len(jobs) == expected_sessions
    assert len({j['id'] for j in jobs}) == expected_sessions
    for arm in ('eager', 'deferred'):
        row = {'id': 'case', 'model': 'gpt-6.1-sol', 'arm': arm,
               'repeat': 0, 'status': 'completed', 'server_calls': []}
        description = '\n'.join(f'### `mcp__native_probe__tool_{n}`'
                                 for n in range(36)) if arm == 'eager' else ''
        events = [{'method': 'rawResponseItem/completed', 'params': {'item': {
            'type': 'additional_tools', 'id': 'initial', 'tools': [{
                'type': 'namespace', 'name': 'functions', 'tools': [{
                    'type': 'custom', 'name': 'exec',
                    'description': description,
                }],
            }],
        }}}]
        audit = study.audit(row, events)
        assert audit['exposure_verified']
        assert audit['initial_native_schemas'] == (36 if arm == 'eager' else 0)


def test_code_approval_turn_routes_native_confirmation(recovery):
    """An MCP elicitation during exec must reach the native approval router."""
    del recovery
    replay = importlib.import_module('ordinary_approval_replay')
    events = [{'id': 1, 'method': 'mcpServer/elicitation/request'},
              {'method': 'turn/completed',
               'params': {'turn': {'status': 'completed'}}}]
    handled = []

    async def request(_method, _params):
        return {}

    async def receive():
        return events.pop(0)

    async def handle(event):
        handled.append(event['method'])

    client = SimpleNamespace(request=request, receive=receive,
                             handle_request=handle)
    assert asyncio.run(replay.native_turn(client, 'thread'))['status']
    assert handled == ['mcpServer/elicitation/request']


def test_ordinary_paired_token_savings_and_sample_variance(recovery):
    """Paired resampling preserves proportional savings and sample variance."""
    del recovery
    analysis = importlib.import_module('analyze_ordinary_loading')
    result = analysis.saving([100, 200, 300], [50, 100, 150])
    assert result['percent'] == pytest.approx(50)
    assert result['ci95'] == [50, 50]
    summary = analysis.continuous([1, 2, 3])
    assert summary['mean'] == pytest.approx(2)
    assert summary['variance'] == 1
    assert summary['ci95'][0] <= summary['mean'] <= summary['ci95'][1]
    assert analysis.saving([], [])['ci95'] is None
