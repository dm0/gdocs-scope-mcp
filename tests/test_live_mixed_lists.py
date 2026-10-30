"""Verify mixed native lists and numbering through isolated STDIO servers."""

# Imported fixture names intentionally match pytest arguments.
# ruff: noqa: F811

import asyncio
import re
import uuid

import pytest

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
