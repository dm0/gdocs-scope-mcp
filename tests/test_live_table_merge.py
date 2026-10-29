"""Verify native merge semantics and guarded merged-cell operations."""

# Imported pytest fixtures are requested by name.
# ruff: noqa: F811
import asyncio

import pytest

from .test_live_table_identity import (
    cell_text,
    raced_edit,
    replacement,
    table_location,
    table_probe,  # noqa: F401
)
from .test_live_table_patch import discover
from .test_live_table_structure import arguments


async def merge_snapshot(probe, doc_id, ref, cells):
    """Take expectations for complete participating logical heads."""
    return await probe.call(0, 'docs_table_snapshot', {
        'doc_id': doc_id, 'table_ref': ref, 'cells': cells,
        'fields': ['merge'],
    })


async def seed_text(probe, doc_id):
    """Create unique styled paragraphs and an independently editable row."""
    await probe.seed(doc_id)
    ref = await discover(probe, doc_id)
    addresses = ['A1', 'B1', 'A2', 'B2', 'A3', 'B3']
    base = await probe.call(0, 'docs_table_snapshot', {
        'doc_id': doc_id, 'table_ref': ref, 'cells': addresses,
    })
    await probe.call(0, 'docs_table_patch', {
        'doc_id': doc_id, 'table_ref': ref, 'base_token': base['base_token'],
        'changes': [{'address': a, 'markdown': value}
                    for a, value in zip(addresses, [
                        'A1 **bold**', 'B1 *italic*<br>soft', 'A2', '',
                        'Outside baseline', 'Outside B3',
                    ], strict=True)],
    })
    return ref


async def transform(probe, doc_id, ref, cells, kind, *, end='B2'):
    """Commit one rectangle and verify its authoritative returned ref."""
    base = await merge_snapshot(probe, doc_id, ref, cells)
    result = await probe.call(1, 'docs_table_structure', arguments(
        doc_id, ref, base, {'type': kind, 'start_cell': 'A1', 'end_cell': end},
    ))
    assert result['committed_batches'] == result['attempts'] == 1
    assert not result['reference_refresh_required']
    assert result['table_ref'] == await discover(probe, doc_id)
    return result['table_ref']


def test_live_native_merge_semantics(live_test_doc, table_probe):
    """Capture paragraph order, placeholders, styles and unmerge contents."""
    async def run():
        async with table_probe('merge-native') as probe:
            native = await probe.seed(live_test_doc)
            table = probe.tables(native)[0]
            cells = [c for r in table['table']['tableRows']
                     for c in r['tableCells']]
            requests = []
            for cell, value in reversed(list(zip(cells, [
                'A1 top\nA1 second', 'B1😀\u000bsoft', 'A2', '',
                'Outside A3', 'Outside B3',
            ], strict=True))):
                requests.extend(replacement(cell, value))
            await probe.batch(requests, native)
            native = await probe.read()
            first = probe.tables(native)[0]
            original_text = [cell_text(c) for r in first['table']['tableRows']
                             for c in r['tableCells']]
            request = {'tableRange': {
                'tableCellLocation': table_location(first, 0, 0),
                'rowSpan': 2, 'columnSpan': 2,
            }}
            await probe.batch([{'mergeTableCells': request}], native)
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            probe.report['merged_table'] = table
            head = table['tableRows'][0]['tableCells'][0]
            assert head['tableCellStyle']['rowSpan'] == 2  # noqa: PLR2004
            assert head['tableCellStyle']['columnSpan'] == 2  # noqa: PLR2004
            text = cell_text(head)
            assert all(value in text for value in original_text[:4])
            assert (text.index('A1 second') < text.index('B1😀') <
                    text.index('A2'))
            for row, column in [(0, 1), (1, 0), (1, 1)]:
                assert cell_text(table['tableRows'][row][
                    'tableCells'][column]) == '\n'
            assert [cell_text(c) for c in table['tableRows'][2][
                'tableCells']] == original_text[4:]
            first = probe.tables(native)[0]
            request['tableRange']['tableCellLocation'] = table_location(
                first, 0, 0,
            )
            await probe.batch([{'unmergeTableCells': request}], native)
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            probe.report['unmerged_table'] = table
            assert cell_text(table['tableRows'][0]['tableCells'][0]) == text
            for row, column in [(0, 1), (1, 0), (1, 1)]:
                assert cell_text(table['tableRows'][row][
                    'tableCells'][column]) == '\n'
            probe.report['checks_passed'] = True
    asyncio.run(run())


