"""Check canonical settings and the removal of legacy environment aliases."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from gdocs_scope_mcp import auth_setup, tool_logging
from gdocs_scope_mcp.google_api import credentials, files, oauth
from gdocs_scope_mcp.settings import Settings, default_token_path, get_settings
from gdocs_scope_mcp.tool_logging import configure_logging

OVERRIDES = {
    'client_id': ('configured-client', 'configured-client'),
    'write_revision_mode': ('target', 'target'),
    'document_cache_enabled': ('true', True),
    'document_cache_storage': ('memory', 'memory'),
    'document_cache_directory': ('/tmp/example-cache',
                                 Path('/tmp/example-cache')),
    'document_cache_database_max_bytes': ('2097152', 2097152),
    'document_cache_ttl_seconds': ('600', 600),
    'document_cache_max_entries': ('10', 10),
    'document_cache_max_bytes': ('1048576', 1048576),
    'table_snapshot_ttl_seconds': ('3600', 3600),
    'code_font_family': (' Consolas ', 'Consolas'),
    'inline_code_color': ('#aabbcc', '#AABBCC'),
    'code_block_highlighting': ('false', False),
    'code_block_style': ('monokai', 'monokai'),
    'code_block_line_spacing': ('1.5', 1.5),
    'code_block_theme_background': ('true', True),
    'code_block_named_ranges': ('false', False),
    'read_inline_code': ('false', False),
    'read_inline_code_fonts': ('["Consolas"]', ['Consolas']),
    'read_inline_code_colors': ('["#112233"]', ['#112233']),
    'read_inline_code_match': ('font', 'font'),
    'read_code_block_heuristic': ('false', False),
    'read_native_code_blocks': ('false', False),
    'read_code_block_fonts': ('["Consolas"]', ['Consolas']),
    'read_code_block_line_spacing': ('1.5', 1.5),
    'read_code_block_require_background': ('true', True),
    'read_code_block_min_lines': ('3', 3),
}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Keep real grants, configuration, and environment out of these tests."""
    for name in list(os.environ):
        if name.startswith(('GDOCS_SCOPE_MCP_', 'GOOGLE_DOCS_',
                            'GOOGLE_DRIVE_MCP_')):
            monkeypatch.delenv(name)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(credentials, 'STANDALONE_TOKEN_PATHS', [])
    monkeypatch.setattr(credentials, 'GOG_CREDENTIALS_PATH', tmp_path / 'gog')
    for name in ('handlers', 'level', 'propagate'):
        monkeypatch.setattr(tool_logging.logger, name,
                            getattr(tool_logging.logger, name))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize('name', OVERRIDES)
def test_every_setting_accepts_canonical_environment(name, monkeypatch):
    """Exercise actual parsing for every supported Settings override."""
    assert OVERRIDES.keys() == Settings.model_fields.keys()
    value, expected = OVERRIDES[name]
    monkeypatch.setenv('GDOCS_SCOPE_MCP_' + name.upper(), value)
    assert getattr(get_settings(), name) == expected


@pytest.mark.parametrize('prefix', ['GOOGLE_DOCS_MCP_', 'GOOGLE_DRIVE_MCP_'])
@pytest.mark.parametrize('name', OVERRIDES)
def test_removed_settings_are_ignored(prefix, name, monkeypatch):
    """Invalid old overrides cannot affect settings or validation."""
    baseline = Settings().model_dump()
    monkeypatch.setenv(prefix + name.upper(), 'invalid-legacy-value')
    assert Settings().model_dump() == baseline


@pytest.mark.parametrize('name', [
    'CLIENT_ID', 'WRITE_REVISION_MODE', 'DOCUMENT_CACHE_ENABLED',
    'TABLE_SNAPSHOT_TTL_SECONDS', 'CODE_FONT_FAMILY', 'INLINE_CODE_COLOR',
])
def test_empty_typed_override_is_invalid(name, monkeypatch):
    """Empty typed settings are explicit invalid values, not file fallback."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_' + name, '')
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize('value', ['', ' ', 'VERBOSE'])
def test_invalid_canonical_log_level_fails(value, monkeypatch):
    """Validate the canonical log setting rather than a legacy alias."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LOG_LEVEL', value)
    with pytest.raises(ValueError, match='GDOCS_SCOPE_MCP_LOG_LEVEL'):
        configure_logging()


