# On-demand catalog research (#60)

Issue: [#60](https://github.com/dm0/gdocs-scope-mcp/issues/60).
Baseline: local main merge `6c42a4e`, toolset v2, full static catalog.
This study is independent of the completed tool-consolidation study. Its model
budget has not been authorized; no earlier budget transfers to this effort.

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

Only after explicit user approval, the optional canary command is:

```bash
uv run --locked python research/on_demand_catalog/probe_client.py run --output PRIVATE_ARTIFACTS --authorized-sessions 6
```

The proposal is six fresh chats: eager/deferred on each of gpt-6-luna,
gpt-6.1-sol and gpt-6-astra, all medium, no provider/model fallback. Only
`server_info` and `docs_get_color_palette` may execute; document access and
writes are rejected before dispatch. Reserve before starting each actor;
failures consume the cap, are not automatically replaced, and stop the run.
Resume skips all reservations. A process lock prevents concurrent invocations.
Raw events, requested/effective settings, usage and reaping are recorded in
private artifacts. This is an infrastructure canary, not a correctness study.

Schema acceptance is checked before requesting authorization. Actual discovery
events, correct palette calls and client behavior must be audited after any
authorized canary. A deferred function appearing to work without observable
search does not alone establish the desired exposure mechanism. No adoption
or default change follows from canaries. Full static v2 remains unchanged.

## Next stages

Verify actual deferred discovery and native MCP approval handling, then choose
the implementation and core before freezing model-study scenarios. Keep all
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

Local discovery findings and their limits will be recorded in `COMPATIBILITY.md`.
