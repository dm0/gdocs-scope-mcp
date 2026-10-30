"""Record issue #24 contracts without treating unsupported lists as success."""

# Fixture offsets and item counts are independent expectations.
# ruff: noqa: PLR2004
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field

import pytest
from bs4 import BeautifulSoup
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.documents import (
    editing as docs_edit,
)
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests
from gdocs_scope_mcp.rich_text.parsing import markdown_to_html


@dataclass
class Unit:
    """Attach observed formatting to one independent UTF-16 code unit."""

    value: bytes
    style: dict = field(default_factory=dict)
    paragraph_style: dict = field(default_factory=dict)
    bullet: dict | None = None
    continued_level: int | None = None


class ListReplay:
    """Observe a bounded subset of Docs operations without backend helpers."""

    def __init__(self, text):
        """Retain source text and numbering identities through index shifts."""
        self.units = self.encode(text)
        self.next_list = 0

    @staticmethod
    def encode(text):
        """Split encoded source without assuming one unit per Python char."""
        data = text.encode('utf-16-le')
        return [Unit(data[i:i + 2]) for i in range(0, len(data), 2)]

    def ranges(self):
        """Return current paragraph ranges, including their newline units."""
        result = []
        start = 0
        for i, unit in enumerate(self.units):
            if unit.value == b'\n\x00':
                result.append((start, i + 1))
                start = i + 1
        if start < len(self.units):
            result.append((start, len(self.units)))
        return result

    @property
    def text(self):
        """Decode the complete buffer, including untouched neighbours."""
        return b''.join(u.value for u in self.units).decode('utf-16-le')

    def apply(self, requests):
        """Replay styles, native markers and tab removal in request order."""
        for request in requests:
            if 'insertText' in request:
                insert = request['insertText']
                at = insert['location']['index']
                assert 0 <= at <= len(self.units)
                self.units[at:at] = self.encode(insert['text'])
                continue
            assert len(request) == 1
            kind, update = next(iter(request.items()))
            if kind == 'deleteContentRange':
                span = update['range']
                start, end = span['startIndex'], span['endIndex']
                assert 0 <= start < end <= len(self.units)
                del self.units[start:end]
                continue
            assert kind in {
                'updateTextStyle', 'updateParagraphStyle',
                'createParagraphBullets', 'deleteParagraphBullets',
            }, kind
            span = update['range']
            start, end = span['startIndex'], span['endIndex']
            assert 0 <= start < end <= len(self.units)
            if kind == 'updateTextStyle':
                for unit in self.units[start:end]:
                    unit.style.update(update['textStyle'])
                continue
            ranges = self.ranges()
            selected = [(a, b) for a, b in ranges if a < end and start < b]
            if kind == 'createParagraphBullets':
                self.next_list += 1
                identity = self.next_list
                preceding = [b for a, b in ranges if b <= selected[0][0]]
                if preceding:
                    previous = self.units[preceding[-1] - 1].bullet
                    if previous and (
                        previous['preset'] == update['bulletPreset']
                    ):
                        identity = previous['id']
            removed_tabs = []
            for a, b in selected:
                if kind == 'updateParagraphStyle':
                    for unit in self.units[a:b]:
                        unit.paragraph_style.update(update['paragraphStyle'])
                elif kind == 'deleteParagraphBullets':
                    for unit in self.units[a:b]:
                        if unit.bullet:
                            unit.continued_level = unit.bullet['level']
                        unit.bullet = None
                else:
                    depth = 0
                    while a + depth < b and (
                        self.units[a + depth].value == b'\t\x00'
                    ):
                        depth += 1
                    for unit in self.units[a:b]:
                        unit.bullet = {
                            'id': identity, 'level': depth,
                            'preset': update['bulletPreset'],
                        }
                        unit.continued_level = None
                    removed_tabs.append((a, depth))
            for a, depth in reversed(removed_tabs):
                del self.units[a:a + depth]

    def rows(self):
        """Expose final paragraph roles and consecutive per-level counters."""
        result = []
        counts = defaultdict(int)
        for a, b in self.ranges():
            unit = self.units[a]
            text = b''.join(u.value for u in self.units[a:b])
            row = {
                'text': (text.decode('utf-16-le').removeprefix('\0')
                         .rstrip('\n')),
                'bullet': unit.bullet,
                'style': unit.paragraph_style,
                'continued_level': unit.continued_level,
            }
            if unit.bullet:
                key = (unit.bullet['id'], unit.bullet['level'])
                counts[key] += 1
                row['number'] = counts[key]
            result.append(row)
        return result

    def styled_text(self, key):
        """Observe only text units carrying the requested inline property."""
        data = b''.join(u.value for u in self.units if u.style.get(key))
        return data.decode('utf-16-le')


