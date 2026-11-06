# Study 1: implementation and validation report

Date: 2026-11-06.
Status: first campaign stopped at the user's request; parallel disposable-Doc
restart preparation is in progress. Machine grades await human audit.
Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

## Decision and scope

Keep **baseline** as the default and retain all four executable static variants.
There is insufficient evidence that consolidation improves correctness. Issue
#59 remains open: regression checks do not satisfy its required model study.
No push, release, publication or deployment was performed.

The approved restart contains 120 new pilot sessions (5 scenarios) and 960 new
main sessions (20 scenarios). The first campaign consumed 241 reservations;
the user explicitly approved 1080 additional sessions, for a cumulative cap of
1321. The 60 native confirmations remain included in the new main schedule.
Failed and interrupted attempts consume the cap; no automatic replacements
are permitted. Earlier outcomes are preserved separately and never pooled.

Pre-inference native calibration exposed setup constraints: tab titles must be
unique; ordinary-text preambles are not headings; whole-paragraph text styling
can include the adjacent newline. The synthetic API and setup now follow these
observations. The original m16 duplicate-tab-title ambiguity was replaced,
before any formal inference, by heading-versus-body ambiguity with a scripted
clarification. A failed native tab-renaming request was retained and cleaned
up without replaying an unknown write. Preparation artifacts preserve failures
separately from model outcomes. These checks consumed no formal model sessions.

The pre-treatment repository revision was
`6f7d48ce0f5db0b03fbdde2a099306dc7982a25f`. The implementation commit is
`ae597460e0cb161384fbdd1abc4dc94de904de2b`; the additional STDIO/live regression
tests are in `6e65a16`. The study's executable baseline is the `baseline` variant
at the same implementation revision as each treatment. This avoids confounding
the interface treatment with different application implementations.

## Implemented interfaces

See [configuration and migration](tool-consolidation.md). Only append/before/
after and resolve/reopen interfaces are consolidated. Heading-subtree
insertion, replacement, destructive comment operations and table operations
retain their existing contracts and approval hints. The selected catalog is
fixed before accepting client connections. Document-access scope is unchanged.

Consolidated adapters delegate to the existing Python tool functions. Their
descriptions include the unchanged baseline documentation. Success responses
keep operation-specific receipt models. Argument validation rejects missing
anchors, contradictory append selectors and unknown target fields before
Google access. Existing repeated-anchor matching is preserved; consolidation
does not introduce uniqueness validation. Google input/image error recovery
guidance also applies to the new insertion tool.

## Automated evidence

The complete offline run passed: **2398 passed, 1 skipped, 138 deselected**.
The deselected tests are opt-in live scenarios, not model trials. The run log
and JUnit report are `/tmp/gdocs-59-offline-final.log` and
`/tmp/gdocs-59-offline-final.xml`. An earlier run failed because the exhaustive
environment-variable test inventory omitted the new setting; that inventory
was updated before the successful complete rerun.

After isolating research in commit `b8834a2`, the default product suite again
passed **2398 passed, 1 skipped, 138 deselected** in 85.42 seconds
(`/tmp/gdocs-59-product-after-isolation.log`). The separate
`research/tool_consolidation/tests/` suite passed **68 passed, 5 deselected**
in 64.70 seconds (`/tmp/gdocs-59-isolated-research-tests.log`). Default
collection contains no research tests. Global Ruff, explicit research-test
lint, the relocated runner's CLI help and `git diff --check` passed. Wheel and
sdist built successfully; the sdist contains both named study directories,
their READMEs and the relocated research tests. Every study now owns a named
subdirectory, as required by `AGENTS.md` and `research/README.md`.

Focused contract checks cover all four static catalogs, unchanged tools and
annotations, literal/rich native insertion requests and receipts, formatting
overrides, expected revisions, missing/repeated anchors, target validation,
comment action/reply delegation, and structured Google input failure guidance.
The original complete baseline contract digest remains unchanged. Global Ruff
and `git diff --check` passed.

