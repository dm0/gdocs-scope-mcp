# Completion and adoption decision

Date: 2026-11-09. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

The user accepted validation and requested completion without more model trials,
including removal of temporary debugging changes. This is an explicit product
acceptance decision, not a revision of the statistical result or a claim that
the original noninferiority gate passed.

Adopt the fully consolidated catalog as the startup default (`toolset_version=v2`):
`docs_insert` replaces append/before/after and `docs_comment_status` replaces
resolve/reopen. The full-drive catalog falls from 39 to 36 tools; selected-files
falls from 40 to 37. Existing application operations, revision and approval
semantics, content formats, access scope and receipts are preserved. Explicit
`toolset_version=v1` remains a supported migration fallback. Four study arms
remain executable through a research-only launcher, outside product settings.
The public experiment selector is removed; an old JSON field or environment
variable fails instead of silently selecting another catalog.

Model inference is finished at 2833 cumulative reservations. No 1500- or
3000-session Luna continuation was authorized or started. The final separate
[infrastructure follow-up](INFRA_FOLLOWUP.md) yielded 250 complete A/D pairs per
model after the recorded bold-oracle correction:

| Model | Baseline success | Consolidated success | Paired effect, pp | Descriptive 95% CI, pp |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 240/250 | 242/250 | +0.80 | [-2.40, +3.20] |
| gpt-6.1-sol | 250/250 | 250/250 | 0.00 | [0.00, 0.00] |
| gpt-6-astra | 250/250 | 250/250 | 0.00 | [0.00, 0.00] |

Luna does not establish noninferiority within 2 pp. Ceiling intervals for the
other models do not establish equivalence. Follow-up replacement, the fixed
25-template mixture, hybrid native/synthetic execution and unblinded assistant
review remain limitations. Historical protocols, reports, grades and private raw
traces are retained without pooling earlier campaigns or relabeling failures.

Research-only controllers, simulator, fixtures and their tests stay together
under this study directory, outside production imports and default pytest
collection. They are reproducibility artifacts, not production diagnostics.
The shipped package must contain no study actor, callback simulator, extra
debug logging, permanent-document fallback or embedded live document/folder ID.

## Initial adoption checks before version naming

Adoption implementation commit: `9964b3d`. Product source fingerprint:
`badaedbb99d1bd3c5bc8f4a84de477a27b6787cc933073e8119b96b7857592aa`.

- Complete offline product suite: **2410 passed, 1 skipped, 138 deselected**
  in 113.32 seconds. Log and JUnit: `/tmp/gdocs-59-completion-product.log`
  and `/tmp/gdocs-59-completion-product.xml`.
- Separate research suite: **119 passed, 27 deselected** in 116.43 seconds.
  Log: `/tmp/gdocs-59-completion-research.log`. No actor models were invoked.
- Focused settings, contracts and STDIO checks: **180 passed, 4 deselected**.
  Default discovery removes the legacy regression suite's explicit baseline
  override and confirms 36/37 tools in full-drive/selected-files modes.
  The original complete baseline contract digest remains unchanged.
- All four native adapter lifecycles: **4 passed, 4 deselected** in 162.24
  seconds. Append/before/after, rich/literal content, emoji/table insertion,
  stale revisions, resolve/reopen action persistence and surrounding-tab
  preservation passed through isolated worktree STDIO servers. Four distinct
  test-owned documents were verified trashed; test reports confirm subprocess
  reaping and cleanup. Log and JUnit: `/tmp/gdocs-59-completion-live.log` and
  `/tmp/gdocs-59-completion-live.xml`. Variant receipts are under
  `/tmp/pytest-of-lapin/pytest-150/test_live_consolidation_lifecy*/report.json`.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
  Tracked-file URL inspection found no real Google document/folder URLs.
  Production changes contain no debugger hooks or temporary logging. Test probes
  remain in tests; research
  actors, simulator and analysis stay outside the shipped package.
- Wheel and sdist built successfully under `/tmp/gdocs-59-completion-dist/`.
  The wheel contains all 99 product modules and no research/test payload.
  The sdist retains the named studies and their tests/reports. An isolated
  installation with locked dependencies confirmed the same source fingerprint,
  default discovery (36 tools), baseline discovery (39 tools), server identity
  and authorization CLI help. Python 3.14.4 / FastMCP 3.3.1. Packaging logs use
  `/tmp/gdocs-59-completion-build.log` and `/tmp/gdocs-59-completion-wheel-*`.

No new model sessions, push, release, remote issue edit or deployment occurred.
The work is completed and committed locally; publication and integration are
separate actions. The retained configuration selector is intentional legacy
compatibility and reproducibility support, not a temporary debugging hook.
