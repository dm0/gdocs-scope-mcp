# Initial client compatibility findings

Date: 2026-11-09. Issue: #60. No-inference preparation passed. The subsequently
authorized [six canaries](CANARY_RESULTS.md) all reached the palette tool and
answered correctly. Explicit search telemetry and joint native deferred-loading
approval behavior were not verified by those canaries. The preparation
findings are preserved.

Subsequent [native MCP baseline approval checks](NATIVE_MCP_APPROVALS.md) passed
with local deterministic replay. Native annotations and approval enforcement
are now verified for the tested policy matrix; joint deferred-loading/native
approval parity subsequently passed a separate nine-case native replay matrix,
including runtime-produced search output. This verifies local protocol plumbing,
not real-model discovery quality. The preparation history below is preserved.

## Observed local behavior

Baseline product revision is local main merge `6c42a4e`. Product source remains
unchanged, with toolset v2 and the complete static 36-tool full-drive catalog.
The probe captures full definitions, original annotations and instructions;
repeated listing is stable. Python/FastMCP negotiated **MCP 2025-11-25**.
This must not be reported as negotiated support for MCP 2026-07-28.

Installed client: `codex-cli 0.166.0-alpha.6`. Local feature inspection reports
`mcp_tool_list_changed=false`, `mcp_2026_07_28=false` and
`incremental_tools=true`. Exported experimental app-server schema supports
`deferLoading` on dynamic functions, including namespaced child functions.
Schema support alone does not establish discovery or backend model access.

Actual thread-start checks found:

| Function definitions | Eager | Deferred |
| --- | --- | --- |
| Flat dynamic functions | Accepted | Rejected: deferred dynamic tool must include a namespace |
| Same `gdocs` namespace in both arms | Accepted | Accepted |

Both successful namespaced handshakes requested gpt-6.1-sol, medium, OpenAI,
with provider/model fallback disabled. No `turn/start` was sent in either
preparation attempt. Three ephemeral threads were accepted in total and one
thread-start request was rejected. No model inference or Google document
operation occurred. All MCP/app-server processes were closed and reaped.
The first failed preparation remains separate from the successful one.

## Interpretation and candidate

Use client-side deferred exposure as the first candidate, preserving domain
tool contracts and keeping the MCP listing static. Namespacing is identical
across eager/deferred comparison arms. The tentative three-tool core is for
the compatibility canary only; it is not a selected production core.

The MCP 2026-07-28 specification prohibits per-connection/request-triggered
listing changes, so activate-then-relist is not a portable fallback.
[MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

OpenAI documents automatic MCP discovery for compatible Agents API runtimes;
it does not establish that this app-server dynamic-function route or every
Codex MCP transport behaves identically.
[OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search).

FastMCP search transforms offer pinned core tools plus search and a generic
call proxy. Local 3.3.1 source constructs that proxy without target-specific
annotations. It is not yet an accepted replacement for distinct read/write/
destructive approval behavior. Native names remain callable beneath the
transform, but a host that only exposes advertised tools needs its proxy or
native deferred loading.
[FastMCP tool search](https://gofastmcp.com/servers/transforms/tool-search).

Dynamic functions supplied to app-server are a canary route, not proof of
native Codex MCP approval parity. The next gates are observable model discovery
and a separate native-MCP approval/provenance check before product adoption.
No on-demand product setting or default change has been implemented yet.

## Evidence and proposed bounded next step

- Probe implementation: `a9187d1`, namespace correction `ba242fa`.
- Four offline tests passed: interface parity across loading arms, rejection
  of accidental unapproved runs, pre-dispatch permission/schema/namespace
  checks, product-drift rejection and no replacement of failed reservations.
- Ruff and `git diff --check` passed. Research tests are isolated from product
  collection. No dependency or product implementation changes were needed.
- First failed preparation:
  `/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/60-client-preflight-2026-11-09/`.
- Successful preparation:
  `/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/60-client-preflight-2026-11-09-namespaced/`.
- Successful manifest SHA-256:
  `53cdb86f23bf4819696813c91e9b36528dc07ee9fc7de0d400577487f727f93b`.
- Supporting logs: `/tmp/gdocs-60-client-prepare.log`,
  `/tmp/gdocs-60-client-namespaced-prepare.log`, `/tmp/gdocs-60-features.log`.
  Exported local schemas are under `/tmp/gdocs-60-codex-schema/`.

The subsequently approved proposal was six fresh model canaries, two arms on each of
gpt-6-luna / gpt-6.1-sol / gpt-6-astra, all medium. The 6/6.1 minor-version mix
is explicit. Only palette/server-info reads are permitted, with no documents,
no writes, a six-attempt cap and no automatic replacements. Token usage is
recorded; monetary cost is not inferred. These six are not a pilot or a main
correctness campaign. All six completed after the user's separate approval.
The earlier 2833 attempts belong only to #59; its budget is not reused here.
