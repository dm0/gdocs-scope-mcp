"""Verify native list reads by parsing and reinserting their structure."""

# Native fixture depths and offsets are independent expectations.
# ruff: noqa: PLR2004
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from gdocs_scope_mcp.documents import editing, parsing, reading
from gdocs_scope_mcp.documents.native_models import GoogleDocument
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests
from gdocs_scope_mcp.rich_text.parsing import html_to_gpars, markdown_to_html
from gdocs_scope_mcp.settings import get_settings

from .test_advanced_list_contracts import ListReplay

ORDERED = 'NUMBERED_DECIMAL_ALPHA_ROMAN'
UNORDERED = 'BULLET_DISC_CIRCLE_SQUARE'
ITEMS = [
    ('Parent😀', 0, 'first'), ('Child🦷', 1, 'first'),
    ('Grandchild [literal]*', 2, 'first'), ('Child sibling', 1, 'first'),
    ('Parent sibling', 0, 'first'), ('Independent', 0, 'second'),
    ('Independent child', 1, 'second'), ('Independent sibling', 0, 'second'),
]


def native_document(items, *, ordered):
    """Build UTF-16 runs independently of rendering and compilation."""
    content = []
    index = 1
    rows = [('Before', None, None), ('Scope😀', None, None), *items,
            ('After', None, None)]
    for text, depth, identity in rows:
        style = {'namedStyleType': 'NORMAL_TEXT'}
        if text == 'Scope😀':
            style = {'namedStyleType': 'HEADING_1', 'headingId': 'scope'}
        text_style = ({'bold': True} if text == 'Parent😀' else
                      {'italic': True} if text == 'Child🦷' else
                      {'link': {'url': 'https://example.com/a?x=1&y=2'}}
                      if text == 'Grandchild [literal]*' else {})
        end = index + len((text + '\n').encode('utf-16-le')) // 2
        paragraph = {'paragraphStyle': style, 'elements': [{
            'startIndex': index, 'endIndex': end,
            'textRun': {'content': text + '\n', 'textStyle': text_style},
        }]}
        if identity is not None:
            paragraph['bullet'] = {'listId': identity, 'nestingLevel': depth,
                                   'textStyle': {}}
        content.append({'startIndex': index, 'endIndex': end,
                        'paragraph': paragraph})
        index = end
    levels = [{'glyphType': 'DECIMAL'} if ordered else {'glyphSymbol': '●'}
              for _ in range(9)]
    return {'documentId': 'example', 'title': 'Native lists',
            'revisionId': 'revision', 'body': {'content': content},
            'lists': {key: {'listProperties': {'nestingLevels': levels}}
                      for _, _, key in items if key is not None}}


@pytest.fixture(params=[False, True], ids=['unordered', 'ordered'])
def list_document(request, simple_document):
    """Supply adjacent lists with surrounding heading/source text."""
    document = native_document(ITEMS, ordered=request.param)
    simple_document.clear()
    simple_document.update(document)
    return simple_document, request.param


@pytest.mark.parametrize('newline_before', [False, True])
def test_native_list_read_parser_and_request_roundtrip(
    list_document, newline_before,
):
    """Observe native depth and group boundaries rather than pretty spaces."""
    source, ordered = list_document
    before = deepcopy(source)
    native = GoogleDocument.model_validate(deepcopy(source))
    markup = native.to_markdown()
    assert native.to_markdown() == markup
    assert parsing.parse_document_tree(source).tree_markdown() == markup
    assert source == before
    parsed = html_to_gpars(markdown_to_html(markup))
    paragraphs = [p for p in parsed if getattr(p, 'bullet_preset', None)]
    assert [p.nesting_level for p in paragraphs] == [r[1] for r in ITEMS]
    assert all(p.bullet_preset == (ORDERED if ordered else UNORDERED)
               for p in paragraphs)
    assert paragraphs[0].list_key == paragraphs[4].list_key
    assert paragraphs[0].list_key != paragraphs[5].list_key
    requests = markdown_to_requests(markup, start=3,
                                    newline_before=newline_before)
    replay = ListReplay('😀\n\nSuffix\n')
    replay.apply(requests)
    rows = [r for r in replay.rows() if r['bullet']]
    assert [r['text'] for r in rows] == [r[0] for r in ITEMS]
    assert [r['bullet']['level'] for r in rows] == [r[1] for r in ITEMS]
    assert rows[0]['bullet']['id'] == rows[4]['bullet']['id']
    assert rows[0]['bullet']['id'] != rows[5]['bullet']['id']
    assert [rows[i]['number'] for i in [0, 4, 5, 7]] == [1, 2, 1, 2]
    assert replay.styled_text('bold') == 'Parent😀'
    assert replay.styled_text('italic') == 'Child🦷'
    assert replay.styled_text('link') == 'Grandchild [literal]*'
    assert 'Before\nScope😀\nParent😀' in replay.text
    assert replay.text.endswith('After' + ('\n' if not newline_before else '')
                                + '\nSuffix\n')


