"""Classify documented Google failures without leaking private payloads."""

# Imported fixture names intentionally match pytest arguments.
# ruff: noqa: F811
import json
from http.client import IncompleteRead, RemoteDisconnected
from socket import gaierror

import pytest
from google.auth.exceptions import (
    ReauthFailError,
    RefreshError,
    TransportError,
)
from googleapiclient.errors import HttpError
from httplib2 import Response, ServerNotFoundError
from jsonschema import validate

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api.failures import classify_failure
from gdocs_scope_mcp.tool_errors import failure_from_exception

from .test_mcp_output_contracts import call_tool, contract_api  # noqa: F401

PRIVATE = 'PRIVATE_TOKEN_DOCUMENT_BODY'


def http_error(status, reasons=(), *, content=None, domain='usageLimits'):
    """Build API errors with private messages and structured reasons."""
    if content is None:
        content = json.dumps({'error': {
            'message': PRIVATE,
            'errors': [{'reason': reason, 'domain': domain, 'message': PRIVATE}
                       for reason in reasons],
        }}).encode()
    return HttpError(Response({'status': status}), content)


def wrap(error):
    """Emulate FastMCP's explicit cause without losing semantic wrappers."""
    outer = RuntimeError(PRIVATE)
    outer.__cause__ = error
    return outer


HTTP_CASES = [
    (403, ['rateLimitExceeded'], 'RATE_LIMITED'),
    (403, ['userRateLimitExceeded'], 'RATE_LIMITED'),
    (403, ['rateLimitExceeded', 'userRateLimitExceeded'], 'RATE_LIMITED'),
    (403, ['dailyLimitExceeded'], 'QUOTA_EXCEEDED'),
    (403, ['storageQuotaExceeded'], 'QUOTA_EXCEEDED'),
    (403, ['insufficientFilePermissions'], 'PERMISSION_DENIED'),
    (403, ['insufficientPermissions'], 'PERMISSION_DENIED'),
    (403, ['appNotAuthorizedToFile'], 'PERMISSION_DENIED'),
    (403, ['domainPolicy'], 'PERMISSION_DENIED'),
    (403, ['unknown'], 'PERMISSION_DENIED'),
    (403, ['rateLimitExceeded', 'domainPolicy'], 'PERMISSION_DENIED'),
    (403, ['rateLimitExceeded', 'unknown'], 'PERMISSION_DENIED'),
    (403, [], 'PERMISSION_DENIED'),
    (400, ['rateLimitExceeded'], 'INVALID_ARGUMENT'),
    (401, [], 'AUTHENTICATION_REQUIRED'),
    (404, [], 'RESOURCE_NOT_FOUND'),
    (408, [], 'TEMPORARILY_UNAVAILABLE'),
    (429, [], 'RATE_LIMITED'),
    (500, [], 'TEMPORARILY_UNAVAILABLE'),
    (502, [], 'TEMPORARILY_UNAVAILABLE'),
    (503, [], 'TEMPORARILY_UNAVAILABLE'),
    (504, [], 'TEMPORARILY_UNAVAILABLE'),
    (501, [], 'GOOGLE_API_ERROR'),
    (418, [], 'GOOGLE_API_ERROR'),
]


@pytest.mark.parametrize(('status', 'reasons', 'expected'), HTTP_CASES)
def test_google_http_classification(status, reasons, expected):
    """Prefer known 403 reasons while respecting the actual HTTP status."""
    result = classify_failure(http_error(status, reasons))
    assert result.code == expected
    assert result.description.endswith(f'HTTP {status}.')
    assert PRIVATE not in result.model_dump_json()


MALFORMED_BODIES = [
    b'', b'<html>rateLimitExceeded</html>', b'\xff', b'null', b'[]', b'"text"',
    b'{"error":null}', b'{"error":[]}', b'{"error":"rateLimitExceeded"}',
    b'{"error":{"errors":"rateLimitExceeded"}}',
    b'{"error":{"errors":[null]}}',
    b'{"error":{"errors":[{"reason":[]}]}}',
    b'{"error":{"errors":[{"reason":"rateLimitExceeded","domain":[]}]}}',
    b'{"error":{"errors":[{"reason":"rateLimitExceeded"},null]}}',
    b'{"error":{"message":"rateLimitExceeded","errors":[]}}',
    b'{"error":{"code":429,"status":"UNAVAILABLE"}}',
    b'[' * 2000 + b']' * 2000,
    b' ' * (64 * 1024 + 1),
]


