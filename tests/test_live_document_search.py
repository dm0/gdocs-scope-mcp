"""Verify escaped searches through an opt-in isolated STDIO MCP server."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get('GDOCS_SCOPE_MCP_LIVE_SEARCH') != '1',
    reason='Set GDOCS_SCOPE_MCP_LIVE_SEARCH=1 for bounded read-only searches.',
)
def test_live_escaped_document_search(isolated_mcp):
    """Send synthetic special characters without reading document contents."""
    marker = 'GDOCSSEARCH' + uuid.uuid4().hex
    log = Path('/tmp/gdocs-scope-mcp-literal-search.log')
    report = {'checks_passed': False, 'processes_reaped': False}

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            report['queries'] = []
            for suffix in (" quinn's paper\\essay", ' "quoted phrase"',
                           "' or trashed=true or name contains '"):
                query = marker + suffix
                result = await client.call_tool('docs_list', {
                    'query': query, 'limit': 1,
                })
                assert not result.is_error
                data = result.structured_content
                assert data['count'] == 0
                assert data['documents'] == []
                assert data['next_page_token'] is None
                report['queries'].append({'query': query, 'count': 0})
            report['checks_passed'] = True
        report['processes_reaped'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