def test_heading_scoped_reads_keep_original_source_targets(
    mock_docs, list_document,
):
    """Render list wrappers without allowing them to enter edit coordinates."""
    source, _ = list_document
    response = reading.read('example', ['scope'])
    assert response.selected_headings == ['scope']
    markup = response.sections[0].markdown
    assert '<a id="scope"></a>' in markup
    assert 'Before' not in markup
    html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
    assert len(html.find_all(['ul', 'ol'], recursive=False)) == 2
    tree = parsing.parse_document_tree(source)
    found = tree.find_first('Child🦷')
    paragraph = next(p for p in source['body']['content']
                     if p['startIndex'] == found.paragraph.start_index)
    assert found.paragraph.text_map == [
        (0, paragraph['startIndex'], 'Child🦷\n'),
    ]
    result = editing.search_replace('example', '🦷', 'X', heading_id='scope')
    assert result.ok
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    deleted = next(r['deleteContentRange']['range'] for r in requests
                   if 'deleteContentRange' in r)
    inserted = next(r['insertText']['location']['index'] for r in requests
                    if 'insertText' in r)
    assert inserted == paragraph['startIndex'] + 5
    # The replacement is inserted before deleting the original two-unit emoji.
    assert deleted == {'startIndex': paragraph['startIndex'] + 6,
                       'endIndex': paragraph['startIndex'] + 8}


@pytest.mark.parametrize('ordered', [False, True])
def test_adjacent_marker_kind_changes_stay_independent(ordered):
    """Keep adjacent root boundaries even when marker types change."""
    source = native_document(ITEMS, ordered=ordered)
    source['lists']['second']['listProperties']['nestingLevels'] = [
        {'glyphSymbol': '●'} if ordered else {'glyphType': 'DECIMAL'}
        for _ in range(9)
    ]
    markup = parsing.parse_document_tree(source).tree_markdown()
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert [p.nesting_level for p in parsed] == [r[1] for r in ITEMS]
    parent, other = (ORDERED, UNORDERED) if ordered else (UNORDERED, ORDERED)
    assert [p.bullet_preset for p in parsed] == [parent] * 5 + [other] * 3
    assert parsed[4].list_key != parsed[5].list_key


@pytest.mark.parametrize('force_html', [False, True])
def test_inline_code_and_soft_breaks_survive_both_formats(
    monkeypatch, force_html,
):
    """Use code spans in Markdown and code elements inside HTML blocks."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_READ_INLINE_CODE_MATCH', 'font')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_READ_INLINE_CODE_FONTS',
                       '["Fixture Mono"]')
    get_settings.cache_clear()
    try:
        items = [
            ('x😀 <b> & `code`', 0, 'first'),
            ('Child\u000bsoft', 1, 'first'),
        ]
        if force_html:
            items.append(('Independent', 0, 'second'))
        source = native_document(items, ordered=False)
        parent = source['body']['content'][2]['paragraph']
        parent['elements'][0]['textRun']['textStyle'] = {
            'weightedFontFamily': {'fontFamily': 'Fixture Mono'},
        }
        markup = parsing.parse_document_tree(source).tree_markdown()
        assert ('<ul>' in markup) is force_html
        html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
        assert html.code.get_text() == 'x😀 <b> & `code`'
        assert html.find('br') is not None
        requests = markdown_to_requests(markup, start=1)
        replay = ListReplay('\0\nSuffix\n')
        replay.apply(requests)
        assert replay.styled_text('weightedFontFamily') == 'x😀 <b> & `code`'
        assert 'Child\u000bsoft' in replay.text
        assert [r['bullet']['level'] for r in replay.rows()
                if r['bullet']] == [0, 1] + ([0] if force_html else [])
    finally:
        get_settings.cache_clear()


def test_plain_paragraphs_end_lists_without_swallowing_prose():
    """Keep separate HTML groups and do not guess unmarked item membership."""
    source = native_document([
        ('First', 0, 'first'), ('Unmarked prose', None, None),
        ('Second', 0, 'first'),
    ], ordered=True)
    markup = parsing.parse_document_tree(source).tree_markdown()
    html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
    assert [li.get_text() for li in html.find_all('li')] == ['First', 'Second']
    assert html.find(string='Unmarked prose').find_parent('li') is None
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert parsed[0].list_key != parsed[1].list_key


def test_orphan_depths_do_not_invent_empty_parent_items():
    """Normalize a fragment's missing ancestors instead of creating items."""
    source = native_document([
        ('Orphan', 2, 'first'), ('Child', 3, 'first'),
    ], ordered=False)
    markup = parsing.parse_document_tree(source).tree_markdown()
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert len(parsed) == 2
    assert [p.nesting_level for p in parsed] == [0, 1]


