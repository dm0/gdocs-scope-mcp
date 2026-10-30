"""Freeze the complete transport contract before package extraction."""


import asyncio
import hashlib
import json
from pathlib import Path

from fastmcp import Client

from gdocs_scope_mcp.documents import editing
from gdocs_scope_mcp.documents.native_models import GoogleDocument
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.rich_text import compiler
from gdocs_scope_mcp.server import mcp

from .refactor_contract_snapshot import capture_behavior


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
    # #47/#51 intentionally update list descriptions and instructions.
    assert hashlib.sha256(encoded).hexdigest() == (
        'df926aada2ab391918ebb225c2cda1eef6d99b8a35a6d65fc76695e71a0a0cd2'
    )


def test_rendering_requests_receipts_and_failures_match_baseline():
    """Compare exact outputs with the pre-refactor source snapshot."""
    expected = json.loads((Path(__file__).parent / 'fixtures'
                           / 'refactor_behavior.json').read_text())
    assert capture_behavior(
        GoogleDocument, compiler, editing, clients, 'get_service',
        ToolFailureError,
    ) == expected
