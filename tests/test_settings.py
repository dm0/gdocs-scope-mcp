"""Verify configuration precedence, validation and generated native styles."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from gdocs_scope_mcp import server
from gdocs_scope_mcp.md2requests import markdown_to_requests
from gdocs_scope_mcp.settings import config_path, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Keep user settings and the process cache outside each test."""
    for name in (
        'GOOGLE_DOCS_MCP_CONFIG', 'GOOGLE_DOCS_MCP_CODE_FONT_FAMILY',
        'GOOGLE_DOCS_MCP_INLINE_CODE_COLOR',
        'GOOGLE_DOCS_MCP_WRITE_REVISION_MODE',
        'GOOGLE_DOCS_MCP_TABLE_SNAPSHOT_TTL_SECONDS',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_ENABLED',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_STORAGE',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DIRECTORY',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DATABASE_MAX_BYTES',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_TTL_SECONDS',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_MAX_ENTRIES',
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_MAX_BYTES',
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def custom_config(tmp_path, monkeypatch):
    """Choose a JSON config outside the default location."""
    path = tmp_path / 'custom.json'
    path.write_text(json.dumps({
        'code_font_family': 'Courier New', 'inline_code_color': '#aabbcc',
    }), encoding='utf-8')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', str(path))
    return path


def test_defaults_need_no_config_file():
    """Match the already verified native Google Docs backtick style."""
    assert not config_path().exists()
    settings = get_settings()
    assert settings.code_font_family == 'Roboto Mono'
    assert settings.inline_code_color == '#188038'
    assert settings.write_revision_mode == 'required'
    assert settings.table_snapshot_ttl_seconds == 86400  # noqa: PLR2004


def test_default_file_is_discovered():
    """Load JSON from the XDG config directory without an explicit path."""
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"inline_code_color": "#112233"}', encoding='utf-8')
    assert get_settings().inline_code_color == '#112233'
    assert get_settings().code_font_family == 'Roboto Mono'


def test_explicit_file_and_environment_precedence(custom_config, monkeypatch):
    """Override individual JSON fields while keeping the other file values."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_FONT_FAMILY', ' Consolas ')
    assert config_path() == custom_config
    assert get_settings().code_font_family == 'Consolas'
    assert get_settings().inline_code_color == '#AABBCC'


def test_environment_without_file(monkeypatch):
    """Allow configuring both fields through the MCP client's environment."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_INLINE_CODE_COLOR', '#000000')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_FONT_FAMILY', 'Consolas')
    assert get_settings().inline_code_color == '#000000'
    assert get_settings().code_font_family == 'Consolas'


@pytest.mark.parametrize('value', ['', ' ', 'missing.json'])
def test_explicit_missing_or_empty_path_fails(value, monkeypatch):
    """Fail when an explicitly chosen file is absent."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', value)
    with pytest.raises(ValueError, match='GOOGLE_DOCS_MCP_CONFIG'):
        get_settings()


@pytest.mark.parametrize('data', [
    {'inline_code_color': 'green'},
    {'inline_code_color': '#123'},
    {'inline_code_color': '#1234567'},
    {'inline_code_color': '#GG0000'},
    {'code_font_family': '  '},
    {'inline_code_colour': '#112233'},
    {'write_revision_mode': 'automatic'},
    {'write_revision_mode': ''},
    {'table_snapshot_ttl_seconds': 0},
    {'table_snapshot_ttl_seconds': 604801},
    {'table_snapshot_ttl_seconds': True},
    {'document_cache_storage': 'unknown'},
    {'document_cache_database_max_bytes': 1048575},
    {'document_cache_ttl_seconds': 86400},
    {'document_cache_max_bytes': 0},
    {'document_cache_max_entries': 0},
])
def test_invalid_settings_fail(custom_config, data):
    """Reject invalid RGB syntax, blank fonts and unknown/typo fields."""
    custom_config.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValidationError):
        get_settings()


def test_invalid_environment_fails(monkeypatch):
    """Validate overrides as strictly as file settings."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_INLINE_CODE_COLOR', 'invalid')
    with pytest.raises(ValidationError):
        get_settings()


