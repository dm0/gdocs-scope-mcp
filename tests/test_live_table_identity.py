"""Probe real table identity and revision races using two STDIO processes."""

import asyncio
import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from gdocs_scope_mcp.diagnostics import capture_server_info
from gdocs_scope_mcp.text_indices import utf16_length


def paragraph_text(item):
    """Read API text including native soft breaks and terminal newlines."""
    return ''.join(e.get('textRun', {}).get('content', '')
                   for e in item.get('paragraph', {}).get('elements', []))


def cells(table):
    """Enumerate physical cells and their verified native geometry."""
    return [(r, c, cell) for r, row in enumerate(table['table']['tableRows'])
            for c, cell in enumerate(row['tableCells'])]


def cell_text(cell):
    """Keep all paragraph breaks without inventing table separators."""
    return ''.join(paragraph_text(item) for item in cell['content'])


def span(cell, *, terminator=True):
    """Cover cell paragraphs, optionally excluding the mandatory newline."""
    return {'startIndex': cell['content'][0]['startIndex'],
            'endIndex': cell['content'][-1]['endIndex'] - int(not terminator)}


def named(document, range_id):
    """Resolve only a native ID; duplicate names and content are irrelevant."""
    return next((n for group in document.get('namedRanges', {}).values()
                 for n in group.get('namedRanges', [])
                 if n['namedRangeId'] == range_id), None)


def containing_cells(document, binding):
    """Observe containment without claiming a marker is a stable cell ID."""
    if binding is None:
        return []
    result = []
    for table_number, table in enumerate(
        item for item in document['body']['content'] if 'table' in item
    ):
        for row, column, cell in cells(table):
            bounds = span(cell)
            if any(bounds['startIndex'] <= s['startIndex']
                   and s['endIndex'] <= bounds['endIndex']
                   for s in binding.get('ranges', [])):
                result.append([table_number, row, column])
    return result


def replacement(cell, text):
    """Replace cell text while retaining the mandatory paragraph newline."""
    bounds = span(cell, terminator=False)
    requests = []
    if bounds['endIndex'] > bounds['startIndex']:
        requests.append({'deleteContentRange': {'range': bounds}})
    if text:
        requests.append({'insertText': {
            'location': {'index': bounds['startIndex']}, 'text': text,
        }})
    return requests