Fresh STDIO discovery passed for all four variants in both access modes. All
non-treatment tool definitions are exactly identical within each access mode;
repeated discovery in the same session is stable. Captures include full schemas,
initialization instructions, process identity and source fingerprints, under
`/tmp/gdocs-59-stdio/test_stdio_study_catalogs_full0/` and
`/tmp/gdocs-59-stdio/test_stdio_study_catalogs_sele0/`.

| Variant | Full-drive tools | Selected-files tools | Full-drive serialized bytes |
| --- | ---: | ---: | ---: |
| A: baseline | 39 | 40 | 232421 |
| B: insertion | 37 | 38 | 225233 |
| C: status | 38 | 39 | 230510 |
| D: both | 36 | 37 | 223322 |

Sizes use sorted-key Python JSON serialization of the full instructions and
catalog, including descriptions, annotations and schemas, with default ASCII
escaping. These are byte counts, not token usage or evidence of correctness.

Full-drive catalog SHA-256 values:

```text
A 544366336de25c02638d251a6fa0028402f47353d8d11f8f8e23c13f2f42077a
B 8e23e80eaf09646be6ed698b158c4f36d945d79fdbc7ff17a3710c82ac31726d
C b51af62ce6561f85c80b2a5d190292c1214e228647a2c5698a546dd9f2851d60
D 2339ad91fed9fa3a323df627d11ba8ddcbbab918f02ed12e82b2d47dab061aed
```

Four live adapter scenarios passed through isolated worktree STDIO servers
against the explicitly authorized development document. Each variant checked
append, before/after insertion, bold/literal text, emoji, a native table, strict
stale-revision rejection, native resolve/reopen action posts with ALL_SAVED,
native comment readback, unchanged surrounding tabs and cleanup. Temporary tabs
and comments were removed. Shared-document setup/final reset passed, leaving
one empty tab, no active comments, no named ranges and no pending suggestions.
All test-owned subprocesses were reaped. Logs and per-variant receipts are under
`/tmp/gdocs-59-live-run/`; JUnit is `/tmp/gdocs-59-live-run.xml`. The document
session report is `/tmp/gdocs-scope-mcp-live-session-r4slg4dc/report.json`.
The four expected `EDIT_CONFLICT` failures in stderr are negative assertions.

An additional combined run of the pre-existing insertion-style, native-comment
and heading-subtree live regressions lost its tool launcher (exit 143), while
the pytest child continued. Read-only host inspection confirmed PID 699070
owned the shared-document lock and matched this exact test command. A second
native-comment invocation correctly refused the occupied lock without touching
the document. Its diagnostic log is `/tmp/gdocs-59-native-comments.log`.
The original run completed: **7 passed in 528.64 seconds**. Its log and JUnit
are `/tmp/gdocs-59-live-regressions.log` and
`/tmp/gdocs-59-live-regressions.xml`. This covers hostile source styles for all
three original insertion tools, nested-list heading insertion, native comment
lifecycle, and heading-subtree revision races in required and target modes.
The session report `/tmp/gdocs-scope-mcp-live-session-hhhjf2h4/report.json`
confirms final reset and subprocess cleanup. The second lock-refused invocation
is retained as an infrastructure attempt, not counted as an application failure
or a passing test.

Worktree live identity: Python 3.14.4, FastMCP 3.3.1, package path
`/home/lapin/.codex/worktrees/4444/gdocs-scope-mcp/src/gdocs_scope_mcp`, source
SHA-256 `24a7be585f48b91ff41368c75bbdbb2a50bc025973a9f088b8692e8444ca9990`.
Source identity, not the editable package's cached version string, identifies
the tested implementation.

Wheel and sdist builds passed and include all 99 Python modules. An isolated
wheel installation successfully ran server identity, baseline discovery,
`both` discovery (36 tools), and authorization CLI help. Its package path was
`/tmp/gdocs-59-wheel-env/lib/python3.14/site-packages/gdocs_scope_mcp`, with the
same source fingerprint. Unconstrained installation resolved FastMCP 4.1.6;
this is packaging/discovery evidence only, not a second live regression run.
Artifacts/logs use `/tmp/gdocs-59-dist/`, `/tmp/gdocs-59-build.log` and
`/tmp/gdocs-59-wheel-*`. The environment selector must be inside FastMCP CLI's
`--command 'env ... gdocs-scope-mcp'`: the CLI filters its child's environment.

