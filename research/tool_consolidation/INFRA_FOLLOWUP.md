# Infrastructure follow-up to the 1500-attempt A/D stage

Date: 2026-11-06. Issue: #59.

The user explicitly requested rerunning the infrastructure failures and then
classified the single agent timeout as an infrastructure problem too. This
authorizes exactly twelve additional fresh sessions: the eleven original
infrastructure failures and that timeout, once each, with the same case, model,
medium effort, catalog and backend. Cumulative reservations may reach 2833.
No other attempt is eligible. A failed follow-up consumes its reservation and
is not automatically repeated. No further sessions are authorized.

The original 1500-attempt ledger, results and prospective protocol remain
unchanged. The timeout reclassification is recorded here as the user's later
decision; its original agent_failure grade is preserved. The original strict
first-stage gate prohibited replacements, so a combined follow-up analysis is
explicitly post-hoc and does not turn that historical gate into a prospective
success. Report both campaigns separately; no default change is authorized.

`retry_noninferiority.py prepare` selects the twelve original failed results,
binds their hashes and freezes a separate manifest and ledger. Execution uses
the original frozen cases, catalogs and references through the unchanged shared
engine. The subsequent m04 generator repair does not resample these tasks.
Native attempts use fresh owned disposable Docs and copied, hash-bound native
gold references; only newly created documents are trashed afterward. All logs
and real document/folder identifiers remain in private artifacts.

The controller reserves before dispatch, uses at most three concurrent jobs,
drains on interruption or infrastructure error, and skips every reservation
on resume. It never reuses or resets an original campaign reservation. After
execution, verify effective model/settings, server identity, process reaping
and native cleanup. Combine only the selected follow-up outcomes with original
grades plus the separately recorded explicit-bold correction for descriptive
estimates. Keep missing outcomes visible. Trace review is required for adoption.

Run from the worktree's root Python project:

```bash
uv run --locked python research/tool_consolidation/retry_noninferiority.py prepare --parent ORIGINAL_ARTIFACTS --output FOLLOWUP_ARTIFACTS
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER='<authorized-test-folder-id>' uv run --locked python research/tool_consolidation/retry_noninferiority.py run --output FOLLOWUP_ARTIFACTS
uv run --locked python research/tool_consolidation/retry_noninferiority.py analyze --output FOLLOWUP_ARTIFACTS
```

## Completed results

All twelve follow-ups completed successfully: three luna, five sol and four
astra, each on the exact requested model with medium effort. This includes the
previous astra timeout. There were zero schema errors, semantic errors or
unintended mutations. All actor processes were confirmed reaped. Four fresh
owned native documents were verified trashed, with all associated MCP processes
reaped. Eight follow-ups used the fixture seam. No follow-up was repeated.
Consumption is exactly twelve new reservations, 2833 cumulatively.

The following separate analysis uses each follow-up in place of its original
failed outcome, retaining the earlier explicit-bold oracle sensitivity. It
contains 250 complete A/D pairs per model with no missing outcomes:

| Model | Success A | Success D | Mean D-A, pp | Variance(D-A) | Descriptive 95% CI, pp | A-only / D-only successes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-6-luna | 240/250 (96.0%) | 242/250 (96.8%) | +0.80 | 0.064193 | [-2.40, +3.20] | 7 / 9 |
| gpt-6.1-sol | 250/250 (100%) | 250/250 (100%) | 0.00 | 0 | [0.00, 0.00] | 0 / 0 |
| gpt-6-astra | 250/250 (100%) | 250/250 (100%) | 0.00 | 0 | [0.00, 0.00] | 0 / 0 |

Variance uses success coded 0/1 and describes paired D-A observations, not the
variance of the estimated mean. Confidence intervals use the original 25-template
cluster bootstrap, 5000 draws, fixed seed. The zero intervals are ceiling
samples, not independent evidence of equivalence.

For sol and astra, the complete-data numerical rule now has zero A-only
successes in 250 pairs and no observed unintended mutation. The one-sided 99%
zero-loss upper bound is 1.8252%, below 2%, under the original independence and
fixed-mixture assumptions. This is supplementary evidence after explicitly
authorized replacements; the original first-stage gate remains historically
unmet. Template dependence, infrastructure selection and the small native
subset limit generalization. Luna still has seven A-only successes, and its
descriptive interval extends below -2 pp. The supported-model adoption criterion
therefore remains unmet, and baseline stays the default.

The research suite passed **119 tests, 27 deselected** in 105.15 seconds.
Six focused schedule/controller tests passed, including failure selection,
reserve-before-dispatch, cap enforcement and no replay on resume. Global Ruff,
explicit changed-test lint and whitespace checks passed. No product code changed.

Frozen execution commit: `3d62e3d`.
Follow-up manifest SHA-256:
`f809fdbb9745769a00dec556114e5942f01eb1dde20e21fdf714725b70fdfe08`.
Parent manifest SHA-256:
`a8251f283b652e79b60f61bdfcb74319a861195ca57ab990cf93e5d70a4ce648`.
The original catalogs, tasks, raw outcomes and primary grades remain unchanged.

Private follow-up artifacts:
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/59-ni-infra-followup-2026-11-06/`.
They contain the frozen manifest/protocol, twelve original-result hashes,
separate ledger, fresh traces and cleanup evidence, and
`followup-analysis.json`. Logs are `/tmp/gdocs-59-ni-infra-prepare.log`,
`/tmp/gdocs-59-ni-infra-run.log`, `/tmp/gdocs-59-ni-infra-analysis.log` and
`/tmp/gdocs-59-ni-infra-research-tests.log`. No further sessions were started;
no push, publication or deployment was performed.
