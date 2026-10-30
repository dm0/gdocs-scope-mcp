"""Observe mixed lists independently of the compiler's temporary indices."""

# Fixture coordinates, counts and depths are independent expectations.
# ruff: noqa: PLR2004
import asyncio

import pytest
from bs4 import BeautifulSoup
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.rich_text.compiler import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.rich_text.parsing import markdown_to_html
from gdocs_scope_mcp.rich_text.plans import TableInsertionPlan

from .test_advanced_list_contracts import ListReplay

ORDERED = 'NUMBERED_DECIMAL_ALPHA_ROMAN'
UNORDERED = 'BULLET_DISC_CIRCLE_SQUARE'
LINES = [
    'Before', 'Parent🦷', 'More linked.', 'Child🦷', 'Child continued',
    'Grandchild', 'Grandchild next', 'Child after grandchild', 'Child next',
    'Parent after child', 'Next parent', 'Between', 'Other root',
    'Other child', 'Other next', 'After',
]


@pytest.fixture(params=[False, True],
                ids=['unordered-parent', 'ordered-parent'])
def mixed_source(request):
    """Build both source formats with alternating levels and continuations."""
    ordered = request.param
    parent, second, child = ('1.', '2.', '-') if ordered else ('-', '-', '1.')
    parent_indent = '   ' if ordered else '  '
    child_indent = parent_indent + ('  ' if ordered else '   ')
    markdown = (
        f'Before\n\n{parent} **Parent🦷**\n\n'
        f'{parent_indent}More [linked](https://example.com).\n\n'
        f'{parent_indent}{child} *Child🦷*\n\n'
        f'{child_indent}Child continued\n\n'
        f'{child_indent}{parent} Grandchild\n'
        f'{child_indent}{second} Grandchild next\n\n'
        f'{child_indent}Child after grandchild\n\n'
        f'{parent_indent}{child} Child next\n\n'
        f'{parent_indent}Parent after child\n\n'
        f'{second} Next parent\n\nBetween\n\n'
        f'{child} Other root\n{("  " if ordered else "   ")}'
        f'{parent} Other child\n{child} Other next\n\nAfter'
    )
    return markdown, ordered


@pytest.fixture(params=['markdown', 'html'])
def mixed_input(request, mixed_source):
    """Use equivalent Markdown and HTML, verifying fixture tree semantics."""
    markdown, ordered = mixed_source
    html = markdown_to_html(markdown)
    root = BeautifulSoup(html, 'html.parser').find('ol' if ordered else 'ul')
    child = root.find('ul' if ordered else 'ol')
    assert child is not None
    assert child.find('ol' if ordered else 'ul') is not None
    assert len(root.find_all('li', recursive=False)) == 2
    return (markdown if request.param == 'markdown' else html), ordered


def assert_mixed(replay, ordered):
    """Check native kinds, identities, numbering and style boundaries."""
    rows = {r['text']: r for r in replay.rows() if r['text'] in LINES}
    assert list(rows) == LINES
    parent = ORDERED if ordered else UNORDERED
    child = UNORDERED if ordered else ORDERED
    for names, level, preset in [
        (['Parent🦷', 'Next parent'], 0, parent),
        (['Child🦷', 'Child next'], 1, child),
        (['Grandchild', 'Grandchild next'], 2, parent),
        (['Other root', 'Other next'], 0, child),
        (['Other child'], 1, parent),
    ]:
        bullets = [rows[name]['bullet'] for name in names]
        assert all(b and b['level'] == level and b['preset'] == preset
                   for b in bullets)
        assert len({b['id'] for b in bullets}) == 1
        assert [rows[name]['number'] for name in names] == list(
            range(1, len(names) + 1),
        )
    assert (rows['Parent🦷']['bullet']['id']
            != rows['Grandchild']['bullet']['id'])
    for name, depth in [('More linked.', 0), ('Child continued', 1),
                        ('Child after grandchild', 1),
                        ('Parent after child', 0)]:
        assert rows[name]['bullet'] is None
        style = rows[name]['style']
        assert style['indentStart'] == style['indentFirstLine']
        assert style['indentStart']['magnitude'] == 36 * (depth + 1)
    assert all(rows[n]['bullet'] is None
               for n in ['Before', 'Between', 'After'])
    assert replay.styled_text('bold') == 'Parent🦷'
    assert replay.styled_text('italic') == 'Child🦷'
    assert replay.styled_text('link') == 'linked'