## Reproduction

Run from the assigned worktree using its `pyproject.toml` and environment:

```bash
uv sync --locked
uv run --locked pytest -m 'not live' -q
uv run --locked pytest tests/test_tool_consolidation_stdio.py -m 'not live' -q
```

For current opt-in adapter lifecycle tests, use the authorized folder and keep
optional UI waits disabled:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER=1j5SqJ2Iu95te9-u_9y_A0DyLcPbOheWt uv run --locked pytest tests/test_tool_consolidation_stdio.py -m live -q
```

This uses per-test disposable documents and isolated STDIO fixtures. Historical
shared-document evidence above used the earlier fixture contract. Local `/tmp`
artifacts are diagnostic evidence, not durable published evaluation data.

## Model-study readiness and limitations

The user approved `gpt-6-luna`, `gpt-6.1-sol` and `gpt-6-astra`, all at `medium`,
including the disclosed mixture of GPT-6 minor versions 6 and 6.1. Current-chat
turn metadata identifies `gpt-6.1-sol`. Fresh desktop chats confirmed actual
access to each model, and isolated app-server chats confirmed tool callbacks
and exact requested model/settings without provider-model fallback. These are
model identifiers, not a claim to know an immutable backend snapshot.

A [12-chat complete-catalog preflight](tool-consolidation-preflight.md) passed
on one synthetic decision-only scenario. It does not establish an interface
effect or replace the formal study. The user subsequently approved the reduced
120-session pilot and 960-session main stage described above. The larger
original 960/7200 design is superseded for this campaign. The reduced corpus,
paired schedules, state oracles, stopping rules and adoption criteria are
defined in the runner and protocol. The execution manifest was frozen after
the requested directory relocation, before formal model inference.
Pilot results are reported below. Main-stage estimates and human review remain
pending; the pilot does not authorize a default-interface change.

Before a chat-based study, verify that catalog exposure, fresh-session
independence, unrelated-tool restrictions, agent-loop settings and trace capture
can meet the [shared protocol](tool-interface-evaluation.md). Any host-imposed
limitations must be recorded before the pilot, not silently attributed to the
interface. Keep the baseline until the required evidence supports a decision.

## Reduced pilot: 120 completed sessions

This section describes the first campaign, before the authorized restart.

All scheduled pilot attempts completed, with no infrastructure exclusion,
automatic replacement, budget failure or unreaped actor process. Each exact
model ran 40 sessions at `medium`, without provider-model fallback. The pilot
has five independent scenario families, one repeat, both evaluation levels and
four static variants. Main scenarios and their schedule were frozen before
pilot inference and were not changed after observing these outcomes.

Frozen execution manifest SHA-256:
`ba0f1c8908597565c9c96bfebe1292ec49835001388a6bd8381869e5ebed0bc2`.
Protocol SHA-256 at the pre-inference repository revision `1dc550a`:
`4145fe398dd77c4f5aad3bb08cf3716631c6c9d3754d544db3dfce7888f0df85`.
The protocol was copied into the private artifact directory after initial
pilot sessions; its content matches that committed pre-inference revision.
Pilot corpus hash:
`cbe0607760752a28defd0d033500ba1090af05e9daf5a2642960fcd45b7fbee6`.
Held-out corpus hash:
`50b509596af9632ef54c5c907dafbf0ccebe152eced31471de55654a42392afb`.
The manifest retains complete catalogs, schedules, source hashes and state
oracles. Baseline and treatments share the production source fingerprint
reported above; only static interface registration differs.

The following are provisional machine grades; every cell has five trials.
Decision-only success means a correct next operation/clarification, not
completion of a multi-operation workflow. End-to-end first-action scores
include valid initial discovery/reading; the decision-only level is the direct
test of selecting the next operation from supplied state.

| Model | Decision first action A/B/C/D | End-to-end final success A/B/C/D |
| --- | --- | --- |
| `gpt-6-luna` | 4/5, 3/5, 4/5, 4/5 | 4/5, 5/5, 5/5, 5/5 |
| `gpt-6.1-sol` | 5/5, 5/5, 5/5, 5/5 | 5/5, 5/5, 5/5, 5/5 |
| `gpt-6-astra` | 5/5, 5/5, 5/5, 5/5 | 5/5, 5/5, 5/5, 5/5 |

Recovery-free completion equals these success counts. The six unsuccessful
outcomes all occurred on luna: five omitted the required tool call, and one
schema-valid insertion changed literal `**Meeting closed**` into
`Meeting closed`. The latter is an actual unintended content change in the
synthetic document, not merely a blocked attempt. There were no invalid-schema
calls or unnecessary clarification tags. Question relevance itself has not
been human-graded and cannot be established by a `clarify` tag.

For primary D-A first-action correctness, scenario-family bootstrap intervals
(5000 draws, fixed seed, equal model weights) are:

| Model | Decision effect, pp [95% CI] | End-to-end effect, pp [95% CI] |
| --- | --- | --- |
| Equal-model summary | 0.0 [-20.0, 20.0] | 6.7 [0.0, 20.0] |
| `gpt-6-luna` | 0.0 [-60.0, 60.0] | 20.0 [0.0, 60.0] |
| `gpt-6.1-sol` | 0.0 [0.0, 0.0]* | 0.0 [0.0, 0.0]* |
| `gpt-6-astra` | 0.0 [0.0, 0.0]* | 0.0 [0.0, 0.0]* |

The starred intervals are degenerate ceiling samples, not evidence of
equivalence or safety. Five families cannot provide reliable power for the
3 pp improvement and 2 pp noninferiority targets. No pilot contrast establishes
the required improvement; keep baseline. The machine-readable analysis also
contains secondary contrasts, strata and paired treatment-by-model differences.
Those analyses are descriptive, without multiplicity-adjusted claims.

Actual pilot usage was 9,971,540 input tokens, including 7,572,480 cached input
tokens, and 15,281 output tokens (1,641 reasoning tokens are a subset).
There were 270 domain calls: 58 discovery and 97 content/comment reads.
Summed turn time was 1227.8 seconds, including controller callbacks; it is not
elapsed campaign time and excludes fixture setup. No monetary cost is inferred.

Private campaign artifacts are under
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/59-reduced-2026-11-06/`:
`manifest.json`, `protocol.md`, `ledger.json`, per-run `result.json` and
`events.json`, `analysis/pilot.json`, and a 26-item blinded audit packet with
initial fixtures, observed reads, normalized operation names and final states.
Its model/arm key is separate. The full blinded trace audit has not occurred.
These local traces are not published; publication remains a separate action.

