"""Verify native table style field masks before exposing formatting tools."""

# Imported pytest fixtures are requested by name in tests.
# Point values below are native API expectations, not implementation constants.
# ruff: noqa: F811, PLR2004
import asyncio

import pytest

from .test_live_table_identity import (
    cell_text,
    raced_edit,
    span,
    table_location,
    table_probe,  # noqa: F401
)
from .test_live_table_patch import discover


def test_live_native_table_format_fields(live_test_doc, table_probe):
    """Verify border/row/column styles and pinned row readback."""
    async def run():
        async with table_probe('format-native') as probe:
            native = await probe.seed(live_test_doc)
            table = probe.tables(native)[0]
            location = {'index': table['startIndex']}
            first = table['table']['tableRows'][0]['tableCells'][0]
            border = {'width': {'magnitude': 2, 'unit': 'PT'},
                      'color': {'color': {'rgbColor': {'red': 1}}},
                      'dashStyle': 'DASH'}
            await probe.batch([
                {'updateTableCellStyle': {
                    'tableRange': {
                        'tableCellLocation': table_location(table, 0, 0),
                        'rowSpan': 1, 'columnSpan': 1,
                    }, 'tableCellStyle': {
                        'borderRight': border,
                        'paddingTop': {'magnitude': 10, 'unit': 'PT'},
                        'contentAlignment': 'MIDDLE',
                    }, 'fields': 'borderRight,paddingTop,contentAlignment',
                }},
                {'updateParagraphStyle': {
                    'range': span(first),
                    'paragraphStyle': {'alignment': 'CENTER'},
                    'fields': 'alignment',
                }},
                {'updateTableColumnProperties': {
                    'tableStartLocation': location, 'columnIndices': [0],
                    'tableColumnProperties': {'widthType': 'FIXED_WIDTH',
                        'width': {'magnitude': 120, 'unit': 'PT'}},
                    'fields': 'widthType,width',
                }},
                {'updateTableRowStyle': {
                    'tableStartLocation': location, 'rowIndices': [1],
                    'tableRowStyle': {'minRowHeight': {
                        'magnitude': 36, 'unit': 'PT',
                    }}, 'fields': 'minRowHeight',
                }},
                {'pinTableHeaderRows': {
                    'tableStartLocation': location, 'pinnedHeaderRowsCount': 1,
                }},
            ], native)
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            first, second = table['tableRows'][0]['tableCells']
            probe.report['cell_styles'] = [first['tableCellStyle'],
                                            second['tableCellStyle']]
            assert first['tableCellStyle']['borderRight']['width'][
                'magnitude'] == 2
            assert second['tableCellStyle']['borderLeft']['width'][
                'magnitude'] == 2
            assert first['tableCellStyle']['paddingTop']['magnitude'] == 10
            assert first['tableCellStyle']['contentAlignment'] == 'MIDDLE'
            assert table['tableStyle']['tableColumnProperties'][0][
                'width']['magnitude'] == 120
            assert table['tableRows'][1]['tableRowStyle'][
                'minRowHeight']['magnitude'] == 36
            assert table['tableRows'][0]['tableRowStyle']['tableHeader']
            assert not table['tableRows'][1]['tableRowStyle'].get(
                'tableHeader',
            )
            probe.report['native_style_readback'] = table['tableStyle']
            probe.report['checks_passed'] = True
    asyncio.run(run())


async def style_snapshot(probe, doc_id, ref, cells, fields):
    """Get granular native properties and portable expectations."""
    return await probe.call(0, 'docs_table_snapshot', {
        'doc_id': doc_id, 'table_ref': ref, 'cells': cells, 'fields': fields,
    })


def format_args(doc_id, ref, base, changes):
    """Describe explicit formatting intent against an earlier snapshot."""
    return {'doc_id': doc_id, 'table_ref': ref,
            'base_token': base['base_token'], 'changes': changes}


