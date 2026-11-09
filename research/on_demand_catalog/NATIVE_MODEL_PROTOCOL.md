# Native loading comparison: sixty real-model sessions

Authorized 2026-11-09 for issue #60: ten eager and ten deferred fresh sessions
per exact model `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra`, reasoning medium.
This is a new 60-attempt cap, separate from the exhausted six-chat canary.
Failures, timeouts and interruptions consume reservations; no replacements.
Resume may execute only unstarted jobs. Three independent clients run together;
infrastructure failure stops further reservations after the active batch drains.

The fixed prompt asks for Google blue from the tool palette. Success requires
a successful native `docs_get_color_palette` call and a final answer containing
`#0000FF` (case insensitive), with no forbidden calls. This is one task repeated
ten times, not ten independent scenario families or a noninferiority study.

Both arms use the complete static v2 full-drive native STDIO catalog, retaining
names, schemas, descriptions and annotations. There are no dynamic tools.
Research middleware permits only bounded `server_info` and palette reads;
all document, account and mutation operations are blocked before execution.
Native approval policy is writes, reviewer user, sandbox read-only. Unexpected
confirmation requests fail closed. No Google document access is authorized.

Both arms use cached exact-model metadata through process-local
`model_catalog_json`. Both omit `tool_mode` to exercise native function routing,
excluding code-mode routing. Eager sets `supports_search_tool=false`; deferred
sets it true. This is an experimental metadata intervention, not a public
product setting, backend model snapshot or production default change. No
global configuration is edited. All MCP schemas are deferred in the treatment;
this differs from the earlier dynamic adapter's three-tool core.

Before inference, six deterministic loopback preflights must show 36 native
schemas initially in eager, zero in deferred, and runtime-produced
`tool_search_output` before the treatment's palette call. Every real session
verifies native descriptors, source fingerprint, exact model/provider and effort.
Raw Responses events are requested to capture actual model search calls when
supported. Preserve events even when search telemetry is incomplete; never
infer a search count of zero from missing telemetry. No extra real-model
preflight is permitted outside the sixty reservations.

Use 120-second turn/read deadlines and a 4096 output-token controller limit.
The middleware permits at most six safe calls per server, including one
pre-turn identity call. All child processes must be reaped. Save raw events,
server journals, results, usage and immutable manifest/source hashes privately.

Report success, search and palette calls, input/cached/output tokens and turn
duration by model and arm. Report sample mean, sample variance and 95% Student
t intervals for continuous metrics (n=10, df=9, t=2.262157), plus paired
deferred-minus-eager differences by repeat. Success intervals use Wilson 95%.
Intervals describe repeated behavior on this one task; no equivalence or
general correctness claim follows. Infrastructure failures are reported
separately and reduce completed denominators; never impute them as model errors.
No monetary cost is inferred from token usage. Cache state is uncontrolled;
alternate arm order per repeat and interleave models to reduce time-order bias.

Run from the assigned worktree root with a new private artifact directory:

```bash
uv run --locked pytest research/on_demand_catalog/tests -q
uv run --locked python research/on_demand_catalog/native_model_study.py prepare --output NEW_PRIVATE_ARTIFACTS
uv run --locked python research/on_demand_catalog/native_model_study.py run --output NEW_PRIVATE_ARTIFACTS --authorized-sessions 60
```
