"""Freeze the complete transport contract before package extraction."""


import asyncio
import hashlib
import json

from fastmcp import Client

from gdocs_scope_mcp.server import mcp


def test_complete_mcp_contract():
    """Preserve initialization text, tool order, metadata and every schema."""
    async def capture():
        async with Client(mcp) as client:
            return {
                'instructions': client.initialize_result.instructions,
                'tools': [tool.model_dump(mode='json', exclude_none=True)
                          for tool in await client.list_tools()],
            }

    data = asyncio.run(capture())
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == (
        '3c9aa0b8235257926bc41575c90169b07f1fd414ef7dccd6af00e5acc27b71b3'
    )
