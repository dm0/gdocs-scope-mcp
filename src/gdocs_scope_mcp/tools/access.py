"""Expose explicit asynchronous file selection through MCP."""

from gdocs_scope_mcp.google_api import selection
from gdocs_scope_mcp.tools.schema import tool_response_schema


def register(mcp):
    """Register selection start and read-only status tools explicitly."""
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
        access there. Poll docs_selection_status in this same server process;
        do not keep starting sessions while one is pending. Existing broad
        credentials require explicit migration using the authorization CLI.
        Selection does not revoke previous grants or change access_mode.
        """
        return selection.manager.start(open_browser=open_browser)

    @mcp.tool(
        output_schema=tool_response_schema(selection.SelectionStatus),
        annotations={'readOnlyHint': True, 'destructiveHint': False,
                     'idempotentHint': True, 'openWorldHint': False},
    )
    def docs_selection_status(session_id: str) -> selection.SelectionStatus:
        """
        Read authorization/selection status without exchanging codes.

        Completed Picker sessions return verified document IDs, names and URLs.
        Full-drive authorization returns an empty documents list on success.
        Other states are pending, cancelled, expired and failed. Session IDs
        belong to this server process and expire after bounded retention;
        after a restart begin a new selection. No credential data is returned.
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
        docs_selection_status in this same server process. Existing tokens are
        replaced only after verified consent for the same bound account/client.
        Cancellation, insufficient permissions and failure preserve the token.
        Never retry a previously failed write without checking its outcome.
        """
        return selection.manager.start(open_browser=open_browser,
                                       selection_only=False)