def test_heading_boundaries_close_list_fragments_before_selection():
    """Each selected section must contain complete list markup."""
    source = native_document(ITEMS, ordered=False)
    source['body']['content'][-1]['paragraph']['paragraphStyle'] = {
        'namedStyleType': 'HEADING_1', 'headingId': 'tail',
    }
    tree = parsing.parse_document_tree(source)
    scope = tree.headings['scope'].markdown
    tail = tree.headings['tail'].markdown
    assert scope.endswith('</li></ul>\n\n')
    assert tail.startswith('### <a id="tail"></a>After\n\n')
    html = BeautifulSoup(markdown_to_html(scope), 'html.parser')
    assert len(html.find_all('ul', recursive=False)) == 2
    assert html.find('h3').find_parent('li') is None


def test_table_cells_keep_independent_list_frames():
    """A native list ID reused in two cells must not join their HTML frames."""
    source = native_document([
        ('Cell parent', 0, 'first'), ('Cell child', 1, 'first'),
    ], ordered=False)
    first = source['body']['content'][2:-1]
    second = deepcopy(first)
    for paragraph in second:
        for key in ['startIndex', 'endIndex']:
            paragraph[key] += 200
        for element in paragraph['paragraph']['elements']:
            element['startIndex'] += 200
            element['endIndex'] += 200
    source['body']['content'] = [{
        'startIndex': 1, 'endIndex': 500,
        'table': {'rows': 1, 'columns': 2, 'tableRows': [{
            'startIndex': 2, 'endIndex': 499, 'tableCells': [
                {'startIndex': 3, 'endIndex': 199, 'content': first},
                {'startIndex': 200, 'endIndex': 498, 'content': second},
            ],
        }]},
    }]
    html = BeautifulSoup(GoogleDocument.model_validate(
        deepcopy(source),
    ).to_markdown(), 'html.parser')
    assert len(html.find_all('td')) == 2
    for cell in html.find_all('td'):
        assert len(cell.find_all('ul', recursive=False)) == 1
        assert len(cell.find_all('li')) == 2
        assert cell.ul.li.ul.li.get_text() == 'Cell child'


@pytest.mark.parametrize('ordered', [False, True])
def test_unambiguous_nested_lists_use_markdown(ordered):
    """Avoid list HTML when Markdown can retain all groups and ancestors."""
    source = native_document(ITEMS[:5], ordered=ordered)
    markup = parsing.parse_document_tree(source).tree_markdown()
    assert '<ol>' not in markup and '<ul>' not in markup
    marker = '1.' if ordered else '-'
    assert f'{marker} <b>Parent😀</b>\n' in markup
    assert f'    {marker} <i>Child🦷</i>\n' in markup
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert [p.nesting_level for p in parsed] == [0, 1, 2, 1, 0]
    assert len({p.list_key for p in parsed}) == 1


@pytest.mark.parametrize('ordered', [False, True])
def test_marker_kind_changes_do_not_force_html(ordered):
    """Let Markdown express adjacent groups of different marker kinds."""
    source = native_document(ITEMS, ordered=ordered)
    source['lists']['second']['listProperties']['nestingLevels'] = [
        {'glyphSymbol': '●'} if ordered else {'glyphType': 'DECIMAL'}
        for _ in range(9)
    ]
    markup = parsing.parse_document_tree(source).tree_markdown()
    assert '<ol>' not in markup and '<ul>' not in markup
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert [p.nesting_level for p in parsed] == [r[1] for r in ITEMS]
    assert parsed[0].list_key != parsed[-1].list_key


