# On-demand catalog research (#60)

Issue: [#60](https://github.com/dm0/gdocs-scope-mcp/issues/60).
Baseline: local main merge `6c42a4e`, toolset v2, full static catalog.
This study is independent of the completed tool-consolidation study. The user
authorized six compatibility canaries and all six completed. See
[canary results](CANARY_RESULTS.md). No pilot/main budget is authorized and no
earlier budget transfers to this effort.

[Native MCP approval checks](NATIVE_MCP_APPROVALS.md) subsequently passed nine
local deterministic scenarios, without more external model inference. The full
36-tool native catalog matched its source descriptors; read/write/delete
approvals, denial blocking and one-shot consent were preserved. A second
nine-case replay also passed combined native deferred discovery and approval
handling, including runtime-produced `tool_search_output`. Both are local
protocol checks, with no additional model inference or Google mutations.

## Compatibility first

The first candidate is host-side deferred loading: preserve the complete MCP
catalog and each domain tool's name, schema, output and annotations, while
delaying model-context exposure of non-core definitions. The tentative core
for this compatibility canary is `server_info`, `docs_get_tree`, `docs_read`.
This is not a frozen core decision for the eventual main study.

OpenAI documents automatic MCP discovery in compatible Agents API runtimes;
that does not establish behavior of this installed Codex client. The local
app-server schema accepts `deferLoading` on dynamic functions. The installed
Codex feature report has `mcp_tool_list_changed` disabled. Neither schema
acceptance nor a smaller advertised list proves successful model discovery.
Codex rejects deferred dynamic functions without a namespace. Both comparison
arms therefore use the identical `gdocs` namespace; only child-function loading
flags vary. The first rejected flat-catalog preparation is retained separately.

MCP 2026-07-28 prohibits request-triggered/per-connection changes to tool lists.
Do not implement activate-then-relist as a portable mechanism. FastMCP's search
transform instead advertises search plus a call proxy. Its generic proxy does
not preserve each target's distinct approval annotations at the outer call;
any proxy alternative must explicitly address this before adoption.

## Probe commands

Run from the assigned worktree root, using its root Python project:

```bash
uv run --locked python research/on_demand_catalog/probe_client.py prepare --output PRIVATE_ARTIFACTS
```

Preparation captures actual STDIO catalog, identity, negotiated MCP version,
and two ephemeral app-server thread handshakes (eager/deferred). It sends no
`turn/start`, invokes no model and never accesses Google documents. Threads
are preparation metadata, not evidence of backend model availability. It
reuses only the bounded transport from the previous study, not its results.

The following command executed the explicitly approved six canaries. The frozen
ledger is complete, so resuming it starts no additional sessions:

```bash
uv run --locked python research/on_demand_catalog/probe_client.py run --output PRIVATE_ARTIFACTS --authorized-sessions 6
```

The approved schedule was six fresh chats: eager/deferred on each of gpt-6-luna,
gpt-6.1-sol and gpt-6-astra, all medium, no provider/model fallback. Only
`server_info` and `docs_get_color_palette` may execute; document access and
writes are rejected before dispatch. Reserve before starting each actor;
failures consume the cap, are not automatically replaced, and stop the run.
Resume skips all reservations. A process lock prevents concurrent invocations.
Raw events, requested/effective settings, usage and reaping are recorded in
private artifacts. This is an infrastructure canary, not a correctness study.

Schema acceptance was checked before authorization. All six sessions reached
the palette and answered correctly, with two redundant reads on astra/deferred. No explicit
search telemetry was exposed. A deferred function appearing to work without
observable search does not alone establish the desired exposure mechanism.
No adoption or default change follows from canaries. Full static v2 remains
unchanged. Read-only reanalysis uses `analyze_canaries.py --output PRIVATE_ARTIFACTS`.

## Next stages

### Native real-model loading comparison

The separately authorized native comparison uses ten repeats per model/arm,
sixty reservations total, exact approved models at medium effort. See
[the frozen protocol](NATIVE_MODEL_PROTOCOL.md). The native runner keeps the
full product catalog and a server-side execution guard; it injects no dynamic
functions. Its eager/deferred profiles differ only in search capability.
Raw Responses events retain actual exposure and search representations.
Preparation uses loopback replay and consumes no real-model sessions.

```bash
uv run --locked python research/on_demand_catalog/native_model_study.py prepare --output NEW_PRIVATE_ARTIFACTS
uv run --locked python research/on_demand_catalog/native_model_study.py run --output NEW_PRIVATE_ARTIFACTS --authorized-sessions 60
uv run --locked python research/on_demand_catalog/analyze_native_models.py --output NEW_PRIVATE_ARTIFACTS
```

Run analysis after the active batch drains. Reservations, including failures,
consume the cap and cannot be replaced automatically. Repeated runs resume
only unstarted jobs. Keep generated traces, measurements and execution reports
outside the source checkout; they are not product documentation or releases.

### Ordinary-profile recovery and comparison

`ordinary_loading_study.py` retains the model's cached `tool_mode` and
`use_responses_lite`. It removes the historical harness's forced code-mode
disables and changes only `supports_search_tool` between arms. Schema exposure
is audited in the code-mode declaration text, and native MCP execution remains
guarded. The historical function-routing experiment is preserved separately.
`search_format_replay.py` exercises both documented search items and the
incompatible function-call representation without normalizing the latter.

Use separate private cohort directories and one shared budget root. Adaptive
diagnostics and validation share a 600-attempt ledger; measurement has its own
600-attempt ledger. Measurement requires a completed ordinary-profile
validation cohort with at least ten repeats per model/arm and reuses those
exact model profiles. Each cohort freezes its source hashes, paired schedule
and protocol before inference. Failed attempts consume the cap. Signals drain
active batches; there are no automatic replacements.

```bash
uv run --locked python research/on_demand_catalog/ordinary_loading_study.py --output PRIVATE_VALIDATION --reference PRIVATE_HISTORICAL_RUN --budget-root PRIVATE_BUDGET_ROOT --phase validation --repeats 10 --authorized-sessions 600
uv run --locked python research/on_demand_catalog/ordinary_loading_study.py --output PRIVATE_MEASUREMENT --reference PRIVATE_HISTORICAL_RUN --budget-root PRIVATE_BUDGET_ROOT --phase measurement --repeats 20 --authorized-sessions 600
```

### Broader evaluation

Joint native discovery/approval plumbing passed the local replay matrix.
Choose the implementation and core before freezing model-study scenarios;
real-model discovery behavior still requires evaluation. Keep all
domain interfaces identical across arms. Include core-only, deferred,
cross-group and no-tool tasks, separate cold/warm strata, missing results,
discovery failures, client isolation, reconnects and all discovery overhead.
Agree on independent task counts, power target, budget and stopping rules
before a pilot or main model campaign. The old Study 1 numerical design is not
automatically approved for Study 2.

## Primary references

- [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
- [OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search).
- [Codex MCP support](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- [FastMCP tool search](https://gofastmcp.com/servers/transforms/tool-search).

See [initial compatibility findings](COMPATIBILITY.md) for observed behavior,
the retained failed attempt, frozen successful manifest and remaining gates.
The probe requires Python 3.11+ like the reused app-server transport; it does
not change the product's supported Python versions.
