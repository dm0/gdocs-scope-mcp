# Study 1: Codex runtime and catalog preflight

Date: 2026-11-06.
Status: infrastructure verified; not the formal pilot or held-out evaluation.
Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

## Approved models and execution route

The user approved this roster and `medium` reasoning for every model:

| Role | Exact selected model | Provider reported by runtime |
| --- | --- | --- |
| Weaker | `gpt-6-luna` | `openai` |
| Current | `gpt-6.1-sol` | `openai` |
| Stronger | `gpt-6-astra` | `openai` |

This intentionally mixes GPT-6 minor versions 6 and 6.1, as disclosed before
approval. The ordering is a selection assumption based on provider/host model
descriptions, not a measured ordering or an immutable backend snapshot.

Three new desktop chats returned `ACCESS_OK`. Their turn metadata confirmed
the exact selected IDs and `medium`. The completed access-check chats were
archived after collecting results, following the repository's requested-test
chat workflow:

```text
gpt-6-luna    01a1b055-aeab-7683-b762-e039f1910ac0
gpt-6.1-sol   01a1b055-b986-7c10-81af-5d5ed3873322
gpt-6-astra   01a1b055-cc43-7111-8a11-066d628caf63
```

The desktop thread-creation action cannot select a restricted tool inventory.
The research runner therefore creates fresh ephemeral chats through the
installed Codex app-server, using existing Codex authentication. It does not
use an independently billed OpenAI API key, modify normal MCP configuration,
restart the user's connected server, or copy credentials.

Codex CLI version: `0.166.0-alpha.6`. The experimental app-server JSON schemas
were generated from that installed executable. `thread/start` supplies the
exact model, `allowProviderModelFallback=false`, the explicit static tool set,
and a read-only sandbox; `turn/start` supplies `medium`. Effective model and
reasoning are checked against the returned values. Unrelated configured MCP
servers, apps, plugins, shell/browser tools, hooks and memories are disabled
for the runner's process. Unexpected non-study requests fail closed.

Infrastructure source commits: `a2346f1` (runtime) and `be63afd` (catalog
preflight, grading and trace privacy). The installed protocol is experimental;
the runner must be revalidated after a Codex upgrade.

## Complete-catalog check

Four isolated worktree STDIO MCP processes supplied the actual catalogs and
initialization instructions for baseline, insertion, status and both. Discovery
called only `server_info` and `tools/list`; no Google documents were accessed.
Catalog fingerprints match the [implementation report](IMPLEMENTATION_REPORT.md).

The runner supplied each catalog's exact tool names, descriptions and input
schemas as app-server function definitions with `deferLoading=false`. Each
model/variant received its own fresh ephemeral chat: 3 models x 4 variants =
**12 chats**, with no reused task history. This engineering check used fixed
variant order and one scenario, with no repeats or randomized trial design.

The scenario supplied already-read document/tab state and requested literal
`**Ready**` at the end of the non-first Review tab, preserving the other tab.
The first actual function call was recorded without execution. JSON Schema
validation and deterministic intent checks verified the operation, document,
tab, text and literal mode. Every chat selected the correct action: **12/12**.
All app-server processes were closed and reaped.

This is one scenario family. It provides no independent sample of ordinary
tasks, ambiguity, comment status, multi-step behavior or controls. No effects,
confidence intervals, power estimate or adoption claim are derived from it.
Google Docs write behavior was covered by the separate implementation live
regressions; no preflight function callback performed document mutations.

## Usage and artifacts

Usage comes from the final cumulative `thread/tokenUsage/updated` event for
each chat. Cached input is a subset of input, not an extra quantity:

| Model | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| `gpt-6-luna` | 194364 | 72320 | 446 |
| `gpt-6.1-sol` | 194266 | 96384 | 351 |
| `gpt-6-astra` | 206880 | 102528 | 399 |
| Total | 595510 | 271232 | 1196 |

The provider also reported 100 reasoning-output tokens across these runs.
No currency cost is inferred from these counters or the user's subscription.
Linear scaling suggests about 48 million input tokens for 960 similarly sized
pilot sessions; multi-step end-to-end tasks can require more, and cache behavior
can differ. This is a planning estimate, not a charge or quota prediction.

Private local artifacts are under `/tmp/gdocs-59-catalog-preflight-run/`:
`manifest.json`, the four captured catalogs, `summary.json`, and per-chat
`report.json`, `events.json` and `stderr.log`. The parent directory is restricted
to its owner. The runner now omits unrelated account/quota notifications from
future saved transcripts. Initial engineering traces remain private and are
not published. These `/tmp` artifacts are not durable public evaluation data.

Retained infrastructure attempts include the sandboxed CLI startup failure,
an invalid quoted override key, and a missing explicit empty STDIO argument
list. These occurred before the successful twelve-chat run and do not count as
model outcomes. Their logs use `/tmp/gdocs-59-cli-access*`,
`/tmp/gdocs-59-isolated-probe/` and `/tmp/gdocs-59-catalog-preflight.log`.

## Limits and next gate

Dynamic function definitions do not carry native MCP output schemas or the
host's MCP approval policy. Full original metadata is retained in catalog
captures, but the preflight does not verify equivalent native host confirmation
behavior. The formal end-to-end design must preserve the relevant distinctions
before any default-adoption claim.

After seeing preflight usage and the original 960/7200-session design, the user
approved a reduced campaign: five pilot scenarios (120 sessions), twenty main
scenarios (960 sessions), and a strict total cap of 1080 attempts. The active
profile is documented in [the protocol](EVALUATION_PROTOCOL.md). The
runner freezes dataset hashes, paired randomization, stopping rules,
clarification policy and native controls before inference. This smaller
campaign supports preliminary conclusions; the original larger design is not
authorized by this approval.

Keep the baseline default. Issue #59 remains open.

## Reproduction

Run from the assigned worktree, with its project environment:

```bash
uv run --locked python research/tool_consolidation/tool_consolidation_preflight.py \
  --output /tmp/gdocs-59-catalog-preflight-new
```

Codex's normal state directory must be writable during app-server startup, so
the parent execution sandbox may require native tool-level approval. The
model's own sandbox remains read-only; this does not disable host safeguards.
