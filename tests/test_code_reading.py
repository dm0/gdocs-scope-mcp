"""Verify code reconstruction without changing editable source coordinates."""

import json
from copy import deepcopy
from pathlib import Path

import mistune
import pytest
from pydantic import ValidationError

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.code_reading import block_marker, code_span
from gdocs_scope_mcp.md2requests import markdown_to_requests
from gdocs_scope_mcp.models import GoogleDocument
from gdocs_scope_mcp.settings import Settings, get_settings
from gdocs_scope_mcp.text_indices import utf16_length
from gdocs_scope_mcp.tool_errors import ToolFailureError

FONT = {'weightedFontFamily': {'fontFamily': 'Roboto Mono'}}
GREEN = {'foregroundColor': {'color': {'rgbColor': {
    'red': 24 / 255, 'green': 128 / 255, 'blue': 56 / 255,
}}}}


@pytest.fixture(autouse=True)
def code_settings(monkeypatch, tmp_path):
    """Keep read settings independent of user files and previous tests."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.delenv('GOOGLE_DOCS_MCP_CONFIG', raising=False)
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'false')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def code_document():
    """Build raw API paragraphs with exact UTF-16 text-run ranges."""
    def build(lines, *, style=None, paragraph_style=None, marked=False,
              language='python'):
        index = 1
        content = []
        for line in lines:
            runs = line if isinstance(line, list) else [(line, style or {})]
            start = index
            elements = []
            for text, run_style in runs:
                end = index + utf16_length(text)
                elements.append({
                    'startIndex': index, 'endIndex': end,
                    'textRun': {'content': text, 'textStyle': run_style},
                })
                index = end
            content.append({
                'startIndex': start, 'endIndex': index,
                'paragraph': {'elements': elements,
                              'paragraphStyle': paragraph_style or {}},
            })
        doc = {'documentId': 'example', 'revisionId': 'revision',
               'title': 'Code', 'body': {'content': content}}
        if marked:
            marker = block_marker(language, 1, max(2, index - 1))[
                'createNamedRange']
            doc['namedRanges'] = {marker['name']: {
                'namedRanges': [{'name': marker['name'],
                                 'ranges': [marker['range']]}],
            }}
        return doc
    return build


def render(doc):
    """Exercise the same hierarchy renderer used by docs_read."""
    tree = docs_edit._parse_document_tree(deepcopy(doc))
    return ''.join(section.subtree_markdown() for section in tree.sections)


def test_inline_runs_merge_without_emphasis_or_links(code_document):
    """Suppress wrappers only inside code, preserving neighboring prose."""
    doc = code_document([[
        ('Before ', {'bold': True}),
        ('x😀', {**FONT, **GREEN, 'bold': True}),
        (' <b> ', {**FONT, **GREEN, 'italic': True}),
        ('`y`', {**FONT, **GREEN, 'link': {'url': 'https://example.com'}}),
        (' after\n', {'italic': True}),
    ]])
    assert render(doc) == '<b>Before</b> `` x😀 <b> `y` `` <i>after</i>\n\n'
    typed = GoogleDocument.model_validate(deepcopy(doc))
    assert typed.to_markdown() == render(doc)


@pytest.mark.parametrize(('mode', 'style', 'detected'), [
    ('both', FONT, False), ('both', GREEN, False),
    ('both', {**FONT, **GREEN}, True),
    ('font', FONT, True), ('color', GREEN, True),
    ('font', GREEN, False), ('color', FONT, False),
])
def test_inline_matching_policy(code_document, monkeypatch, mode, style,
                                detected):
    """Require the configured signals rather than any incidental style."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_INLINE_CODE_MATCH', mode)
    markdown = render(code_document(['code\n'], style=style))
    assert ('`code`' in markdown) == detected


