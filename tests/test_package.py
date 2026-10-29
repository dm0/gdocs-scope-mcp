"""Check installed entry points without starting or authenticating."""


import asyncio
from importlib.metadata import distribution

from gdocs_scope_mcp import auth_setup, server


def test_renamed_entry_points_load():
    """New commands resolve to the installed package's entry points."""
    expected = {
        'gdocs-scope-mcp': server.main,
        'gdocs-scope-mcp-auth': auth_setup.main,
    }
    entry_points = {
        entry.name: entry
        for entry in distribution('gdocs-scope-mcp').entry_points
        if entry.group == 'console_scripts'
    }

    assert set(entry_points) == set(expected)
    for name, target in expected.items():
        assert entry_points[name].load() is target


def test_probe_server_discovers_without_google_access(
    isolated_mcp, tmp_path, monkeypatch,
):
    """Validate live-test launchers and their seams without Google access."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_TOKEN', str(tmp_path / 'missing.json'))

    async def check():
        async with isolated_mcp(tmp_path / 'probe.log', probe=True) as session:
            client, _ = session
            names = {tool.name for tool in await client.list_tools()}
            assert {'server_info', 'docs_read', 'docs_append',
                    'probe_pause_table_lookup', 'probe_batch'} <= names
            gate = await client.call_tool('probe_read_gate', {})
            assert not gate.is_error
            assert gate.structured_content['armed'] is False

    asyncio.run(check())
