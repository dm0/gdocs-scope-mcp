"""Define authorization scope policy shared by the CLI and API clients."""

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError

DRIVE_FILE = 'https://www.googleapis.com/auth/drive.file'
DRIVE_FULL = 'https://www.googleapis.com/auth/drive'
FULL_SCOPES = [DRIVE_FULL]
AUTHORIZATION_ACTION = (
    'Call docs_authorize to request user consent for the configured '
    'access_mode, then poll docs_authorization_status with its session_id in '
    'the same MCP process. Present authorization_url if manual browser '
    'opening is needed. Alternatively run gdocs-scope-mcp-auth with the '
    'same mode and token destination. Inspect the outcome of any failed '
    'write before retrying it.'
)


def scopes_for_mode(mode):
    """Return a fresh scope list without incremental broad authorization."""
    return [DRIVE_FILE] if mode == 'selected_files' else list(FULL_SCOPES)


def require_selected_scopes(scopes):
    """Reject unknown or broader grants, regardless of local mode labels."""
    if (not isinstance(scopes, (list, tuple))
            or not all(isinstance(scope, str) for scope in scopes)
            or set(scopes) != {DRIVE_FILE}):
        raise ToolFailureError(EditFailedResponse(
            code='AUTHENTICATION_REQUIRED',
            description='Selected-file mode requires a verified drive.file '
            'grant without additional scopes.',
            suggested_action=AUTHORIZATION_ACTION + ' In selected_files '
            'mode, incompatible broad credentials require a separate narrow '
            'token destination or explicit grant revocation and '
            'reauthorization. If Google retains '
            'broader grants, revoke the application grant in your Google '
            'account and authorize again. '
            'Configuration does not revoke grants.',
        ))


def is_selected_grant(scopes):
    """Recognize narrow legacy grants without trusting a mode label."""
    if not isinstance(scopes, (list, tuple)):
        return False
    return {scope for scope in scopes if isinstance(scope, str)} - {
        'openid', 'email', 'profile',
    } == {DRIVE_FILE}


def require_full_scopes(scopes):
    """Request additional consent instead of using a narrow token as full."""
    if not isinstance(scopes, (list, tuple)) or DRIVE_FULL not in scopes:
        raise ToolFailureError(EditFailedResponse(
            code='AUTHENTICATION_REQUIRED',
            description='Full-drive mode requires additional Google Drive '
            'permissions; the existing grant is insufficient.',
            suggested_action=AUTHORIZATION_ACTION,
        ))
