"""Verify syntax colors, lossless code text and native UTF-16 style ranges."""


from types import SimpleNamespace
from typing import ClassVar

import pytest
from pydantic import ValidationError
from pygments.style import Style
from pygments.token import Token

from gdocs_scope_mcp import code_highlighting
from gdocs_scope_mcp.code_highlighting import code_shading, code_spans
from gdocs_scope_mcp.rich_text.compiler import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.settings import get_settings

CUSTOM_LINE_SPACING = 1.25
SINGLE_LINE_SPACING_PERCENT = 100


@pytest.fixture(autouse=True)
def clean_config(monkeypatch, tmp_path):
    """Isolate cached settings and avoid reading any user config."""
    for name in ('CONFIG', 'CODE_FONT_FAMILY', 'INLINE_CODE_COLOR',
                 'CODE_BLOCK_HIGHLIGHTING', 'CODE_BLOCK_STYLE',
                 'CODE_BLOCK_LINE_SPACING', 'CODE_BLOCK_THEME_BACKGROUND'):
        monkeypatch.delenv('GDOCS_SCOPE_MCP_' + name, raising=False)
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
    assert style.background_color is None


def test_dark_theme_has_readable_foreground_and_background(monkeypatch):
    """Transfer Monokai's light base text and dark background together."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_STYLE', 'monokai')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND', 'true')
    [(text, style)] = code_spans('()', 'python')
    assert text == '()'
    fg = style.foreground_color.color.rgb_color
    assert style.background_color is None
    bg = code_shading([style]).background_color.color.rgb_color
    assert (fg.red, fg.green, fg.blue) == (248 / 255, 248 / 255, 242 / 255)
    assert (bg.red, bg.green, bg.blue) == (39 / 255, 40 / 255, 34 / 255)


def test_highlighting_can_be_disabled_without_losing_font(monkeypatch):
    """Keep the configured font while disabling all syntax-derived styles."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_HIGHLIGHTING', 'false')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_FONT_FAMILY', 'Courier New')
    [(text, style)] = code_spans('return "x"', 'python')
    assert text == 'return "x"'
    assert style.model_dump(by_alias=True, exclude_unset=True) == {
        'weightedFontFamily': {'fontFamily': 'Courier New'},
    }


@pytest.mark.parametrize('style', ['', 'not-a-real-theme'])
def test_unknown_theme_fails_configuration_validation(style, monkeypatch):
    """Catch a theme typo before any document insertion can happen."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_STYLE', style)
    with pytest.raises(ValidationError, match='Unknown Pygments style'):
        get_settings()


def test_file_and_environment_control_highlighting(monkeypatch, tmp_path):
    """Override JSON's theme with environment while retaining its switch."""
    path = tmp_path / 'style.json'
    path.write_text(
        '{"code_block_highlighting":false,"code_block_style":"friendly"}',
        encoding='utf-8',
    )
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CONFIG', str(path))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_STYLE', 'monokai')
    assert get_settings().code_block_style == 'monokai'
    assert not get_settings().code_block_highlighting


def test_layout_defaults():
    """Use single-spaced code and omit theme backgrounds by default."""
    assert get_settings().code_block_line_spacing == 1.0
    assert not get_settings().code_block_theme_background


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', '-inf', 'bad'])
def test_line_spacing_must_be_positive_and_finite(value, monkeypatch):
    """Reject invalid spacing before issuing document updates."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING', value)
    with pytest.raises(ValidationError):
        get_settings()


def test_layout_file_values_and_environment_override(monkeypatch, tmp_path):
    """Read layout values from JSON and override the spacing independently."""
    path = tmp_path / 'layout.json'
    path.write_text(
        '{"code_block_line_spacing":1.5,"code_block_theme_background":true}',
        encoding='utf-8',
    )
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CONFIG', str(path))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING', '1.25')
    assert get_settings().code_block_line_spacing == CUSTOM_LINE_SPACING
    assert get_settings().code_block_theme_background


@pytest.mark.parametrize('background', [False, True])
def test_background_switch_reaches_native_styles(background, monkeypatch):
    """Toggle background without suppressing colors or clearing emphasis."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND',
                       str(background).lower())
    requests = markdown_to_requests('```python\nreturn (1)\n```', start=1)
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if 'updateTextStyle' in r]
    assert styles
    assert all('backgroundColor' not in s for s in styles)
    paragraphs = [r['updateParagraphStyle'] for r in requests
                  if 'updateParagraphStyle' in r]
    assert len(paragraphs) == 1
    assert ('shading' in paragraphs[0]['paragraphStyle']) == background
    assert all('foregroundColor' in s for s in styles)
    assert any(s['bold'] for s in styles)
    assert any(not s['bold'] for s in styles)


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('html', [False, True])
def test_paragraph_shading_includes_empty_lines_and_stays_within_code(
    monkeypatch, newline_before, html,
):
    """Fill the whole block range, including leading/trailing blank lines."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND', 'true')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_STYLE', 'monokai')
    code = '\nfirst🦷\n\nlast\n\n'
    block = (f'<pre><code class="language-python">{code}\n</code></pre>'
             if html else f'```python\n{code}\n```')
    requests = markdown_to_requests(
        f'Before\n\n{block}\n\nAfter', start=10,
        newline_before=newline_before,
    )
    shaded = [(i, r['updateParagraphStyle'])
              for i, r in enumerate(requests)
              if 'shading' in r.get('updateParagraphStyle', {}).get(
                  'paragraphStyle', {})]
    assert len(shaded) == 1
    index, update = shaded[0]
    inserted = inserted_text_from_requests(requests)
    start = len(inserted[:inserted.index(code)].encode('utf-16-le')) // 2
    end = len(inserted[:inserted.index('After')].encode('utf-16-le')) // 2
    assert update['range'] == {'startIndex': 10 + start, 'endIndex': 10 + end}
    assert 'shading' in update['fields'].split(',')
    assert update['paragraphStyle']['shading'] == {'backgroundColor': {
        'color': {'rgbColor': {
            'red': 39 / 255, 'green': 40 / 255, 'blue': 34 / 255,
        }},
    }}
    assert all('insertText' not in r and 'insertInlineImage' not in r
               for r in requests[index:])


@pytest.mark.parametrize(('markup', 'highlighting'), [
    ('```unknown_language\nplain\n```', True),
    ('```\nplain\n```', True),
    ('`inline`', True),
    ('```python\nreturn\n```', False),
])
def test_no_shading_without_highlighted_block(
    monkeypatch, markup, highlighting,
):
    """Keep unsupported/unlabelled blocks and inline code unshaded."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND', 'true')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_HIGHLIGHTING',
                       str(highlighting).lower())
    requests = markdown_to_requests(markup, start=1)
    assert all('shading' not in r.get('updateParagraphStyle', {}).get(
        'paragraphStyle', {}) for r in requests)