@pytest.mark.parametrize('newline_before', [False, True])
def test_mixed_requests_preserve_text_and_native_membership(
    mixed_input, newline_before,
):
    """Rebase nested replacements and preserve untouched list neighbours."""
    source, ordered = mixed_input
    prefix, suffix = 'Prefix 😀\n', '\nSuffix\n'
    start = len(prefix.encode('utf-16-le')) // 2
    requests = markdown_to_requests(source, start=start,
                                    newline_before=newline_before)
    replay = ListReplay(prefix + suffix)
    neighbour = {'id': 0, 'level': 0, 'preset': ORDERED}
    for unit in replay.units[:start]:
        unit.bullet = neighbour
    replay.apply(requests)
    expected = '\n'.join(LINES)
    expected = '\n' + expected if newline_before else expected + '\n'
    assert replay.text == prefix + expected + suffix
    assert inserted_text_from_requests(requests) == expected
    assert replay.rows()[0]['bullet'] == neighbour
    assert replay.rows()[-1]['bullet'] is None
    assert_mixed(replay, ordered)


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('rich', [True, False])
def test_mixed_mcp_receipts_and_literal_mode(
    mixed_input, operation, rich, mock_docs, simple_document,
):
    """Exercise all public insertion adapters with final-text receipts."""
    source, ordered = mixed_input
    arguments = {'doc_id': 'example', 'text': source, 'rich': rich}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(f'docs_{operation}', arguments)

    result = asyncio.run(call())
    data = result.structured_content
    expected = '\n'.join(LINES) if rich else source
    expected = (expected + '\n' if operation == 'insert_before'
                else '\n' + expected)
    preview = 'appended' if operation == 'append' else 'inserted_text'
    assert data[preview] == expected[:200]
    assert data['inserted_char_count'] == len(expected)
    assert data['preview_truncated'] == (len(expected) > 200)
    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    original = '\0' + ''.join(
        e['textRun']['content'] for item in simple_document['body']['content']
        for e in item['paragraph']['elements']
    )
    replay = ListReplay(original)
    replay.apply(requests)
    at = data['at_index']
    assert replay.text == original[:at] + expected + original[at:]
    if rich:
        assert_mixed(replay, ordered)
    else:
        assert requests == [{'insertText': {
            'location': {'index': at}, 'text': expected,
        }}]


def test_observer_removes_only_selected_utf16_content():
    """Control the observer's deletion semantics with a non-BMP neighbour."""
    replay = ListReplay('😀ROOT\nTail\n')
    replay.apply([{'deleteContentRange': {'range': {
        'startIndex': 2, 'endIndex': 7,
    }}}])
    assert replay.text == '😀Tail\n'


@pytest.mark.parametrize('newline_before', [False, True])
def test_mixed_lists_preserve_later_code_markers(newline_before):
    """Rebase code metadata by net text changes, excluding temporary roots."""
    requests = markdown_to_requests(
        '- Parent😀\n  1. Child\n\n```python\nprint("🦷")\n```',
        start=3, newline_before=newline_before,
    )
    text = inserted_text_from_requests(requests)
    assert 'ROOT' not in text and '\t' not in text
    marker = next(r['createNamedRange']['range'] for r in requests
                  if 'createNamedRange' in r)
    replay = ListReplay('😀\n\nSuffix\n')
    replay.apply([r for r in requests if 'createNamedRange' not in r])
    native = replay.text.encode('utf-16-le')
    code = native[marker['startIndex'] * 2:marker['endIndex'] * 2]
    assert code.decode('utf-16-le').startswith('print("🦷")')


@pytest.mark.parametrize('newline_before', [False, True])
def test_mixed_lists_around_table_rebase_and_preview(newline_before):
    """Retain component ancestry when a structural plan moves paragraphs."""
    plan = markdown_to_requests(
        '- Parent\n  1. Child\n\n| Header |\n| --- |\n| Cell |\n\n'
        '1. Other root\n   - Other child',
        start=8, newline_before=newline_before,
    )
    assert isinstance(plan, TableInsertionPlan)
    expected = ('\nParent\nChild\nHeader\nCell\n\nOther root\nOther child'
                if newline_before else
                'Parent\nChild\n\nHeader\nCell\nOther root\nOther child\n')
    assert inserted_text_from_requests(plan) == expected
    groups = [g for g in plan.request_groups() if isinstance(g, list)]
    for group in groups:
        requests = plan.paragraph_requests(group, 13)
        replay = ListReplay('Prefix😀 here\n\nSuffix\n')
        replay.apply(requests)
        rows = [r for r in replay.rows() if r['bullet']]
        assert [r['bullet']['level'] for r in rows] == [0, 1]
        assert rows[0]['bullet']['preset'] != rows[1]['bullet']['preset']
        assert 'ROOT' not in replay.text


def test_mixed_list_image_slots_keep_following_styles():
    """Keep native objects and emoji styles across temporary text changes."""
    requests = markdown_to_requests(
        '- Parent\n  1. ![](https://example.com/image.png) **After😀**',
        start=1,
    )
    assert inserted_text_from_requests(requests) == '\nParent\n\ufffc After😀'
    replay = ListReplay('\0\nSuffix\n')
    observed = []
    for request in requests:
        if 'insertInlineImage' in request:
            image = request['insertInlineImage']
            observed.append({'insertText': {'location': image['location'],
                                             'text': '\ufffc'}})
        else:
            observed.append(request)
    replay.apply(observed)
    assert replay.styled_text('bold') == 'After😀'
    assert replay.text.count('\ufffc') == 1
