"""Verify mixed native lists and numbering through isolated STDIO servers."""

# Imported fixture names intentionally match pytest arguments.
# ruff: noqa: F811

import asyncio
import re
import uuid
from html import unescape

import pytest
from bs4 import BeautifulSoup

from gdocs_scope_mcp.rich_text.parsing import markdown_to_html

from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401

ORDERED = 'NUMBERED_DECIMAL_ALPHA_ROMAN'
UNORDERED = 'BULLET_DISC_CIRCLE_SQUARE'


def probe_rows(document, marker):
    """Select only synthetic probe paragraphs with their original indices."""
    return {paragraph_text(item).strip(): item
            for item in document['body']['content']
            if marker in paragraph_text(item)}


def glyph(document, item):
    """Resolve the actual native glyph definition at the paragraph's level."""
    bullet = item['paragraph']['bullet']
    return document['lists'][bullet['listId']]['listProperties'][
        'nestingLevels'][bullet.get('nestingLevel', 0)]


@pytest.mark.parametrize('parent_preset', [ORDERED, UNORDERED])
def test_live_mixed_list_feasibility(
    live_test_doc, table_probe, parent_preset,
):
    """Keep a parent list's identity after replacing its children's markers."""
    marker = 'MIXED_' + uuid.uuid4().hex
    labels = [marker + ' Parent one😀', marker + ' Child one',
              marker + ' Child two', marker + ' Parent two']
    child_preset = UNORDERED if parent_preset == ORDERED else ORDERED
    mode = 'ordered-parent' if parent_preset == ORDERED else 'unordered-parent'

    async def run():
        async with table_probe('mixed-feasibility-' + mode) as probe:
            before = await probe.read()
            probe.initial_body = before['body']
            probe.start = before['body']['content'][-1]['endIndex'] - 1
            await probe.call(0, 'docs_append', {
                'doc_id': live_test_doc, 'rich': False,
                'text': (marker + ' Before\n' + labels[0] + '\n\t' + labels[1]
                         + '\n\t' + labels[2] + '\n' + labels[3]
                         + '\n' + marker + ' After'),
            })
            document = await probe.read()
            rows = probe_rows(document, marker)
            first, last = rows[labels[0]], rows[labels[-1]]
            await probe.batch([{'createParagraphBullets': {
                'range': {'startIndex': first['startIndex'],
                          'endIndex': last['endIndex'] - 1},
                'bulletPreset': parent_preset,
            }}], document)
            document = await probe.read()
            rows = probe_rows(document, marker)
            parent_id = rows[labels[0]]['paragraph']['bullet']['listId']
            left, right = rows[labels[1]], rows[labels[2]]
            requests = [{'deleteParagraphBullets': {'range': {
                'startIndex': left['startIndex'],
                'endIndex': right['endIndex'] - 1,
            }}}]
            for child in (right, left):
                requests.append({'insertText': {
                    'location': {'index': child['startIndex']}, 'text': '\t',
                }})
            requests.append({'insertText': {
                'location': {'index': left['startIndex']}, 'text': 'ROOT\n',
            }})
            requests.append({'updateParagraphStyle': {
                'range': {'startIndex': left['startIndex'],
                          'endIndex': right['endIndex'] + 6},
                'paragraphStyle': {
                    'indentStart': {'magnitude': 0, 'unit': 'PT'},
                    'indentEnd': {'magnitude': 0, 'unit': 'PT'},
                    'indentFirstLine': {'magnitude': 0, 'unit': 'PT'},
                },
                'fields': 'indentStart,indentEnd,indentFirstLine',
            }})
            requests.append({'createParagraphBullets': {
                'range': {'startIndex': left['startIndex'],
                          'endIndex': right['endIndex'] + 6},
                'bulletPreset': child_preset,
            }})
            requests.append({'deleteContentRange': {'range': {
                'startIndex': left['startIndex'],
                'endIndex': left['startIndex'] + 5,
            }}})
            await probe.batch(requests, document)
            document = await probe.read()
            rows = probe_rows(document, marker)
            probe.report['observations'] = [{
                'text': label,
                'bullet': rows[label]['paragraph'].get('bullet'),
                'glyph': glyph(document, rows[label]),
            } for label in labels]
            for label in (labels[0], labels[3]):
                bullet = rows[label]['paragraph']['bullet']
                assert bullet['listId'] == parent_id
                assert bullet.get('nestingLevel', 0) == 0
            for label in labels[1:3]:
                bullet = rows[label]['paragraph']['bullet']
                assert bullet['listId'] != parent_id
                assert bullet.get('nestingLevel', 0) == 1
                definition = glyph(document, rows[label])
                assert bool(definition.get('glyphSymbol')) == (
                    child_preset == UNORDERED)
                assert definition['indentStart']['magnitude'] == 72  # noqa: PLR2004
            exported = await probe.call(
                0, 'probe_list_export', {'marker': marker},
            )
            probe.report['exported_lines'] = exported['lines']
            if parent_preset == ORDERED:
                for number, label in enumerate((labels[0], labels[3]), 1):
                    pattern = rf'^\s*{number}\.\s+{re.escape(label)}$'
                    assert any(re.search(pattern, line)
                               for line in exported['lines'])
            probe.report['checks_passed'] = True

    asyncio.run(run())


