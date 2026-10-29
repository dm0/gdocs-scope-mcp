"""Thin MCP adapters for diagnostics."""

# Preserve the exact public description after nesting registration functions.
# ruff: noqa: E501

from gdocs_scope_mcp.diagnostics import ServerInfo
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp, identity):
    """Register diagnostics tools in their established order."""

    @mcp.tool(
        output_schema=tool_response_schema(ServerInfo),
        title='Server info',
        annotations={
            'readOnlyHint': True,
            'destructiveHint': False,
            'openWorldHint': False,
            'idempotentHint': True,
        },
    )
    def server_info() -> ServerInfo:
        """Return startup identity and source fingerprint without Google access."""
        return identity()