def full_border(color, width=1):
    """Avoid guessing omitted inherited borders in live table fixtures."""
    return {'color': color, 'width': width, 'dash_style': 'SOLID'}


def test_live_table_format_and_pdf(live_test_doc, table_probe):
    """Read public styles, export a preview and check atomic failure."""
    async def run():
        async with table_probe('format-public') as probe:
            before = await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            addresses = ['A1', 'B1', 'A2', 'B2', 'A3', 'B3']
            text = await probe.call(0, 'docs_table_snapshot', {
                'doc_id': live_test_doc, 'table_ref': ref, 'cells': addresses,
            })
            await probe.call(0, 'docs_table_patch', {
                'doc_id': live_test_doc, 'table_ref': ref,
                'base_token': text['base_token'], 'changes': [
                    {'address': a, 'markdown': value} for a, value in zip(
                        addresses, ['**Item**', '**Amount**', 'Service plan',
                                    '42.00', '**Total**', '**42.00**'],
                        strict=True,
                    )
                ],
            })
            fields = ['cell.background_color', 'cell.vertical_alignment',
                      'cell.padding_top', 'cell.padding_bottom',
                      'cell.padding_left', 'cell.padding_right',
                      'cell.border_top', 'cell.border_bottom',
                      'cell.border_left', 'cell.border_right',
                      'paragraph.alignment', 'column.width', 'row.min_height',
                      'table.header_rows']
            base = await style_snapshot(probe, live_test_doc, ref, addresses,
                                        fields)
            colors = ['#D9EAF7'] * 2 + ['#FFFFFF'] * 2 + ['#EEF2F6'] * 2
            changes = {'cells': [{
                'address': a, 'background_color': shade,
                'vertical_alignment': 'MIDDLE',
                'horizontal_alignment': (
                    'END' if a.startswith('B') else 'START'),
                'padding_top': 8, 'padding_bottom': 8,
                'padding_left': 8, 'padding_right': 8,
                **{'border_' + side: full_border('#777777')
                   for side in ['top', 'bottom', 'left', 'right']},
            } for a, shade in zip(addresses, colors, strict=True)],
                       'columns': [{'column': 'A', 'width': 200},
                                   {'column': 'B', 'width': 140}],
                       'rows': [{'row': 2, 'min_height': 36}],
                       'header_rows': 1}
            result = await probe.call(1, 'docs_table_format', format_args(
                live_test_doc, ref, base, changes,
            ))
            assert result['committed_batches'] == result['attempts'] == 1
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            first, second = table['tableRows'][0]['tableCells']
            assert cell_text(first) == 'Item\n'
            assert cell_text(second) == 'Amount\n'
            assert first['tableCellStyle']['paddingTop']['magnitude'] == 8
            assert first['tableCellStyle']['contentAlignment'] == 'MIDDLE'
            assert first['content'][0]['paragraph']['paragraphStyle'][
                'alignment'] == 'START'
            assert second['content'][0]['paragraph']['paragraphStyle'][
                'alignment'] == 'END'
            widths = table['tableStyle']['tableColumnProperties']
            assert [c['width']['magnitude'] for c in widths] == [200, 140]
            assert table['tableRows'][0]['tableRowStyle']['tableHeader']
            assert table['tableRows'][1]['tableRowStyle'][
                'minRowHeight']['magnitude'] == 36
            exported = await probe.call(0, 'probe_export_pdf')
            probe.report['pdf_preview'] = exported
            # Verify explicit zero/default settings against fresh expectations.
            base = await style_snapshot(probe, live_test_doc, ref, ['A1'], [
                'cell.background_color', 'column.width', 'table.header_rows',
            ])
            await probe.call(1, 'docs_table_format', format_args(
                live_test_doc, ref, base, {
                    'cells': [{'address': 'A1',
                               'background_color': 'transparent'}],
                    'columns': [{'column': 'A', 'width': 'auto'}],
                    'header_rows': 0,
                },
            ))
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            assert table['tableStyle']['tableColumnProperties'][0][
                'widthType'] == 'EVENLY_DISTRIBUTED'
            assert not table['tableRows'][0]['tableRowStyle'].get(
                'tableHeader')
            assert not table['tableRows'][0]['tableCells'][0][
                'tableCellStyle'].get('backgroundColor')
            base = await style_snapshot(probe, live_test_doc, ref, ['A1'], [
                'cell.padding_top',
            ])
            native = await probe.read()
            await probe.call(1, 'probe_fail_next_format')
            failed = await probe.clients[1].call_tool('docs_table_format',
                format_args(live_test_doc, ref, base, {'cells': [{
                    'address': 'A1', 'padding_top': 99,
                }]}), raise_on_error=False)
            assert failed.is_error
            assert failed.structured_content['committed_batches'] == 0
            assert (await probe.read())['body'] == native['body']
            assert native.get('namedRanges', {}) == before.get(
                'namedRanges', {},
            )
            probe.report['checks_passed'] = True
    asyncio.run(run())


