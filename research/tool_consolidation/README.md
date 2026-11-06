# Tool consolidation study (#59)

All experiment scripts, synthetic fixtures and research-only tests for this
study live here, including the [study report](REPORT.md). Product implementation
documentation remains under `docs/development/`. Run commands from
the repository root using its Python project and worktree environment.

The [retrospective audit](AUDIT.md) preserves the frozen grades and adds
separate user-adjudicated and scenario/fixture sensitivity estimates.
`audit_reduced_study.py --output ARTIFACTS/restart-001` verifies the completed
restart and writes private audit evidence without starting any model sessions.

Run the research checks separately from the default product suite:

```bash
uv run --locked pytest research/tool_consolidation/tests -m 'not live' -q
```

Native calibration tests carry the `live` marker and require the explicitly
authorized folder ID in `GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER`. Model
inference never runs as part of pytest. Product adapter/contract regressions
remain under the root `tests/` directory.

## Isolated Codex study runtime

`codex_study_runtime.py` uses the installed Codex app-server protocol and the
user's existing Codex authentication to create fresh ephemeral chats on the
approved #59 model roster. It requires Python 3.11+ and Codex CLI
`0.166.0-alpha.6` with experimental dynamic tools. It disables configured MCP
servers and unrelated capabilities only for its own process, never by editing
the user's configuration. Unknown server-name syntax fails closed.

The bounded infrastructure probe uses only a synthetic echo tool:

```bash
uv run --locked python research/tool_consolidation/codex_study_runtime.py \
  --model gpt-6-luna --output /tmp/gdocs-59-isolated-probe/luna
```

This checks model dispatch, `medium` reasoning, dynamic-tool callbacks and
process cleanup. It is not a pilot or evidence of improved tool correctness.
The ordinary Codex state directory must be writable during app-server startup;
the restricted parent sandbox may therefore require native tool approval.

`tool_consolidation_preflight.py` captures all four actual STDIO catalogs and
runs one non-mutating decision scenario in twelve fresh chats. See the
[preflight report](../../docs/development/tool-consolidation-preflight.md) for
actual usage, infrastructure failures, limitations and reproduction. It is
not a formal pilot and does not support a default-adoption claim.

## Approved reduced Study 1

The user approved a fresh 1080-session restart: 120 pilot sessions over five
scenarios, then 960 main sessions over twenty scenarios. The prior campaign's
241 attempts remain counted, giving a cumulative cap of 1321. Its outcomes
remain separate. The corpus
is `study_scenarios.py`. `study_fixture_api.py` supplies only the deterministic
Google API seam; `study_fixture_server.py` runs unchanged production MCP tools.
`study_live.py` creates an independent document per native job in the authorized
test folder, using the repository's `LiveDocuments` infrastructure. Jobs run
in parallel and verify trashing only their owned IDs plus process cleanup.

`run_reduced_study.py prepare` freezes datasets, catalogs, paired schedules,
source hashes, state references and native conformance for all 25 cases before
model trials. Preparation performs authorized test-document creation/trashing
but does
not start model sessions. Run commands from this linked worktree:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER=1j5SqJ2Iu95te9-u_9y_A0DyLcPbOheWt uv run --locked python research/tool_consolidation/run_reduced_study.py prepare --output ARTIFACTS --previous-campaign PRIOR_ARTIFACTS
uv run --locked python research/tool_consolidation/run_reduced_study.py pilot --output ARTIFACTS
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER=1j5SqJ2Iu95te9-u_9y_A0DyLcPbOheWt uv run --locked python research/tool_consolidation/run_reduced_study.py main --output ARTIFACTS
uv run --locked python research/tool_consolidation/analyze_reduced_study.py --stage main --output ARTIFACTS
```

Use a separate persistent owner-private directory for the authorized restart,
preserving the prior campaign. Its immutable ledger is bound by hash and count
in the new manifest. Never use a new directory to reset cumulative spending.
Each attempt is reserved once in `ledger.json`; failed attempts consume the
same global cap and are not silently rerun. The main stage is gated on
finishing the pilot. SIGINT/SIGTERM drain current jobs before exiting; they
do not cancel actors or document cleanup in flight.
The runner rejects changed source/manifests, interleaves paired variants,
counterbalances catalog groups, enforces finite budgets, retains all traces,
and stops new work on infrastructure failure. No unrelated document/file/
authorization operations or public uploads are permitted.

The analyzer reports scenario-family bootstrap intervals, incomplete paired
blocks and infrastructure separately. Its blinded audit packet requires human
review; machine grades alone do not authorize changing the default interface.

The user accepted an optional final period in m09's closing action text on
2026-11-06. That narrow decision is recorded in `adjudications/` and bound to
the frozen main corpus hash. Preserve the original machine report and request
a separate post-hoc sensitivity report with:

```bash
uv run --locked python research/tool_consolidation/analyze_reduced_study.py --stage main --output ARTIFACTS --m09-human-sensitivity
```

For the original cohort this changes no prompt, raw trace or primary grade.
It does not relax status, target, post count or any other state invariant, and
does not constitute a complete human audit.

The user subsequently extended the rule to all unquoted inserted paragraphs
and comment action text in this corpus. The corpus-bound decision is recorded
in `adjudications/unquoted-terminal-periods.json`. Report that broader
sensitivity separately for either stage:

```bash
uv run --locked python research/tool_consolidation/analyze_reduced_study.py --stage main --output ARTIFACTS --terminal-period-human-sensitivity
```

Only the newly inserted paragraph at its gold target, or the new action post,
can differ by one final period. Its style must match the preceding text.
Protected paragraphs, literal markup, action/status, post count and replacement
strings remain exact. This remains a post-hoc sensitivity for the original
cohort. The explicitly approved restart freezes the rule as its primary
state grading before new inference and retains exact-state matching as a
diagnostic. The observer snapshots initial/final state and every mutating call;
read-only calls reuse the last observed state in each private job document.
