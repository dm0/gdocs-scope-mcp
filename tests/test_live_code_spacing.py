"""Verify native code spacing and cleanup through worktree STDIO servers."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from gdocs_scope_mcp.documents.snapshots import normalized
from gdocs_scope_mcp.text_indices import utf16_length

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


@pytest.mark.live
@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('spacing', [None, 1.5])
def test_live_code_spacing(live_test_doc, table_probe, monkeypatch, tool,
                           spacing):
    """Retain outside inheritance and explicitly zero every internal gap."""
    if spacing is not None:
        monkeypatch.setenv('GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING',
                           str(spacing))
    else:
        monkeypatch.delenv('GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING',
                           raising=False)
    expected_spacing = (1.15 if spacing is None else spacing) * 100
    blocks = ['single🦷', '\nfirst🦷\n\n\tlast  \n\n', '', '\n\n']
    markup = 'Inserted prose\n\n' + '\n\n'.join(
        f'```python\n{code}\n```' for code in blocks
    ) + '\n\nFinal prose'

    async def run():
        name = f'code-spacing-{tool}-{spacing}'
        async with table_probe(name) as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None

            async def native():
                """Read native ranges through the same isolated MCP server."""
                return await probe.call(0, 'probe_tabs_document')

            def selected(document):
                """Keep assertions within the disposable test tab."""
                return next(t['documentTab'] for t in document['tabs']
                            if t['tabProperties']['tabId'] == tab_id)

            try:
                result = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': name},
                }}], await native())
                tab_id = result['response']['replies'][0][
                    'addDocumentTab']['tabProperties']['tabId']
                await probe.batch([{'insertText': {
                    'location': {'index': 1, 'tabId': tab_id},
                    'text': 'Before\nAnchor\nTail',
                }}, {'updateParagraphStyle': {
                    'range': {'startIndex': 1, 'endIndex': 19,
                              'tabId': tab_id},
                    'paragraphStyle': {
                        'spaceAbove': {'magnitude': 36, 'unit': 'PT'},
                        'spaceBelow': {'magnitude': 48, 'unit': 'PT'},
                    }, 'fields': 'spaceAbove,spaceBelow',
                }}], await native())
                seeded = selected(await native())
                arguments = {'doc_id': live_test_doc, 'tab_id': tab_id,
                             'text': markup}
                if tool != 'docs_append':
                    arguments['anchor'] = 'Anchor'
                await probe.call(0, tool, arguments)
                updated = selected(await native())
                paragraphs = updated['body']['content']
                originals = [
                    p for p in paragraphs
                    if 'paragraph' not in p or paragraph_text(p).strip()
                    in {'Before', 'Anchor', 'Tail'}
                ]
                assert normalized(originals) == normalized(
                    seeded['body']['content'],
                )
                assert updated['namedStyles'] == seeded['namedStyles']
                markers = sorted((n['ranges'][0]
                                  for group in updated['namedRanges'].values()
                                  for n in group['namedRanges']),
                                 key=lambda r: r['startIndex'])
                assert len(markers) == len(blocks)
                for code, marker in zip(blocks, markers, strict=True):
                    start = marker['startIndex']
                    cursor = start
                    for index, line in enumerate(code.split('\n')):
                        row = next(p for p in paragraphs
                                   if p.get('startIndex') == cursor)
                        assert paragraph_text(row) == line + '\n'
                        style = row['paragraph']['paragraphStyle']
                        assert style['lineSpacing'] == pytest.approx(
                            expected_spacing,
                        )
                        assert ('spaceAbove' not in style if index == 0
                                else style['spaceAbove'].get('magnitude', 0)
                                == 0)
                        assert ('spaceBelow' not in style
                                if index == len(code.split('\n')) - 1
                                else style['spaceBelow'].get('magnitude', 0)
                                == 0)
                        cursor += utf16_length(line + '\n')
                for p in paragraphs:
                    if paragraph_text(p).strip() in {
                        'Inserted prose', 'Final prose',
                    }:
                        style = p['paragraph']['paragraphStyle']
                        assert not {
                            'lineSpacing', 'spaceAbove', 'spaceBelow',
                        } & style.keys()
                probe.report.update(checks_passed=True,
                                    expected_line_spacing=expected_spacing)
            finally:
                if tab_id is not None:
                    await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                      await native())
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
