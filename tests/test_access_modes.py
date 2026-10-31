"""Reject broad credentials before selected-file document access."""

import json
from unittest.mock import Mock

import pytest

from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import credentials
from gdocs_scope_mcp.google_api.access import (
    DRIVE_FILE,
    require_selected_scopes,
)
from gdocs_scope_mcp.settings import Settings, default_token_path, get_settings


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch, tmp_path):
    """Use a private configuration and invalidate cached settings."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_mode_precedence(monkeypatch, tmp_path):
    """Environment overrides JSON while the compatibility default is broad."""
    assert Settings().access_mode == 'full_drive'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'access_mode': 'selected_files'}))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CONFIG', str(config))
    assert Settings().access_mode == 'selected_files'
    assert default_token_path(get_settings().access_mode).name == (
        'selected-files-token.json'
    )
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'full_drive')
    assert Settings().access_mode == 'full_drive'


@pytest.mark.parametrize('scopes', [None, [], ['openid', DRIVE_FILE],
                                  ['https://www.googleapis.com/auth/drive']])
def test_narrow_policy_rejects_unknown_and_broad(scopes):
    """A label or a requested scope cannot prove the actual grant."""
    with pytest.raises(ToolFailureError):
        require_selected_scopes(scopes)


def test_no_legacy_fallback(monkeypatch, tmp_path):
    """Selected mode never exports or loads a broad legacy token."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'selected_files')
    monkeypatch.delenv('GDOCS_SCOPE_MCP_TOKEN', raising=False)
    legacy = tmp_path / 'legacy.json'
    legacy.write_text('{"refresh_token":"broad"}')
    monkeypatch.setattr(credentials, 'STANDALONE_TOKEN_PATHS', [legacy])
    export = Mock(side_effect=AssertionError('must not export'))
    monkeypatch.setattr(credentials, 'export_gog_token', export)
    with pytest.raises(ToolFailureError) as raised:
        credentials.load_token()
    assert 'docs_authorize' in raised.value.failure.suggested_action
    export.assert_not_called()


@pytest.mark.parametrize('saved,granted,success', [
    ([DRIVE_FILE], [DRIVE_FILE], True),
    ([DRIVE_FILE], None, False),
    ([DRIVE_FILE], [DRIVE_FILE, 'openid'], False),
    (['https://www.googleapis.com/auth/drive'], [DRIVE_FILE], False),
])
def test_refresh_checks_actual_grant(monkeypatch, saved, granted, success):
    """Refresh must independently confirm the exact narrow scope."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'selected_files')
    monkeypatch.setattr(credentials, 'load_token', lambda: {
        'client_id': 'client', 'client_secret': 'secret',
        'refresh_token': 'refresh', 'scopes': saved,
    })
    def refresh(self, _request):
        self._granted_scopes = granted
    monkeypatch.setattr(credentials.Credentials, 'refresh', refresh)
    if success:
        assert credentials.load_credentials().granted_scopes == [DRIVE_FILE]
    else:
        with pytest.raises(ToolFailureError):
            credentials.load_credentials()


@pytest.mark.parametrize('labelled', [False, True])
def test_full_mode_rejects_selected_token(monkeypatch, labelled):
    """Changing settings alone cannot turn a narrow token into broad access."""
    token = {'scopes': [DRIVE_FILE]}
    if labelled:
        token['access_mode'] = 'selected_files'
    monkeypatch.setattr(credentials, 'load_token', lambda: token)
    with pytest.raises(ToolFailureError) as raised:
        credentials.load_credentials()
    assert raised.value.failure.code == 'AUTHENTICATION_REQUIRED'
    assert 'docs_authorize' in raised.value.failure.suggested_action


def test_default_mode_switch_requests_authorization(monkeypatch):
    """A default-path switch finds the narrow token before gog fallback."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_TOKEN', raising=False)
    monkeypatch.setattr(credentials, 'STANDALONE_TOKEN_PATHS', [])
    path = default_token_path('selected_files')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'scopes': [DRIVE_FILE]}))
    export = Mock(side_effect=AssertionError('must not export'))
    monkeypatch.setattr(credentials, 'export_gog_token', export)
    with pytest.raises(ToolFailureError) as raised:
        credentials.load_credentials()
    assert 'docs_authorize' in raised.value.failure.suggested_action
    export.assert_not_called()


def test_full_mode_checks_refreshed_narrow_grant(monkeypatch):
    """Actual refreshed scopes override broad-looking saved metadata."""
    monkeypatch.setattr(credentials, 'load_token', lambda: {
        'client_id': 'client', 'client_secret': 'secret',
        'refresh_token': 'refresh',
        'scopes': ['https://www.googleapis.com/auth/drive'],
    })
    def refresh(self, _request):
        self._granted_scopes = [DRIVE_FILE]
    monkeypatch.setattr(credentials.Credentials, 'refresh', refresh)
    with pytest.raises(ToolFailureError) as raised:
        credentials.load_credentials()
    assert 'docs_authorize' in raised.value.failure.suggested_action
