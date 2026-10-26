"""Verify agent-facing formatting overrides and request-local isolation."""

import asyncio

import pytest
from fastmcp import Client
from pydantic import TypeAdapter
from pygments.styles import get_all_styles

from gdocs_scope_mcp import server
from gdocs_scope_mcp.settings import (
    code_formatting,
    get_code_settings,
    get_settings,
)
from gdocs_scope_mcp.tool_inputs import CodeBlockStyle

OPERATIONS = ['append', 'insert_before', 'insert_after']


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Keep server defaults deterministic without changing global config."""
    for name in ('CONFIG', 'CODE_FONT_FAMILY', 'INLINE_CODE_COLOR',
                 'CODE_BLOCK_HIGHLIGHTING', 'CODE_BLOCK_STYLE',
                 'CODE_BLOCK_LINE_SPACING', 'CODE_BLOCK_THEME_BACKGROUND'):
        monkeypatch.delenv('GOOGLE_DOCS_MCP_' + name, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def arguments(operation, **overrides):
    """Build the same code insertion for all three public tools."""
    result = {
        'doc_id': 'example', 'text': 'Before\n\n```python\n()\n```\n\nAfter',
        **overrides,
    }
    if operation != 'append':
        result['anchor'] = 'Introduction'
    return result


def call(operation, args, *, raise_on_error=True):
    """Exercise schema validation and the real converter through MCP."""
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_' + operation, args,
                                          raise_on_error=raise_on_error)

    return asyncio.run(run())


def assert_style(mock_docs, theme, background):
    """Inspect native colors and paragraph fill, independently of settings."""
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if 'updateTextStyle' in r]
    assert len(styles) == 1
    rgb = styles[0]['foregroundColor']['color']['rgbColor']
    color = tuple(rgb.get(key, 0) for key in ('red', 'green', 'blue'))
    expected = ((248 / 255, 248 / 255, 242 / 255)
                if theme == 'monokai' else (0, 0, 0))
    assert color == expected
    shaded = [r for r in requests if 'shading' in r.get(
        'updateParagraphStyle', {}).get('paragraphStyle', {})]
    assert bool(shaded) == background


@pytest.mark.parametrize('operation', OPERATIONS)
@pytest.mark.parametrize(('base_theme', 'base_background', 'overrides',
                          'expected_theme', 'expected_background'), [
    ('default', False, {}, 'default', False),
    ('monokai', True, {}, 'monokai', True),
    ('monokai', True, {'code_block_style': None,
                       'code_block_theme_background': None}, 'monokai', True),
    ('monokai', True, {'code_block_theme_background': False},
     'monokai', False),
    ('default', False, {'code_block_style': 'monokai'}, 'monokai', False),
    ('monokai', True, {'code_block_style': 'default',
                       'code_block_theme_background': False},
     'default', False),
    ('default', False, {'code_block_style': 'monokai',
                        'code_block_theme_background': True}, 'monokai', True),
])
def test_agent_values_override_or_inherit_environment(
    mock_docs, monkeypatch, *, operation, base_theme, base_background,
    overrides, expected_theme, expected_background,
):
    """Distinguish explicit False from omitted/null inherited defaults."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE', base_theme)
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_THEME_BACKGROUND',
                       str(base_background).lower())
    defaults = get_settings()
    result = call(operation, arguments(operation, **overrides))
    assert not result.is_error
    assert_style(mock_docs, expected_theme, expected_background)
    assert get_settings() is defaults
    assert get_code_settings() is defaults


@pytest.mark.parametrize('operation', OPERATIONS)
@pytest.mark.parametrize('upload_local_images', [False, True])
def test_override_does_not_leak_to_next_call(
    mock_docs, operation, upload_local_images,
):
    """Cover both insertion planners and restore defaults for the next call."""
    result = call(operation, arguments(
        operation, code_block_style='monokai',
        code_block_theme_background=True,
        upload_local_images=upload_local_images,
    ))
    assert not result.is_error
    assert_style(mock_docs, 'monokai', True)
    result = call(operation, arguments(operation))
    assert not result.is_error
    assert_style(mock_docs, 'default', False)


