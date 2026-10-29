"""Translate tool failures into structured MCP errors."""

from http import HTTPStatus

from fastmcp.tools.base import ToolResult
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from mcp.types import CallToolResult
from pydantic import ValidationError

from .errors import ToolFailureError
from .models import EditFailedResponse


class ErrorToolResult(ToolResult):
    """Preserve structured content and mark the wire result as an error."""

    def to_mcp_result(self) -> CallToolResult:
        """Set the protocol flag unavailable on FastMCP's ToolResult."""
        return CallToolResult(
            content=self.content,
            structuredContent=self.structured_content,
            isError=True,
            _meta=self.meta,
        )


def failure_from_exception(
    error: Exception, tool_name: str
) -> EditFailedResponse:
    """Classify known exceptions without exposing API bodies or internals."""
    # FastMCP wraps backend exceptions in ToolError, preserving their cause.
    while not isinstance(error, ToolFailureError) and isinstance(
        error.__cause__, Exception,
    ):
        error = error.__cause__
    if isinstance(error, ToolFailureError):
        return error.failure
    # Callable argument validation is titled with the function name. Model
    # validation inside the backend is an internal failure, not bad input.
    if (
        isinstance(error, ValidationError)
        and error.title == f'call[{tool_name}]'
    ):
        fields = ', '.join(
            '.'.join(map(str, item['loc']))
            for item in error.errors(include_input=False, include_url=False)
        )
        return EditFailedResponse(
            code='INVALID_ARGUMENT',
            description=f'Invalid tool arguments: {fields}.',
            suggested_action='Check required fields and types in inputSchema.',
        )
    if isinstance(error, RefreshError):
        return EditFailedResponse(
            code='AUTHENTICATION_REQUIRED',
            description='Google credentials could not be refreshed.',
            suggested_action='Run gdocs-scope-mcp-auth, then retry the call.',
        )
    if isinstance(error, HttpError):
        status = error.resp.status
        code, action = {
            400: (
                'INVALID_ARGUMENT',
                'Check the tool arguments and document state.',
            ),
            401: ('AUTHENTICATION_REQUIRED', 'Run gdocs-scope-mcp-auth.'),
            403: (
                'PERMISSION_DENIED',
                'Check document access, OAuth scopes and quota limits.',
            ),
            404: (
                'RESOURCE_NOT_FOUND',
                'Check the document/comment ID and access permissions.',
            ),
            429: ('RATE_LIMITED', 'Wait for the quota to recover.'),
        }.get(
            status,
            (
                'GOOGLE_API_ERROR',
                'Inspect server logs and Google API availability.',
            ),
        )
        if status == HTTPStatus.BAD_REQUEST and tool_name in {
            'docs_list', 'docs_read_comments',
        }:
            action = (
                'Check listing arguments. If a page token is invalid or '
                'expired, omit page_token to restart pagination with the '
                'same query and filters; deduplicate items already seen.'
            )
        if status == HTTPStatus.BAD_REQUEST and tool_name in {
            'docs_append', 'docs_insert_before', 'docs_insert_after',
        }:
            action = (
                'Check input and document state. For images, use a publicly '
                'accessible PNG, JPEG or GIF smaller than 50 MB and no more '
                'than 25 megapixels; Google must be able to fetch the URL.'
            )
        return EditFailedResponse(
            code=code,
            description=f'Google API request failed with HTTP {status}.',
            suggested_action=action
            + ' Verify document/comment state before retrying a write.',
        )
    return EditFailedResponse(
        code='INTERNAL_ERROR',
        description='The tool could not complete the operation.',
        suggested_action=(
            'Inspect server logs. Verify document/comment state before '
            'retrying a write.'
        ),
    )
