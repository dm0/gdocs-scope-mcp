"""Verify canonical environment settings through an isolated MCP server."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from gdocs_scope_mcp.google_api.credentials import STANDALONE_TOKEN_PATHS
from gdocs_scope_mcp.settings import default_token_path

pytestmark = pytest.mark.live


def test_live_canonical_environment(
    live_test_doc, isolated_mcp, monkeypatch, tmp_path,
):
    """Refresh an existing grant and read using only canonical overrides."""
    # Reuse the explicitly authorized local token configuration for the test.
    # The application itself has no lookup of the former environment name.
    configured = (os.environ.get('GDOCS_SCOPE_MCP_TOKEN')
                  or os.environ.get('GOOGLE_DOCS_MCP_TOKEN'))
    candidates = ([Path(configured)] if configured else
                  [default_token_path(), *STANDALONE_TOKEN_PATHS])
    token = next((path for path in candidates if path.is_file()), None)
    assert token is not None, 'Set GDOCS_SCOPE_MCP_TOKEN to a test token.'
    config = tmp_path / 'canonical-config.json'
    config.write_text('{"document_cache_enabled":false,'
                      '"write_revision_mode":"target"}')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', str(token))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CONFIG', str(config))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LOG_LEVEL', 'DEBUG')
    for name in ('GOOGLE_DOCS_MCP_TOKEN', 'GOOGLE_DRIVE_MCP_TOKEN',
                 'GOOGLE_DOCS_TOKEN_FILE', 'GOOGLE_DOCS_MCP_CONFIG'):
        monkeypatch.setenv(name, str(tmp_path / 'missing-legacy.json'))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_LOG_LEVEL', 'INVALID')
    log = Path('/tmp/gdocs-45-canonical-environment.log')
    report = {'checks_passed': False}

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            result = await client.call_tool('docs_get_tree', {
                'doc_id': live_test_doc,
            }, raise_on_error=False)
            assert not result.is_error, result.structured_content
            report['checks_passed'] = True
        report['process_reaped'] = True
        messages = log.read_text()
        assert 'tool=docs_get_tree status=started' in messages
        assert 'tool=docs_get_tree status=success' in messages
        report['canonical_debug_logging'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
