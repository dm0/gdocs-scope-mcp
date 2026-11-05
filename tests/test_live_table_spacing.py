"""Verify compact cell paragraphs through isolated STDIO MCP servers."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from gdocs_scope_mcp.documents.snapshots import normalized

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_insertion_styles import document_tab
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


@pytest.mark.live
@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('html', [False, True])
def test_live_table_paragraph_spacing(live_test_doc, table_probe, tool, html):
    """Zero cell spacing while retaining inline styles and nearby prose."""
    async def run():
        name = f'table-spacing-{tool}-{html}'
        async with table_probe(name) as probe:
            async def native():
                """Read current native content through the isolated MCP."""
                return await probe.call(0, 'probe_tabs_document')

            before = await native()
            tab_id = None
            try:
                result = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': name},
                }}], before)
                tab_id = result['response']['replies'][0][
                    'addDocumentTab']['tabProperties']['tabId']
                await probe.call(0, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'text': 'Before\n\nAnchor\n\nTail',
                })
                document = await native()
                source = document_tab(document, tab_id)['body']['content'][-1]
                await probe.batch([{'updateParagraphStyle': {
                    'range': {'startIndex': 1,
                              'endIndex': source['endIndex'] - 1,
                              'tabId': tab_id},
                    'paragraphStyle': {
                        'spaceAbove': {'magnitude': 12, 'unit': 'PT'},
                        'spaceBelow': {'magnitude': 24, 'unit': 'PT'},
                    },
                    'fields': 'spaceAbove,spaceBelow',
                }}], document)
                seeded = document_tab(await native(), tab_id)
                markup = (
                    '<table><tr><th align="center">Header</th><th></th></tr>'
                    '<tr><td align="center"><b>bold😀</b><br><i>line</i></td>'
                    '<td></td></tr></table>'
                    if html else '| Header | |\n| :---: | --- |\n'
                    '| **bold😀**<br>*line* | |'
                )
                arguments = {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'text': 'Inserted before\n\n' + markup +
                            '\n\nInserted after',
                }
                if tool != 'docs_append':
                    arguments['anchor'] = 'Anchor'
                await probe.call(0, tool, arguments)
                updated = document_tab(await native(), tab_id)
                content = updated['body']['content']
                table, = [item['table'] for item in content if 'table' in item]
                rows = [row['tableCells'] for row in table['tableRows']]
                assert [[paragraph_text(cell['content'][0]) for cell in row]
                        for row in rows] == [
                    ['Header\n', '\n'], ['bold😀\vline\n', '\n'],
                ]
                for row in rows:
                    for cell in row:
                        paragraph = cell['content'][0]['paragraph']
                        style = paragraph['paragraphStyle']
                        for key in ('spaceAbove', 'spaceBelow'):
                            assert style[key].get('magnitude', 0) == 0
                            assert style[key]['unit'] == 'PT'
                    assert row[0]['content'][0]['paragraph'][
                        'paragraphStyle']['alignment'] == 'CENTER'
                runs = rows[1][0]['content'][0]['paragraph']['elements']
                for label, flag in [('bold😀', 'bold'), ('line', 'italic')]:
                    assert any(label in run.get('textRun', {}).get(
                                   'content', '')
                               and run['textRun']['textStyle'].get(flag)
                               for run in runs)
                originals = [item for item in content
                             if paragraph_text(item).strip()
                             in {'Before', 'Anchor', 'Tail'}]
                expected = [item for item in seeded['body']['content']
                            if paragraph_text(item).strip()
                            in {'Before', 'Anchor', 'Tail'}]
                assert normalized(originals) == normalized(expected)
                for item in content:
                    if paragraph_text(item).strip().startswith('Inserted'):
                        style = item['paragraph']['paragraphStyle']
                        assert 'spaceAbove' not in style
                        assert 'spaceBelow' not in style
                assert updated['namedStyles'] == seeded['namedStyles']
                probe.report.update(
                    checks_passed=True,
                    normal_style=next(
                        s for s in seeded['namedStyles']['styles']
                        if s['namedStyleType'] == 'NORMAL_TEXT'),
                )
            finally:
                if tab_id is not None:
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