def test_old_config_and_log_level_cannot_affect_startup(monkeypatch):
    """Ignore broken obsolete inputs rather than opening or validating them."""
    for prefix in ('GOOGLE_DOCS_MCP_', 'GOOGLE_DRIVE_MCP_'):
        monkeypatch.setenv(prefix + 'CONFIG', '/missing/old-config.json')
        monkeypatch.setenv(prefix + 'LOG_LEVEL', 'INVALID')
    assert get_settings().write_revision_mode == 'required'
    assert configure_logging() == 'INFO'
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LOG_LEVEL', ' debug ')
    assert configure_logging() == 'DEBUG'


@pytest.mark.parametrize('name', [
    'GOOGLE_DOCS_MCP_TOKEN', 'GOOGLE_DRIVE_MCP_TOKEN',
    'GOOGLE_DOCS_TOKEN_FILE',
])
def test_removed_token_alias_does_not_select_a_file(name, monkeypatch):
    """An obsolete explicit path cannot override the retained default path."""
    path = default_token_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"source":"default"}')
    monkeypatch.setenv(name, '/missing/obsolete-token.json')
    assert credentials.load_token() == {'source': 'default'}


def test_canonical_token_path_empty_and_invalid_values(monkeypatch, tmp_path):
    """Empty means default; nonempty paths never silently fall back."""
    path = default_token_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"source":"default"}')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', '')
    assert credentials.load_token() == {'source': 'default'}
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', ' ')
    with pytest.raises(ValueError, match='GDOCS_SCOPE_MCP_TOKEN'):
        credentials.load_token()
    missing = tmp_path / 'missing.json'
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', str(missing))
    with pytest.raises(FileNotFoundError):
        credentials.load_token()
    missing.write_text('{malformed')
    with pytest.raises(json.JSONDecodeError):
        credentials.load_token()
    missing.write_text('{"source":"explicit"}')
    assert credentials.load_token() == {'source': 'explicit'}


@pytest.mark.parametrize('stored', [False, True])
def test_server_client_precedence_and_removed_aliases(stored, monkeypatch):
    """Keep token over new environment over JSON and ignore old secrets."""
    config = default_token_path().with_name('config.json')
    config.parent.mkdir(parents=True)
    config.write_text('{"client_id":"json-client"}')
    token = {'refresh_token': 'refresh'}
    if stored:
        token.update(client_id='token-client', client_secret='token-secret')
    monkeypatch.setattr(credentials, 'load_token', lambda: token)
    public, secret = Mock(), Mock()
    monkeypatch.setattr(credentials, 'PublicClientCredentials', public)
    monkeypatch.setattr(credentials, 'Credentials', secret)
    for prefix in ('GOOGLE_DOCS_MCP_', 'GOOGLE_DRIVE_MCP_'):
        monkeypatch.setenv(prefix + 'CLIENT_ID', 'old-client')
        monkeypatch.setenv(prefix + 'CLIENT_SECRET', 'old-secret')
    credentials.load_credentials()
    constructor = secret if stored else public
    assert constructor.call_args.kwargs['client_id'] == (
        'token-client' if stored else 'json-client')
    assert constructor.call_args.kwargs['client_secret'] == (
        'token-secret' if stored else '')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_ID', ' env-client ')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_SECRET', 'env-secret')
    credentials.load_credentials()
    assert secret.call_args.kwargs['client_id'] == (
        'token-client' if stored else 'env-client')
    assert secret.call_args.kwargs['client_secret'] == (
        'token-secret' if stored else 'env-secret')


def test_authorization_cli_ignores_aliases_and_prints_new_token_name(
    monkeypatch, tmp_path, capsys,
):
    """Select the shared client without reading obsolete client overrides."""
    for prefix in ('GOOGLE_DOCS_MCP_', 'GOOGLE_DRIVE_MCP_'):
        monkeypatch.setenv(prefix + 'CLIENT_ID', 'old-client')
        monkeypatch.setenv(prefix + 'CLIENT_SECRET', 'old-secret')
    monkeypatch.setattr(auth_setup.sys, 'argv', [
        'auth', '--out', str(tmp_path / 'new-token.json'),
    ])
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    auth_setup.main()
    assert run.call_args.args[:2] == (oauth.PROJECT_CLIENT_ID,
                                    oauth.PROJECT_CLIENT_SECRET)
    assert 'Set GDOCS_SCOPE_MCP_TOKEN=' in capsys.readouterr().out


