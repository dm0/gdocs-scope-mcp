"""Exercise the fixture's production MCP boundary in an isolated process."""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from .test_study_fixture_api import fixture_specification  # noqa: F401


def test_fixture_stdio_round_trip(fixture_specification, tmp_path):  # noqa: F811
    """Check real tool validation, native state and server process cleanup."""
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(fixture_specification))
    root = Path(__file__).parents[1]

    async def run():
        info = None
        transport = StdioTransport(
            command=sys.executable,
            args=[str(root / 'research/study_fixture_server.py')],
            cwd=str(root), env={
                **os.environ, 'GDOCS_STUDY_FIXTURE': str(path),
                'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': 'both',
            },
            log_file=tmp_path / 'fixture.stderr', keep_alive=False,
        )
        async with Client(transport) as client:
            info = (await client.call_tool('server_info', {})
                    ).structured_content
            await client.call_tool('docs_insert', {
                'doc_id': 'study_fixture', 'tab_id': 't.review',
                'target': {'position': 'append'}, 'text': 'New paragraph',
            })
            receipt = (await client.call_tool('docs_comment_status', {
                'doc_id': 'study_fixture', 'comment_id': 'c.review',
                'action': 'resolve',
            })).structured_content
            assert receipt['resolved']
            native = (await client.call_tool('study_native_snapshot', {})
                      ).structured_content
            assert native['comments'][0]['status'] == 'RESOLVED'
            assert 'New paragraph' in str(native['tabs'][1])
        assert not Path(f'/proc/{info["pid"]}').exists()
    asyncio.run(run())
