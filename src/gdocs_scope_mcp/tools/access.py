"""Expose authorization and mode-specific file selection through MCP."""

from gdocs_scope_mcp.google_api import selection
from gdocs_scope_mcp.settings import get_settings
from gdocs_scope_mcp.tools.schema import tool_response_schema


def _register_selection(mcp):
    """Register the Picker tool only when its configured mode supports it."""
    @mcp.tool(
        output_schema=tool_response_schema(selection.SelectionStatus),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_select_files(
        open_browser: bool = True,
    ) -> selection.SelectionStatus:
        """
        Start Google Docs selection in configured selected_files mode.

        Return session_id, pending status, expiry and a manual-open
        authorization_url immediately. With open_browser=True also attempt
        to open the system browser. The user chooses documents and grants
        access there. Poll docs_authorization_status in this server process;
        do not keep starting sessions while one is pending. Existing broad
        credentials require explicit migration using the authorization CLI.
        Selection does not revoke previous grants or change access_mode.
        """
        return selection.manager.start(open_browser=open_browser)


def register(mcp):
    """Register common auth tools and mode-appropriate file selection."""
    if get_settings().access_mode == 'selected_files':
        _register_selection(mcp)

    @mcp.tool(
        output_schema=tool_response_schema(selection.SelectionStatus),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': False},
    )
    def docs_authorization_status(
        session_id: str,
    ) -> selection.SelectionStatus:
        """
        Read authorization/selection status without exchanging codes.

        Completed Picker sessions return verified document IDs, names and URLs.
        Full-drive authorization returns an empty documents list on success.
        Other states are pending, cancelled, expired and failed. Session IDs
        belong to this server process and expire after bounded retention;
        after a restart begin a new session. No credential data is returned.
        """
        return selection.manager.status(session_id)

    @mcp.tool(
        output_schema=tool_response_schema(selection.SelectionStatus),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_authorize(
        open_browser: bool = True,
    ) -> selection.SelectionStatus:
        """
        Request Google authorization for the configured access_mode.

        Use when a user switches selected_files to full_drive and additional
        permissions are required, or for initial authorization. Full-drive mode
        requests broad Drive permissions; selected_files opens Google Picker
        with only drive.file. The agent cannot change the configured mode.
        Explain the requested access to the user before starting consent.
        Return session_id, expiry and authorization_url immediately; poll
        docs_authorization_status in this server process. Existing tokens are
        replaced only after verified consent for the same bound account/client.
        Cancellation, insufficient permissions and failure preserve the token.
        Never retry a previously failed write without checking its outcome.
        """
        return selection.manager.start(open_browser=open_browser,
                                       selection_only=False)

    @mcp.tool(
        output_schema=tool_response_schema(selection.SelectionStatus),
        annotations={'readOnlyHint': False, 'destructiveHint': False,
                     'idempotentHint': False, 'openWorldHint': True},
    )
    def docs_authorization_complete(
        session_id: str, callback_url: str,
    ) -> selection.SelectionStatus:
        """
        Submit a full OAuth redirect URL from a browser on another computer.

        First start docs_authorize or docs_select_files with open_browser=False
        and give the user authorization_url. After consent, the browser may
        fail to connect to 127.0.0.1; ask for the full address-bar URL.
        Pass it here with the original session_id in the same server process,
        before expiry. A bare code cannot replace the complete redirect URL.
        The server validates destination, state and PKCE session, then handles
        the callback once. It does not navigate to or fetch callback_url.
        Poll docs_authorization_status for final completion; do not resubmit
        a callback after an uncertain result. This works in both access modes.
        The URL contains a short-lived authorization code: do not quote it in
        replies or reports. Tokens and PKCE verifier stay inside the server.
        """
        return selection.manager.complete(session_id, callback_url)
