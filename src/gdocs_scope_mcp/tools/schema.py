"""Build the common success and failure MCP output union."""

from pydantic import BaseModel, TypeAdapter

from gdocs_scope_mcp.contracts import EditFailedResponse


def tool_response_schema(success_model: type[BaseModel]) -> dict:
    """Expose success/error objects without FastMCP's result wrapper."""
    schema = TypeAdapter(success_model | EditFailedResponse).json_schema(
        mode='serialization',
    )
    # Both branches are objects. Explicitly stating this prevents FastMCP
    # from treating the union as a non-object result that needs wrapping.
    return {'type': 'object', **schema}
