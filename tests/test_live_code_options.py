"""Check code switches through independently configured STDIO servers."""

import asyncio
import json
import uuid
from pathlib import Path

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.code_reading import MARKER_PREFIX


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
    service = docs_edit._get_service()
    baseline = _code_range_ids(docs_edit._get_document(service, live_test_doc))
    code = f'{marker} = 1\nreturn {marker}'

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['enabled'] = info
            await client.call_tool('docs_append', {
                'doc_id': live_test_doc, 'text': f'```python\n{code}\n```',
            })
        native = docs_edit._get_document(service, live_test_doc)
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
        assert _code_range_ids(docs_edit._get_document(
            service, live_test_doc,
        )) == added
        report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
