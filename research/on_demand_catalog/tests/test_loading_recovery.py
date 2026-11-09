"""Validate isolated profile interventions before real diagnostic calls."""

import importlib
from pathlib import Path

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
