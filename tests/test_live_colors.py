"""Verify native color writes/readback through isolated STDIO MCP servers."""

import asyncio

import pytest

from gdocs_scope_mcp.colors import GOOGLE_COLORS

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


def rgb_hex(optional):
    """Normalize independently observed native channels to bytes."""
    rgb = optional['color']['rgbColor']
    return '#' + ''.join(f'{round(rgb.get(key, 0) * 255):02X}'
                          for key in ('red', 'green', 'blue'))


@pytest.mark.live
def test_live_colors(live_test_doc, table_probe):
    """Check all palette entries, custom colors, fills, resets and tab safety."""
    async def run():
        async with table_probe('issue55-colors') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            async def native():
                return await probe.call(0, 'probe_tabs_document')
            def selected(document):
                return next(t['documentTab'] for t in document['tabs']
                            if t['tabProperties']['tabId'] == tab_id)
            try:
                result = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': 'Issue 55 colors'},
                }}], before)
                tab_id = result['response']['replies'][0]['addDocumentTab'][
                    'tabProperties']['tabId']
                palette = await probe.call(0, 'docs_get_color_palette')
                assert {c['name']: c['hex'] for row in palette['rows']
                        for c in row} == GOOGLE_COLORS
                markup = '\n\n'.join(
                    f'<p data-mcp-background-color="{name}">'
                    f'<span data-mcp-color="{name}" '
                    f'data-mcp-background-color="{name}">Palette {i}😀</span></p>'
                    for i, name in enumerate(GOOGLE_COLORS)
                )
                markup += ('\n\n<p data-mcp-background-color="light orange 2">'
                           '<b><span data-mcp-color="#123456">Target😀</span></b>'
                           ' neighbour</p>\n\n'
                           '<ul><li><p data-mcp-background-color="yellow">'
                           'List fill</p></li></ul>\n\n'
                           '<h3 data-mcp-background-color="light blue 2">'
                           'Heading fill</h3>\n\n'
                           '<table><tr><td><span data-mcp-color="red">'
                           'Cell target</span></td></tr></table>')
                await probe.call(0, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': tab_id, 'text': markup,
                })
                document = selected(await native())
                paragraphs = document['body']['content']
                rows = {paragraph_text(p).strip(): p for p in paragraphs
                        if 'paragraph' in p}
                for i, (name, value) in enumerate(GOOGLE_COLORS.items()):
                    paragraph = rows[f'Palette {i}😀']['paragraph']
                    assert rgb_hex(paragraph['paragraphStyle']['shading'][
                        'backgroundColor']) == value
                    run = next(e['textRun'] for e in paragraph['elements']
                               if e.get('textRun', {}).get('content', '').strip())
                    for key in ('foregroundColor', 'backgroundColor'):
                        optional = run.get('textStyle', {}).get(key)
                        if key == 'foregroundColor' and value == '#000000' and not optional:
                            # Google may omit a direct color equal to the
                            # inherited NORMAL_TEXT black baseline.
                            continue
                        assert optional, (i, name, key, run)
                        assert rgb_hex(optional) == value, (i, name, key, run)
                args = {'doc_id': live_test_doc, 'tab_id': tab_id,
                        'anchor_text': 'Target😀'}
                await probe.call(0, 'docs_format_text', {
                    **args, 'foreground_color': 'green',
                    'background_color': 'yellow',
                })
                await probe.call(0, 'docs_format_paragraph', {
                    **args, 'background_color': '#123456',
                })
                updated = selected(await native())
                target = next(p['paragraph'] for p in updated['body']['content']
                              if paragraph_text(p).strip() == 'Target😀 neighbour')
                assert rgb_hex(target['paragraphStyle']['shading'][
                    'backgroundColor']) == '#123456'
                run = next(e['textRun'] for e in target['elements']
                           if 'Target😀' in e.get('textRun', {}).get('content', ''))
                assert run['textStyle']['bold'] is True
                assert rgb_hex(run['textStyle']['foregroundColor']) == '#00FF00'
                assert rgb_hex(run['textStyle']['backgroundColor']) == '#FFFF00'
                read = await probe.call(1, 'docs_read', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                })
                rendered = ''.join(s['markdown'] for s in read['sections'])
                assert 'data-mcp-color="green"' in rendered
                assert 'data-mcp-background-color="#123456"' in rendered
                for tool in ('docs_format_text', 'docs_format_paragraph'):
                    arguments = {**args, 'background_color': 'reset'}
                    if tool == 'docs_format_text':
                        arguments['foreground_color'] = 'reset'
                    await probe.call(0, tool, arguments)
                reset = selected(await native())
                target = next(p['paragraph'] for p in reset['body']['content']
                              if paragraph_text(p).strip() == 'Target😀 neighbour')
                assert not target['paragraphStyle'].get('shading', {}).get(
                    'backgroundColor', {}).get('color')
                for element in target['elements']:
                    if 'Target😀' in element.get('textRun', {}).get('content', ''):
                        style = element['textRun'].get('textStyle', {})
                        assert style.get('bold') is True
                        assert not style.get('foregroundColor', {}).get('color')
                        assert not style.get('backgroundColor', {}).get('color')
                await probe.call(0, 'docs_format_paragraph', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'anchor_text': 'Cell target', 'background_color': 'cyan',
                })
                table = next(p['table'] for p in selected(await native())[
                    'body']['content'] if 'table' in p)
                cell = table['tableRows'][0]['tableCells'][0]
                assert rgb_hex(cell['content'][0]['paragraph']['paragraphStyle'][
                    'shading']['backgroundColor']) == '#00FFFF'
                assert not cell.get('tableCellStyle', {}).get('backgroundColor',
                                                            {}).get('color')
                probe.report.update(palette_entries_verified=80,
                                    checks_passed=True)
            finally:
                if tab_id is not None:
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
            assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
            probe.report['cleanup_passed'] = True
    asyncio.run(run())