During the main run, the user adjudicated m09's unquoted closing text as
allowing both `Verified against the original` and the same phrase with a final
period. The frozen exact-state grader penalizes the latter. Preserve its
primary results and report a separately labeled post-hoc sensitivity using
`--m09-human-sensitivity`. The recorded decision is bound to the main corpus
hash and relaxes only that action-post text; every other target, status,
post-count, content and style invariant remains enforced. This single intent
adjudication does not replace the pending blinded trace audit.

After the same unquoted-punctuation ambiguity appeared in m03, the user
extended the rule to every unquoted inserted paragraph and comment action text
in this corpus. The broader `--terminal-period-human-sensitivity` output is
reported separately from the frozen grades and bound to both corpus hashes.
Permissions attach to the gold insertion position or new action-post index,
so an identical protected paragraph elsewhere cannot be normalized. A paragraph
period must retain the preceding text's style; other literal characters,
formatting, scope, status and post counts remain strict. Replacement strings
are outside this rule. The model prompts, execution and raw traces are unchanged.

The completed pilot's broader sensitivity has the same six unsuccessful
outcomes as the frozen grades. After adding adjudication checks, the isolated
research suite passed **89 passed, 5 deselected** in 59.82 seconds
(`/tmp/gdocs-59-research-post-adjudication.log`). The 28 corpus checks execute
all four production catalogs and validate every allowed insertion position;
negative checks preserve duplicate protected paragraphs, literal characters,
style boundaries, action/status and post counts. Read-only validation against
all five saved native-reference trajectories also passed. Global Ruff and
explicit research-test lint passed. No new model sessions were used for these
analysis checks.

