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
                'instructions': client.initialize_result.instructions.replace(
                    '    docs_insert_at_heading Insert before/after a complete '
                    'heading subtree by ID\n', '',
                ),
                'tools': [tool.model_dump(mode='json', exclude_none=True)
                          for tool in await client.list_tools()
                          # #56 is additive; freeze all pre-existing contracts.
                          if tool.name != 'docs_insert_at_heading'],
            }

    data = asyncio.run(capture())
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    # #55 adds palette discovery, anchored formatting and color guidance.
    assert hashlib.sha256(encoded).hexdigest() == (
        'e6f03a5e7f95767885db0f6886814d4360cf93016ef7bca859a184c891992c10'
    )


def test_rendering_requests_receipts_and_failures_match_baseline():
    """Compare exact outputs with the pre-refactor source snapshot."""
    expected = json.loads((Path(__file__).parent / 'fixtures'
                           / 'refactor_behavior.json').read_text())
    assert capture_behavior(
        GoogleDocument, compiler, editing, clients, 'get_service',
        ToolFailureError,
    ) == expected