@pytest.fixture(params=[False, True], ids=['unordered', 'ordered'])
def advanced_item(request):
    """Build three item paragraphs with optional nested children."""
    ordered = request.param

    def build(nested):
        marker, next_marker, indent = (
            ('1.', '2.', '   ') if ordered else ('-', '-', '  ')
        )
        markdown = (
            f'Before\n\n{marker} **Parent🦷**\n\n'
            f'{indent}More [linked](https://example.com/continuation).\n\n'
            f'{indent}Third paragraph.\n\n'
        )
        lines = ['Before', 'Parent🦷', 'More linked.', 'Third paragraph.']
        if nested:
            markdown += (
                f'{indent}{marker} *Child🦷*\n\n'
                f'{indent}Parent after child.\n\n'
            )
            lines.extend(['Child🦷', 'Parent after child.'])
        markdown += f'{next_marker} Next parent\n\nAfter'
        lines.extend(['Next parent', 'After'])
        return markdown, lines, ordered

    return build


@pytest.mark.parametrize('nested', [False, True])
def test_advanced_item_fixtures_have_intended_markdown_structure(
    advanced_item, nested,
):
    """Validate fixtures before unsupported conversion can mask bad syntax."""
    markdown, _, ordered = advanced_item(nested)
    html = BeautifulSoup(markdown_to_html(markdown), 'html.parser')
    root = html.find('ol' if ordered else 'ul')
    items = root.find_all('li', recursive=False)
    assert len(items) == 2
    assert len(items[0].find_all('p', recursive=False)) == (4 if nested else 3)
    assert bool(items[0].find(['ol', 'ul'])) is nested


def assert_item_contract(replay, lines, ordered, nested):
    """Check markers, continuation indentation, text order and style scope."""
    rows = [row for row in replay.rows() if row['text'] in lines]
    assert [row['text'] for row in rows] == lines
    by_text = {row['text']: row for row in rows}
    first, second = by_text['Parent🦷'], by_text['Next parent']
    assert first['bullet'] and second['bullet']
    preset = (
        'NUMBERED_DECIMAL_ALPHA_ROMAN' if ordered
        else 'BULLET_DISC_CIRCLE_SQUARE'
    )
    assert first['bullet']['preset'] == second['bullet']['preset'] == preset
    assert first['bullet']['id'] == second['bullet']['id']
    assert first['bullet']['level'] == second['bullet']['level'] == 0
    assert (first['number'], second['number']) == (1, 2)
    continuation = ['More linked.', 'Third paragraph.']
    if nested:
        child = by_text['Child🦷']
        assert child['bullet']
        assert child['bullet']['level'] == 1
        continuation.append('Parent after child.')
    for name in continuation:
        row = by_text[name]
        assert row['bullet'] is None
        if row['continued_level'] != 0:
            # A planner may instead set indentation directly on plain rows.
            style = row['style']
            assert style['indentStart'] == style['indentFirstLine']
            assert style['indentStart']['magnitude'] > 0
    assert by_text['Before']['bullet'] is by_text['After']['bullet'] is None
    assert replay.styled_text('bold') == 'Parent🦷'
    assert replay.styled_text('link') == 'linked'
    targets = {
        u.style['link']['url'] for u in replay.units if u.style.get('link')
    }
    assert targets == {'https://example.com/continuation'}
    assert replay.styled_text('italic') == ('Child🦷' if nested else '')


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('newline_before', [False, True])
def test_advanced_list_paragraphs_and_numbering(
    advanced_item, nested, newline_before,
):
    """Keep logical item boundaries on either insertion side."""
    markdown, lines, ordered = advanced_item(nested)
    prefix, suffix = 'Prefix 😀\n', '\nSuffix\n'
    start = len(prefix.encode('utf-16-le')) // 2
    requests = markdown_to_requests(
        markdown, start=start, newline_before=newline_before,
    )
    replay = ListReplay(prefix + suffix)
    original_bullet = {
        'id': 0, 'level': 0, 'preset': 'BULLET_DISC_CIRCLE_SQUARE',
    }
    for unit in replay.units[:start]:
        unit.bullet = original_bullet
    replay.apply(requests)
    inserted = '\n'.join(lines)
    inserted = '\n' + inserted if newline_before else inserted + '\n'
    assert replay.text == prefix + inserted + suffix
    assert replay.rows()[0]['bullet'] == original_bullet
    assert replay.rows()[-1]['bullet'] is None
    assert_item_contract(replay, lines, ordered, nested)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
