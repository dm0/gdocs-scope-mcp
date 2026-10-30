"""Verify atomic patches and interleavings across STDIO MCP processes."""

# Imported pytest fixtures are requested by name in tests.
# ruff: noqa: F811
import asyncio

import pytest

from .test_live_table_identity import (
    cell_text,
    cells,
    raced_edit,
    span,
    table_location,
    table_probe,  # noqa: F401
)

pytestmark = pytest.mark.live


async def discover(probe, doc_id):
    """Select the first of two probe-owned tables by its returned ref."""
    listing = await probe.call(0, 'docs_tables_list', {'doc_id': doc_id})
    return listing['tables'][-2]['table_ref']


async def snapshot(probe, doc_id, ref, addresses, client=0):
    """Capture default text/style expectations from the chosen process."""
    return await probe.call(client, 'docs_table_snapshot', {
        'doc_id': doc_id, 'table_ref': ref, 'cells': addresses,
    })


def arguments(doc_id, ref, base, address, text):
    """Construct one typed patch against an agent's earlier snapshot."""
    return {'doc_id': doc_id, 'table_ref': ref,
            'base_token': base['base_token'],
            'changes': [{'address': address, 'markdown': text}]}


def test_live_rich_cell_patch_and_atomic_failure(live_test_doc, table_probe):
    """Preserve native properties and roll back an invalid atomic batch."""
    async def run():
        async with table_probe('rich-patch') as probe:
            native = await probe.seed(live_test_doc)
            table = probe.tables(native)[0]
            first = table['table']['tableRows'][1]['tableCells'][0]
            await probe.batch([
                {'updateTableCellStyle': {
                    'tableRange': {
                        'tableCellLocation': table_location(table, 1, 0),
                        'rowSpan': 1, 'columnSpan': 1,
                    },
                    'tableCellStyle': {'backgroundColor': {
                        'color': {'rgbColor': {'red': 0.8, 'green': 0.9}},
                    }}, 'fields': 'backgroundColor',
                }},
                {'updateParagraphStyle': {
                    'range': span(first),
                    'paragraphStyle': {'alignment': 'END'},
                    'fields': 'alignment',
                }},
                {'updateTextStyle': {
                    'range': span(first),
                    'textStyle': {'bold': True}, 'fields': 'bold',
                }},
                {'updateTextStyle': {
                    'range': span(first, terminator=False),
                    'textStyle': {'link': {
                        'url': 'https://example.com/old',
                    }}, 'fields': 'link',
                }},
            ], native)
            native = await probe.read()
            first = probe.tables(native)[0]['table']['tableRows'][1][
                'tableCells'][0]
            style = first['tableCellStyle']
            paragraph_style = first['content'][0]['paragraph'][
                'paragraphStyle']
            ref = await discover(probe, live_test_doc)
            base = await snapshot(probe, live_test_doc, ref,
                                  ['A2', 'B2', 'A3'])
            result = await probe.call(1, 'docs_table_patch', {
                'doc_id': live_test_doc, 'table_ref': ref,
                'base_token': base['base_token'], 'changes': [
                    {'address': 'A2', 'markdown':
                        'plain **bold😀** [new](https://example.com/new) '
                        '`code`<br>line'},
                    {'address': 'B2', 'markdown': ''},
                    {'address': 'A3', 'markdown': '*filled🦷*'},
                ],
            })
            assert result['committed_batches'] == result['attempts'] == 1
            native = await probe.read()
            table = probe.tables(native)[0]
            first = table['table']['tableRows'][1]['tableCells'][0]
            assert first['tableCellStyle'] == style
            assert first['content'][0]['paragraph']['paragraphStyle'] == (
                paragraph_style
            )
            assert cell_text(first) == 'plain bold😀 new code\vline\n'
            cleared = table['table']['tableRows'][1]['tableCells'][1]
            filled = table['table']['tableRows'][2]['tableCells'][0]
            assert cell_text(cleared) == '\n'
            assert cell_text(filled) == 'filled🦷\n'
            runs = first['content'][0]['paragraph']['elements']
            plain = next(r['textRun'] for r in runs
                         if r.get('textRun', {}).get('content', '').startswith(
                             'plain',
                         ))
            assert not plain.get('textStyle', {}).get('bold', False)
            assert not plain.get('textStyle', {}).get('link')
            assert any(r.get('textRun', {}).get('textStyle', {}).get('bold')
                       for r in runs)
            assert any(r.get('textRun', {}).get('textStyle', {}).get(
                'weightedFontFamily', {}).get('fontFamily') == 'Roboto Mono'
                       for r in runs)
            # A deliberately invalid second native request must roll back
            # all valid replacements from the public tool in the same batch.
            base = await snapshot(probe, live_test_doc, ref, ['A2', 'B2'])
            native = await probe.read()
            await probe.call(1, 'probe_fail_next_patch')
            result = await probe.clients[1].call_tool('docs_table_patch', {
                'doc_id': live_test_doc, 'table_ref': ref,
                'base_token': base['base_token'], 'changes': [
                    {'address': 'A2', 'markdown': 'must not commit'},
                    {'address': 'B2', 'markdown': 'neither may this'},
                ],
            }, raise_on_error=False)
            assert result.is_error
            assert result.structured_content['committed_batches'] == 0
            after = await probe.read()
            assert after['body'] == native['body']
            assert after['revisionId'] == native['revisionId']
            probe.report['checks_passed'] = True
    asyncio.run(run())


