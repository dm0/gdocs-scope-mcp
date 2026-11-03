"""Verify named heading spacing through isolated STDIO MCP servers."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from gdocs_scope_mcp.documents.snapshots import normalized

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


@pytest.mark.live
@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
def test_live_heading_spacing_inheritance(live_test_doc, table_probe, tool):
    """Reset both spacing overrides without changing existing paragraphs."""
    async def run():
        async with table_probe('heading-spacing-' + tool) as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None

            async def native():
                """Read current native styles through the isolated MCP."""
                return await probe.call(0, 'probe_tabs_document')

            def document_tab(document):
                """Select only this test's temporary tab."""
                return next(t['documentTab'] for t in document['tabs']
                            if t['tabProperties']['tabId'] == tab_id)

            try:
                result = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': 'heading-spacing-' + tool},
                }}], await native())
                tab_id = result['response']['replies'][0][
                    'addDocumentTab']['tabProperties']['tabId']
                await probe.batch([{'insertText': {
                    'location': {'index': 1, 'tabId': tab_id},
                    'text': 'Before\nAnchor\nAfter',
                }}], await native())
                for level in range(1, 7):
                    for spacing in (1, 100):
                        document = await native()
                        body = document_tab(document)['body']['content']
                        source = (body[-1] if tool == 'docs_append' else next(
                            p for p in body
                            if paragraph_text(p).strip() == 'Anchor'))
                        await probe.batch([{'updateParagraphStyle': {
                            'range': {'startIndex': source['startIndex'],
                                      'endIndex': source['endIndex'],
                                      'tabId': tab_id},
                            'paragraphStyle': {
                                key: {'magnitude': spacing, 'unit': 'PT'}
                                for key in ('spaceAbove', 'spaceBelow')
                            },
                            'fields': 'spaceAbove,spaceBelow',
                        }}], document)
                        seeded = document_tab(await native())
                        label = f'Spacing probe {level}-{spacing}'
                        arguments = {
                            'doc_id': live_test_doc, 'tab_id': tab_id,
                            'text': '#' * (level + 2) + ' ' + label,
                        }
                        if tool != 'docs_append':
                            arguments['anchor'] = 'Anchor'
                        await probe.call(0, tool, arguments)
                        updated = document_tab(await native())
                        paragraphs = updated['body']['content']
                        item = next(p for p in paragraphs
                                    if paragraph_text(p).strip() == label)
                        style = item['paragraph']['paragraphStyle']
                        assert style['namedStyleType'] == f'HEADING_{level}'
                        assert 'spaceAbove' not in style
                        assert 'spaceBelow' not in style
                        assert normalized([
                            p for p in paragraphs if p is not item
                        ]) == normalized(seeded['body']['content'])
                        assert updated['namedStyles'] == seeded['namedStyles']
                        probe.report[label] = {
                            'spacing_inherits_named_style': True,
                            'surrounding_paragraphs_unchanged': True,
                        }
                probe.report['checks_passed'] = True
            finally:
                if tab_id is not None:
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
