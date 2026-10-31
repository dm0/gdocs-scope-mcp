# Selected-file access implementation plan

Issue: [#40](https://github.com/dm0/gdocs-scope-mcp/issues/40).
Baseline: `e57f35e` (v0.7.0). Reviewed on 2026-10-31.

This is a proposed implementation plan, not evidence that selected-file access
is implemented or verified. Public OAuth readiness remains a separate issue
([#46](https://github.com/dm0/gdocs-scope-mcp/issues/46)).

## Confirmed integration path

The [Desktop Picker guide](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker)
documents an OAuth redirect flow. Use PKCE S256 and state, request only
`https://www.googleapis.com/auth/drive.file`, and add `prompt=consent`,
`trigger_onepick=true`, `allow_multiple=true`, and
`mimetypes=application/vnd.google-apps.document`. Do not combine this request
with identity, Docs, broad Drive, or Apps Script scopes. Do not enable
incremental authorization that combines previous scopes.

Google returns `picked_file_ids` with the authorization code. Validate the
callback, exchange the code, and resolve names, MIME types and URLs using the
new credential. Treat callback IDs as untrusted input until that verification
succeeds. This flow does not require serving a custom JavaScript Picker page.
The Google Picker API must be enabled for the OAuth client's Cloud project.

[Drive about.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/about/get)
supports `drive.file`. Use its authenticated user information for account
binding without introducing identity scopes. Verify availability and stability
of the chosen user identifier during the live check; do not infer identity
from file ownership or trust an OAuth login hint as proof.

## Current implementation seams

- `settings.py` resolves environment overrides over JSON settings.
- `auth_setup.py` owns the authorization CLI and loopback listener. Its
  `SCOPES` constant currently defines one broad authorization flow.
- `google_api/oauth.py` owns PKCE, callback checks, private session files,
  exchange and refresh adaptation. The CLI and new selection workflow should
  share these primitives rather than duplicate OAuth logic.
- `google_api/credentials.py` loads tokens through the established precedence
  and refreshes them. It does not currently enforce access-mode compatibility.
- `google_api/clients.py` constructs authenticated clients. Keep credential
  enforcement below document, comment, suggestion and image workflows.
- `tools/files.py` and `tools/diagnostics.py` provide the natural MCP boundaries
  for selection tools and access-mode discovery. Feature orchestration must
  remain independent of FastMCP.

## Proposed contracts

### Configuration and credentials

Add `access_mode: Literal['full_drive', 'selected_files']`, defaulting to
`full_drive`, with `GDOCS_SCOPE_MCP_ACCESS_MODE` as the environment override.
Both entry points resolve the same setting; tools cannot override it.

Preserve existing full-drive credential lookup and compatibility. Use a
separate default selected-file token location so opting into the mode does not
overwrite a broad token. An explicitly configured token path remains explicit;
reject an incompatible token there with actionable authorization guidance.
Do not fall back to legacy or gog broad tokens in selected-file mode.

Keep the token's original OAuth client, actual granted scopes, mode and account
binding. Reject missing/unknown or broader granted scopes in selected-file
mode, including broad Docs or Drive scopes. Validate both the exchange result
and refreshed credentials; a local mode label alone is insufficient evidence.
Never claim that changing settings or requesting a narrower token revokes
previous grants. Document explicit Google-side revocation and reauthorization
when required to obtain a verified narrow credential.

Use owner-only, atomic token replacement and a lock for the destination.
Compare the original credential generation before committing a completed
selection. A stale session must not overwrite a token changed by another
process. Keep existing credentials on mismatch, cancellation or failure.

### Selection tools

Proposed names:

- `docs_select_files`: start a bounded selection session in selected-file
  mode, with optional browser launch. Return `session_id`, status, expiry,
  browser-launch outcome and a manual-open authorization URL immediately.
- `docs_authorization_status`: accept only `session_id` and return current status.
  On completion return verified document IDs, names and URLs. Do not expose
  credentials, callback URLs, authorization codes or PKCE verifiers.

The status tool must be read-only: callbacks and background completion perform
the exchange, account check and credential commit. Polling must not exchange
the same code or replay a failed operation. MCP annotations must reflect that
starting selection opens an authorization workflow and changes access.

Represent pending, completed, cancelled, expired and failed states explicitly.
Return stable, sanitized failure reasons for account mismatch, incompatible
granted scopes, credential-generation conflict, and invalid callbacks.
Report unknown/evicted session IDs explicitly. Empty selection is not a
successful document selection.

Bind each attempt to its client, redirect, state, verifier, mode, destination,
account and deadline. Permit only one active attempt per credential destination
and return a clear busy result for competing starts. Bound retained sessions
and result lifetimes. Close listeners on completion, failure, expiry and server
shutdown; an interrupted process must not leave a reusable pending attempt.
Session IDs belong to the originating server process; document restart behavior.

Validate exact loopback destination, state, duplicate parameters, response size,
file-ID count and syntax. Ignore unrelated paths without consuming the active
attempt. A callback failing authentication must not install credentials.
Keep callback contents out of HTTP and application logs.

Additional selection uses the same client and account. Verify the returned
credential's account before saving it. For the initial authorization, establish
the binding explicitly; later sessions must reject a different account without
silently switching the server. A browser login hint may improve the experience
but is not an identity check.

### Access behavior and recovery

Expose the configured mode through process diagnostics without credentials.
Explain that selected-file listing covers files available to the application,
including application-created files; it is not merely the latest session's
selection. Let Google enforce file grants. A pasted document URL does not grant
access, and local selection history is not an authoritative allowlist.

Permission and not-found failures in selected-file mode should suggest explicit
selection when appropriate, while retaining the distinction between missing
files, insufficient sharing rights and domain policy. Do not automatically
launch the browser, label every 403 as a missing selection, or replay failed
writes. Preserve partial-write and unknown-outcome receipts.

Review caches and cached API clients when credentials change: account or mode
changes must not expose an earlier credential's cached content or retain an old
authenticated transport. Token installation and cache invalidation need tests.

## Implementation sequence and verification

Each completed implementation step receives relevant checks and its own commit.

1. Add shared access-mode/scope policy, configuration and token-path resolution.
   Test JSON/environment precedence, invalid settings, default compatibility,
   and CLI/server agreement.
2. Enforce credential-mode validation and safe persistence. Test legacy
   full-drive tokens, selected-mode rejection before use, actual granted scopes,
   refresh behavior, private atomic replacement, and destination conflicts.
3. Extend shared OAuth primitives for Picker callback data and the CLI flow.
   Keep existing ordinary authorization and headless completion working. Test
   PKCE/state, parameter ambiguity, cancellation, empty/malformed selections,
   scope mismatches and expiry using real loopback sockets with substituted
   Google responses.
4. Add bounded application-owned selection sessions and their lifecycle.
   Test asynchronous completion, account binding, competing sessions, shutdown,
   stale token generations and no leaked listeners or secrets.
5. Add thin MCP adapters, mode diagnostics and recovery guidance. Register tools
   explicitly. Update only deliberately changed frozen transport contracts;
   preserve existing tool behavior and structured write receipts.
6. Update architecture, configuration, human onboarding and agent protocol
   guidance. Explain mode migration, token locations, previously granted access,
   revocation, manual-open fallback and server restart behavior.
7. Run the complete offline suite, global Ruff and `git diff --check`. Verify
   isolated STDIO source identity, tool discovery and installed wheel/sdist
   entry points using the worktree environment.
8. Perform bounded live MCP checks with a separate selected-file token and
   isolated configuration. Keep the user's normal MCP and broad credentials
   intact. Verify initial selection, later selection, account mismatch,
   cancellation, listing, reads, edits, native comments and suggestions, local
   image upload/cleanup, refresh and process restart. Also run affected
   full-drive regressions. Inspect stderr and verify process/content cleanup.

## Live verification boundaries

Browser consent and document selection require user interaction. Use the
already authorized development document for mutations. Demonstrating a second
file grant needs a second specifically authorized document or explicit approval
to create and clean up a disposable document. Do not reuse an earlier release's
disposable-create approval as blanket authorization for new files.

Before live selection, confirm Picker API availability and the Desktop client's
registration requirements, including Google's current AI-agent guidance. Do not
change Cloud configuration, revoke grants or replace normal credentials silently.

Current broad-token regressions do not establish selected-file compatibility.
Native comments, suggestions and image operations remain unverified under the
narrow scope until the live matrix passes. If an operation is unsupported,
report its specific limitation without broadening authorization automatically.

## Completion criteria

Close #40 only after the implemented contracts, permanent tests, documentation,
bounded live evidence and cleanup checks cover the issue's acceptance criteria.
Record confirmed limitations separately from hypotheses. Do not treat this work
as completion of public OAuth verification in #46.
