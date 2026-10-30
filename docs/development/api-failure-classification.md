# Google API failure classification (#53)

## Evidence and policy

References reviewed on 2026-10-30:

- [Drive error reasons](https://developers.google.com/workspace/drive/api/guides/handle-errors)
- [Docs quotas and bounded exponential backoff](https://developers.google.com/workspace/docs/api/limits)
- [OAuth refresh invalidation](https://developers.google.com/identity/protocols/oauth2/web-server#offline)
- [OAuth token endpoint errors, RFC 6749 section 5.2](https://www.rfc-editor.org/rfc/rfc6749#section-5.2)
- [google-auth exceptions](https://google-auth.readthedocs.io/en/latest/reference/google.auth.exceptions.html)
- [google-auth refresh implementation](https://github.com/googleapis/google-auth-library-python/blob/main/google/oauth2/_client.py)

The installed, locked `google-auth==2.53.0` source was also inspected. Its
refresh exceptions retain the structured OAuth response in `args` and expose
the library's `retryable` flag. This implementation uses those public exception
attributes, not imports of the library's private retry helpers.

`google_api/failures.py` is a pure classifier. It consumes only known exception
types, HTTP status and allowlisted structured reasons. It never executes an
API request. `tool_errors.py` adapts its results to MCP and retains existing
listing/image recovery hints for HTTP 400.

| Evidence | Code | Policy |
| --- | --- | --- |
| HTTP 403 `rateLimitExceeded`, `userRateLimitExceeded` | `RATE_LIMITED` | A time-based project/user limit; back off safe reads. |
| HTTP 403 `dailyLimitExceeded` | `QUOTA_EXCEEDED` | Check project caps or wait for reset. |
| HTTP 403 `storageQuotaExceeded` | `QUOTA_EXCEEDED` | Check storage capacity. |
| Other HTTP 403, including `insufficientFilePermissions`, `insufficientPermissions`, `appNotAuthorizedToFile`, `domainPolicy` | `PERMISSION_DENIED` | Access/scope/policy guidance; unknown reasons retain a status-based fallback. |
| HTTP 429 | `RATE_LIMITED` | Throttling guidance regardless of payload shape. |
| HTTP 408, 500, 502, 503, 504 | `TEMPORARILY_UNAVAILABLE` | Service/timeout evidence; no claim that a write was rejected. |
| HTTP 401 | `AUTHENTICATION_REQUIRED` | Authorize again. |
| HTTP 400 / 404 | `INVALID_ARGUMENT` / `RESOURCE_NOT_FOUND` | Preserve existing status-based recovery. |
| Other HTTP statuses | `GOOGLE_API_ERROR` | No unsupported retryability inference. |
| Refresh `invalid_grant` or explicit `ReauthFailError` | `AUTHENTICATION_REQUIRED` | The grant is unusable; authorize again. |
| Refresh `invalid_client`, `unauthorized_client`, `invalid_scope` | `AUTH_CONFIGURATION_ERROR` | Correct client/scope configuration before authorizing. |
| Refresh `retryable=True`, `server_error`, `temporarily_unavailable`, `internal_failure`, or a known transport cause | `TEMPORARILY_UNAVAILABLE` | Do not infer revocation. |
| Other refresh errors | `GOOGLE_API_ERROR` | Inspect diagnostics; no unconditional authorization prompt. |
| Known transport exceptions | `TEMPORARILY_UNAVAILABLE` | Check connectivity; safe-read backoff guidance. |

Known transport exceptions are google-auth `TransportError`, built-in
`TimeoutError`/`ConnectionError`, socket `gaierror`, httplib2
`ServerNotFoundError`, and HTTP `RemoteDisconnected`/`IncompleteRead`.
Local file-not-found and permission errors are not treated as temporary network
failures. No raw exception text is copied into MCP results.

Legacy Drive reasons are extracted only from `error.errors[].reason` with
`global`/`usageLimits` domains (or omitted domain). All entries must be valid
and all reasons must belong to the same recognized category to override HTTP
403. Unknown/mixed reasons, malformed JSON or shapes, foreign domains and bodies
larger than 64 KiB use the status fallback. Free-text messages and modern
`error.status`/`error.details` do not override HTTP classification in this
policy. This is a deliberate conservative boundary, not an exhaustive inventory
of every Google API error format.

Explicit grant/configuration errors take precedence over a contradictory
retryable flag or nested transport cause. Unknown refresh errors may use
transport evidence from their explicit cause chain. The classifier walks
explicit causes without losing outer semantic exceptions or looping on cycles.

## Read backoff decision

This task changes classification and caller recovery guidance. It adds no
automatic retry of an API request or an entire MCP call. Bounded exponential
backoff with jitter is appropriate for safe reads after `RATE_LIMITED` or
`TEMPORARILY_UNAVAILABLE`; it does not address daily caps, storage exhaustion,
revoked grants or configuration failures.

A generic retry around an MCP call is unsuitable here: reads can combine
multiple requests and revision/cache validation; restarting the whole call
can repeat completed work and increase latency. A generic client wrapper also
serves writes. Separately, google-auth already performs its own token-request
backoff. This task leaves those existing library behaviors unchanged.

Any future automatic read backoff should live at an explicitly read-only
request boundary, with a total time/attempt budget, jitter, cancellation and
revision-coherence tests. It must not wrap document creation, insertion,
comment creation or other non-idempotent writes, and must not replay unknown
write outcomes. No retryability boolean is returned that could imply permission
to replay a write.

## Write safeguards and compatibility

`ToolFailureError` receipts anywhere in the cause chain take precedence over
generic API classification, preserving the exact code and committed-batch
count. Revision guards remain unchanged. The #49 partial-creation response
still retains its document identity and initial-content outcome.

Three codes are added to the common failure schema: `QUOTA_EXCEEDED`,
`TEMPORARILY_UNAVAILABLE` and `AUTH_CONFIGURATION_ERROR`. Success payloads,
tool registration, inputs and annotations are unchanged. The frozen catalog
hash was updated intentionally for these enum additions. Both MCP result
channels remain identical, with `isError=true` on failures.

## Verification

Permanent backend and MCP tests in `tests/test_google_failures.py` cover
documented reasons, conflicting/unknown reasons, malformed bodies, OAuth
response shapes and retryability, nested/cyclic causes, transport errors,
privacy and single execution without retries. Existing #49 and revision-guard
regressions verify partial creation and guarded writes.

An isolated STDIO smoke uses `tests/test_live_document_search.py` with three
unique synthetic searches, at most one metadata result per query and no document
content reads or writes. Actual quota exhaustion, revoked tokens and Google
service outages are not induced; failure classification is verified offline
at the API-client seam.

Checks on 2026-10-30:

- Targeted classifier, MCP, partial-creation, revision-guard, architecture and
  frozen-contract regressions: 403 passed.
- Complete offline suite with external sockets blocked: 2137 passed,
  107 skips. The network-blocking regression emitted its expected warning.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
- Wheel and sdist contain 91 identical source modules; both isolated installs
  passed CLI/auth checks and discovery of all 32 MCP tools.
- The read-only live smoke passed all three searches, with zero documents
  returned. The fixture verified the assigned worktree's package path and
  source fingerprint and confirmed subprocess reaping. Server stderr contained
  no warnings, errors or tracebacks.

Full logs are under `/tmp/gdocs-53-{targeted,offline,live,build,artifacts}.log`.
Live identity and cleanup evidence are in
`/tmp/gdocs-scope-mcp-literal-search.json`, with stderr in the matching `.log`.
No normal user MCP process was reconfigured or restarted.