def test_inline_custom_fonts_colors_and_disabled(code_document, monkeypatch):
    """Use case-insensitive font/color settings and allow opting out."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_INLINE_CODE_FONTS',
                       '["consolas"]')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_INLINE_CODE_COLORS',
                       '["#000000"]')
    style = {'weightedFontFamily': {'fontFamily': 'Consolas'},
             'foregroundColor': {'color': {'rgbColor': {}}}}
    doc = code_document(['word\n'], style=style)
    assert render(doc) == '`word`\n\n'
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_INLINE_CODE', 'false')
    get_settings.cache_clear()
    assert render(doc) == 'word\n\n'


@pytest.mark.parametrize('text', [
    '`x`', 'a``b', ' edge ', ' ', '  ', '<b>😀</b>',
])
def test_inline_markdown_delimiters(text):
    """Round-trip literal spaces and backticks through a Markdown parser."""
    ast = mistune.create_markdown(renderer='ast')(code_span(text))
    assert ast[0]['children'][0]['type'] == 'codespan'
    assert ast[0]['children'][0]['raw'] == text


@pytest.mark.parametrize('lines', [
    ['first😀\n', '\n', '\tsecond  \n', '\n'],
    ['\n', '  <b>**literal**</b> ```\n', '\n'], ['\n'],
])
def test_marked_blocks_preserve_literal_content(code_document, lines):
    """Read raw code, including trailing blank lines, ignoring every style."""
    doc = code_document(lines, style={**FONT, **GREEN, 'bold': True,
                                     'italic': True, 'underline': True},
                        marked=True)
    expected = ''.join(lines)[:-1]
    markdown = render(doc)
    ast = mistune.create_markdown(renderer='ast')(markdown)
    assert ast[0]['type'] == 'block_code'
    assert ast[0]['attrs']['info'] == 'python'
    assert ast[0]['raw'] == expected + '\n'
    typed = GoogleDocument.model_validate(deepcopy(doc))
    assert typed.to_markdown() == markdown


@pytest.mark.parametrize('mutation', ['split', 'overlap', 'partial', 'unknown',
                                      'heading', 'object', 'gap', 'deleted'])
def test_invalid_markers_do_not_consume_prose(code_document, mutation):
    """Reject ambiguous ranges rather than swallowing or joining paragraphs."""
    doc = code_document(['code\n', 'next\n'], marked=True)
    named = next(iter(doc['namedRanges'].values()))['namedRanges'][0]
    if mutation == 'split':
        named['ranges'].append({'startIndex': 1, 'endIndex': 3})
    elif mutation == 'overlap':
        doc['namedRanges']['duplicate'] = {'namedRanges': [deepcopy(named)]}
    elif mutation == 'partial':
        named['ranges'][0]['endIndex'] -= 2
    elif mutation == 'unknown':
        named['name'] = named['name'].replace(':v1:', ':v999:')
    elif mutation == 'heading':
        doc['body']['content'][1]['paragraph']['paragraphStyle'] = {
            'headingId': 'heading', 'namedStyleType': 'HEADING_1',
        }
    elif mutation == 'object':
        doc['body']['content'][1]['paragraph']['elements'][0] = {
            'startIndex': 6, 'endIndex': 7,
            'horizontalRule': {'textStyle': {}},
        }
    elif mutation == 'gap':
        element = doc['body']['content'][1]['paragraph']['elements'][0]
        element['startIndex'] += 1
    elif mutation == 'deleted':
        named['ranges'] = []
    assert '```' not in render(doc)


def test_marker_does_not_absorb_following_paragraph(code_document):
    """A marker ending before its terminator leaves adjacent text outside."""
    doc = code_document(['first\n', 'next\n'], marked=True)
    named = next(iter(doc['namedRanges'].values()))['namedRanges'][0]
    named['ranges'][0]['endIndex'] = 6
    assert render(doc) == '```python\nfirst\n```\n\nnext\n\n'


def test_optional_block_heuristic_preserves_internal_blank_lines(
    code_document, monkeypatch,
):
    """Detect unmarked blocks when enabled, without guessing language."""
    doc = code_document(['first\n', '\n', '  second\n'], style=FONT,
                        paragraph_style={'lineSpacing': 100})
    assert '```' not in render(doc)
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    get_settings.cache_clear()
    assert render(doc) == '```\nfirst\n\n  second\n```\n\n'
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_REQUIRE_BACKGROUND',
                       'true')
    get_settings.cache_clear()
    assert '```' not in render(doc)


@pytest.mark.parametrize('mismatch', ['font', 'spacing', 'single', 'heading'])
def test_block_heuristic_rejects_weak_signals(code_document, monkeypatch,
                                            mismatch):
    """Do not turn isolated monospace prose into a block by default."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    style = FONT if mismatch != 'font' else {}
    lines = ['a\n'] if mismatch == 'single' else ['a\n', 'b\n']
    paragraph_style = {'lineSpacing': 100}
    if mismatch == 'spacing':
        paragraph_style = {}
    if mismatch == 'heading':
        paragraph_style['namedStyleType'] = 'HEADING_1'
    assert '```' not in render(code_document(
        lines, style=style, paragraph_style=paragraph_style,
    ))


