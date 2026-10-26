"""Verify syntax colors, lossless code text and native UTF-16 style ranges."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pygments.token import Token

from gdocs_scope_mcp import code_highlighting
from gdocs_scope_mcp.code_highlighting import code_spans
from gdocs_scope_mcp.md2requests import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def clean_config(monkeypatch, tmp_path):
    """Isolate cached settings and avoid reading any user config."""
    for name in ('CONFIG', 'CODE_FONT_FAMILY', 'INLINE_CODE_COLOR',
                 'CODE_BLOCK_HIGHLIGHTING', 'CODE_BLOCK_STYLE'):
        monkeypatch.delenv('GOOGLE_DOCS_MCP_' + name, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize('language', ['python', 'json', 'bash', 'javascript'])
@pytest.mark.parametrize('content', [
    '\n\nfirst🦷\n\tsecond = "🦷"  \n\n', '', 'x', '\ufeffx\r\ny\r\n',
])
def test_lexing_never_changes_source_text(language, content):
    """Retain blank lines, tabs, trailing spaces, BOM and line endings."""
    spans = code_spans(content, language)
    assert ''.join(value for value, _ in spans) == content
    assert all(value for value, _ in spans)
    assert all(spans[i][1] != spans[i - 1][1] for i in range(1, len(spans)))


@pytest.mark.parametrize('language', [None, '', 'not-a-real-language'])
def test_unspecified_and_unknown_languages_stay_plain(language):
    """Avoid guessing a language or applying theme colors to plain blocks."""
    [(text, style)] = code_spans('return "🦷"\n', language)
    assert text == 'return "🦷"\n'
    assert style.weighted_font_family.font_family == 'Roboto Mono'
    assert style.foreground_color is None
    assert style.background_color is None


def test_default_python_keyword_style():
    """Apply the default theme's native RGB and weight to a Python keyword."""
    [(text, style)] = code_spans('return', 'python')
    assert text == 'return'
    assert style.bold
    rgb = style.foreground_color.color.rgb_color
    assert (rgb.red, rgb.green, rgb.blue) == (0, 128 / 255, 0)
    assert style.background_color is not None


def test_dark_theme_has_readable_foreground_and_background(monkeypatch):
    """Transfer Monokai's light base text and dark background together."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE', 'monokai')
    [(text, style)] = code_spans('()', 'python')
    assert text == '()'
    fg = style.foreground_color.color.rgb_color
    bg = style.background_color.color.rgb_color
    assert (fg.red, fg.green, fg.blue) == (248 / 255, 248 / 255, 242 / 255)
    assert (bg.red, bg.green, bg.blue) == (39 / 255, 40 / 255, 34 / 255)


def test_highlighting_can_be_disabled_without_losing_font(monkeypatch):
    """Keep the configured font while disabling all syntax-derived styles."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_HIGHLIGHTING', 'false')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_FONT_FAMILY', 'Courier New')
    [(text, style)] = code_spans('return "x"', 'python')
    assert text == 'return "x"'
    assert style.model_dump(by_alias=True, exclude_unset=True) == {
        'weightedFontFamily': {'fontFamily': 'Courier New'},
    }


@pytest.mark.parametrize('style', ['', 'not-a-real-theme'])
def test_unknown_theme_fails_configuration_validation(style, monkeypatch):
    """Catch a theme typo before any document insertion can happen."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE', style)
    with pytest.raises(ValidationError, match='Unknown Pygments style'):
        get_settings()


def test_file_and_environment_control_highlighting(monkeypatch, tmp_path):
    """Override JSON's theme with environment while retaining its switch."""
    path = tmp_path / 'style.json'
    path.write_text(
        '{"code_block_highlighting":false,"code_block_style":"friendly"}',
        encoding='utf-8',
    )
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', str(path))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE', 'monokai')
    assert get_settings().code_block_style == 'monokai'
    assert not get_settings().code_block_highlighting


@pytest.mark.parametrize('html', [False, True])
@pytest.mark.parametrize('newline_before', [False, True])
def test_highlight_ranges_respect_utf16_and_literal_whitespace(
    html, newline_before,
):
    """Color only the code despite emoji, paragraphs and trailing newlines."""
    code = '\ndef f():\n\t# 🦷 comment\n\treturn "🦷"  \n\n'
    block = (f'<pre><code class="language-python">{code}\n</code></pre>'
             if html else f'```python\n{code}\n```')
    requests = markdown_to_requests(
        f'Before🦷\n\n{block}\n\nAfter',
        start=10, newline_before=newline_before,
    )
    inserted = inserted_text_from_requests(requests)
    plain = 'Before🦷\n' + code + '\nAfter'
    expected = '\n' + plain if newline_before else plain + '\n'
    assert inserted == expected
    raw = inserted.encode('utf-16-le')
    styles = [r['updateTextStyle'] for r in requests if 'updateTextStyle' in r]
    assert len(styles) > 1
    left = len(expected[:expected.index(code)].encode('utf-16-le')) // 2
    right = left + len(code.encode('utf-16-le')) // 2
    covered = []
    for update in styles:
        a = update['range']['startIndex'] - 10
        b = update['range']['endIndex'] - 10
        assert left <= a < b <= right
        assert 'foregroundColor' in update['textStyle']
        assert all(flag in update['textStyle']
                   for flag in ('bold', 'italic', 'underline'))
        covered.append(raw[a * 2:b * 2].decode('utf-16-le'))
    assert ''.join(covered) == code


def test_transforming_lexer_falls_back_to_plain_source(monkeypatch):
    """Never apply token offsets when a specialised lexer rewrites input."""
    lexer = SimpleNamespace(
        get_tokens_unprocessed=lambda _: [(0, Token.Text, 'changed')],
    )
    monkeypatch.setattr(
        code_highlighting, 'get_lexer_by_name', lambda _: lexer,
    )
    [(text, style)] = code_spans('original', 'python')
    assert text == 'original'
    assert style.foreground_color is None