class Probe:
    """Coordinate interleavings without process-local server state."""

    def __init__(self, first, second, report):
        """Retain clients and sanitized observations for one bounded run."""
        self.clients = (first, second)
        self.report = report
        self.bindings = {}
        self.start = None
        self.initial_body = None

    async def call(self, client, tool, arguments=None):
        """Require MCP success, including observed API rejections."""
        result = await self.clients[client].call_tool(tool, arguments or {})
        assert not result.is_error
        return result.structured_content

    async def read(self, client=0):
        """Fetch a current native snapshot from the selected process."""
        return await self.call(client, 'probe_document')

    async def batch(self, requests, document, *, client=0, target=False,
                    accepted=True):
        """Use a chosen snapshot, making stale revision tests deterministic."""
        key = 'targetRevisionId' if target else 'requiredRevisionId'
        result = await self.call(client, 'probe_batch', {
            'requests': requests,
            'write_control': {key: document['revisionId']},
        })
        if accepted is not None:
            assert result['accepted'] is accepted, result
        return result

    def tables(self, document):
        """Inspect only the tables appended by this probe."""
        return [item for item in document['body']['content']
                if 'table' in item and item['startIndex'] > self.start]

    async def seed(self, doc_id):
        """Create identical tables without visible ID markers."""
        before = await self.read()
        self.initial_body = before['body']
        self.start = before['body']['content'][-1]['endIndex'] - 1
        table = ('| same | same |\n| --- | --- |\n'
                 '| duplicate😀<br>soft | duplicate😀<br>soft |\n| | |')
        await self.call(0, 'docs_append', {
            'doc_id': doc_id, 'text': table + '\n\n' + table,
        })
        document = await self.read()
        tables = self.tables(document)
        expected_tables = 2
        assert len(tables) == expected_tables
        assert [[cell_text(c) for _, _, c in cells(t)] for t in tables] == [
            ['same\n', 'same\n', 'duplicate😀\u000bsoft\n',
             'duplicate😀\u000bsoft\n', '\n', '\n'],
        ] * expected_tables
        return document

    async def bind(self, label, bounds, document, *, accepted=True):
        """Record native IDs locally and use namespaced metadata only."""
        result = await self.batch([{'createNamedRange': {
            'name': 'table-probe:' + uuid.uuid4().hex, 'range': bounds,
        }}], document, accepted=accepted)
        if accepted:
            self.bindings[label] = result['response']['replies'][0][
                'createNamedRange']['namedRangeId']
        return await self.read()

    def observe(self, label, document):
        """Save synthetic cell values and relative ranges, omitting all IDs."""
        tables = self.tables(document)
        entry = {'tables': [{
            'rows': t['table']['rows'], 'columns': t['table']['columns'],
            'cells': [{
                'row': r, 'column': c, 'text': cell_text(cell),
                'row_span': cell['tableCellStyle']['rowSpan'],
                'column_span': cell['tableCellStyle']['columnSpan'],
            } for r, c, cell in cells(t)],
        } for t in tables], 'bindings': {}}
        origin = self.start
        for name, range_id in self.bindings.items():
            binding = named(document, range_id)
            entry['bindings'][name] = {
                'exists': binding is not None,
                'ranges': [{'start': r['startIndex'] - origin,
                            'end': r['endIndex'] - origin}
                           for r in binding.get('ranges', [])]
                if binding else [],
                'containing_cells': containing_cells(
                    {'body': {'content': tables}}, binding,
                ),
            }
        self.report[label] = entry

    async def cleanup(self):
        """Remove the appended region while retaining earlier test content."""
        if self.start is None:
            return
        document = await self.read()
        end = document['body']['content'][-1]['endIndex'] - 1
        requests = [{'deleteNamedRange': {'namedRangeId': range_id}}
                    for range_id in self.bindings.values()
                    if named(document, range_id)]
        if end > self.start:
            requests.append({'deleteContentRange': {'range': {
                'startIndex': self.start, 'endIndex': end,
            }}})
        if requests:
            await self.batch(requests, document)
        cleaned = await self.read()
        assert cleaned['body'] == self.initial_body
        assert all(named(cleaned, range_id) is None
                   for range_id in self.bindings.values())
        self.report['cleanup_passed'] = True


@pytest.fixture
def table_probe(live_test_doc):
    """Open two test-only MCP servers and always close and reap both."""
    @asynccontextmanager
    async def connect(name):
        repo = Path(__file__).resolve().parents[1]
        launcher = repo / 'tests/probes/table_server.py'
        report = {'servers': [], 'probe_server_sha256': hashlib.sha256(
            launcher.read_bytes(),
        ).hexdigest()}
        root = Path('/tmp/gdocs-scope-mcp-table-probe-' + name)
        transports = [StdioTransport(
            command=str(repo / '.venv/bin/fastmcp'),
            args=['run', str(launcher), '--transport', 'stdio'],
            cwd=str(repo), env={
                **os.environ,
                'GDOCS_SCOPE_MCP_LIVE_TEST_DOC': live_test_doc,
            },
            log_file=root.with_suffix(f'.{i}.log'), keep_alive=False,
        ) for i in range(2)]
        try:
            async with Client(transports[0]) as first, Client(
                transports[1],
            ) as second:
                for client in (first, second):
                    result = await client.call_tool('server_info', {})
                    info = result.structured_content
                    assert info['source_fingerprint'] == (
                        capture_server_info().source_fingerprint
                    )
                    assert info['package_path'] == str(
                        repo / 'src/gdocs_scope_mcp',
                    )
                    report['servers'].append(info)
                pids = [info['pid'] for info in report['servers']]
                assert len(set(pids)) == len(pids)
                probe = Probe(first, second, report)
                try:
                    yield probe
                finally:
                    await probe.cleanup()
        finally:
            for info in report['servers']:
                assert not Path(f'/proc/{info["pid"]}').exists()
            report['processes_reaped'] = True
            root.with_suffix('.json').write_text(json.dumps(report, indent=2))
    return connect