def test_live_public_merge_unmerge(live_test_doc, table_probe):
    """Retain text/styles, handle existing spans and reject atomic failure."""
    async def run():
        async with table_probe('merge-public') as probe:
            ref = await seed_text(probe, live_test_doc)
            colors = await probe.call(0, 'docs_table_snapshot', {
                'doc_id': live_test_doc, 'table_ref': ref,
                'cells': ['A1', 'B1'], 'fields': ['cell.background_color'],
            })
            await probe.call(0, 'docs_table_format', {
                'doc_id': live_test_doc, 'table_ref': ref,
                'base_token': colors['base_token'], 'changes': {'cells': [
                    {'address': 'A1', 'background_color': '#D9EAF7'},
                    {'address': 'B1', 'background_color': '#FFE0E0'},
                ]},
            })
            original = await probe.read()
            neighbor = probe.tables(original)[1]['table']
            ref = await transform(probe, live_test_doc, ref, ['A1', 'B1'],
                                  'merge_cells', end='B1')
            ref = await transform(probe, live_test_doc, ref,
                                  ['A1', 'A2', 'B2'], 'merge_cells')
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            head = table['tableRows'][0]['tableCells'][0]
            probe.report['merged_head_style'] = head['tableCellStyle']
            expected = 'A1 bold\nB1 italic\u000bsoft\nA2\n'
            assert cell_text(head) == expected
            runs = [e['textRun'] for p in head['content']
                    for e in p['paragraph']['elements'] if 'textRun' in e]
            assert any(r.get('textStyle', {}).get('bold') and
                       'bold' in r['content'] for r in runs)
            assert any(r.get('textStyle', {}).get('italic') and
                       'italic' in r['content'] for r in runs)
            base = await merge_snapshot(probe, live_test_doc, ref, ['A1'])
            rejected = await probe.clients[1].call_tool('docs_table_structure',
                arguments(live_test_doc, ref, base, {
                    'type': 'unmerge_cells', 'start_cell': 'A1',
                    'end_cell': 'A1',
                }), raise_on_error=False)
            assert rejected.is_error
            assert rejected.structured_content['code'] == 'INVALID_ARGUMENT'
            ref = await transform(probe, live_test_doc, ref, ['A1'],
                                  'unmerge_cells')
            table = probe.tables(await probe.read())[0]['table']
            probe.report['unmerged_cell_styles'] = [
                c['tableCellStyle'] for r in table['tableRows'][:2]
                for c in r['tableCells']
            ]
            assert cell_text(table['tableRows'][0][
                'tableCells'][0]) == expected
            for row, column in [(0, 1), (1, 0), (1, 1)]:
                assert cell_text(table['tableRows'][row][
                    'tableCells'][column]) == '\n'
            native = await probe.read()
            base = await merge_snapshot(probe, live_test_doc, ref,
                                        ['A3', 'B3'])
            await probe.call(1, 'probe_fail_next_structure')
            failed = await probe.clients[1].call_tool('docs_table_structure',
                arguments(live_test_doc, ref, base, {
                    'type': 'merge_cells', 'start_cell': 'A3',
                    'end_cell': 'B3',
                }), raise_on_error=False)
            assert failed.is_error
            assert failed.structured_content['committed_batches'] == 0
            assert (await probe.read())['body'] == native['body']
            current = probe.tables(native)[1]['table']
            assert [[cell_text(c) for c in row['tableCells']]
                    for row in current['tableRows']] == [
                        [cell_text(c) for c in row['tableCells']]
                        for row in neighbor['tableRows']]
            probe.report['checks_passed'] = True
    asyncio.run(run())


