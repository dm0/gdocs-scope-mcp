# Document creation recovery (#49)

## Contract

`docs_create` makes two independent calls when `initial_text` is nonempty:
document creation, followed by one literal-text insertion batch. A confirmed
create response establishes document identity even when insertion subsequently
fails. That identity must survive the failure so callers can recover without
creating duplicates.

Success remains `{id, title, webViewLink}`. A failure after confirmed creation
adds a feature-owned error branch only to the `docs_create` output schema:

```json
{
  "ok": false,
  "code": "WRITE_OUTCOME_UNKNOWN",
  "description": "The document was created, but initial content insertion was not confirmed.",
  "suggested_action": "Do not repeat docs_create. Inspect the created document using created_document.id before adding any missing text to that same document.",
  "committed_batches": 0,
  "created_document": {
    "id": "confirmed-document-id",
    "title": "Requested title",
    "webViewLink": "https://docs.google.com/document/d/confirmed-document-id/edit"
  },
  "initial_content": "unknown"
}
```

The result sets MCP `isError=true`; structured content and text contain the
same object. It never includes the initial text or raw exception/API body.
Underlying exceptions remain chained for existing server diagnostics.

| Initial insertion outcome | Evidence | Error code |
| --- | --- | --- |
| `not_attempted` | Local request construction raised before `execute` | `PARTIAL_WRITE` |
| `rejected` | HTTP 400, 401, 403, 404, 409, 412 or 429 | `PARTIAL_WRITE` |
| `unknown` | Timeout, HTTP 408/5xx, an unrecognized status or another execution error | `WRITE_OUTCOME_UNKNOWN` |

This is a conservative write-outcome policy, not a general API-reason
classifier. Credential-refresh errors raised during execution also remain
`unknown`. Creation is not a Docs update batch, so `committed_batches` is zero.
No automatic insertion/create retry, readback or rollback is performed. If
creation itself fails, the existing generic error remains; no confirmed ID
can be claimed. A timeout during creation may still have created a document.

References checked on 2026-10-30:

- [Docs batch atomicity and validation](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate)
- [Google API error meanings](https://developers.google.com/workspace/drive/api/guides/handle-errors)

## Verification

`tests/test_document_creation.py` covers successful creation with and without
initial text, failed creation, rejected insertion, local request-construction
failure and unknown execution outcomes. Backend assertions check single
execution without replay; serialized MCP tests validate the advertised schema,
both result channels, error flag, identity and privacy of returned data.

Local checks on 2026-10-30:

- Targeted backend, MCP, architecture and frozen-contract tests: 223 passed.
- Complete offline suite with external sockets blocked: 1989 passed,
  107 skips. The network-blocking test emitted its expected warning.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
- Wheel and sdist contain 90 identical source modules; both isolated installs
  passed CLI/auth checks and discovery of all 32 MCP tools.

The optional `tests/test_live_document_creation.py` requires separate explicit
permission to create and trash one disposable document. It uses isolated STDIO
for `server_info`, `docs_create` and `docs_read`, then verifies and trashes only
the returned ID using the native Drive API. It does not deliberately cause a
live insertion failure. Failure scenarios are tested offline at client seams.

Run only after permission has been granted:

```bash
GDOCS_SCOPE_MCP_LIVE_CREATE=1 uv run --locked pytest -q tests/test_live_document_creation.py
```

The fixture writes identity, cleanup and process-reaping results to
`/tmp/gdocs-scope-mcp-document-creation.json` and server stderr to the matching
`.log` file. Full local check logs use `/tmp/gdocs-49-*.log`.