@pytest.mark.parametrize('background', [False, True])
def test_token_background_is_separate_from_paragraph_fill(
    monkeypatch, background,
):
    """Preserve a token-specific overlay while using the theme's base fill."""
    class ProbeStyle(Style):
        background_color = '#272822'
        styles: ClassVar[dict] = {Token: '#abcdef bg:#123456'}

    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND',
                       str(background).lower())
    monkeypatch.setattr(code_highlighting, 'get_style_by_name',
                        lambda _: ProbeStyle)
    [(text, style)] = code_spans('value', 'python')
    assert text == 'value'
    shading = code_shading([style])
    if background:
        color = style.background_color.color.rgb_color
        assert (color.red, color.green, color.blue) == (
            18 / 255, 52 / 255, 86 / 255,
        )
        color = shading.background_color.color.rgb_color
        assert (color.red, color.green, color.blue) == (
            39 / 255, 40 / 255, 34 / 255,
        )
    else:
        assert style.background_color is None
        assert shading is None


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('block', [
    '```python\nfirst🦷\n\nsecond\n```',
    '```unknown_language\nfirst🦷\n\nsecond\n```',
    '    first🦷\n\n    second',
    '<pre><code>first🦷\n\nsecond\n</code></pre>',
])
def test_spacing_only_targets_code_after_all_insertions(
    block, newline_before, monkeypatch,
):
    """Set percent-based spacing without leaking it to surrounding prose."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING', '1.25')
    requests = markdown_to_requests(
        'Before🦷\n\n' + block + '\n\nAfter `inline`', start=10,
        newline_before=newline_before,
    )
    spacing = [(i, r['updateParagraphStyle'])
               for i, r in enumerate(requests)
               if 'lineSpacing' in r.get('updateParagraphStyle', {}).get(
                   'paragraphStyle', {})]
    assert len(spacing) == 1
    index, update = spacing[0]
    assert update['paragraphStyle']['lineSpacing'] == CUSTOM_LINE_SPACING * 100
    assert 'lineSpacing' in update['fields'].split(',')
    inserted = inserted_text_from_requests(requests)
    raw = inserted.encode('utf-16-le')
    a, b = (update['range'][key] - 10
            for key in ('startIndex', 'endIndex'))
    assert raw[a * 2:b * 2].decode('utf-16-le') == 'first🦷\n\nsecond'
    assert all('insertText' not in r and 'insertInlineImage' not in r
               for r in requests[index:])


@pytest.mark.parametrize('newline_before', [False, True])
def test_spacing_includes_trailing_empty_code_paragraphs(newline_before):
    """Keep trailing blank lines single-spaced without formatting prose."""
    requests = markdown_to_requests(
        'Before\n\n```python\nfirst\n\n\n```\n\nAfter', start=10,
        newline_before=newline_before,
    )
    inserted = inserted_text_from_requests(requests)
    spacing = [r['updateParagraphStyle'] for r in requests
               if 'lineSpacing' in r.get('updateParagraphStyle', {}).get(
                   'paragraphStyle', {})]
    assert len(spacing) == 1
    update = spacing[0]
    assert update['range'] == {
        'startIndex': 10 + inserted.index('first'),
        'endIndex': 10 + inserted.index('After'),
    }
    assert (
        update['paragraphStyle']['lineSpacing'] == SINGLE_LINE_SPACING_PERCENT
    )


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