def table_location(table, row, column):
    """Build fresh native row/column locations for structural API probes."""
    return {'tableStartLocation': {'index': table['startIndex']},
            'rowIndex': row, 'columnIndex': column}


def assert_lifecycle_observations(report):
    """Detect changes to captured API behavior without exposing native IDs."""
    fixture = json.loads((Path(__file__).parent / 'fixtures' /
                          'table_identity_observations.json').read_text())
    for step, bindings in fixture['lifecycle'].items():
        for label, expected in bindings.items():
            actual = report[step]['bindings'][label]
            if isinstance(expected, bool):
                assert actual['exists'] is expected, (step, label, actual)
            else:
                assert actual['exists'], (step, label)
                assert actual['containing_cells'] == [expected], (
                    step, label, actual,
                )
    for step in ['replace', 'clear', 'refill']:
        bounds = report[step]['bindings']['cell']['ranges']
        assert len(bounds) == 1
        assert bounds[0]['end'] - bounds[0]['start'] == 1
    before = report['baseline']['bindings']['whole']['ranges'][0]['start']
    after = report['text_before_table']['bindings']['whole']['ranges'][0][
        'start']
    assert after - before == utf16_length('Outside edit😀\n')
    for step in ['merge', 'unmerge']:
        row = [c for c in report[step]['tables'][0]['cells'] if c['row'] == 1]
        assert [c['text'] for c in row] == [fixture['merged_head'],
                                           fixture['merged_placeholder']]
        assert row[0]['column_span'] == (2 if step == 'merge' else 1)


def test_live_named_range_lifecycle(live_test_doc, table_probe):
    """Observe named ranges through cell and structural transformations."""
    async def run():
        async with table_probe('lifecycle') as probe:
            document = await probe.seed(live_test_doc)
            first, second = probe.tables(document)
            for label, bounds in [
                ('whole', {'startIndex': first['startIndex'],
                           'endIndex': first['endIndex']}),
                ('other', {'startIndex': second['startIndex'],
                           'endIndex': second['endIndex']}),
                ('text', span(first['table']['tableRows'][1][
                    'tableCells'][1], terminator=False)),
                ('cell', span(first['table']['tableRows'][1][
                    'tableCells'][1])),
                ('empty', span(first['table']['tableRows'][2][
                    'tableCells'][1])),
                ('row_anchor', span(first['table']['tableRows'][2][
                    'tableCells'][0])),
            ]:
                document = await probe.bind(label, bounds, document)
            empty = first['table']['tableRows'][2]['tableCells'][0]
            assert len(set(probe.bindings.values())) == len(probe.bindings)
            await probe.bind('zero_width', span(empty, terminator=False),
                             document, accepted=False)
            probe.observe('baseline', document)
            # Shift every table index without changing cell contents.
            await probe.batch([{'insertText': {
                'location': {'index': first['startIndex'] - 1},
                'text': 'Outside edit😀\n',
            }}], document, client=1)
            document = await probe.read()
            probe.observe('text_before_table', document)
            for label, new_text in [('replace', 'changed😀\u000bsoft'),
                                    ('clear', ''), ('refill', 'refilled😀')]:
                first = probe.tables(document)[0]
                cell = first['table']['tableRows'][1]['tableCells'][1]
                await probe.batch(replacement(cell, new_text), document)
                document = await probe.read(1)
                probe.observe(label, document)
            for operation in ['insert_row', 'delete_row',
                              'insert_column', 'delete_column',
                              'merge', 'unmerge', 'delete_target_column',
                              'delete_empty_row', 'delete_table']:
                first = probe.tables(document)[0]
                location = table_location(first, 0, 0)
                if operation == 'insert_row':
                    request = {'insertTableRow': {
                        'tableCellLocation': location, 'insertBelow': False,
                    }}
                elif operation == 'delete_row':
                    request = {'deleteTableRow': {
                        'tableCellLocation': location,
                    }}
                elif operation == 'insert_column':
                    request = {'insertTableColumn': {
                        'tableCellLocation': location, 'insertRight': False,
                    }}
                elif operation in {'delete_column', 'delete_target_column'}:
                    location['columnIndex'] = int(
                        operation != 'delete_column',
                    )
                    request = {'deleteTableColumn': {
                        'tableCellLocation': location,
                    }}
                elif operation in {'merge', 'unmerge'}:
                    location['rowIndex'] = 1
                    request = {('mergeTableCells' if operation == 'merge'
                                else 'unmergeTableCells'): {'tableRange': {
                        'tableCellLocation': location,
                        'rowSpan': 1, 'columnSpan': 2,
                    }}}
                elif operation == 'delete_empty_row':
                    location['rowIndex'] = 2
                    request = {'deleteTableRow': {
                        'tableCellLocation': location,
                    }}
                else:
                    request = {'deleteContentRange': {'range': {
                        'startIndex': first['startIndex'] - 1,
                        'endIndex': first['endIndex'],
                    }}}
                await probe.batch([request], document, client=1)
                document = await probe.read()
                probe.observe(operation, document)
            assert named(document, probe.bindings['other']) is not None
            assert_lifecycle_observations(probe.report)
            probe.report['checks_passed'] = True
    asyncio.run(run())


