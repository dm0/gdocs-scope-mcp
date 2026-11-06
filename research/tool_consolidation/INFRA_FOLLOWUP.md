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

Execution results will be appended after all twelve attempts and cleanup finish.