@pytest.mark.parametrize('before', [True, False])
def test_marker_positions_after_list_tab_removal(before):
    """Build final block references after preceding nested-list indentation."""
    requests = markdown_to_requests(
        '- Parent\n  - Child😀\n\n```python\nx = 1\n```',
        start=1, newline_before=before,
    )
    marker = requests[-1]['createNamedRange']
    text = ''
    for request in requests:
        if 'insertText' in request:
            text += request['insertText']['text']
    final = text.replace('\t', '')
    left = marker['range']['startIndex'] - 1
    right = marker['range']['endIndex'] - 1
    marked_text = final.encode('utf-16-le')[left * 2:right * 2]
    assert marked_text.decode('utf-16-le') == 'x = 1'


def test_code_marker_write_is_revision_guarded(mock_docs):
    """Keep marker ranges and text in the same guarded atomic batch."""
    docs_edit.append('example', '```python\nx = 1\n```')
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert 'createNamedRange' in body['requests'][-1]


def test_named_ranges_are_enabled_by_default():
    """Keep language-preserving code markers enabled without configuration."""
    assert Settings().code_block_named_ranges is True


def test_disabled_named_ranges_are_not_created(mock_docs, monkeypatch):
    """Keep rich code styling while disabling only code metadata writes."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_NAMED_RANGES', 'false')
    docs_edit.append('example', '```python\nx = 1\n```')
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert not any('createNamedRange' in request for request in requests)
    assert any('updateTextStyle' in request for request in requests)


@pytest.mark.parametrize('malformed', [False, True])
def test_disabled_named_ranges_do_not_affect_reading(
    code_document, monkeypatch, malformed,
):
    """Ignore both valid and broken markers, allowing formatting heuristics."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_NAMED_RANGES', 'false')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    doc = code_document(['first\n', 'second\n'], style=FONT,
                        paragraph_style={'lineSpacing': 100}, marked=True)
    if malformed:
        named = next(iter(doc['namedRanges'].values()))['namedRanges'][0]
        named['ranges'].append({'startIndex': 1, 'endIndex': 4})
    assert render(doc) == '```\nfirst\nsecond\n```\n\n'
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'false')
    get_settings.cache_clear()
    assert render(doc) == 'first\n\nsecond\n\n'


def test_block_heuristic_is_enabled_by_default(monkeypatch):
    """Use the default policy requested for documents without code markers."""
    monkeypatch.delenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC')
    assert Settings().read_code_block_heuristic is True


def test_long_code_language_fails_before_writes(mock_docs):
    """Reject oversized metadata without creating partial text."""
    with pytest.raises(ToolFailureError):
        docs_edit.append('example', f'```{"x" * 300}\ncode\n```')
    mock_docs.batchUpdate.assert_not_called()


def test_empty_blocks_are_not_dropped():
    """Create a real empty paragraph and its semantic marker."""
    requests = markdown_to_requests('```python\n```', start=1)
    marker = requests[-1]['createNamedRange']
    assert marker['range'] == {'startIndex': 2, 'endIndex': 3}
    assert requests[0] == {'insertText': {
        'location': {'index': 1}, 'text': '\n',
    }}


def test_marked_language_wins_over_heuristic(code_document, monkeypatch):
    """Do not replace explicit language or absorb neighboring styled prose."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    doc = code_document(['first\n', 'second\n', 'next\n'], style=FONT,
                        paragraph_style={'lineSpacing': 100}, marked=True)
    named = next(iter(doc['namedRanges'].values()))['namedRanges'][0]
    named['ranges'][0]['endIndex'] = 13
    assert render(doc) == '```python\nfirst\nsecond\n```\n\nnext\n\n'


def test_heuristic_stops_at_different_background(code_document, monkeypatch):
    """Keep sequences with different paragraph shading separate."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    doc = code_document(['a\n', 'b\n', 'c\n'], style=FONT,
                        paragraph_style={'lineSpacing': 100})
    doc['body']['content'][-1]['paragraph']['paragraphStyle'] = {
        'lineSpacing': 100, 'shading': {'backgroundColor': {
            'color': {'rgbColor': {'red': 1}},
        }},
    }
    assert render(doc) == '```\na\nb\n```\n\nc\n\n'