def test_live_revision_interleavings(live_test_doc, table_probe):
    """Reject stale writes and rebase independent edits after validation."""
    async def run():
        async with table_probe('revisions') as probe:
            baseline = await probe.seed(live_test_doc)
            table = probe.tables(baseline)[0]
            target = table['table']['tableRows'][1]['tableCells'][1]
            baseline = await probe.bind('target', span(target), baseline)
            stale = await probe.read(1)
            first_cell = probe.tables(baseline)[0]['table']['tableRows'][1][
                'tableCells'][0]
            await probe.batch(replacement(first_cell, 'A changed😀'), baseline)
            changed = await probe.read()
            await probe.batch(replacement(target, 'B stale'), stale, client=1,
                              accepted=False)
            assert (await probe.read())['body'] == changed['body']
            binding = named(changed, probe.bindings['target'])
            located = containing_cells(changed, binding)
            assert len(located) == 1
            _, row, column = located[0]
            rebased = probe.tables(changed)[0]['table']['tableRows'][row][
                'tableCells'][column]
            assert cell_text(rebased) == cell_text(target)
            await probe.batch(replacement(rebased, 'B rebased🦷'), changed,
                              client=1)
            changed = await probe.read()
            probe.observe('required_revision_rebase', changed)
            values = [cell_text(c) for _, _, c in cells(
                probe.tables(changed)[0],
            )]
            assert 'A changed😀\n' in values
            assert 'B rebased🦷\n' in values
            # Invalid second request must roll back the valid first request.
            table = probe.tables(changed)[0]
            good = table['table']['tableRows'][0]['tableCells'][0]
            await probe.batch([
                {'insertText': {
                    'location': {'index': span(good)['startIndex']},
                    'text': 'ATOMIC_FAILURE',
                }},
                {'deleteContentRange': {'range': {
                    'startIndex': 0, 'endIndex': 999999999,
                }}},
            ], changed, accepted=False)
            assert (await probe.read())['body'] == changed['body']
            probe.report['invalid_batch_atomic'] = True
            # Server-side targetRevisionId rebases without semantic checking.
            old = await probe.read(1)
            table = probe.tables(old)[1]
            a, b = table['table']['tableRows'][1]['tableCells']
            await probe.batch(replacement(a, 'TARGET_A😀'), old)
            await probe.batch(replacement(b, 'TARGET_B🦷'), old, client=1,
                              target=True)
            changed = await probe.read()
            probe.observe('target_revision_independent', changed)
            values = [cell_text(c) for _, _, c in cells(
                probe.tables(changed)[1],
            )]
            assert 'TARGET_A😀\n' in values
            assert 'TARGET_B🦷\n' in values
            # targetRevisionId also accepts overlapping edits. Record its
            # server-chosen ordering, not an assumed semantic conflict check.
            old = await probe.read()
            overlap = probe.tables(old)[1]['table']['tableRows'][0][
                'tableCells'][0]
            position = span(overlap)['startIndex'] + 1
            for client, value in [(0, 'X-'), (1, 'Y-')]:
                await probe.batch([{'insertText': {
                    'location': {'index': position}, 'text': value,
                }}], old, client=client, target=True)
            changed = await probe.read()
            probe.observe('target_revision_overlap', changed)
            overlap = probe.tables(changed)[1]['table']['tableRows'][0][
                'tableCells'][0]
            assert 'X-' in cell_text(overlap) and 'Y-' in cell_text(overlap)

            # Submit two genuine simultaneous CAS writes from separate servers.
            document = await probe.read()
            table = probe.tables(document)[0]
            for index, cell in enumerate(table['table']['tableRows'][0][
                'tableCells']):
                document = await probe.bind('race_' + str(index),
                                             span(cell), document)
            base = await probe.read()
            row_cells = probe.tables(base)[0]['table']['tableRows'][0][
                'tableCells']
            requests = [[{'insertText': {
                'location': {'index': span(cell)['startIndex'] + 1},
                'text': f'RACE_{index}😀',
            }}] for index, cell in enumerate(row_cells)]
            outcomes = await asyncio.gather(*(
                probe.batch(request, base, client=index, accepted=None)
                for index, request in enumerate(requests)
            ))
            assert sum(result['accepted'] for result in outcomes) == 1
            loser = next(i for i, result in enumerate(outcomes)
                         if not result['accepted'])
            current = await probe.read(loser)
            binding = named(current, probe.bindings['race_' + str(loser)])
            coordinate = containing_cells(current, binding)
            assert len(coordinate) == 1
            _, row, column = coordinate[0]
            fresh = probe.tables(current)[0]['table']['tableRows'][row][
                'tableCells'][column]
            assert cell_text(fresh) == cell_text(row_cells[loser])
            await probe.batch([{'insertText': {
                'location': {'index': span(fresh)['startIndex'] + 1},
                'text': f'RACE_{loser}😀',
            }}], current, client=loser)
            current = await probe.read()
            for index, cell in enumerate(probe.tables(current)[0][
                'table']['tableRows'][0]['tableCells']):
                assert cell_text(cell).count(f'RACE_{index}😀') == 1
            probe.observe('simultaneous_required_revision', current)
            probe.report['simultaneous_acceptance'] = [
                result['accepted'] for result in outcomes
            ]
            probe.report['checks_passed'] = True
    asyncio.run(run())