@pytest.mark.parametrize('operation', OPERATIONS)
@pytest.mark.parametrize('overrides', [
    {'code_block_style': 'unknown-theme'}, {'code_block_style': ''},
    {'code_block_style': 12}, {'code_block_theme_background': 'false'},
    {'code_block_theme_background': 0},
])
def test_invalid_agent_formatting_fails_before_google_access(
    mock_docs, operation, overrides,
):
    """Reject invalid themes and non-boolean switches at the MCP boundary."""
    result = call(operation, arguments(operation, **overrides),
                  raise_on_error=False)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('operation', OPERATIONS)
def test_literal_mode_does_not_apply_formatting(mock_docs, operation):
    """Leave literal text unaffected by valid formatting options."""
    result = call(operation, arguments(
        operation, rich=False, code_block_style='monokai',
        code_block_theme_background=True,
    ))
    assert not result.is_error
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert all('insertText' in r for r in requests)


@pytest.mark.parametrize('operation', OPERATIONS)
def test_failed_google_write_restores_defaults(mock_docs, operation):
    """Do not let a failed request change subsequent requests' formatting."""
    mock_docs.batchUpdate.return_value.execute.side_effect = RuntimeError(
        'probe',
    )
    result = call(operation, arguments(
        operation, code_block_style='monokai',
        code_block_theme_background=True,
    ), raise_on_error=False)
    assert result.is_error
    assert get_code_settings() is get_settings()
    mock_docs.batchUpdate.return_value.execute.side_effect = None
    result = call(operation, arguments(operation))
    assert not result.is_error
    assert_style(mock_docs, 'default', False)


@pytest.mark.parametrize('operation', OPERATIONS)
def test_omitted_parameters_inherit_json_file(
    mock_docs, monkeypatch, tmp_path, operation,
):
    """Keep JSON settings as defaults without requiring agent arguments."""
    path = tmp_path / 'defaults.json'
    path.write_text(
        '{"code_block_style":"monokai","code_block_theme_background":true}',
        encoding='utf-8',
    )
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', str(path))
    result = call(operation, arguments(operation))
    assert not result.is_error
    assert_style(mock_docs, 'monokai', True)


def test_schema_exposes_optional_nullable_overrides():
    """Tell agents both overrides are optional and inherit when null."""
    async def run():
        async with Client(server.mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(run())
    found = set()
    for tool in tools:
        if tool.name not in ['docs_' + name for name in OPERATIONS]:
            continue
        found.add(tool.name)
        for field, kind in [('code_block_style', 'string'),
                            ('code_block_theme_background', 'boolean')]:
            schema = tool.inputSchema['properties'][field]
            assert field not in tool.inputSchema.get('required', [])
            assert schema['default'] is None
            assert {v['type'] for v in schema['anyOf']} == {kind, 'null'}
            assert 'inherit' in schema['description']
            if field == 'code_block_style':
                choices = next(v['enum'] for v in schema['anyOf']
                               if v['type'] == 'string')
                assert choices == sorted(set(get_all_styles()))
                assert {'default', 'monokai'} <= set(choices)
    assert found == {'docs_' + name for name in OPERATIONS}


def test_every_advertised_theme_is_accepted():
    """Keep enum discovery consistent with the parameter's real validator."""
    adapter = TypeAdapter(CodeBlockStyle)
    for name in get_all_styles():
        assert adapter.validate_python(name) == name


def test_nested_context_restores_settings_after_exception():
    """Restore the outer override on failure, then restore server defaults."""
    defaults = get_settings()
    with code_formatting(style='monokai', theme_background=True):
        outer = get_code_settings()
        with (pytest.raises(RuntimeError),
              code_formatting(theme_background=False)):
            assert not get_code_settings().code_block_theme_background
            raise RuntimeError('probe')
        assert get_code_settings() is outer
    assert get_code_settings() is defaults


def test_concurrent_requests_keep_separate_formatting():
    """Interleave requests while retaining each call's own theme and fill."""
    async def request(style, background):
        with code_formatting(style=style, theme_background=background):
            await asyncio.sleep(0)
            settings = get_code_settings()
            return (settings.code_block_style,
                    settings.code_block_theme_background)

    async def run():
        return await asyncio.gather(request('monokai', True),
                                    request('default', False))

    assert asyncio.run(run()) == [('monokai', True), ('default', False)]
    assert get_code_settings() is get_settings()