@pytest.mark.parametrize('scenario', ['merge_outside', 'merge_overlap',
                                      'merge_border', 'merge_structure',
                                      'unmerge_outside', 'unmerge_overlap',
                                      'receipt_race'])
def test_live_merge_races(live_test_doc, table_probe, scenario):
    """Revalidate original state and preserve a confirmed write receipt."""
    async def run():
        async with table_probe('merge-race-' + scenario,
                               revision_mode='target') as probe:
            ref = await seed_text(probe, live_test_doc)
            unmerge = scenario.startswith('unmerge')
            if unmerge:
                ref = await transform(probe, live_test_doc, ref,
                                      ['A1', 'B1', 'A2', 'B2'], 'merge_cells')
            addresses = ['A1'] if unmerge else ['A1', 'B1', 'A2', 'B2']
            base = await merge_snapshot(probe, live_test_doc, ref, addresses)
            operation = {'type': 'unmerge_cells' if unmerge else 'merge_cells',
                         'start_cell': 'A1', 'end_cell': (
                             'B3' if scenario == 'unmerge_outside' else 'B2')}

            async def mutation():
                """Use a separate server to change one known dependency."""
                if scenario == 'merge_structure':
                    plain = await probe.call(0, 'docs_table_snapshot', {
                        'doc_id': live_test_doc, 'table_ref': ref,
                        'cells': ['A3'],
                    })
                    await probe.call(0, 'docs_table_structure', arguments(
                        live_test_doc, ref, plain, {'type': 'insert_rows',
                            'row': 3, 'position': 'after'},
                    ))
                elif scenario == 'merge_border':
                    native = await probe.read()
                    first = probe.tables(native)[0]
                    await probe.batch([{'updateTableCellStyle': {
                        'tableRange': {'tableCellLocation': table_location(
                            first, 2, 0,
                        ), 'rowSpan': 1, 'columnSpan': 1},
                        'tableCellStyle': {'borderTop': {
                            'color': {'color': {'rgbColor': {'red': 1}}},
                            'width': {'magnitude': 3, 'unit': 'PT'},
                            'dashStyle': 'SOLID',
                        }}, 'fields': 'borderTop',
                    }}], native)
                else:
                    overlap = scenario.endswith('overlap')
                    await probe.call(0, 'docs_search_replace', {
                        'doc_id': live_test_doc,
                        'find': 'A1 bold' if overlap else 'Outside baseline',
                        'replace': 'collaborator😀',
                    })

            result = await raced_edit(probe, 'docs_table_structure', arguments(
                live_test_doc, ref, base, operation,
            ), mutation, arm=('probe_pause_structure_receipt'
                              if scenario == 'receipt_race' else
                              'probe_pause_read'))
            if scenario in {'merge_overlap', 'unmerge_overlap', 'merge_border',
                            'merge_structure'}:
                assert result.is_error
                expected = ('TARGET_CHANGED' if scenario == 'merge_structure'
                            else 'EDIT_CONFLICT')
                assert result.structured_content['code'] == expected
            else:
                assert not result.is_error, result.structured_content
                data = result.structured_content
                assert data['committed_batches'] == 1
                if scenario == 'receipt_race':
                    assert data['attempts'] == 1
                    assert data['reference_refresh_required']
                    assert data['table_ref'] is None
                else:
                    assert data['attempts'] == 2  # noqa: PLR2004
                    assert data['table_ref'] == await discover(
                        probe, live_test_doc,
                    )
                native = probe.tables(await probe.read())[0]['table']
                assert cell_text(native['tableRows'][2][
                    'tableCells'][0]) == 'collaborator😀\n'
                if scenario == 'receipt_race':
                    head = native['tableRows'][0]['tableCells'][0]
                    assert cell_text(head).count('A1 bold') == 1
            probe.report['checks_passed'] = True
    asyncio.run(run())