@pytest.mark.parametrize('name', ['CLIENT_ID', 'CLIENT_SECRET'])
def test_authorization_rejects_blank_credentials(name, monkeypatch):
    """Reject whitespace-only overrides before starting consent or exchange."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_' + name, ' ')
    monkeypatch.setattr(auth_setup.sys, 'argv', ['auth'])
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    with pytest.raises(SystemExit) as error:
        auth_setup.main()
    assert error.value.code == 1
    run.assert_not_called()


def test_explicit_credentials_file_wins_over_invalid_environment(
    monkeypatch, tmp_path,
):
    """Retain credentials-file priority over unrelated ambient overrides."""
    path = tmp_path / 'client.json'
    path.write_text('{"installed":{"client_id":"file-client",'
                    '"client_secret":"file-secret"}}')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_ID', ' ')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_SECRET', ' ')
    monkeypatch.setattr(auth_setup.sys, 'argv', [
        'auth', '--credentials', str(path), '--client-id', 'cli-client',
    ])
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    auth_setup.main()
    assert run.call_args.args[:2] == ('file-client', 'file-secret')


def test_empty_secret_selects_public_client(monkeypatch):
    """An empty optional secret keeps a custom grant secretless."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_SECRET', '')
    monkeypatch.setattr(auth_setup.sys, 'argv', [
        'auth', '--client-id', 'custom-client',
    ])
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    auth_setup.main()
    assert run.call_args.args[:2] == ('custom-client', None)


@pytest.mark.parametrize(('name', 'value'), [
    ('USE_DRIVE', ' '), ('USE_DRIVE', 'invalid'),
    ('DRIVE_ID', ' '), ('DRIVE_ID', '\t'),
])
def test_shared_drive_invalid_values_fail_before_auth(
    name, value, monkeypatch,
):
    """Reject bad booleans and blank IDs before creating Google clients."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_' + name, value)
    factory = Mock()
    monkeypatch.setattr(files.clients, 'get_service', factory)
    with pytest.raises(ValueError, match='GDOCS_SCOPE_MCP_' + name):
        files.list_documents()
    factory.assert_not_called()


def test_old_shared_drive_variables_are_ignored(monkeypatch):
    """Do not let either former shared-drive switch select another corpus."""
    monkeypatch.setenv('GOOGLE_DOCS_USE_DRIVE', 'true')
    monkeypatch.setenv('GOOGLE_DOCS_DRIVE_ID', 'old-drive')
    service = Mock()
    service.files.return_value.list.return_value.execute.return_value = {}
    monkeypatch.setattr(files.clients, 'get_service',
                        lambda *_a, **_k: service)
    files.list_documents()
    request = service.files.return_value.list.call_args.kwargs
    assert not {'corpora', 'driveId', 'supportsAllDrives'} & request.keys()


@pytest.mark.parametrize(('switch', 'drive_id', 'expected'), [
    ('', '', {}),
    ('TrUe', '', {'supportsAllDrives': True,
                  'includeItemsFromAllDrives': True}),
    ('false', 'new-drive', {'corpora': 'drive', 'driveId': 'new-drive',
                          'supportsAllDrives': True,
                          'includeItemsFromAllDrives': True}),
])
def test_canonical_shared_drive_options(
    switch, drive_id, expected, monkeypatch,
):
    """Empty options are unset; new names select the intended Drive."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_USE_DRIVE', switch)
    monkeypatch.setenv('GDOCS_SCOPE_MCP_DRIVE_ID', drive_id)
    service = Mock()
    service.files.return_value.list.return_value.execute.return_value = {}
    monkeypatch.setattr(files.clients, 'get_service',
                        lambda *_a, **_k: service)
    files.list_documents()
    arguments = service.files.return_value.list.call_args.kwargs
    relevant = {'corpora', 'driveId', 'supportsAllDrives',
                'includeItemsFromAllDrives'}
    assert {key: value for key, value in arguments.items()
            if key in relevant} == expected
