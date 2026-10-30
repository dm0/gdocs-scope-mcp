"""Translate tool failures into structured MCP errors."""


from http import HTTPStatus

from fastmcp.tools.base import ToolResult
from googleapiclient.errors import HttpError
from mcp.types import CallToolResult
from pydantic import ValidationError

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api.failures import (
    classify_failure,
    exception_chain,
)


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
    # Keep a structured write failure even when it chains a transport cause.
    chain = exception_chain(error)
    for cause in chain:
        if isinstance(cause, ToolFailureError):
            return cause.failure
    error = chain[-1]
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
    for cause in chain:
        failure = classify_failure(cause)
        if failure is not None:
            error = cause
            break
    else:
        failure = None
    if failure is not None:
        action = failure.suggested_action
        status = (
            getattr(error.resp, 'status', None)
            if isinstance(error, HttpError) else None
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
        return failure.model_copy(update={
            'suggested_action': action + ' A failed write may have committed; '
            'verify document/comment state before retrying a write.',
        })
    return EditFailedResponse(
        code='INTERNAL_ERROR',
        description='The tool could not complete the operation.',
        suggested_action=(
            'Inspect server logs. Verify document/comment state before '
            'retrying a write.'
        ),
    )