def test_replacement_keeps_utf16_cell_terminator():
    """Test request planning offline before it can touch a document."""
    cell = {'content': [{'startIndex': 10, 'endIndex': 16}]}
    assert replacement(cell, '😀') == [
        {'deleteContentRange': {'range': {'startIndex': 10, 'endIndex': 15}}},
        {'insertText': {'location': {'index': 10}, 'text': '😀'}},
    ]
    assert utf16_length('😀') == 2  # noqa: PLR2004


def test_cell_identity_does_not_fall_back_to_duplicate_text():
    """Missing IDs stay missing even when all cells look alike."""
    document = {'namedRanges': {'duplicate': {'namedRanges': [{
        'namedRangeId': 'other', 'ranges': [{'startIndex': 1, 'endIndex': 2}],
    }]}}}
    assert named(document, 'deleted') is None
    assert containing_cells(document, None) == []


async def raced_edit(probe, tool, arguments, mutation,
                     arm='probe_pause_read'):
    """Force a separate process to write inside a public edit's read window."""
    await probe.call(1, arm)
    task = asyncio.create_task(probe.clients[1].call_tool(
        tool, arguments, raise_on_error=False,
    ))
    try:
        async with asyncio.timeout(25):
            while not (await probe.call(1, 'probe_read_gate'))['ready']:
                await asyncio.sleep(0.05)
            await mutation()
    finally:
        await probe.call(1, 'probe_release_read')
    return await asyncio.wait_for(task, timeout=30)