@pytest.mark.parametrize('scenario', ['text', 'property', 'overlap',
                                      'shared_border', 'column'])
def test_live_formatting_races(live_test_doc, table_probe, scenario):
    """Revalidate properties after another process wins the CAS."""
    async def run():
        async with table_probe('format-race-' + scenario,
                               revision_mode='target') as probe:
            await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            addresses = ['A1', 'B1', 'A2']
            fields = ['cell.background_color', 'cell.padding_top',
                      'cell.border_right', 'cell.border_left', 'column.width']
            base = await style_snapshot(probe, live_test_doc, ref, addresses,
                                        fields)
            ours = {'cells': [
                {'address': 'A2', 'background_color': '#FF0000'},
            ]}
            theirs = {'cells': [{'address': 'A2', 'padding_top': 12}]}
            if scenario == 'overlap':
                theirs = {'cells': [{'address': 'A2',
                                     'background_color': '#0000FF'}]}
            elif scenario == 'shared_border':
                ours = {'cells': [{'address': 'A1',
                    'border_right': full_border('#FF0000', 2)}]}
                theirs = {'cells': [{'address': 'B1',
                    'border_left': full_border('#0000FF', 3)}]}
            elif scenario == 'column':
                ours = {'columns': [{'column': 'A', 'width': 150}]}
                theirs = {'columns': [{'column': 'B', 'width': 140}]}

            async def mutation():
                """Commit a competing style request or text replacement."""
                if scenario == 'text':
                    text = await probe.call(0, 'docs_table_snapshot', {
                        'doc_id': live_test_doc, 'table_ref': ref,
                        'cells': ['A2'],
                    })
                    await probe.call(0, 'docs_table_patch', {
                        'doc_id': live_test_doc, 'table_ref': ref,
                        'base_token': text['base_token'], 'changes': [{
                            'address': 'A2', 'markdown': 'collaborator text',
                        }],
                    })
                else:
                    await probe.call(0, 'docs_table_format', format_args(
                        live_test_doc, ref, base, theirs,
                    ))

            result = await raced_edit(probe, 'docs_table_format', format_args(
                live_test_doc, ref, base, ours,
            ), mutation)
            native = await probe.read()
            table = probe.tables(native)[0]['table']
            if scenario in {'overlap', 'shared_border'}:
                assert result.is_error
                assert result.structured_content['code'] == 'EDIT_CONFLICT'
            else:
                assert not result.is_error, result.structured_content
                assert result.structured_content['attempts'] == 2
                a2 = table['tableRows'][1]['tableCells'][0]
                if scenario == 'text':
                    assert cell_text(a2) == 'collaborator text\n'
                elif scenario == 'property':
                    assert a2['tableCellStyle']['paddingTop'][
                        'magnitude'] == 12
                else:
                    widths = table['tableStyle']['tableColumnProperties']
                    assert [v['width']['magnitude'] for v in widths] == [
                        150, 140,
                    ]
            probe.report['checks_passed'] = True
    asyncio.run(run())
