"""Exercise atomic table geometry and races across independent MCP servers."""

# Imported pytest fixtures are requested by name.
# ruff: noqa: F811
import asyncio

import pytest

from .test_live_table_identity import (
    cell_text,
    raced_edit,
    table_probe,  # noqa: F401
)
from .test_live_table_patch import discover


async def snapshot(probe, doc_id, ref, cells, *, deletion=False):
    """Read current state to prepare the next structural intent."""
    args = {'doc_id': doc_id, 'table_ref': ref, 'cells': cells}
    if deletion:
        args['fields'] = ['deletion']
    return await probe.call(0, 'docs_table_snapshot', args)


def arguments(doc_id, ref, base, operation):
    """Keep the original reference and expectations across interleavings."""
    return {'doc_id': doc_id, 'table_ref': ref,
            'base_token': base['base_token'], 'operation': operation}


def test_live_table_structure_sequence(live_test_doc, table_probe):
    """Check new refs, atomic failure and retention of neighboring tables."""
    async def run():
        async with table_probe('structure-sequence') as probe:
            await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            before = await probe.read()
            original = probe.tables(before)
            first_text = [[cell_text(c) for c in r['tableCells']]
                          for r in original[0]['table']['tableRows']]
            for operation, selected, dimensions in [
                ({'type': 'insert_rows', 'row': 1, 'position': 'before',
                  'count': 2}, ['A1'], (5, 2)),
                ({'type': 'insert_columns', 'column': 'B', 'position': 'after',
                  'count': 2}, ['A1'], (5, 4)),
                ({'type': 'delete_rows', 'row': 1, 'count': 2},
                 [f'{c}{r}' for r in (1, 2) for c in 'ABCD'], (3, 4)),
                ({'type': 'delete_columns', 'column': 'C', 'count': 2},
                 [f'{c}{r}' for r in (1, 2, 3) for c in 'CD'], (3, 2)),
            ]:
                base = await snapshot(probe, live_test_doc, ref, selected,
                                      deletion=operation['type'].startswith(
                                          'delete'))
                result = await probe.call(1, 'docs_table_structure', arguments(
                    live_test_doc, ref, base, operation,
                ))
                assert result['committed_batches'] == result['attempts'] == 1
                assert (result['rows'], result['columns']) == dimensions
                ref = result['table_ref']
                assert ref == await discover(probe, live_test_doc)
                native = probe.tables(await probe.read())[0]['table']
                assert (native['rows'], native['columns']) == dimensions
            native = await probe.read()
            restored = probe.tables(native)[0]['table']
            assert [[cell_text(c) for c in r['tableCells']]
                    for r in restored['tableRows']] == first_text
            base = await snapshot(probe, live_test_doc, ref, ['A1'])
            await probe.call(1, 'probe_fail_next_structure')
            failed = await probe.clients[1].call_tool(
                'docs_table_structure', arguments(live_test_doc, ref, base, {
                    'type': 'insert_rows', 'row': 1, 'position': 'after',
                    'count': 2,
                }), raise_on_error=False,
            )
            assert failed.is_error
            assert failed.structured_content['committed_batches'] == 0
            assert (await probe.read())['body'] == native['body']
            base = await snapshot(probe, live_test_doc, ref,
                                  [f'{c}{r}' for r in (1, 2, 3) for c in 'AB'],
                                  deletion=True)
            result = await probe.call(1, 'docs_table_structure', arguments(
                live_test_doc, ref, base, {'type': 'delete_table'},
            ))
            assert result['table_ref'] is None
            remaining = probe.tables(await probe.read())
            assert len(remaining) == 1
            assert [[cell_text(c) for c in r['tableCells']]
                    for r in remaining[0]['table']['tableRows']] == first_text
            probe.report['checks_passed'] = True
    asyncio.run(run())


@pytest.mark.parametrize('scenario', ['insert_text', 'delete_outside',
                                      'delete_overlap', 'same_boundary',
                                      'outside_shift'])
def test_live_structure_races(live_test_doc, table_probe, scenario):
    """Preserve compatible text changes and reject ambiguous new structure."""
    async def run():
        async with table_probe('structure-race-' + scenario,
                               revision_mode='target') as probe:
            await probe.seed(live_test_doc)
            ref = await discover(probe, live_test_doc)
            insertion = {'type': 'insert_rows', 'row': 1, 'position': 'after'}
            operation = (insertion if scenario in {'insert_text',
                                                   'same_boundary'} else
                         {'type': 'delete_rows', 'row': 1})
            base = await snapshot(probe, live_test_doc, ref, ['A1', 'B1'],
                                  deletion=True)

            async def mutation():
                """Change text or the exact same structural boundary."""
                if scenario == 'same_boundary':
                    await probe.call(0, 'docs_table_structure', arguments(
                        live_test_doc, ref, base, insertion,
                    ))
                elif scenario == 'outside_shift':
                    native = await probe.read()
                    first = probe.tables(native)[0]
                    await probe.batch([{'insertText': {
                        'location': {'index': first['startIndex'] - 1},
                        'text': 'Independent outside shift😀\n',
                    }}], native)
                else:
                    target = 'A1' if scenario == 'delete_overlap' else 'A2'
                    text = await snapshot(probe, live_test_doc, ref, [target])
                    await probe.call(0, 'docs_table_patch', {
                        'doc_id': live_test_doc, 'table_ref': ref,
                        'base_token': text['base_token'], 'changes': [{
                            'address': target, 'markdown': 'collaborator😀',
                        }],
                    })

            result = await raced_edit(probe, 'docs_table_structure', arguments(
                live_test_doc, ref, base, operation,
            ), mutation)
            if scenario in {'delete_overlap', 'same_boundary'}:
                assert result.is_error
                expected = ('EDIT_CONFLICT' if scenario == 'delete_overlap'
                            else 'TARGET_CHANGED')
                assert result.structured_content['code'] == expected
            else:
                assert not result.is_error, result.structured_content
                assert result.structured_content['attempts'] == 2  # noqa: PLR2004
                fresh_ref = result.structured_content['table_ref']
                assert fresh_ref == await discover(probe, live_test_doc)
                if scenario != 'outside_shift':
                    first = probe.tables(await probe.read())[0]['table']
                    index = 2 if scenario == 'insert_text' else 0
                    assert cell_text(first['tableRows'][index][
                        'tableCells'][0]) == 'collaborator😀\n'
            probe.report['checks_passed'] = True
    asyncio.run(run())
