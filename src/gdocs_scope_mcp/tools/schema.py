"""Build the common success and failure MCP output union."""

from pydantic import BaseModel, TypeAdapter

from gdocs_scope_mcp.contracts import EditFailedResponse


def tool_response_schema(
    success_model: type[BaseModel], *,
    additional_failure: type[BaseModel] | None = None,
) -> dict:
    """Expose success/error objects without FastMCP's result wrapper."""
    response_type = success_model | EditFailedResponse
    if additional_failure is not None:
        response_type |= additional_failure
    schema = TypeAdapter(response_type).json_schema(
        mode='serialization',
    )
    # Both branches are objects. Explicitly stating this prevents FastMCP
    # from treating the union as a non-object result that needs wrapping.
    return {'type': 'object', **schema}