@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('ordered', [False, True])
def test_live_mixed_insertion(live_test_doc, table_probe, tool, ordered):
    """Verify the compiler, absolute depths and actual parent numbers."""
    marker = 'MIXED_' + uuid.uuid4().hex
    parent, second, child, indent = (
        ('1.', '2.', '-', '   ') if ordered else ('-', '-', '1.', '  ')
    )
    deeper = indent + ('  ' if ordered else '   ')
    labels = [
        'Before', 'Parent😀', 'More linked.', 'Child', 'Child continued',
        'Grandchild', 'Grandchild next', 'Child after grandchild',
        'Child next', 'Parent after child', 'Next parent', 'After',
    ]
    source = (
        f'{marker} Before\n\n{parent} **{marker} Parent😀**\n\n'
        f'{indent}{marker} More [linked](https://example.com).\n\n'
        f'{indent}{child} *{marker} Child*\n\n'
        f'{deeper}{marker} Child continued\n\n'
        f'{deeper}{parent} {marker} Grandchild\n'
        f'{deeper}{second} {marker} Grandchild next\n\n'
        f'{deeper}{marker} Child after grandchild\n\n'
        f'{indent}{child} {marker} Child next\n\n'
        f'{indent}{marker} Parent after child\n\n'
        f'{second} {marker} Next parent\n\n{marker} After'
    )
    if tool == 'docs_insert_before':
        source = markdown_to_html(source)

    async def run():
        mode = 'ordered' if ordered else 'unordered'
        async with table_probe(f'mixed-{tool}-{mode}') as probe:
            before = await probe.read()
            probe.initial_body = before['body']
            probe.start = before['body']['content'][-1]['endIndex'] - 1
            await probe.call(0, 'docs_append', {
                'doc_id': live_test_doc, 'rich': False,
                'text': f'{marker} Left\n{marker} Anchor\n{marker} Right',
            })
            arguments = {'doc_id': live_test_doc, 'text': source}
            if tool != 'docs_append':
                arguments['anchor'] = marker + ' Anchor'
            result = await probe.call(0, tool, arguments)
            expected = '\n'.join(marker + ' ' + label for label in labels)
            expected = (expected + '\n' if tool == 'docs_insert_before'
                        else '\n' + expected)
            preview = 'appended' if tool == 'docs_append' else 'inserted_text'
            assert result[preview] == expected[:200]
            assert result['inserted_char_count'] == len(expected)
            document = await probe.read()
            rows = {label.removeprefix(marker + ' '): item
                    for label, item in probe_rows(document, marker).items()}
            expected_order = (
                ['Left', *labels, 'Anchor', 'Right']
                if tool == 'docs_insert_before' else
                ['Left', 'Anchor', *labels, 'Right']
                if tool == 'docs_insert_after' else
                ['Left', 'Anchor', 'Right', *labels]
            )
            assert list(rows) == expected_order
            parent_id = rows['Parent😀']['paragraph']['bullet']['listId']
            for names, depth, is_ordered in [
                (['Parent😀', 'Next parent'], 0, ordered),
                (['Child', 'Child next'], 1, not ordered),
                (['Grandchild', 'Grandchild next'], 2, ordered),
            ]:
                identities = set()
                for label in names:
                    item = rows[label]
                    bullet = item['paragraph']['bullet']
                    identities.add(bullet['listId'])
                    assert bullet.get('nestingLevel', 0) == depth
                    definition = glyph(document, item)
                    assert bool(definition.get('glyphType')) == is_ordered
                    assert (definition['indentStart']['magnitude']
                            == 36 * (depth + 1))
                assert len(identities) == 1
                if depth:
                    assert parent_id not in identities
            for label, depth in [('More linked.', 0), ('Child continued', 1),
                                 ('Child after grandchild', 1),
                                 ('Parent after child', 0)]:
                paragraph = rows[label]['paragraph']
                assert 'bullet' not in paragraph
                style = paragraph['paragraphStyle']
                assert style['indentStart'] == style['indentFirstLine']
                assert style['indentStart']['magnitude'] == 36 * (depth + 1)
            for label in ['Left', 'Anchor', 'Right', 'Before', 'After']:
                assert 'bullet' not in rows[label]['paragraph']
            for label, flag in [('Parent😀', 'bold'), ('Child', 'italic')]:
                assert all(e['textRun']['textStyle'].get(flag)
                           for e in rows[label]['paragraph']['elements']
                           if e.get('textRun', {}).get('content', '').strip())
            assert any(e.get('textRun', {}).get('textStyle', {}).get('link',
                       {}).get('url') == 'https://example.com'
                       for e in rows['More linked.']['paragraph']['elements'])
            exported = await probe.call(
                0, 'probe_list_export', {'marker': marker},
            )
            if ordered:
                for number, label in enumerate(['Parent😀', 'Next parent'], 1):
                    pattern = rf'^\s*{number}\.\s+{marker} {label}$'
                    assert any(re.search(pattern, line)
                               for line in exported['lines'])
            read = await probe.call(1, 'docs_read', {'doc_id': live_test_doc})
            markdown = unescape('\n'.join(s['markdown']
                                          for s in read['sections']))
            visible = BeautifulSoup(markdown_to_html(markdown),
                                    'html.parser').get_text()
            assert all(marker + ' ' + label in visible for label in labels)
            # Reads expose the existing depth/marker display. Canonical
            # read-to-write list serialization is tracked separately in #51.
            plain_markup = markdown.replace('*', '')
            for label, depth, is_ordered in [
                ('Parent😀', 0, ordered), ('Next parent', 0, ordered),
                ('Child', 1, not ordered), ('Grandchild', 2, ordered),
            ]:
                prefix = ' ' * depth + ('1.' if is_ordered else '-')
                assert (prefix + ' ' + marker + ' ' + label) in plain_markup
            probe.report['exported_lines'] = exported['lines']
            probe.report['checks_passed'] = True

    asyncio.run(run())