def test_table_snapshot_environment(monkeypatch):
    """Choose snapshot expiry independently of process lifetime."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_TABLE_SNAPSHOT_TTL_SECONDS', '3600')
    assert get_settings().table_snapshot_ttl_seconds == 3600  # noqa: PLR2004


def test_document_cache_configuration(custom_config, monkeypatch):
    """Override bounded cache settings through the usual configuration."""
    custom_config.write_text(json.dumps({
        'document_cache_enabled': True, 'document_cache_ttl_seconds': 600,
        'document_cache_max_entries': 8, 'document_cache_max_bytes': 1048576,
    }))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_ENABLED', 'false')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_TTL_SECONDS', '900')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_STORAGE', 'memory')
    monkeypatch.setenv(
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DIRECTORY', '/tmp/cache',
    )
    monkeypatch.setenv(
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DATABASE_MAX_BYTES', '2097152',
    )
    settings = get_settings()
    assert settings.document_cache_enabled is False
    assert settings.document_cache_storage == 'memory'
    assert str(settings.document_cache_directory) == '/tmp/cache'
    assert settings.document_cache_database_max_bytes == 2097152  # noqa: PLR2004
    assert settings.document_cache_ttl_seconds == 900  # noqa: PLR2004
    assert settings.document_cache_max_entries == 8  # noqa: PLR2004
    assert settings.document_cache_max_bytes == 1048576  # noqa: PLR2004


def test_malformed_json_fails_before_server_runs(custom_config, monkeypatch):
    """Report broken configuration before accepting tool calls."""
    custom_config.write_text('{broken', encoding='utf-8')
    run = Mock()
    monkeypatch.setattr(server.mcp, 'run', run)
    monkeypatch.setattr(server, 'configure_logging', Mock())
    with pytest.raises(json.JSONDecodeError):
        server.main()
    run.assert_not_called()


def test_settings_are_cached_until_restart(custom_config):
    """Avoid changing style midway through a running server's operations."""
    initial = get_settings()
    custom_config.write_text(
        '{"code_font_family":"Consolas"}', encoding='utf-8',
    )
    assert get_settings() is initial
    get_settings.cache_clear()
    assert get_settings().code_font_family == 'Consolas'


def test_revision_mode_configuration(custom_config, monkeypatch):
    """Select target in JSON, override by environment, and reject typos."""
    custom_config.write_text('{"write_revision_mode":"target"}')
    assert get_settings().write_revision_mode == 'target'
    get_settings.cache_clear()
    monkeypatch.setenv('GOOGLE_DOCS_MCP_WRITE_REVISION_MODE', 'required')
    assert get_settings().write_revision_mode == 'required'
    get_settings.cache_clear()
    monkeypatch.setenv('GOOGLE_DOCS_MCP_WRITE_REVISION_MODE', 'merge')
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize('markup', ['Before `word🦷` after',
                                    'Before <code>word🦷</code> after'])
@pytest.mark.usefixtures('custom_config')
def test_custom_inline_style_reaches_native_requests(markup):
    """Use the configured RGB channels and font for Markdown and HTML code."""
    requests = markdown_to_requests(markup, start=1, newline_before=False)
    updates = [r['updateTextStyle'] for r in requests
               if 'updateTextStyle' in r]
    assert len(updates) == 1
    assert updates[0] == {
        'range': {'startIndex': 8, 'endIndex': 14},
        'textStyle': {
            'weightedFontFamily': {'fontFamily': 'Courier New'},
            'foregroundColor': {'color': {'rgbColor': {
                'red': 170 / 255, 'green': 187 / 255, 'blue': 204 / 255,
            }}},
        },
        'fields': 'weightedFontFamily,foregroundColor',
    }


@pytest.mark.usefixtures('custom_config')
def test_custom_font_applies_to_blocks_without_inline_color():
    """Keep block styling independent from the inline-only color setting."""
    requests = markdown_to_requests('```\nword\n```', start=1)
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if 'updateTextStyle' in r]
    assert styles == [{'weightedFontFamily': {'fontFamily': 'Courier New'}}]
