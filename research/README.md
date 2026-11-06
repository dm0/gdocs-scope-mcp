# Research scripts

Keep development experiments and measurement scripts here. Reports and
implementation documentation belong under `docs/`; do not place scripts there.

## Isolated Codex study runtime

`codex_study_runtime.py` uses the installed Codex app-server protocol and the
user's existing Codex authentication to create fresh ephemeral chats on the
approved #59 model roster. It requires Python 3.11+ and Codex CLI
`0.166.0-alpha.6` with experimental dynamic tools. It disables configured MCP
servers and unrelated capabilities only for its own process, never by editing
the user's configuration. Unknown server-name syntax fails closed.

The bounded infrastructure probe uses only a synthetic echo tool:

```bash
uv run --locked python research/codex_study_runtime.py \
  --model gpt-6-luna --output /tmp/gdocs-59-isolated-probe/luna
```

This checks model dispatch, `medium` reasoning, dynamic-tool callbacks and
process cleanup. It is not a pilot or evidence of improved tool correctness.
The ordinary Codex state directory must be writable during app-server startup;
the restricted parent sandbox may therefore require native tool approval.

`tool_consolidation_preflight.py` captures all four actual STDIO catalogs and
runs one non-mutating decision scenario in twelve fresh chats. See the
[preflight report](../docs/development/tool-consolidation-preflight.md) for
actual usage, infrastructure failures, limitations and reproduction. It is
not the 960-session formal pilot and does not support a default-adoption claim.

## Approved reduced Study 1

The user approved a maximum of 1080 model sessions: 120 pilot sessions over
five scenarios, then up to 960 main sessions over twenty scenarios. The corpus
is `study_scenarios.py`. `study_fixture_api.py` supplies only the deterministic
Google API seam; `study_fixture_server.py` runs unchanged production MCP tools.
`study_live.py` serializes the predeclared native confirmation subset under the
authorized development-document lock and verifies reset/process cleanup.

`run_reduced_study.py prepare` freezes datasets, catalogs, paired schedules,
source hashes, state references and native conformance before model trials.
Preparation performs authorized development-document setup/cleanup but does
not start model sessions. Run commands from this linked worktree:

```bash
uv run --locked python research/run_reduced_study.py prepare --output ARTIFACTS
uv run --locked python research/run_reduced_study.py pilot --output ARTIFACTS
uv run --locked python research/run_reduced_study.py main --output ARTIFACTS
```

Use one persistent owner-private artifact directory for the whole campaign.
Each attempt is reserved once in `ledger.json`; failed attempts consume the
same global cap and are not silently rerun. Never create a new campaign
directory to evade that cap. The main stage is gated on finishing the pilot.
The runner rejects changed source/manifests, interleaves paired variants,
counterbalances catalog groups, enforces finite budgets, retains all traces,
and stops new work on infrastructure failure. No unrelated document/file/
authorization operations or public uploads are permitted.

## List token measurements

From the repository root:

```bash
uv run --locked --with tiktoken==0.12.0 python research/measure_list_tokens.py
```

The optional tokenizer is loaded into a temporary uv environment without
changing project dependencies. Inputs are synthetic; the script does not access
Google documents. See [the report](../docs/development/list-read-roundtrip.md)
for methodology, character counts and limits of the token estimates.
