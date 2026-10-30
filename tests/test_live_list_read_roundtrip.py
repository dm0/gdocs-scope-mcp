"""Read and reinsert native lists through independent isolated MCP servers."""

# Imported fixture names intentionally match pytest arguments.
# Fixture depths and counts are independent expectations.
# ruff: noqa: F811, PLR2004
import asyncio
import uuid

import pytest
from bs4 import BeautifulSoup

from gdocs_scope_mcp.rich_text.parsing import markdown_to_html

from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401

pytestmark = pytest.mark.live


def scoped_rows(document, marker, start, end):
    """Inspect only synthetic paragraphs in a verified source/copy interval."""
    return [item for item in document['body']['content']
            if start <= item.get('startIndex', -1) < end
            and paragraph_text(item).startswith(marker + ' ')]


def list_shape(document, rows, marker):
    """Normalize IDs by first occurrence, keeping marker kind and depth."""
    identities = {}
    result = []
    for item in rows:
        bullet = item['paragraph'].get('bullet')
        if bullet is None:
            continue
        identity = bullet['listId']
        identities.setdefault(identity, len(identities))
        depth = bullet.get('nestingLevel', 0)
        level = document['lists'][identity]['listProperties'][
            'nestingLevels'][depth]
        result.append({
            'text': paragraph_text(item).strip().removeprefix(marker + ' '),
            'depth': depth, 'ordered': bool(level.get('glyphType')),
            'group': identities[identity],
        })
    return result


@pytest.mark.parametrize('ordered', [False, True])
@pytest.mark.parametrize('independent', [False, True])
def test_live_native_list_read_roundtrip(
    live_test_doc, table_probe, ordered, independent,
):
    """Keep native levels, independent groups, styles and edit targeting."""
    marker = 'READLIST_' + uuid.uuid4().hex
    tag = 'ol' if ordered else 'ul'
    labels = [
        'Parent😀', 'Child🦷', 'Grandchild [literal]*', 'Child sibling',
        'Parent sibling', 'Independent', 'Independent child',
        'Independent sibling',
    ]
    source = (
        f'### {marker} Scope\n\n{marker} Before\n\n'
        f'<{tag}><li><b>{marker} Parent😀</b><{tag}>'
        f'<li><i>{marker} Child🦷</i><{tag}><li>'
        f'<a href="https://example.com">{marker} Grandchild [literal]*</a>'
        f'</li></{tag}></li><li>{marker} Child sibling</li></{tag}></li>'
        f'<li>{marker} Parent sibling</li></{tag}>'
        f'<{tag}><li>{marker} Independent<{tag}>'
        f'<li>{marker} Independent child</li></{tag}></li>'
        f'<li>{marker} Independent sibling</li></{tag}>\n\n'
        f'{marker} After\n\n### {marker} Boundary'
    )
    if not independent:
        source = source.replace(f'</{tag}><{tag}>', '')

    async def run():
        mode = ('ordered' if ordered else 'unordered') + (
            '-html' if independent else '-markdown')
        async with table_probe('list-read-roundtrip-' + mode) as probe:
            before = await probe.read()
            probe.initial_body = before['body']
            probe.start = before['body']['content'][-1]['endIndex'] - 1
            await probe.call(0, 'docs_append', {
                'doc_id': live_test_doc, 'text': source,
            })
            document = await probe.read()
            end = document['body']['content'][-1]['endIndex']
            original = scoped_rows(document, marker, probe.start, end)
            heading = original[0]['paragraph']['paragraphStyle']['headingId']
            expected_shape = list_shape(document, original, marker)
            assert [r['text'] for r in expected_shape] == labels
            assert [r['depth'] for r in expected_shape] == [
                0, 1, 2, 1, 0, 0, 1, 0,
            ]
            assert [r['group'] for r in expected_shape] == (
                [0] * 5 + [1] * 3 if independent else [0] * 8)
            assert all(r['ordered'] == ordered for r in expected_shape)
            read = await probe.call(1, 'docs_read', {
                'doc_id': live_test_doc, 'heading_ids': [heading],
            })
            assert len(read['sections']) == 1
            markup = read['sections'][0]['markdown']
            html = BeautifulSoup(markdown_to_html(markup), 'html.parser')
            assert (f'<{tag}>' in markup) is independent
            assert len(html.find_all(tag, recursive=False)) == (
                2 if independent else 1)
            assert len(html.find_all('li')) == 8
            assert marker + ' Boundary' not in html.get_text()
            copy_at = document['body']['content'][-1]['endIndex'] - 1
            await probe.call(1, 'docs_append', {
                'doc_id': live_test_doc, 'text': markup,
            })
            current = await probe.read()
            copied = scoped_rows(current, marker, copy_at,
                                 current['body']['content'][-1]['endIndex'])
            assert list_shape(current, copied, marker) == expected_shape
            assert scoped_rows(current, marker, probe.start,
                               copy_at) == original
            rows = {paragraph_text(p).strip().removeprefix(marker + ' '): p
                    for p in copied}
            for label, flag in [('Parent😀', 'bold'), ('Child🦷', 'italic')]:
                assert all(e['textRun']['textStyle'].get(flag)
                           for e in rows[label]['paragraph']['elements']
                           if e.get('textRun', {}).get('content', '').strip())
            assert any(e.get('textRun', {}).get('textStyle', {}).get('link',
                       {}).get('url') == 'https://example.com'
                       for e in rows['Grandchild [literal]*'][
                           'paragraph']['elements'])
            copied_heading = copied[0]['paragraph']['paragraphStyle'][
                'headingId']
            assert copied_heading != heading
            replaced = await probe.call(0, 'docs_search_replace', {
                'doc_id': live_test_doc, 'heading_id': copied_heading,
                'find': '🦷', 'replace': 'X',
            })
            offset = len((marker + ' Child').encode('utf-16-le')) // 2
            assert (replaced['at_index']
                    == rows['Child🦷']['startIndex'] + offset)
            current = await probe.read()
            assert scoped_rows(current, marker, probe.start,
                               copy_at) == original
            assert marker + ' ChildX\n' in [
                paragraph_text(p) for p in scoped_rows(
                    current, marker, copy_at,
                    current['body']['content'][-1]['endIndex'],
                )
            ]
            probe.report['shape'] = expected_shape
            probe.report['checks_passed'] = True

    asyncio.run(run())