@pytest.mark.parametrize('scenario', ['independent', 'overlap', 'shift'])
def test_live_cell_patch_race(live_test_doc, table_probe, scenario):
    """Revalidate after another process commits inside the read window."""
    async def run():
        async with table_probe('patch-race-' + scenario,
                               revision_mode='target') as probe:
            await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            base = await snapshot(probe, live_test_doc, ref, ['A2', 'B2'])
            ours = arguments(live_test_doc, ref, base, 'B2', '**ours🦷**')

            async def mutation():
                """Commit an independent/overlapping cell or an index shift."""
                if scenario == 'shift':
                    native = await probe.read()
                    await probe.batch([{'insertText': {
                        'location': {'index': probe.tables(native)[0][
                            'startIndex'] - 1}, 'text': 'outside😀',
                    }}], native)
                else:
                    address = 'A2' if scenario == 'independent' else 'B2'
                    await probe.call(0, 'docs_table_patch', arguments(
                        live_test_doc, ref, base, address, 'collaborator😀',
                    ))

            result = await raced_edit(probe, 'docs_table_patch', ours,
                                      mutation)
            native = await probe.read()
            table = probe.tables(native)[0]
            a, b = table['table']['tableRows'][1]['tableCells']
            if scenario == 'overlap':
                assert result.is_error
                assert result.structured_content['code'] == 'EDIT_CONFLICT'
                assert cell_text(b) == 'collaborator😀\n'
                assert 'ours' not in cell_text(b)
            else:
                assert not result.is_error, result.structured_content
                assert result.structured_content['attempts'] == 2  # noqa: PLR2004
                assert cell_text(b) == 'ours🦷\n'
                if scenario == 'independent':
                    assert cell_text(a) == 'collaborator😀\n'
            probe.report['checks_passed'] = True
    asyncio.run(run())


def test_live_simultaneous_cell_patches(live_test_doc, table_probe):
    """Allow disjoint concurrent patches and reject one overlapping writer."""
    async def run():
        async with table_probe('simultaneous-patches') as probe:
            await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            base = await snapshot(probe, live_test_doc, ref, ['A2', 'B2'])
            outcomes = await asyncio.gather(*(
                probe.clients[i].call_tool('docs_table_patch', arguments(
                    live_test_doc, ref, base, address, f'writer-{i}😀',
                ), raise_on_error=False)
                for i, address in enumerate(['A2', 'B2'])
            ))
            assert all(not r.is_error for r in outcomes)
            native = await probe.read()
            values = [cell_text(c) for _, _, c in cells(
                probe.tables(native)[0],
            )]
            assert values[2:4] == ['writer-0😀\n', 'writer-1😀\n']
            base = await snapshot(probe, live_test_doc, ref, ['A2'])
            outcomes = await asyncio.gather(*(
                probe.clients[i].call_tool('docs_table_patch', arguments(
                    live_test_doc, ref, base, 'A2', f'winner-{i}🦷',
                ), raise_on_error=False) for i in range(2)
            ))
            assert sum(not r.is_error for r in outcomes) == 1
            loser = next(r for r in outcomes if r.is_error)
            assert loser.structured_content['code'] == 'EDIT_CONFLICT'
            native = await probe.read()
            row = probe.tables(native)[0]['table']['tableRows'][1]
            a, b = row['tableCells']
            assert cell_text(a) in {'winner-0🦷\n', 'winner-1🦷\n'}
            assert cell_text(b) == 'writer-1😀\n'
            probe.report['checks_passed'] = True
    asyncio.run(run())
