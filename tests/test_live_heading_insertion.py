"""Verify heading subtree insertions and boundary races over isolated STDIO."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from gdocs_scope_mcp.documents.snapshots import normalized

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import (
    paragraph_text,
    raced_edit,
    table_probe,  # noqa: F401
)


@pytest.mark.live
@pytest.mark.parametrize('mode', ['required', 'target'])
def test_live_heading_subtrees(live_test_doc, table_probe, mode):
    """Read back both boundaries, preserve native content and reject races."""
    async def run():
        async with table_probe('heading-subtrees-' + mode,
                               revision_mode=mode) as probe:
            async def native():
                return await probe.call(0, 'probe_tabs_document')

            before = await native()
            tab_id = None
            try:
                created = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': 'heading-subtrees-' + mode},
                }}], before)
                tab_id = created['response']['replies'][0][
                    'addDocumentTab']['tabProperties']['tabId']

                def body(document):
                    return next(t['documentTab']['body']['content']
                                for t in document['tabs']
                                if t['tabProperties']['tabId'] == tab_id)

                await probe.call(0, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'text': '### Same\n\nBody😀\n\n#### Child\n\n'
                            '| Header |\n| --- |\n| Cell🦷 |\n\n'
                            '### Same\n\nTail',
                })
                seeded = body(await native())
                outline = await probe.call(0, 'docs_get_tree', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                })
                headings = [h for h in outline['sections']
                            if h['title'].strip() in {'Same', 'Child'}]
                assert len(headings) == 3
                parent, child, other = [h['id'] for h in headings]
                assert headings[0]['title'] == headings[2]['title']
                operations = [
                    (parent, 'before_subtree', '**Before parent**', True),
                    (parent, 'after_subtree', 'After parent', True),
                    (child, 'before_subtree', '**Literal before child**', False),
                    (other, 'after_subtree', '**Literal at end**', False),
                ]
                inserted_labels = []
                for heading, position, text, rich in operations:
                    receipt = await probe.call(0, 'docs_insert_at_heading', {
                        'doc_id': live_test_doc, 'tab_id': tab_id,
                        'heading_id': heading, 'position': position,
                        'text': text, 'rich': rich,
                    })
                    assert receipt['heading_id'] == heading
                    assert receipt['tab_id'] == tab_id
                    assert receipt['insert_position'] == position
                    inserted_labels.append(text.replace('**', '')
                                           if rich else text)
                updated = body(await native())
                labels = [paragraph_text(p).strip() for p in updated]
                assert labels.index('Before parent') < labels.index('Same')
                assert labels.index('**Literal before child**') < (
                    labels.index('Child'))
                table_index = next(i for i, p in enumerate(updated)
                                   if 'table' in p)
                assert table_index < labels.index('After parent') < max(
                    i for i, label in enumerate(labels) if label == 'Same')
                assert labels[-1] == '**Literal at end**'
                inserted = [p for p in updated
                            if paragraph_text(p).strip() in inserted_labels]
                assert len(inserted) == 4
                assert all(p['paragraph']['paragraphStyle'][
                    'namedStyleType'] == 'NORMAL_TEXT' for p in inserted)
                assert normalized([p for p in updated if p not in inserted
                                   ]) == normalized(seeded)

                table_receipt = await probe.call(0, 'docs_insert_at_heading', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'heading_id': child, 'position': 'after_subtree',
                    'text': '| New header |\n| --- |\n| **New cell** |',
                    'table_borders': False,
                })
                assert table_receipt['ok']
                tables = [p for p in body(await native()) if 'table' in p]
                assert len(tables) == 2
                assert 'New cell' in str(tables[1])

                # An unrelated process changes the subtree boundary after read.
                for position in ('before_subtree', 'after_subtree'):
                    async def mutate():
                        await probe.call(0, 'docs_insert_at_heading', {
                            'doc_id': live_test_doc, 'tab_id': tab_id,
                            'heading_id': parent, 'position': 'after_subtree',
                            'text': '### Concurrent boundary',
                        })
                    result = await raced_edit(probe, 'docs_insert_at_heading', {
                        'doc_id': live_test_doc, 'tab_id': tab_id,
                        'heading_id': parent, 'position': position,
                        'text': 'Must not appear',
                    }, mutate)
                    assert result.is_error
                    assert result.structured_content['code'] == 'EDIT_CONFLICT'
                    assert 'Must not appear' not in ''.join(
                        paragraph_text(p) for p in body(await native()))
                probe.report['checks_passed'] = True
            finally:
                if tab_id is not None:
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                probe.report['cleanup_passed'] = True
    asyncio.run(run())
