# Native MCP connection and approval enforcement

Date: 2026-11-09. Issue: #60. Status: native baseline connection and approval
checks passed. Joint native deferred-loading checks also passed, as reported
below. No external model inference or Google document operation.

## What was exercised

The real installed Codex app-server connected to the worktree's production
`gdocs-scope-mcp` over native STDIO MCP, without injected dynamic functions.
It discovered the full v2 catalog and performed a native `server_info` call.
All **36 tool definitions** matched the direct SDK capture: names, descriptions,
input/output schemas and annotations. Comparison used SDK wire aliases
(`_meta`) and omitted only null top-level optional descriptor fields; JSON
Schema contents and annotation values were not normalized or weakened.

Next, native Codex executed synthetic read, write and delete tools. They copy
the annotation sets of `server_info`, `docs_insert` and `docs_delete_comment`.
Their bodies only append test nonces to a private execution journal. They do
not implement or simulate Google Docs edits. This separates confirmation
enforcement from application behavior, which was already tested under #59.

A loopback Responses fixture supplied deterministic function-call events.
The actual Codex runtime resolved and executed its native MCP tools, including
approval handling. No `dynamicTools` or `item/tool/call` callback bridge was
used. This is a native-client protocol integration test, not a model study or
Google live mutation test. The fixture provider requires no OpenAI auth,
has a loopback-only endpoint, and effective provider identity was checked
before each turn. It served 19 requests across nine final local scenarios;
external model inference remained **zero**. The six earlier paid-model canaries
remain a separate, exhausted budget.

## Results

| Policy | Operation | Decision | Approval requests | Executions |
| --- | --- | --- | ---: | ---: |
| auto | read | automatic | 0 | 1 |
| auto | write | accept once | 1 | 1 |
| auto | delete | accept once | 1 | 1 |
| writes | read | automatic | 0 | 1 |
| writes | write | accept once | 1 | 1 |
| writes | write | decline | 1 | 0 |
| writes | delete | accept once | 1 | 1 |
| writes | delete | decline | 1 | 0 |
| writes | write twice in one connection | accept each once | 2 | 2 |

All nine scenarios passed. Every approval was observed before its nonce
appeared in the execution journal. In the repeated-write case, prior execution
counts were zero before the first approval and one before the second: a
one-shot accept did not silently grant the next call. Declined write/delete
nonces never reached the server body. Fresh isolated clients reconnected with
the same annotation sets, and prior accepts did not suppress later prompts.
No persistent approval was selected; responses contained only action and
empty accepted content, without session/always consent.

The observed native approval transport was **`mcpServer/elicitation/request`**,
form mode, `_meta.codex_approval_kind="mcp_tool_call"`, correlated with the
native `mcpToolCall` item, server, arguments and target tool. The fixture server
contains no elicitation code: confirmations originated in Codex. The controller
rejects unrelated servers, request kinds, argument correlations and form
schemas. All native Codex and MCP subprocesses were verified reaped, including
the real product connection. Local HTTP servers were shut down and joined.

## Configuration and interpretation

Only process-local configuration overrides were used. Existing MCP servers,
apps, plugins and unrelated tools were disabled in those child processes.
The probe selected `approval_policy="on-request"`, reviewer `user`, a read-only
sandbox and explicit server approval modes `auto` / `writes`. It neither
changed the user's config file nor disabled approval boundaries. Test accepts
and declines applied only to identified no-op operations.

