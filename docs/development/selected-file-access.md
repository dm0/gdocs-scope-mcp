# Selected-file authorization and selection sessions

Issue [#40](https://github.com/dm0/gdocs-scope-mcp/issues/40).
See [configuration](../configuration.md#document-access-modes) for the user
setting and [protocol](../protocol.md#document-access-and-selection) for agents.
The [implementation plan](selected-file-access-plan.md) records the intended
scope; it does not establish completion of the live acceptance checks.

## Ownership and invariants

`google_api/access.py` defines scope policy. `authorization.py` verifies selected
account/file metadata and installs private tokens atomically. `selection.py`
owns bounded background workers, loopback listeners and public session state.
`tools/access.py` only adapts these operations to MCP.

Both the CLI and server read `access_mode`. Full-drive lookup remains compatible
with legacy files and gog. Selected-file lookup uses its separate default token
and never falls back to a broad grant. Token exchange and each refresh must
confirm exactly `drive.file`; a saved mode label cannot prove the grant.

The native Desktop Picker redirect supplies file IDs alongside a PKCE-bound
code. File IDs, names and account identity are checked through Drive before
token installation. Account matching uses `about.user.permissionId`, without
identity scopes. Later selection cannot silently switch an existing selected
token to a different client or account.

Credential locks use canonical destination paths, including symlink aliases.
MCP workers and active CLI authorization hold the destination lock throughout
their attempt. Headless preparation retains its destination and generation in
the private session file; completion checks that generation before replacement.
Atomic installation uses an owner-only temporary file in the destination
directory. A conflicting writer cannot make an older attempt overwrite a newer
token. Locks require a local filesystem with native lock support.

The application never revokes Google-side grants automatically. A failed local
installation can follow successful browser consent, so preserving the previous
token does not imply that remote grants are unchanged.

## Lifetimes and cleanup

A server retains at most 32 sessions. Selection lasts at most 300 seconds;
terminal results are evicted 300 seconds after the original expiry. Status is
an in-memory read, not a token-exchange trigger. Worker completion removes the
authorization URL from public state. Tokens, verifiers and callback URLs are
never returned in status or logged by the callback handler.

One loopback listener belongs to each active session. Unauthenticated requests
do not consume an attempt; authenticated cancellation and malformed selections
end it. Workers close listeners and release token locks on every exit.
Shutdown signals pending workers; Google operations have transport timeouts,
and expired/cancelled attempts cannot install a token after those operations.
Abrupt process termination discards sessions and the OS releases sockets/locks;
session IDs do not survive a restart.

Existing discovery clients are constructed for each API operation. The document
cache already separates grants using client ID, refresh token and scopes and
validates current Google access before reusing a snapshot. Selection does not
reuse a previous credential's authenticated transport.

## Verification

Permanent offline coverage is in `test_access_modes.py`,
`test_picker_authorization.py` and `test_selection_sessions.py`, alongside the
existing OAuth, configuration, MCP contract and architecture tests. Loopback
tests use real sockets with substituted Google responses; they do not establish
that Google's production Picker accepts the client or that document features
work with the narrow scope.

The opt-in interactive test uses the same isolated STDIO fixture as other live
checks. It publishes a manual-open URL, waits for the user's explicit selection,
then checks document reading, refresh and listing in a restarted process. Run
from the repository root, setting the already authorized test document and a
separate token destination outside the repository:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=AUTHORIZED_DOCUMENT_ID \
GDOCS_SCOPE_MCP_LIVE_SELECTED_TOKEN=/private/test-directory/token.json \
uv run --locked pytest -s -q -m live tests/test_live_selected_access.py
```

The normal token configuration supplies the session fixture's before/after
document cleanup. This requires permission to erase the designated test
document. The test does not replace that token or reconfigure the normal MCP.

After successful selection, run the affected live comment, suggestion and
image tests with `GDOCS_SCOPE_MCP_ACCESS_MODE=selected_files` and
`GDOCS_SCOPE_MCP_TOKEN` pointing at the separate narrow token. Keep all edits
within the explicitly authorized development document. A later grant to a
second existing document requires separate authorization for that document.
Public OAuth verification remains outside this issue.

### Upgrading to full-drive authorization

`docs_authorize` uses the same bounded session manager and read-only status
tool. It chooses scopes only from the server's configured mode. Full mode uses
ordinary PKCE consent without Picker parameters or selected-file callback data.
An existing narrow token, including one without a local mode label, results in
actionable `AUTHENTICATION_REQUIRED` guidance before document access.

For a shared explicit token path, verified full authorization atomically
replaces the narrow token. With separate default paths, the selected token is
used only to retain client/account identity; the new broad token is written to
the full-mode destination. A different account, incomplete grant, cancellation
or failure does not install a replacement. The CLI supports the same upgrade.

Permanent regressions in the access-mode, session and Picker authorization
tests exercise those transitions through real loopback callbacks and the MCP
adapters with substituted Google responses. They include insufficient returned
scopes, account mismatch, cancellation, and loading the installed broad token.
These checks do not establish production Google consent behavior; that remains
part of the pending live acceptance matrix.

Live acceptance is pending until browser selection and the narrow-scope
operation matrix succeed. Do not infer compatibility from broad-token tests,
offline mocks, artifact discovery or an authorization URL alone.
