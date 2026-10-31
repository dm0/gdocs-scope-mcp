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

Registration uses the startup access mode. `docs_select_files` is advertised
only in `selected_files`; `docs_authorize`, `docs_authorization_complete` and
`docs_authorization_status` are registered in both modes. Status covers consent
and Picker sessions. A server restart is needed after a mode change to update
its catalog.
Permanent STDIO catalog tests cover both modes and verify process cleanup.

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

The separately gated `test_live_additional_selection` uses an existing narrow
token. Set `GDOCS_SCOPE_MCP_LIVE_ADDITIONAL_SELECTION=1` only with explicit
permission to create and trash one synthetic Google Doc. Run the test with the
normal broad configuration and `GDOCS_SCOPE_MCP_LIVE_SELECTED_TOKEN` pointing
at the narrow token. It creates the temporary document through isolated MCP,
checks its initial narrow-access result, starts another Picker session and
publishes `SELECT_DOCUMENT`, `PICKER_URL` and `CALLBACK_FILE`. Select only that
temporary document. The test verifies both document reads before and after a
process restart, then checks the temporary document's identity before trashing
it. It does not trash the existing development document.

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=AUTHORIZED_DOCUMENT_ID \
GDOCS_SCOPE_MCP_LIVE_SELECTED_TOKEN=/private/test-directory/token.json \
GDOCS_SCOPE_MCP_LIVE_ADDITIONAL_SELECTION=1 \
uv run --locked pytest -s -q -m live \
  tests/test_live_selected_access.py::test_live_additional_selection
```

App-created files can already be available to `drive.file`; this test records
the actual result before selection instead of assuming denial. Run document
mutation sessions sequentially: the development document has an exclusive
session lock, and each session restores an empty single-tab document before
and after its tests.

### Remote browser completion

Remote Codex clients can open the Google URL on another computer without an SSH
tunnel. `docs_authorization_complete` submits the complete returned redirect
URL to the original server session. An authenticated HTTP callback and a manual
submission share one locked receiver; only one can consume the response.
Validation precedes consumption, and no callback URL is fetched. The worker
exchanges the code with its retained verifier exactly once. Existing deadline,
account, scope and token-generation checks remain in effect.

The callback contains a short-lived code and is never included in server
responses, package logs or evidence reports. The MCP host can retain messages
and tool arguments, so those surfaces must also be treated as sensitive.
Permanent MCP tests cover manual completion in both modes, invalid state,
destination and payload size, cancellation, expiry and concurrent submission.

For interactive live verification, the test reports a `CALLBACK_FILE` path in
the separate token directory. Use a private directory. Place the full callback
URL there atomically when supplied by the user; the test sends it through the
MCP completion tool and removes the file immediately, also on failure. Never
copy callback contents into test reports or command-line arguments. The normal
loopback callback remains supported by that same test.

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
These checks do not establish production broader-consent or account-switch
behavior. The live evidence below uses an existing broad grant for full mode;
it does not exercise a real browser upgrade or a second Google account.

Missing credentials, a missing configured token file, HTTP 401 and confirmed
refresh-token rejection share the authorization recovery guidance from
`google_api/access.py`: use `docs_authorize`, then `docs_authorization_status`.
The CLI remains an alternative. Only the credential loader maps a missing
token file to authentication; unrelated local IO failures are not reclassified.
Network failures, unknown refresh failures and document permission failures do
not imply that a new authorization session is needed. Read-error regressions
verify these distinctions through MCP without opening a browser automatically.

## Live evidence (2026-10-31)

The isolated worktree servers reported source fingerprint
`dc7e4da8fbb32984375a1ec0af91fb57e7da66a5911e1a4708b56ad3b23bf416`,
Python 3.14.4 and FastMCP 3.3.1. Startup identity verified the worktree package
path and source snapshot independently of installed development-version
metadata. The normal MCP configuration and broad token were preserved.

| Mode | Scenario | Result |
| --- | --- | --- |
| `selected_files` | Initial Desktop Picker consent with only `drive.file`; manual callback from a browser on another computer | Passed |
| `selected_files` | Read the selected development document; restart, refresh, read and list | Passed |
| `selected_files` | Anchored native comment creation, reply/edit, resolve/reopen and deletion | Passed |
| `selected_files` | Public text/formatting proposals and decisions with `requiredRevisionId` | Passed |
| `selected_files` | The same proposal workflow with `targetRevisionId` | Passed |
| `selected_files` | Local image upload, native layout readback and temporary-image cleanup | Passed |
| `selected_files` | Later Picker session selects a second document; both documents remain readable after restart | Passed |
| `full_drive` | Bounded document search with literal quote/backslash inputs | Passed |
| `full_drive` | Native comment lifecycle | Passed |
| `full_drive` | Public proposal workflow with `requiredRevisionId` | Passed |
| `full_drive` | Public proposal workflow with `targetRevisionId` | Passed |
| `full_drive` | Local image upload, layout and cleanup | Passed |

Before the second selection, the narrow token received `RESOURCE_NOT_FOUND`
for the newly created synthetic document. After selection it could read the
synthetic text, and the original selected document remained accessible. The
test restarted the server and read both again, then verified the new file's
identity, moved only that file to the trash and confirmed `trashed=true`.
Both manually submitted callback files were removed immediately after use.

Evidence outside the repository:

- Initial selection and restart: `/tmp/gdocs-40-remote-live.xml` and
  `/tmp/gdocs-40-picker.Y5quD5/selection-report.json`.
- Narrow-scope operation matrix: `/tmp/gdocs-40-selected-matrix.xml`,
  `/tmp/gdocs40-selected-evidence.sNBQQq/` and
  `/tmp/gdocs-scope-mcp-live-session-1ndyawsv/report.json`.
- Additional selection: `/tmp/gdocs-40-additional-live.xml`,
  `/tmp/gdocs-40-picker.Y5quD5/additional/selection-report.json` and
  `/tmp/gdocs-scope-mcp-live-session-bt2r9a3q/report.json`.
- Full-mode search: `/tmp/gdocs-40-full-search.xml`.
- Broad-scope operation matrix: `/tmp/gdocs-40-full-matrix.xml` and
  `/tmp/gdocs-40-full-matrix.log`; its XML records the document cleanup report.

Both operation matrices and browser sessions verified subprocess reaping and
before/after document cleanup. Cleanup left one empty root tab, no suggestions,
active comments or named ranges. Current-run stderr had no unexpected errors;
the second document's pre-selection not-found error was an asserted outcome.
Table-probe log files can contain older runs, so correlate their lines with the
reported startup time and PID rather than scanning unrelated historical errors.

Final offline verification passed 2233 tests with external sockets disabled;
109 live cases were deselected. Global Ruff, explicit changed-test lint and
`git diff --check` passed. Wheel and sdist checks confirmed 95 identical source
modules, isolated CLI/auth entry points and the full-mode 35-tool catalog.
The selected-mode 36-tool catalog has permanent isolated STDIO coverage.
Across the two browser tests, both operation matrices and the full-mode search,
11 live tests passed. The narrow token's exact scope, account binding and
owner-only file permissions were checked without exposing credential contents.

Cancellation, expiry, concurrent completion, account mismatch and broader-scope
upgrade failures are covered by permanent tests with substituted Google
responses. They are not additional production-browser observations. Public
OAuth verification remains separate work in
[#46](https://github.com/dm0/gdocs-scope-mcp/issues/46).
