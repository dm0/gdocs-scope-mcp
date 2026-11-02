"""Observe inherited spacing overrides when MCP inserts a named heading."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


@pytest.mark.live
def test_live_heading_spacing_inheritance(live_test_doc, table_probe):
    """Distinguish a named heading from resetting its paragraph overrides."""
    async def run():
        async with table_probe('heading-spacing') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            created = []

            async def native():
                """Read current native styles through the isolated MCP."""
                return await probe.call(0, 'probe_tabs_document')

            def heading(document, tab_id):
                """Find only the synthetic heading in this test's tab."""
                tab = next(t for t in document['tabs']
                           if t['tabProperties']['tabId'] == tab_id)
                return next(p for p in tab['documentTab']['body']['content']
                            if paragraph_text(p).strip() == 'Spacing probe')

            try:
                for override in (False, True):
                    result = await probe.batch([{'addDocumentTab': {
                        'tabProperties': {
                            'title': f'heading-spacing-probe-{override}',
                        },
                    }}], await native())
                    tab_id = result['response']['replies'][0][
                        'addDocumentTab']['tabProperties']['tabId']
                    created.append(tab_id)
                    # Newlines copy this source paragraph's direct spacing.
                    await probe.batch([{'updateParagraphStyle': {
                        'range': {'startIndex': 1, 'endIndex': 2,
                                  'tabId': tab_id},
                        'paragraphStyle': {'spaceAbove': {
                            'magnitude': 1, 'unit': 'PT',
                        }} if override else {},
                        'fields': 'spaceAbove',
                    }}], await native())
                    await probe.call(0, 'docs_append', {
                        'doc_id': live_test_doc, 'tab_id': tab_id,
                        'text': '<h6>Spacing probe</h6>',
                    })
                    document = await native()
                    item = heading(document, tab_id)
                    style = item['paragraph']['paragraphStyle']
                    assert style['namedStyleType'] == 'HEADING_4'
                    probe.report[str(override)] = {'inserted_style': style}
                    tab = next(t for t in document['tabs']
                               if t['tabProperties']['tabId'] == tab_id)
                    probe.report[str(override)]['named_style'] = next(
                        s for s in tab['documentTab']['namedStyles']['styles']
                        if s['namedStyleType'] == 'HEADING_4')
                    if override:
                        assert style['spaceAbove']['magnitude'] == 1
                    else:
                        assert 'spaceAbove' not in style
                    # A mask-only reset returns spacing to the named style.
                    await probe.batch([{'updateParagraphStyle': {
                        'range': {'startIndex': item['startIndex'],
                                  'endIndex': item['endIndex'],
                                  'tabId': tab_id},
                        'paragraphStyle': {}, 'fields': 'spaceAbove',
                    }}], document)
                    reset = heading(await native(), tab_id)[
                        'paragraph']['paragraphStyle']
                    assert reset['namedStyleType'] == 'HEADING_4'
                    assert 'spaceAbove' not in reset
                    probe.report[str(override)]['reset_style'] = reset
                probe.report['checks_passed'] = True
            finally:
                for tab_id in reversed(created):
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