@pytest.mark.parametrize('scenario', ['shift', 'overlap', 'append', 'table'])
def test_live_public_edit_revision_race(live_test_doc, table_probe, scenario):
    """Exercise actual guarded public tools, not only raw API probes."""
    async def run():
        async with table_probe('public-' + scenario) as probe:
            before = await probe.read()
            probe.initial_body = before['body']
            probe.start = before['body']['content'][-1]['endIndex'] - 1
            await probe.call(0, 'docs_append', {
                'doc_id': live_test_doc,
                'text': 'Guard prefix😀\n\n### Guard scope\n\n'
                        'Guard target 🦷 phrase\n\nGuard independent\n\n'
                        'Guard tail',
            })
            native = await probe.read()
            heading = next(item['paragraph']['paragraphStyle']['headingId']
                           for item in native['body']['content']
                           if paragraph_text(item) == 'Guard scope\n')
            arguments = {'doc_id': live_test_doc}
            arm = 'probe_pause_read'
            if scenario in {'append', 'table'}:
                tool = 'docs_append'
                arguments.update(text='Guard ours appended😀', rich=False)
                if scenario == 'table':
                    arguments.update(text='| Guard header |\n| --- |\n'
                                     '| Guard cell |', rich=True)
                    arm = 'probe_pause_table_lookup'

                async def mutation():
                    """Commit an independent append before the stale write."""
                    await probe.call(0, 'docs_append', {
                        'doc_id': live_test_doc,
                        'text': 'Guard collaborator appended🦷', 'rich': False,
                    })
            else:
                tool = 'docs_search_replace'
                arguments.update(find='Guard target 🦷 phrase',
                                 replace='Guard ours replacement😀',
                                 heading_id=heading)

                async def mutation():
                    """Either shift indices or overlap the original target."""
                    if scenario == 'shift':
                        await probe.call(0, 'docs_insert_before', {
                            'doc_id': live_test_doc,
                            'anchor': 'Guard prefix😀',
                            'text': 'Guard collaborator prefix🦷',
                            'rich': False,
                        })
                    else:
                        await probe.call(0, 'docs_search_replace', {
                            'doc_id': live_test_doc,
                            'find': 'Guard target 🦷 phrase',
                            'replace': 'Guard collaborator replacement😀',
                            'heading_id': heading,
                        })
            result = await raced_edit(probe, tool, arguments, mutation, arm)
            content = ''.join(paragraph_text(item) for item in (
                await probe.read())['body']['content'])
            if scenario == 'table':
                assert result.is_error
                assert result.structured_content['code'] == 'PARTIAL_WRITE'
                assert result.structured_content['committed_batches'] == 1
                native = await probe.read()
                assert len(probe.tables(native)) == 1
                assert 'Guard collaborator appended🦷' in content
                assert 'Guard header' not in content
            elif scenario == 'overlap':
                assert result.is_error
                assert result.structured_content['code'] == 'EDIT_CONFLICT'
                assert 'Guard collaborator replacement😀' in content
                assert 'Guard ours replacement😀' not in content
            elif scenario == 'append':
                assert not result.is_error, result.structured_content
                assert content.count('Guard ours appended😀') == 1
                assert content.count('Guard collaborator appended🦷') == 1
                assert content.index('Guard collaborator appended🦷') < (
                    content.index('Guard ours appended😀'))
            else:
                assert not result.is_error, result.structured_content
                assert 'Guard collaborator prefix🦷' in content
                assert content.count('Guard ours replacement😀') == 1
            probe.report['checks_passed'] = True
    asyncio.run(run())
