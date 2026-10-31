"""Verify document-resident code markers through isolated STDIO processes."""

import asyncio
import json
import uuid
from html import unescape
from pathlib import Path

import pytest

from gdocs_scope_mcp.code_reading import MARKER_PREFIX
from gdocs_scope_mcp.documents import (
    fetching,
    tabs,
)
from gdocs_scope_mcp.google_api import clients

pytestmark = pytest.mark.live


def _markdown(result):
    """Join sections without normalizing code whitespace."""
    assert not result.is_error
    return ''.join(s['markdown'] for s in
                   result.structured_content['sections'])


@pytest.mark.parametrize('tool', ['docs_append', 'docs_insert_before',
                                 'docs_insert_after'])
def test_live_code_reads(live_test_doc, isolated_mcp, tool):
    """Persist language and whitespace across processes and internal edits."""
    marker = 'CODE_' + uuid.uuid4().hex
    log = Path(f'/tmp/gdocs-scope-mcp-code-{tool}.log')
    report = {'identities': []}
    code = f'{marker} = "{marker}😀"\n\n\treturn 1  \n'
    expected = f'```python\n{code}\n```'

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['identities'].append(info)
            if tool != 'docs_append':
                await client.call_tool('docs_append', {
                    'doc_id': live_test_doc, 'text': marker + ' anchor',
                    'rich': False,
                })
            arguments = {
                'doc_id': live_test_doc,
                'text': f'Before {marker} `inline😀`\n\n'
                f'```python\n{code}\n```\n\nAfter {marker}',
            }
            if tool != 'docs_append':
                arguments['anchor'] = marker + ' anchor'
            result = await client.call_tool(tool, arguments,
                                            raise_on_error=False)
            report['insertion'] = result.structured_content
            assert not result.is_error, report
            read = await client.call_tool('docs_read',
                                          {'doc_id': live_test_doc})
            markdown = _markdown(read)
            assert expected in markdown
            assert f'Before {marker} `inline😀`' in unescape(markdown)
            assert f'After {marker}' in unescape(markdown)
            await client.call_tool('docs_search_replace', {
                'doc_id': live_test_doc, 'find': f'"{marker}😀"',
                'replace': f'"{marker}🦷"',
            })
            # Use this block's unique prefix on later boundary operations.
            read = await client.call_tool('docs_read',
                                          {'doc_id': live_test_doc})
            assert expected.replace('😀', '🦷') in _markdown(read)
            report['interior_changed'] = True
            await client.call_tool('docs_search_replace', {
                'doc_id': live_test_doc, 'find': f'{marker} = "{marker}🦷"',
                'replace': marker + '_updated = 1',
            })
        # A first-line replacement can remove the marker's start boundary.
        # Incomplete markers must degrade to ordinary text.
        async with isolated_mcp(log.with_suffix('.second.log')) as session:
            client, info = session
            report['identities'].append(info)
            read = await client.call_tool('docs_read',
                                          {'doc_id': live_test_doc})
            markdown = _markdown(read)
            assert marker + '_updated = 1' in unescape(markdown)
            assert expected.replace('😀', '🦷') not in markdown
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))


def test_live_unmarked_code_heuristic(
    live_test_doc, isolated_mcp, monkeypatch,
):
    """Read externally styled text without adding markers during reads."""
    marker = 'UNMARKED_' + uuid.uuid4().hex
    log = Path('/tmp/gdocs-scope-mcp-code-heuristic.log')
    report = {}

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['writer'] = info
            result = await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'Before {marker}\n\n```python\n{marker}\n\n'
                f'  second\n```\n\nAfter {marker}',
            })
            assert not result.is_error
        service = clients.get_service()
        native = fetching.get_document(service, live_test_doc)
        ranges = native.get('namedRanges', {})
        # Remove only the marker of this test's appended block. This backend
        # setup simulates external formatting; reads still go through STDIO.
        matching = []
        for group in ranges.values():
            for named in group.get('namedRanges', []):
                if not named['name'].startswith(MARKER_PREFIX):
                    continue
                span = named['ranges'][0]
                for item in native['body']['content']:
                    if item.get('startIndex') != span['startIndex']:
                        continue
                    text = ''.join(e.get('textRun', {}).get('content', '')
                                   for e in item['paragraph']['elements'])
                    if marker in text:
                        matching.append(named['namedRangeId'])
        assert len(matching) == 1
        service.documents().batchUpdate(documentId=live_test_doc, body={
            'requests': tabs.scope_requests([
                {'deleteNamedRange': {'namedRangeId': matching[0]}},
            ], native['_mcp_tab_id']),
            'writeControl': {'requiredRevisionId': native['revisionId']},
        }).execute()
        monkeypatch.setenv('GDOCS_SCOPE_MCP_READ_CODE_BLOCK_HEURISTIC', 'true')
        async with isolated_mcp(log.with_suffix('.reader.log')) as session:
            client, info = session
            report['reader'] = info
            before = fetching.get_document(service, live_test_doc)[
                'revisionId']
            result = await client.call_tool('docs_read',
                                            {'doc_id': live_test_doc})
            markdown = _markdown(result)
            assert f'```\n{marker}\n\n  second\n```' in markdown
            assert f'Before {marker}' in unescape(markdown)
            assert f'After {marker}' in unescape(markdown)
            assert fetching.get_document(service, live_test_doc)[
                'revisionId'] == before
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))


@pytest.mark.parametrize('operation', ['before', 'after', 'delete',
                                      'copy', 'plain_copy'])
def test_live_code_marker_boundaries(live_test_doc, isolated_mcp, operation):
    """Observe range identity at boundaries, deletion, and copies."""
    marker = 'BOUNDARY_CODE_' + uuid.uuid4().hex
    log = Path(f'/tmp/gdocs-scope-mcp-code-boundary-{operation}.log')
    report = {}
    code = f'{marker}_first\n{marker}_last'
    expected = f'```python\n{code}\n```'

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'Before {marker}\n\n{expected}\n\nAfter {marker}',
            })
            if operation in {'before', 'after'}:
                await client.call_tool('docs_insert_' + operation, {
                    'doc_id': live_test_doc,
                    'anchor': marker + ('_first' if operation == 'before'
                                        else '_last'),
                    'text': 'Outside ' + marker,
                })
            elif operation == 'delete':
                await client.call_tool('docs_delete_paragraph', {
                    'doc_id': live_test_doc, 'anchor': marker + '_',
                })
            else:
                await client.call_tool('docs_append', {
                    'doc_id': live_test_doc,
                    'text': expected if operation == 'copy' else code,
                    'rich': operation == 'copy',
                })
            result = await client.call_tool('docs_read',
                                            {'doc_id': live_test_doc})
            markdown = _markdown(result)
            expected_count = (0 if operation == 'delete' else
                              2 if operation == 'copy' else 1)
            assert markdown.count(expected) == expected_count
            if operation in {'before', 'after'}:
                assert 'Outside ' + marker in unescape(markdown)
                assert f'```python\nOutside {marker}' not in markdown
            if operation == 'delete':
                assert marker + '_first' not in markdown
                assert marker + '_last' not in markdown
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