@pytest.mark.parametrize('ordered', [False, True])
def test_blank_native_paragraphs_do_not_merge_independent_lists(ordered):
    """Blank lines alone cannot distinguish two Markdown lists of one kind."""
    source = native_document([
        ('First', 0, 'first'), ('', None, None), ('Second', 0, 'second'),
    ], ordered=ordered)
    markup = parsing.parse_document_tree(source).tree_markdown()
    tag = 'ol' if ordered else 'ul'
    assert markup.count(f'<{tag}>') == 2
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert len(parsed) == 2
    assert parsed[0].list_key != parsed[1].list_key


def test_html_fallback_is_local_to_the_ambiguous_run():
    """Keep Markdown around a run requiring explicit independent groups."""
    source = native_document([
        ('Simple first', 0, 'simple'), ('Separator', None, None),
        ('Complex first', 0, 'first'), ('Complex second', 0, 'second'),
        ('Another separator', None, None), ('Simple last', 0, 'last'),
    ], ordered=False)
    markup = parsing.parse_document_tree(source).tree_markdown()
    assert '- Simple first\n\n' in markup
    assert '- Simple last\n\n' in markup
    assert '<ul><li>Complex first</li></ul><ul><li>Complex second' in markup


@pytest.mark.parametrize('ordered', [False, True])
def test_mixed_nesting_uses_markdown_when_unambiguous(ordered):
    """A change in marker kind does not by itself require HTML lists."""
    items = [
        (text, depth, 'child' if depth == 1 else identity)
        for text, depth, identity in ITEMS[:5]
    ]
    source = native_document(items, ordered=ordered)
    source['lists']['child']['listProperties']['nestingLevels'] = [
        {'glyphSymbol': '●'} if ordered else {'glyphType': 'DECIMAL'}
        for _ in range(9)
    ]
    markup = parsing.parse_document_tree(source).tree_markdown()
    assert '<ul>' not in markup and '<ol>' not in markup
    parsed = [p for p in html_to_gpars(markdown_to_html(markup))
              if p.bullet_preset]
    assert [p.nesting_level for p in parsed] == [0, 1, 2, 1, 0]
    parent, child = (ORDERED, UNORDERED) if ordered else (UNORDERED, ORDERED)
    assert [p.bullet_preset for p in parsed] == [
        parent, child, parent, child, parent,
    ]


def test_markdown_list_after_aligned_html_keeps_its_block_boundary():
    """A Markdown list must start outside the preceding raw HTML block."""
    source = native_document([
        ('Aligned before', None, None), ('Simple', 0, 'first'),
    ], ordered=False)
    source['body']['content'][2]['paragraph']['paragraphStyle'][
        'alignment'] = 'CENTER'
    markup = parsing.parse_document_tree(source).tree_markdown()
    assert '</p>\n\n- Simple\n\n' in markup
    html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
    assert html.ul.li.get_text() == 'Simple'
    assert html.ul.find_parent('p') is None


def test_markdown_list_after_html_table_keeps_its_block_boundary():
    """End a table's raw HTML block before starting compact list markup."""
    source = native_document([('Simple', 0, 'first')], ordered=False)
    source['body']['content'] = [{
        'startIndex': 1, 'endIndex': 10,
        'table': {'rows': 1, 'columns': 1, 'tableRows': [{
            'startIndex': 2, 'endIndex': 9, 'tableCells': [{
                'startIndex': 3, 'endIndex': 8, 'content': [{
                    'startIndex': 4, 'endIndex': 7,
                    'paragraph': {'paragraphStyle': {}, 'elements': [{
                        'startIndex': 4, 'endIndex': 7,
                        'textRun': {'content': 'X\n', 'textStyle': {}},
                    }]},
                }],
            }],
        }]},
    }, {
        'startIndex': 11, 'endIndex': 18,
        'paragraph': {'paragraphStyle': {}, 'elements': [{
            'startIndex': 11, 'endIndex': 18,
            'textRun': {'content': 'Simple\n', 'textStyle': {}},
        }], 'bullet': {'listId': 'first', 'textStyle': {}}},
    }]
    markup = GoogleDocument.model_validate(source).to_markdown()
    assert '</table>\n\n- Simple\n\n' in markup
    html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
    assert html.ul.li.get_text() == 'Simple'
    assert html.ul.find_parent('table') is None