def test_code_read_preserves_editable_utf16_positions(code_document,
                                                     mock_docs,
                                                     monkeypatch):
    """Rendered fence syntax never becomes part of source text mapping."""
    doc = code_document(['a😀 = 1\n', '\n', '  return 2\n'], marked=True)
    mock_docs.get.return_value.execute.side_effect = lambda: deepcopy(doc)
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    result = docs_edit.search_replace('example', 'return 2', 'return 3')
    expected_index = utf16_length('a😀 = 1\n\n  ') + 1
    assert result.ok
    assert result.at_index == expected_index
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[0]['insertText']['location']['index'] == expected_index


def test_heuristics_do_not_cross_table_cells(table_document, monkeypatch):
    """Adjacent monospaced cells cannot become a single code block."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    table = table_document['body']['content'][2]['table']
    for row in table['tableRows']:
        for cell in row['tableCells']:
            for paragraph in cell['content']:
                paragraph['paragraph']['paragraphStyle']['lineSpacing'] = 100
                for run in paragraph['paragraph']['elements']:
                    run['textRun']['textStyle'] = FONT
    markup = render(table_document)
    expected_fences = 2
    assert markup.count('```') == expected_fences
    assert 'Second\n```' not in markup


def test_custom_block_policy_and_json_settings(code_document, monkeypatch):
    """Combine a custom font, spacing, minimum length and required fill."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_FONTS',
                       '["Consolas"]')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_LINE_SPACING', '1.5')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_MIN_LINES', '1')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_REQUIRE_BACKGROUND',
                       'true')
    doc = code_document(['custom\n'], style={
        'weightedFontFamily': {'fontFamily': 'Consolas'},
    }, paragraph_style={'lineSpacing': 150, 'shading': {'backgroundColor': {
        'color': {'rgbColor': {'red': 1}},
    }}})
    assert render(doc) == '```\ncustom\n```\n\n'


@pytest.fixture
def native_code_document():
    """Load the normalized API capture from a UI-created Python block."""
    path = Path(__file__).parent / 'fixtures/native_code.json'
    return json.loads(path.read_text())


def test_native_ui_code_without_spacing(native_code_document, monkeypatch):
    """Require observed delimiter pairs without inventing a language."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    expected = ('```\nUI_CODE_20261027 = 1\n\n'
                '    return UI_CODE_20261027\n\n```\n\n')
    assert render(native_code_document) == expected
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'false')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_NATIVE_CODE_BLOCKS', 'false')
    get_settings.cache_clear()
    assert '```' not in render(native_code_document)


@pytest.mark.parametrize('heuristic', [True, False])
def test_native_switch_is_independent(native_code_document, monkeypatch,
                                      heuristic):
    """Keep native blocks plain even when generic heuristics are enabled."""
    assert Settings().read_native_code_blocks is True
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC',
                       str(heuristic))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_NATIVE_CODE_BLOCKS', 'false')
    for item in native_code_document['body']['content']:
        item['paragraph']['paragraphStyle']['lineSpacing'] = 100
        for element in item['paragraph']['elements']:
            element['textRun']['textStyle'].update({**FONT, **GREEN})
    markup = render(native_code_document)
    assert '```' not in markup
    assert '`UI_CODE' not in markup
    assert '\ue907' not in markup
    assert 'UI_CODE_20261027 = 1' in markup
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_NATIVE_CODE_BLOCKS', 'true')
    get_settings.cache_clear()
    assert markup != render(native_code_document)
    assert render(native_code_document).startswith('```\n')


@pytest.mark.parametrize('change', ['missing_end', 'body_font', 'heading',
                                   'bare_character'])
def test_native_delimiters_alone_are_not_code(native_code_document,
                                             monkeypatch, change):
    """Reject private-use text and incomplete UI blocks."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
    content = native_code_document['body']['content']
    if change == 'missing_end':
        content.pop()
    elif change == 'body_font':
        content[2]['paragraph']['elements'][1]['textRun']['textStyle'] = {}
    elif change == 'heading':
        style = content[2]['paragraph']['paragraphStyle']
        style['namedStyleType'] = 'HEADING_1'
    else:
        run = content[0]['paragraph']['elements'][0]['textRun']
        run['content'] = '\ue907x'
    assert '```' not in render(native_code_document)


@pytest.mark.parametrize('kwargs', [
    {'read_inline_code_match': 'any'},
    {'read_inline_code_fonts': ['']},
    {'read_inline_code_colors': ['green']},
    {'read_code_block_min_lines': 0},
    {'read_code_block_line_spacing': float('inf')},
])
def test_read_settings_validation(kwargs):
    """Reject invalid heuristic policies before serving tools."""
    with pytest.raises(ValidationError):
        Settings(**kwargs)
