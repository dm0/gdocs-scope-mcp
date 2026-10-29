"""Check code switches through independently configured STDIO servers."""

import asyncio
import json
import uuid
from pathlib import Path

from gdocs_scope_mcp.code_reading import MARKER_PREFIX
from gdocs_scope_mcp.documents import (
    fetching,
)
from gdocs_scope_mcp.google_api import clients


def _code_range_ids(document):
    """Observe only code metadata, excluding unrelated named ranges."""
    return {named['namedRangeId']
            for group in document.get('namedRanges', {}).values()
            for named in group.get('namedRanges', [])
            if named['name'].startswith(MARKER_PREFIX)}


def test_live_named_range_switch(live_test_doc, isolated_mcp, monkeypatch):
    """Disable marker reads/writes while retaining heuristics and styles."""
    log = Path('/tmp/gdocs-scope-mcp-code-option-named.log')
    report = {}
    marker = 'OPTION_' + uuid.uuid4().hex
    service = clients.get_service()
    baseline = _code_range_ids(fetching.get_document(service, live_test_doc))
    code = f'{marker} = 1\nreturn {marker}'

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['enabled'] = info
            await client.call_tool('docs_append', {
                'doc_id': live_test_doc, 'text': f'```python\n{code}\n```',
            })
        native = fetching.get_document(service, live_test_doc)
        added = _code_range_ids(native)
        assert len(added - baseline) == 1
        monkeypatch.setenv('GOOGLE_DOCS_MCP_CODE_BLOCK_NAMED_RANGES', 'false')
        async with isolated_mcp(log.with_suffix('.disabled.log')) as session:
            client, info = session
            report['disabled'] = info
            result = await client.call_tool('docs_read',
                                            {'doc_id': live_test_doc})
            assert not result.is_error
            markdown = ''.join(s['markdown'] for s in
                               result.structured_content['sections'])
            assert f'```\n{code}\n```' in markdown
            assert f'```python\n{code}\n```' not in markdown
            await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'After {marker}\n\n```python\n{marker}_new = 2\n```',
            })
        assert _code_range_ids(fetching.get_document(
            service, live_test_doc,
        )) == added
        report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))


def test_live_native_code_insertion_capability(live_test_doc, isolated_mcp):
    """Verify native delimiters cannot be inserted through the text API."""
    marker = 'NATIVE_PROBE_' + uuid.uuid4().hex
    log = Path('/tmp/gdocs-scope-mcp-code-native-insertion-probe.log')
    report = {}
    service = clients.get_service()
    before = fetching.get_document(service, live_test_doc)

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            result = await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'\ue907{marker} = 1\nreturn {marker}\n\ue907',
                'rich': False,
            })
            assert not result.is_error
            native = fetching.get_document(service, live_test_doc)
            texts = [''.join(e.get('textRun', {}).get('content', '')
                             for e in item.get('paragraph', {}).get(
                                 'elements', []))
                     for item in native['body']['content']]
            created = [text for text in texts if marker in text]
            expected_paragraphs = 2
            assert len(created) == expected_paragraphs
            assert all('\ue907' not in text for text in created)
            assert sum(text.count('\ue907') for text in texts) == sum(
                e.get('textRun', {}).get('content', '').count('\ue907')
                for item in before['body']['content']
                for e in item.get('paragraph', {}).get('elements', [])
            )
            assert _code_range_ids(native) == _code_range_ids(before)
            report['private_use_delimiters_stripped'] = True
            report['native_block_created'] = False
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
