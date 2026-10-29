"""Carry application failures independently of the MCP transport."""


from gdocs_scope_mcp.contracts import EditFailedResponse


class ToolFailureError(ValueError):
    """Carry a structured failure while retaining ValueError compatibility."""

    def __init__(self, failure: EditFailedResponse):
        """Retain the recovery fields supplied by the application."""
        super().__init__(failure.description)
        self.failure = failure
