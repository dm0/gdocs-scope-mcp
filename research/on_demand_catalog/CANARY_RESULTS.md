# Six client-loading canaries

Date: 2026-11-09. Issue: #60. Status: the authorized six attempts completed;
no infrastructure failures or replacements. No further model sessions authorized.

Later [native MCP baseline checks](NATIVE_MCP_APPROVALS.md) verified the approval
boundary with local deterministic replay and no additional external model calls.
The six-canary observations below retain their original scope and limitations.

## Scope and execution

The user approved exactly six fresh chats: eager/deferred loading on each of
gpt-6-luna, gpt-6.1-sol and gpt-6-astra, all medium. Exact requested settings
were confirmed for all six, with provider/model fallback disabled. Model IDs
do not identify immutable backend snapshots; the 6/6.1 minor-version mix is
disclosed. Each arm uses the same complete v2 callable definitions in the same
`gdocs` namespace. Only `deferLoading` differs for tools outside the tentative
core: `server_info`, `docs_get_tree`, `docs_read`.

Only server-info and palette reads were permitted at dispatch. The request was
to read the palette and report the hex value of Google blue. Every session
reached the actual isolated worktree MCP palette tool and answered the returned
`blue` entry, `#0000FF`. There were eight palette reads in total and no other
model-requested domain operations. The target is a document-independent palette:
no Google documents were accessed, created or edited. All six actor and MCP
processes were closed and reaped. This campaign is separate from #59's 2833
reservations and does not extend that study.

| Model | Correct answer, eager/deferred | Palette reads, eager/deferred | Input tokens, eager/deferred | Input change | Turn seconds, eager/deferred |
| --- | ---: | ---: | ---: | ---: | ---: |
| gpt-6-luna | yes / yes | 1 / 1 | 44,210 / 31,463 | -28.83% | 7.31 / 26.14 |
| gpt-6.1-sol | yes / yes | 1 / 1 | 44,211 / 29,990 | -32.17% | 8.00 / 7.71 |
| gpt-6-astra | yes / yes | 1 / 3 | 47,539 / 57,264 | +20.46% | 8.56 / 15.22 |

The two additional astra reads returned the same palette and were allowed by
the four-action limit. They are redundant operations, not invalid calls or
evidence that discovery failed. No successful result is rewritten as a failure
merely for repeating a permitted read. Repetition and overhead remain visible.

Recorded usage totals: **254,677 input tokens**, including **128,512 cached input
tokens** (a subset), and **500 output tokens**. Turn duration includes model and
callback work, excludes fixture/process/thread setup, and is not total campaign
wall time. No monetary cost is inferred. Cache history and fixed eager-first
order are uncontrolled; these are compatibility canaries, not randomized trials.

## Observability and limits

All six app-server traces contain the palette callbacks and final answers.
None contains a separate explicit tool-search item or method. Eager traces have
two token-usage updates each; deferred traces have three for luna/sol and five
for astra. Those counts are recorded as usage updates, not relabeled as search
calls or a verified count of model requests.

The requested deferred-loading configuration successfully reaches a non-core
function. Its provider request payload and exact schema-exposure timeline were
not observed. Token reduction on two models is consistent with deferred
exposure but does not by itself reveal the discovery path. Search recall,
missing results, loops and search-only latency cannot be recovered from these
app-server events. Do not manufacture search events from successful callbacks.

There is one request per model/arm. No effect confidence interval, noninferiority
claim, safety conclusion or general efficiency improvement follows. Astra's
increased input and repeated reads already show why fewer initial definitions
are not a sufficient adoption criterion. Warm tasks, cross-group workflows,
no-tool tasks and independent scenarios have not been evaluated.

The catalog was captured over real STDIO MCP, then exposed as app-server dynamic
functions backed by that MCP connection. This confirms the callback bridge;
it does not establish native Codex MCP discovery or read/write/destructive
approval parity. Those remain gates before choosing a product implementation.
The full static v2 product baseline remains unchanged and #60 remains open.

## Reproduction and evidence

Execution source: namespace-corrected probe commit `ba242fa`. Read-only audit
implementation: `f2769b9` (`analyze_canaries.py`). Frozen manifest SHA-256:
`53cdb86f23bf4819696813c91e9b36528dc07ee9fc7de0d400577487f727f93b`.
The six-run ledger was empty before authorization. Every reservation is terminal
and counted; none was freed or retried. Both arms' domain definitions compare
identically after removing only the loading flag.

Private artifacts:
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/60-client-preflight-2026-11-09-namespaced/`.
They include the frozen manifest and schemas, separate authorization record,
ledger, per-run results/events, cleanup flags and `canary-analysis.json` with
hashes of all twelve raw result/event inputs. Logs are
`/tmp/gdocs-60-canary-run.log` and `/tmp/gdocs-60-canary-analysis.log`.

```bash
uv run --locked python research/on_demand_catalog/analyze_canaries.py --output PRIVATE_ARTIFACTS
```

This command only reads saved traces; it starts no chats. Five isolated offline
research tests passed in 1.11 seconds, including the distinction between a
correct callback, redundant reads and explicit search telemetry. Global Ruff,
explicit research-test lint and `git diff --check` passed. No production source,
dependency, configuration or Google document changed. No push was performed.
