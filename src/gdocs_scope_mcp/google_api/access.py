"""Define authorization scope policy shared by the CLI and API clients."""

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError

DRIVE_FILE = 'https://www.googleapis.com/auth/drive.file'
DRIVE_FULL = 'https://www.googleapis.com/auth/drive'
FULL_SCOPES = [
    'https://www.googleapis.com/auth/documents',
    DRIVE_FULL,
    'https://www.googleapis.com/auth/drive.readonly',
    DRIVE_FILE,
]


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
            suggested_action='Run gdocs-scope-mcp-auth with '
            'GDOCS_SCOPE_MCP_ACCESS_MODE=selected_files. If Google retains '
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
            suggested_action='Call docs_authorize and ask the user to grant '
            'the additional permissions, then poll docs_selection_status. '
            'Alternatively run gdocs-scope-mcp-auth with '
            'access_mode=full_drive '
            'and the same configured token destination. Do not retry a failed '
            'write without first checking its outcome.',
        ))