@pytest.mark.parametrize('content', MALFORMED_BODIES)
@pytest.mark.parametrize('status', [403, 503])
def test_malformed_payload_uses_status_fallback(content, status):
    """Bad JSON, shape, size or spoofed text never breaks failure handling."""
    error = http_error(status, content=content)
    result = failure_from_exception(wrap(error), 'docs_list')
    assert result.code == (
        'PERMISSION_DENIED' if status == 403  # noqa: PLR2004
        else 'TEMPORARILY_UNAVAILABLE'
    )


def test_foreign_reason_domain_is_not_throttling():
    """Unknown reason domains do not establish a retryable limit."""
    error = http_error(403, ['rateLimitExceeded'], domain='unknown.example')
    assert classify_failure(error).code == 'PERMISSION_DENIED'


REFRESH_CASES = [
    ({'error': 'invalid_grant'}, False, 'AUTHENTICATION_REQUIRED'),
    ({'error': 'invalid_client'}, False, 'AUTH_CONFIGURATION_ERROR'),
    ({'error': 'unauthorized_client'}, False, 'AUTH_CONFIGURATION_ERROR'),
    ({'error': 'invalid_scope'}, False, 'AUTH_CONFIGURATION_ERROR'),
    ({'error': 'server_error'}, False, 'TEMPORARILY_UNAVAILABLE'),
    ({'error': 'temporarily_unavailable'}, False, 'TEMPORARILY_UNAVAILABLE'),
    ({'error': 'internal_failure'}, False, 'TEMPORARILY_UNAVAILABLE'),
    ({}, True, 'TEMPORARILY_UNAVAILABLE'),
    ({'error': 'unknown'}, True, 'TEMPORARILY_UNAVAILABLE'),
    ({'error': 'invalid_grant'}, True, 'AUTHENTICATION_REQUIRED'),
    ({}, False, 'GOOGLE_API_ERROR'),
    ({'error': 'unknown'}, False, 'GOOGLE_API_ERROR'),
    ({'error': []}, False, 'GOOGLE_API_ERROR'),
    ({'error_description': 'invalid_grant'}, False, 'GOOGLE_API_ERROR'),
]


@pytest.mark.parametrize(('body', 'retryable', 'expected'), REFRESH_CASES)
def test_refresh_classification(body, retryable, expected):
    """Require evidence before claiming revocation or a temporary failure."""
    error = RefreshError(PRIVATE, body, retryable=retryable)
    result = failure_from_exception(wrap(wrap(error)), 'docs_read')
    assert result.code == expected
    assert PRIVATE not in result.model_dump_json()
    if expected in {'TEMPORARILY_UNAVAILABLE', 'GOOGLE_API_ERROR'}:
        assert 'gdocs-scope-mcp-auth' not in result.suggested_action


@pytest.mark.parametrize('error_type', [
    TransportError, TimeoutError, ConnectionError, gaierror,
    ServerNotFoundError, RemoteDisconnected,
])
def test_transport_errors_are_temporary(error_type):
    """Known networking failures do not require new OAuth credentials."""
    result = failure_from_exception(wrap(error_type(PRIVATE)), 'docs_list')
    assert result.code == 'TEMPORARILY_UNAVAILABLE'
    assert PRIVATE not in result.model_dump_json()


def test_incomplete_response_is_temporary():
    """A truncated HTTP response leaves the request outcome unconfirmed."""
    result = failure_from_exception(IncompleteRead(b'private'), 'docs_read')
    assert result.code == 'TEMPORARILY_UNAVAILABLE'


def test_unknown_refresh_with_transport_cause_is_temporary():
    """A semantic refresh wrapper retains transport evidence beneath it."""
    error = RefreshError(PRIVATE)
    error.__cause__ = TransportError(PRIVATE)
    assert failure_from_exception(wrap(error), 'docs_read').code == (
        'TEMPORARILY_UNAVAILABLE'
    )


def test_invalid_grant_survives_nonsemantic_cause():
    """Do not replace the structured refresh reason with an inner exception."""
    error = RefreshError(PRIVATE, {'error': 'invalid_grant'})
    error.__cause__ = RuntimeError(PRIVATE)
    assert failure_from_exception(wrap(error), 'docs_read').code == (
        'AUTHENTICATION_REQUIRED'
    )


def test_reauth_failure_requires_authentication():
    """The explicit google-auth reauthentication exception is sufficient."""
    assert classify_failure(ReauthFailError(PRIVATE)).code == (
        'AUTHENTICATION_REQUIRED'
    )