def test_advanced_list_mcp_receipt_and_preservation(
    mock_docs, simple_document, advanced_item, nested, operation,
):
    """Return success and final-text receipts without altering neighbours."""
    markdown, lines, ordered = advanced_item(nested)
    arguments = {'doc_id': 'example', 'text': markdown}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                f'docs_{operation}', arguments, raise_on_error=False,
            )

    result = asyncio.run(call())
    assert result.is_error is False, result.structured_content
    data = result.structured_content
    source = '\0' + ''.join(
        element['textRun']['content']
        for item in simple_document['body']['content']
        for element in item['paragraph']['elements']
    )
    at = (len(source) - 1 if operation == 'append' else
          1 if operation == 'insert_before' else len('\0Introduction'))
    assert data['at_index'] == at
    expected = '\n'.join(lines)
    expected = (
        expected + '\n' if operation == 'insert_before' else '\n' + expected
    )
    preview = 'appended' if operation == 'append' else 'inserted_text'
    assert data[preview] == expected
    assert data['inserted_char_count'] == len(expected)
    assert data['preview_truncated'] is False
    mock_docs.batchUpdate.assert_called_once()
    replay = ListReplay(source)
    replay.apply(mock_docs.batchUpdate.call_args.kwargs['body']['requests'])
    assert replay.text == source[:at] + expected + source[at:]
    assert_item_contract(replay, lines, ordered, nested)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
def test_advanced_list_literal_mode_is_already_supported(
    mock_docs, advanced_item, nested, operation,
):
    """Preserve already-working literal insertion without expected failure."""
    markdown, _, _ = advanced_item(nested)
    if operation == 'append':
        result = docs_edit.append('example', markdown, rich=False)
        preview = result.appended
    else:
        result = getattr(docs_edit, operation)(
            'example', 'Introduction', markdown, rich=False,
        )
        preview = result.inserted_text
    expected = (
        markdown + '\n' if operation == 'insert_before' else '\n' + markdown
    )
    limit = 200
    assert preview == expected[:limit]
    assert result.inserted_char_count == len(expected)
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests == [{'insertText': {
        'location': {'index': result.at_index}, 'text': expected,
    }}]


@pytest.mark.parametrize('ordered', [False, True])
@pytest.mark.parametrize('newline_before', [False, True])
def test_loose_list_spacing_is_distinct_without_extra_items(
    ordered, newline_before,
):
    """Use paragraph spacing rather than turning blank lines into items."""
    marker = '1.' if ordered else '-'
    scores = []
    for gap in ['\n', '\n\n']:
        replay = ListReplay('\nSuffix\n')
        replay.apply(markdown_to_requests(
            f'{marker} First{gap}{marker} Second',
            newline_before=newline_before,
        ))
        rows = [r for r in replay.rows() if r['text'] in {'First', 'Second'}]
        assert len(rows) == 2
        assert all(row['bullet'] for row in rows)
        scores.append(sum(
            row['style'].get(field, {}).get('magnitude', 0)
            for row in rows for field in ['spaceAbove', 'spaceBelow']
        ))
    assert scores[1] > scores[0]


@pytest.mark.parametrize('ordered', [False, True])
def test_replay_controls_bullet_removal_and_numbering(ordered):
    """Ensure the test observer handles a continuation-producing deletion."""
    marker = '1.' if ordered else '-'
    replay = ListReplay('\nSuffix\n')
    replay.apply(markdown_to_requests(
        f'{marker} First\n{marker} Continued\n{marker} Second',
    ))
    # All characters in this control are ASCII: the middle paragraph starts
    # after the leading inserted break and First's terminating newline.
    replay.apply([{'deleteParagraphBullets': {'range': {
        'startIndex': len('\nFirst\n'),
        'endIndex': len('\nFirst\nContinued'),
    }}}])
    rows = [r for r in replay.rows() if r['text'] != 'Suffix']
    numbered = [r for r in rows if r['bullet']]
    assert [r['text'] for r in numbered] == ['First', 'Second']
    assert [r['number'] for r in numbered] == [1, 2]
    continuation = next(r for r in rows if r['text'] == 'Continued')
    assert continuation['bullet'] is None
    assert continuation['continued_level'] == 0


@pytest.mark.parametrize('newline_before', [False, True])
def test_deep_continuations_and_separate_lists(newline_before):
    """Rebase continuation ranges after all nesting tabs in each list."""
    markdown = (
        '1. Parent\n\n'
        '   1. Child\n\n'
        '      Child continued😀\n\n'
        '      1. Grandchild\n\n'
        '         Grandchild continued\n\n'
        '      Child after grandchild\n\n'
        '   Parent after child\n\n'
        '2. Last\n\nBetween\n\n'
        '- Other\n\n  Other continued\n\n- Last other'
    )
    replay = ListReplay('\nSuffix\n')
    requests = markdown_to_requests(markdown, newline_before=newline_before)
    replay.apply(requests)
    rows = {row['text']: row for row in replay.rows()}
    for label, level in [('Child continued😀', 1),
                         ('Grandchild continued', 2),
                         ('Child after grandchild', 1),
                         ('Parent after child', 0), ('Other continued', 0)]:
        row = rows[label]
        assert row['bullet'] is None
        assert row['style']['indentStart']['magnitude'] == 36 * (level + 1)
    assert rows['Parent']['bullet']['id'] == rows['Last']['bullet']['id']
    assert rows['Other']['bullet']['id'] == rows['Last other']['bullet']['id']
    assert rows['Last']['number'] == rows['Last other']['number'] == 2
    assert rows['Between']['bullet'] is None
