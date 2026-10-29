"""Verify startup identity through a real in-process MCP connection."""


import asyncio
import os
from importlib.metadata import version

from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.diagnostics import capture_server_info


def test_server_info_keeps_startup_snapshot(tmp_path, monkeypatch):
    """Source edits affect the next snapshot, not an already running server."""
    source = tmp_path / 'example.py'
    source.write_text('before = True\n')
    startup = capture_server_info(tmp_path)
    monkeypatch.setattr(server, 'SERVER_INFO', startup)

    def unexpected_auth():
        raise AssertionError('server_info must not use Google credentials')

    monkeypatch.setattr(
        server.credentials, 'load_credentials', unexpected_auth,
    )

    async def check():
        async with Client(server.mcp) as client:
            initialization = client.initialize_result.model_dump(by_alias=True)
            assert initialization['serverInfo']['name'] == 'gdocs-scope-mcp'
            assert (
                initialization['serverInfo']['version']
                == version('gdocs-scope-mcp')
            )
            first = await client.call_tool('server_info')
            source.write_text('after = True\n')
            second = await client.call_tool('server_info')
            assert first.structured_content == second.structured_content
            return first.structured_content

    info = asyncio.run(check())

    assert info['package_version'] == version('gdocs-scope-mcp')
    assert info['pid'] == os.getpid()
    assert info['package_path'] == str(tmp_path)
    assert info['started_at']
    assert info['python_executable']
    assert info['fastmcp_version'] == version('fastmcp')
    assert info['source_fingerprint'] == startup.source_fingerprint
    assert (
        capture_server_info(tmp_path).source_fingerprint
        != startup.source_fingerprint
    )
