"""Define authorization scope policy shared by the CLI and API clients."""

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError

DRIVE_FILE = 'https://www.googleapis.com/auth/drive.file'
FULL_SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.readonly',
    DRIVE_FILE,
]


def scopes_for_mode(mode):
    """Return a fresh scope list without incremental broad authorization."""
    return [DRIVE_FILE] if mode == 'selected_files' else list(FULL_SCOPES)


def require_selected_scopes(scopes):
    """Reject unknown or broader grants, regardless of local mode labels."""
    if not isinstance(scopes, (list, tuple)) or set(scopes) != {DRIVE_FILE}:
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
