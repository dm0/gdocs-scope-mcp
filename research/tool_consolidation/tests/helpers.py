"""Construct actual product tool catalogs for research checks."""

from fastmcp import FastMCP

from gdocs_scope_mcp.tool_logging import ToolCallLoggingMiddleware
from gdocs_scope_mcp.tools import comments, documents


def study_server(variant):
    """Create the actual adapters without importing product test modules."""
    server = FastMCP('study', middleware=[ToolCallLoggingMiddleware()])
    documents.register_editing(
        server, consolidated=variant in {'insertion', 'both'},
    )
    comments.register(server, consolidated=variant in {'status', 'both'})
    return server