## Restart 001 readiness

The first campaign was stopped for the user-requested infrastructure change:
120 pilot and 118 main sessions completed. Three in-flight reservations remain
counted: one recorded a disconnected-client error during SIGINT; two were
cancelled while waiting for the shared document. Preserve their original
ledger/results and the separate `restart-audit.json`, rather than reclassifying
them as model failures or freeing their budget. The previous ledger SHA-256 is
`0a498a0a8b5a4845b63bf3694414ddb94b39040ee49bf567c212173b009470a7`.

The interrupted shared-document cleanup did not finish inside that run. A
separate existing native-reference context performed and verified final
cleanup: one empty tab, no active comments or suggestions, and all owned MCP
processes reaped. Evidence is `interruption-cleanup/live-cleanup.json` under
the first campaign's artifact directory. No actor model was invoked for it.

Local `main` at `2070654` introduced test-owned disposable documents. It was
merged in `3ef6aee`; 55 integration checks and 21 lifecycle checks passed.
Pytest hook signatures were reduced to their used arguments and interruption
error propagation kept an explicit lint exception. No product implementation
or MCP catalog changed. The authorized folder is read from the workspace's
current instructions and still requires an explicit environment opt-in.

Commit `b556893` adapted research to one document per native job and verified
independent ownership, cleanup and lack of a permanent-Doc fallback. A real
m01 calibration passed in 24.51 seconds; the owned document was verified
trashed and both isolated MCP processes reaped. Its evidence is under
`/tmp/pytest-of-lapin/pytest-109/test_native_fixture_calibratio0/live/`.

The restart will calibrate all 25 gold trajectories on native Docs before
inference and freeze the user-approved period rule as primary grading, with
exact matching as a diagnostic. Native snapshots occur initially, after
mutating calls and finally, avoiding repeated observer reads around unchanged
read-only operations. Native jobs use three independent documents concurrently.
SIGINT/SIGTERM stop new reservations and drain active jobs. Budget lineage,
protocol text/hash, native references and executable hashes are frozen before
new model trials; the previously evaluated scenarios are not described as a
fresh unseen confirmatory dataset.

After restart integration, the full default product suite passed **2408 passed,
1 skipped, 138 deselected** in 122.36 seconds, while the separate research
suite passed **99 passed, 25 deselected** in 93.47 seconds. Logs are
`/tmp/gdocs-59-restart-product-checks.log` and
`/tmp/gdocs-59-restart-research-checks.log`. Global Ruff and explicit research
and fixture lint passed. These checks do not invoke actor models.

Restart preparation passed native/fixture semantic parity on **all 25 cases**.
It created 25 distinct documents, observed three overlapping live contexts,
verified every document trashed and every MCP process reaped. Calibration
covers text, hierarchy, explicit styles/colors and comment state/actions in
the declared corpus; it does not establish complete Google API emulation.
No actor sessions were used for preparation. Evidence is under the separate
`restart-001/live-references/` directory. The frozen restart manifest is
`e6c15741378738c86ddf71fa3840ea6529d15e5f3b278ef550f1ba82d2e80b82`;
its protocol hash is
`afebd91f6075724711c46964825497d156dd9aad4a1a97b7c7c3c4d533d8f13b`.
The manifest records Codex CLI `0.166.0-alpha.6`, commit `fa01992`, 1080 new
sessions, 241 prior attempts and the cumulative cap of 1321. The version probe
emitted a read-only PATH-alias warning but returned successfully; actor runs
use the approved ordinary Codex state access.