@pytest.mark.parametrize('code', [
    'PARTIAL_WRITE', 'WRITE_OUTCOME_UNKNOWN', 'EDIT_CONFLICT',
])
def test_structured_write_failure_has_precedence(code):
    """Never reclassify a guarded write or lose its completed-batch count."""
    receipt = EditFailedResponse(
        code=code, description='Protected outcome',
        suggested_action='Inspect before retrying.', committed_batches=2,
    )
    error = ToolFailureError(receipt)
    error.__cause__ = http_error(503)
    assert failure_from_exception(wrap(error), 'docs_append') is receipt


def test_exception_cause_cycle_terminates():
    """Cycles in third-party wrappers cannot hang error handling."""
    error = RuntimeError(PRIVATE)
    error.__cause__ = wrap(error)
    assert failure_from_exception(error, 'docs_read').code == 'INTERNAL_ERROR'


@pytest.mark.parametrize('error_type', [FileNotFoundError, PermissionError])
def test_local_io_errors_are_not_temporary_network_errors(error_type):
    """Local credential/configuration file problems require investigation."""
    assert failure_from_exception(error_type(PRIVATE), 'docs_read').code == (
        'INTERNAL_ERROR'
    )


@pytest.mark.parametrize(('status', 'reasons', 'expected'), HTTP_CASES)
def test_mcp_http_failure_contract(contract_api, status, reasons, expected):
    """Validate both MCP channels, recovery privacy and absence of retries."""
    request = contract_api.files.return_value.list.return_value
    request.execute.side_effect = http_error(status, reasons)
    tool, result = call_tool('docs_list', {}, raise_on_error=False)
    assert result.is_error
    data = result.structured_content
    assert data['code'] == expected
    assert data['committed_batches'] == 0
    assert json.loads(result.content[0].text) == data
    assert PRIVATE not in json.dumps(data)
    validate(data, tool.outputSchema)
    request.execute.assert_called_once_with()


@pytest.mark.parametrize(('body', 'retryable', 'expected'), REFRESH_CASES)
def test_mcp_refresh_failure_contract(contract_api, body, retryable, expected):
    """Preserve structured OAuth evidence through FastMCP error wrapping."""
    request = contract_api.files.return_value.list.return_value
    request.execute.side_effect = RefreshError(
        PRIVATE, body, retryable=retryable,
    )
    tool, result = call_tool('docs_list', {}, raise_on_error=False)
    assert result.is_error
    assert result.structured_content['code'] == expected
    assert PRIVATE not in result.content[0].text
    assert json.loads(result.content[0].text) == result.structured_content
    validate(result.structured_content, tool.outputSchema)
    request.execute.assert_called_once_with()


@pytest.mark.parametrize('content', MALFORMED_BODIES[:15])
def test_mcp_malformed_body_is_a_safe_failure(contract_api, content):
    """Malformed API bodies retain a valid, sanitized status fallback."""
    request = contract_api.files.return_value.list.return_value
    request.execute.side_effect = http_error(403, content=content)
    tool, result = call_tool('docs_list', {}, raise_on_error=False)
    assert result.is_error
    assert result.structured_content['code'] == 'PERMISSION_DENIED'
    assert json.loads(result.content[0].text) == result.structured_content
    validate(result.structured_content, tool.outputSchema)
    request.execute.assert_called_once_with()


@pytest.mark.parametrize('code', [
    'PARTIAL_WRITE', 'WRITE_OUTCOME_UNKNOWN', 'EDIT_CONFLICT',
])
def test_mcp_guarded_failure_preserves_receipt(contract_api, code):
    """Keep write accounting even when the underlying cause is temporary."""
    receipt = EditFailedResponse(
        code=code, description='Protected outcome',
        suggested_action='Inspect before retrying.', committed_batches=2,
    )
    error = ToolFailureError(receipt)
    error.__cause__ = http_error(503)
    request = contract_api.files.return_value.list.return_value
    request.execute.side_effect = error
    tool, result = call_tool('docs_list', {}, raise_on_error=False)
    assert result.is_error
    assert result.structured_content == receipt.model_dump()
    validate(result.structured_content, tool.outputSchema)
    request.execute.assert_called_once_with()


def test_temporary_create_failure_is_not_replayed(contract_api):
    """Classification does not retry non-idempotent document creation."""
    docs = contract_api.documents.return_value
    docs.create.return_value.execute.side_effect = http_error(503)
    tool, result = call_tool('docs_create', {'title': 'Example'},
                             raise_on_error=False)
    assert result.is_error
    assert result.structured_content['code'] == 'TEMPORARILY_UNAVAILABLE'
    assert 'may have committed' in (
        result.structured_content['suggested_action']
    )
    assert 'created_document' not in result.structured_content
    validate(result.structured_content, tool.outputSchema)
    docs.create.return_value.execute.assert_called_once_with()
    docs.batchUpdate.assert_not_called()
