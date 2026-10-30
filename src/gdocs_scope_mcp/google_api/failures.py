"""Classify Google failures without exposing payloads or replaying requests."""

import json
from http import HTTPStatus
from http.client import IncompleteRead, RemoteDisconnected
from socket import gaierror

from google.auth.exceptions import (
    ReauthFailError,
    RefreshError,
    TransportError,
)
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from gdocs_scope_mcp.contracts import EditFailedResponse

MAX_ERROR_BODY = 64 * 1024
RATE_REASONS = frozenset({'rateLimitExceeded', 'userRateLimitExceeded'})
QUOTA_REASONS = frozenset({'dailyLimitExceeded'})
STORAGE_REASONS = frozenset({'storageQuotaExceeded'})
TEMPORARY_OAUTH_ERRORS = frozenset({
    'internal_failure', 'server_error', 'temporarily_unavailable',
})
CONFIGURATION_OAUTH_ERRORS = frozenset({
    'invalid_client', 'unauthorized_client', 'invalid_scope',
})
TRANSPORT_ERRORS = (
    TransportError, TimeoutError, ConnectionError, gaierror,
    ServerNotFoundError, RemoteDisconnected, IncompleteRead,
)


def exception_chain(error: Exception) -> list[Exception]:
    """Keep semantic wrappers and stop safely at repeated exception causes."""
    result = []
    seen = set()
    while isinstance(error, Exception) and id(error) not in seen:
        seen.add(id(error))
        result.append(error)
        error = error.__cause__
    return result


def _reasons(error: HttpError) -> set[str]:  # noqa: PLR0911
    """Read only structured legacy reasons, ignoring messages and metadata."""
    content = error.content
    if not isinstance(content, (bytes, str)) or len(content) > MAX_ERROR_BODY:
        return set()
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        return set()
    if not isinstance(payload, dict):
        return set()
    detail = payload.get('error')
    if not isinstance(detail, dict):
        return set()
    items = detail.get('errors')
    if not isinstance(items, list):
        return set()
    # Mixed, unknown or malformed entries must not imply retryable throttling.
    if any(not isinstance(item, dict)
           or not isinstance(item.get('reason'), str)
           or item.get('domain', 'global') not in ('global', 'usageLimits')
           for item in items):
        return set()
    return {item['reason'] for item in items}


def _refresh_failure(error: RefreshError) -> EditFailedResponse:
    """Use structured OAuth codes and the library's retryability evidence."""
    reasons = {
        arg['error'] for arg in error.args
        if isinstance(arg, dict) and isinstance(arg.get('error'), str)
    }
    if reasons == {'invalid_grant'} or isinstance(error, ReauthFailError):
        return EditFailedResponse(
            code='AUTHENTICATION_REQUIRED',
            description='Google authorization is no longer valid.',
            suggested_action='Run gdocs-scope-mcp-auth to authorize again.',
        )
    if reasons and reasons <= CONFIGURATION_OAUTH_ERRORS:
        return EditFailedResponse(
            code='AUTH_CONFIGURATION_ERROR',
            description='Google rejected the OAuth client configuration.',
            suggested_action='Check OAuth client credentials, client type and '
            'configured scopes before authorizing again.',
        )
    if (error.retryable
        or (reasons and reasons <= TEMPORARY_OAUTH_ERRORS)
        or any(isinstance(cause, TRANSPORT_ERRORS)
               for cause in exception_chain(error)[1:])):
        return EditFailedResponse(
            code='TEMPORARILY_UNAVAILABLE',
            description='Google credentials could not be refreshed due to '
            'a temporary service or transport failure.',
            suggested_action='Wait and retry safe reads with bounded '
            'exponential backoff. This failure does not establish revocation.',
        )
    return EditFailedResponse(
        code='GOOGLE_API_ERROR',
        description='Google credentials could not be refreshed; '
        'the cause is unclassified.',
        suggested_action='Inspect server diagnostics and OAuth configuration. '
        'An unclassified refresh failure does not establish revocation.',
    )


def classify_failure(error: Exception) -> EditFailedResponse | None:
    """Return a sanitized failure for known Google or network exceptions."""
    if isinstance(error, RefreshError):
        return _refresh_failure(error)
    if isinstance(error, TRANSPORT_ERRORS):
        return EditFailedResponse(
            code='TEMPORARILY_UNAVAILABLE',
            description='A transport failure prevented confirmation of '
            'the Google request.',
            suggested_action='Check connectivity and retry safe reads with '
            'bounded exponential backoff.',
        )
    if not isinstance(error, HttpError):
        return None
    status = getattr(error.resp, 'status', None)
    if (not isinstance(status, int)
        or not HTTPStatus.CONTINUE <= status <= 599):  # noqa: PLR2004
        return EditFailedResponse(
            code='GOOGLE_API_ERROR',
            description='Google returned an unclassified API failure.',
            suggested_action='Inspect server diagnostics and '
            'API availability.',
        )
    code, action = {
        HTTPStatus.BAD_REQUEST: (
            'INVALID_ARGUMENT', 'Check tool arguments and document state.',
        ),
        HTTPStatus.UNAUTHORIZED: (
            'AUTHENTICATION_REQUIRED', 'Run gdocs-scope-mcp-auth.',
        ),
        HTTPStatus.FORBIDDEN: (
            'PERMISSION_DENIED',
            'Check document access, granted OAuth scopes and domain policy. '
            'Unknown 403 reasons may also require inspecting quota settings.',
        ),
        HTTPStatus.NOT_FOUND: (
            'RESOURCE_NOT_FOUND',
            'Check the document/comment ID and access permissions.',
        ),
        HTTPStatus.TOO_MANY_REQUESTS: (
            'RATE_LIMITED',
            'Wait and retry safe reads with bounded exponential backoff.',
        ),
    }.get(status, ('GOOGLE_API_ERROR',
                   'Inspect server diagnostics and Google API availability.'))
    if status == HTTPStatus.FORBIDDEN:
        reasons = _reasons(error)
        if reasons and reasons <= RATE_REASONS:
            code, action = (
                'RATE_LIMITED',
                'Wait and retry safe reads with bounded exponential backoff.',
            )
        elif reasons and reasons <= QUOTA_REASONS:
            code, action = (
                'QUOTA_EXCEEDED',
                'Check project quota caps or wait for quota reset. '
                'Immediate retries will not resolve the limit.',
            )
        elif reasons and reasons <= STORAGE_REASONS:
            code, action = (
                'QUOTA_EXCEEDED',
                'Check Drive storage capacity and available quota '
                'before retrying.',
            )
    if status in {
        HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY, HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }:
        code, action = (
            'TEMPORARILY_UNAVAILABLE',
            'Wait and retry safe reads with bounded exponential backoff.',
        )
    return EditFailedResponse(
        code=code,
        description=f'Google API request failed with HTTP {status}.',
        suggested_action=action,
    )