OpenAI documents `default_tools_approval_mode` and per-tool overrides; the
`writes` policy prompts for tools not marked read-only.
[Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).
The app-server documentation distinguishes native MCP elicitation from
app/connector approvals that can use `tool/requestUserInput`. We recorded the
actual native route rather than assuming the app route.
[App-server protocol](https://learn.chatgpt.com/docs/app-server).

This confirms the existing native MCP approval boundary and provides a
regression fixture for #60. It does not establish approvals for an unimplemented
on-demand product mode, the earlier dynamic-function adapter, all custom policy
overrides, desktop UI rendering, or OpenAI Auto-review decisions. The local
provider controls proposed calls; it measures no model judgment or discovery
quality. The subsequent joint characterization below closes the local native
transport gate for this matrix. Static v2 remains the baseline.

## Joint deferred loading and native approvals

A separate nine-case run passed the same table above with actual native MCP
deferred discovery enabled. It used harness revision `ccfb536`, the installed
Codex runtime and a process-local `model_catalog_json` copied from the cached
`gpt-6.1-sol` metadata. The `tool_mode` override was omitted to keep native
function routing rather than code-mode routing. The effective provider remained
the loopback fixture, not OpenAI: selecting this model metadata made no model
inference request and establishes no real-model discovery quality.

Every first provider request lacked all three fixture operation schemas and
contained a client-executed `tool_search` definition in an `additional_tools`
input item. The replay proposed a search by operation name. **Codex itself**
searched its native MCP inventory and returned `tool_search_output`, correlated
to `search_fixture`, containing the requested namespaced function with
`defer_loading: true` and its nonce schema. Only then did the replay propose the
native function call. It did not fabricate the search result or inject a dynamic
function. Later native approvals still used `mcpServer/elicitation/request`.
This matches the documented client-executed search lifecycle.
[OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search).

Across nine turns there were **28 loopback provider requests**, nine searches,
ten native MCP operation attempts, eight approval requests and eight executions.
Reads had no approval; accepted writes/deletes executed after approval; declined
writes/deletes did not execute. Repeated write used one search and two separately
approved native calls; prior execution counts remained zero and one. Production
discovery again matched all 36 SDK descriptors, including annotations. Every
Codex/MCP process was reaped. No Google mutation, global configuration change,
external model inference or additional paid canary occurred.

Private evidence is retained under
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/60-native-deferred-approvals-2026-11-09/`.
It includes the local model catalog, native descriptors, raw events, exposed
provider tool definitions and discovery items, journals and results.
`verification.json` hashes 47 JSON/JSONL evidence files. Fourteen isolated tests
passed; explicit Ruff checks and `git diff --check` passed. Product code is
unchanged. Reproduce with a fresh private output directory:

```bash
uv run --locked python research/on_demand_catalog/native_mcp_check.py --deferred --output NEW_PRIVATE_ARTIFACTS
```

Preparation is retained separately under
`60-native-deferred-smoke-2026-11-09/`. Its first turn failed because the old
replay expected eagerly exposed functions; no operation executed. The second
smoke completed native search and read. Both clients were reaped. The verifier
now rejects failed turns even when the controller reached `turn/completed`.

The combined result covers local native search/execution/approval plumbing,
including denial and one-shot consent. It does not cover desktop rendering,
Auto-review, persistent consent choices, code-mode routing, arbitrary policy
overrides, Google mutation semantics or autonomous discovery by real models.
The six paid canaries retain their original dynamic-adapter scope; these replay
results must not be pooled with them as model success rates.

## Reproduction and retained evidence

Run from the assigned worktree root, using its Python project and a **new**
private directory for each native characterization run:

```bash
uv run --locked pytest research/on_demand_catalog/tests -q
uv run --locked python research/on_demand_catalog/native_mcp_check.py --output NEW_PRIVATE_ARTIFACTS
```

The native command does not contact an external model provider. It performs
only product server-info discovery and local no-op fixture operations.

- Product fingerprint:
  `73d9b0147cd06eb6126888afd9062882f05ddb5aa583cdf361f1596239805c4a`.
- Installed Codex: `0.166.0-alpha.6`; production Python/FastMCP: 3.14.4/3.3.1.
- Initial harness: `e01d997`; native elicitation adapter: `1396675`; final
  nine-case collection with before-response and repeated-call checks: `c424885`.
- Explicit result invariant verification: `945f38e`. Thirteen isolated offline
  tests passed in 2.04 seconds. Global Ruff, explicit study-test lint and
  `git diff --check` passed. Production sources and dependencies are unchanged.
- Private final evidence:
  `/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/60-native-approvals-2026-11-09-r3/`.
  `native-production.json` retains full source/native catalogs and identity;
  each case retains fixture definitions, native events, provider tool-name
  records, execution journal, process identity and result. `summary.json` and
  `verification.json` retain outcomes and input hashes.
- Logs: `/tmp/gdocs-60-native-approvals-r3.log` and
  `/tmp/gdocs-60-native-unit-final.log`.

The first characterization stopped when the harness expected the app approval
request but received native MCP elicitation. Its write was not executed and
its processes were reaped. It remains under the sibling
`60-native-approvals-2026-11-09/` directory. The subsequent eight-case run is
retained under `60-native-approvals-2026-11-09-r2/`. These are local replay
preparations, not extra model trials or replacements of the six canaries.
No push, global MCP reconfiguration, release or deployment occurred.
