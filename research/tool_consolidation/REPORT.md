# Tool consolidation model study

Current product decision (2026-11-09): validation accepted by the user and
toolset `v2` adopted as default. See [completion and limitations](DECISION.md).
The dated study results and original recommendations below are historical
and remain unchanged; acceptance does not establish Luna noninferiority.

Date: 2026-11-06. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).
Status: all 1080 restarted attempts finished; machine analysis complete.
Full blinded human review and external publication remain pending.
The [retrospective audit](AUDIT.md) corrects the m11 interpretation and reports
separate user-adjudicated displayed-text and fixture-error sensitivities.
With the displayed-text adjudication, end-to-end A and D both reach 95.83%;
paired D-A is 0.00 pp [−2.50, +2.50]. The frozen tables below remain unchanged.

## Result and adoption decision

Keep **baseline** as the default. The combined treatment D shows a positive
decision-only point estimate, but its primary interval includes zero. The
end-to-end result does not establish the required final-success noninferiority,
especially for Luna. The predeclared adoption criteria are not met. Retain
the four opt-in static variants for further evaluation; do not claim improved
correctness, equivalence or safety from this study.

The fixed main schedule reserved all 960 attempts: 957 completed, one agent
budget failure, and two infrastructure failures. All 480 decision trials were
graded; 478 of 480 end-to-end trials were graded. Infrastructure failures are
excluded, while the budget failure is unsuccessful under the frozen grader.
The pilot reserved 120 attempts, with 119 completed and one infrastructure
failure; its 114/119 final successes are separate from main estimates.
The restart has 1080 distinct records, 360 per model, with no missing results
or outstanding reservations. Including the preserved prior 241 attempts gives
exactly **1321**, the approved cumulative cap. No failed trial was replaced.

### Main observed rates

Decision-only first-action correctness (each cell has 40 trials per model;
summary cells have 120 and equal model weight):

| Model | A baseline | B insertion | C status | D both |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 82.5% | 82.5% | 72.5% | 95.0% |
| gpt-6.1-sol | 100% | 97.5% | 97.5% | 100% |
| gpt-6-astra | 100% | 100% | 100% | 100% |
| Equal-model summary | 94.17% | 93.33% | 90.00% | 98.33% |

End-to-end final success (40 graded trials per cell except Astra B/C, 39):

| Model | A baseline | B insertion | C status | D both |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 95.0% | 95.0% | 95.0% | 87.5% |
| gpt-6.1-sol | 95.0% | 95.0% | 97.5% | 97.5% |
| gpt-6-astra | 97.5% | 97.44% | 100% | 97.5% |
| Equal-model summary | 95.83% | 95.81% | 97.50% | 94.17% |

Summary first-action correctness for end-to-end A/B/C/D is
98.33/98.33/100/99.17%; recovery-free completion is
90.00/90.73/89.91/89.17%. There were zero schema errors, 31 semantic error
responses, 15 machine-tagged unnecessary clarifications and no protected-state
changes detected by the grader. Clarification tags require review: the native
seeding limitation below makes some apparently unnecessary questions sensible.
Zero observed unintended changes does not establish a population safety bound.

### Paired primary contrasts

D-A effects below are percentage points with scenario-family bootstrap 95%
intervals. Every main estimate uses 20 families. Decision estimates use 40
complete four-arm blocks per model, 120 in summary; end-to-end estimates use
40/40/38 for Luna/Sol/Astra and 118 in summary. All available complete blocks
are used. Incomplete native blocks are excluded even from D-A, as specified.

| Model | Decision first action | End-to-end first action | End-to-end final success | End-to-end recovery-free |
| --- | --- | --- | --- | --- |
| gpt-6-luna | +12.50 [-2.50, 30.00] | +2.50 [-5.00, 10.00] | -7.50 [-20.00, 2.50] | -5.00 [-17.50, 5.00] |
| gpt-6.1-sol | 0 [0, 0]* | 0 [0, 0]* | +2.50 [0, 7.50] | +2.50 [-5.00, 10.00] |
| gpt-6-astra | 0 [0, 0]* | 0 [0, 0]* | 0 [0, 0]* | 0 [0, 0]* |
| Equal-model summary | +4.17 [-0.83, 10.00] | +0.83 [-1.67, 3.33] | -1.67 [-5.83, 1.67] | -0.83 [-5.83, 4.17] |

*Degenerate empirical intervals reflect constant observed family contrasts;
they do not prove equivalence. Summary and Luna final-success lower bounds
fall below the -2 pp noninferiority margin. The primary decision estimate
exceeds +3 pp, but its interval does not exclude zero; end-to-end first action
does not meet either improvement requirement.

Secondary first-action B-A/C-A/interaction effects are respectively
-0.83 [-5.83, 4.17], -4.17 [-9.17, 0.83], +9.17 [2.50, 16.67] for decisions;
0 [-4.17, 3.33], +1.67 [0, 4.17], -0.83 [-5.00, 4.17] end-to-end.
The positive decision interaction and multi-step decision stratum
(D-A +20.83 [8.33, 33.33], four families) are descriptive, without multiplicity
adjustment. Other decision D-A strata are zero point estimates; end-to-end
final-success D-A is -11.11 pp in controls, -2.78 in insertion, zero in
ambiguity and multi-step, and +4.17 in status. Small strata are exploratory.
The Luna-minus-Sol and Luna-minus-Astra decision treatment differences are
both +12.50 [-2.50, 30.00]; this does not establish model moderation.

### Real Google Docs confirmation and validity threat

Native execution completed 58/60 attempts without infrastructure failure;
48/58 reached the specified final state. Synthetic end-to-end success was
410/420, including one unsuccessful budget failure. These are different
scenario mixes and must not be interpreted as an unbiased backend effect.
For the five shared cases, synthetic/native final-success counts were:

| Case | Synthetic first repeat | Native second repeat |
| --- | ---: | ---: |
| m01 literal insertion | 12/12 | 12/12 |
| m08 reopen with action text | 12/12 | 10/11 |
| m11 insert then reopen | 8/12 | 2/11 |
| m15 ambiguous target | 12/12 | 12/12 |
| m20 foreground color | 12/12 | 12/12 |

Native A/B/C/D final-success counts are 12/15, 12/14, 12/14, 12/15.
The native paired equal-model D-A first-action and final-success contrasts
are both zero with degenerate intervals, using only three families and nine
blocks (13 complete blocks available; all models required per family).
Luna alone has five native families: first action +40 [0, 80] pp and final
success 0 [-60, 60]. This subset cannot establish native noninferiority.

Inspection identified a scenario ambiguity in m11. Both native and synthetic
seeding anchor every seeded comment to the first tab's first body paragraph.
Here that is **Reference**, which the request says to leave unchanged.
Synthetic reads also expose this anchor; the earlier native-only explanation
was incorrect and is corrected by the [audit](AUDIT.md). Sol and Astra often
inserted the requested Operations paragraph and then asked whether reopening
the Reference-anchored thread was allowed. That is a reasonable ambiguity
introduced by the harness. Two Luna traces searched without
`include_resolved=true`, received no visible threads and stopped to clarify.
Thus the large m11 backend gap cannot be attributed to the interface or model
alone. Gold state calibration did not detect the common request ambiguity.
Keep all frozen grades, disclose the ambiguity, and require unambiguous comment
targets/protection plus full observation/trajectory calibration in future work.
No new campaign is authorized by this report.

### Operations, failures and trace review

The pilot infrastructure failure was a model-provider TLS EOF. Main failures
were a Google transport error before actor startup and a broken native pipe
after two discovery reads; the latter's root cause is unconfirmed. One Luna
synthetic m02/D trial exhausted its 120-second budget after a successful tree
read; the frozen grader marks first/final/recovery false. This coarse timeout
outcome is not evidence of semantic confusion. Failed attempts remain counted;
only unstarted scheduled jobs resumed after each infrastructure stop.

All 60 native actor-attempt documents and all 25 gold-calibration documents
have distinct IDs and verified trashing. Native child processes and every
started model actor were reaped. One native cleanup initially failed; a
separate ownership-checked recovery confirmed trashing, preserving the original
failure report. No unsupported-fixture-operation calls were observed.

Main usage was 81,233,799 input tokens, including 73,170,816 cached;
141,665 output tokens, including 16,015 reasoning tokens. The pilot adds
9,994,767 input and 15,304 output. Cached/reasoning counts are subsets.
No monetary cost is inferred. Main made 2204 domain calls, including 579
discovery and 803 content reads. End-to-end operational totals follow;
they include partial failed attempts and are descriptive, not paired effects:

| Arm | Domain calls | Discovery | Content reads | Input tokens | Cached input | Output tokens | Completed-turn seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 464 | 146 | 197 | 14811546 | 13824128 | 24668 | 2023.56 |
| B | 468 | 144 | 202 | 14846659 | 13718656 | 25858 | 2053.08 |
| C | 472 | 143 | 203 | 15032223 | 13854208 | 24944 | 1924.35 |
| D | 468 | 146 | 201 | 14796506 | 13734656 | 24642 | 2131.30 |

Latency includes controller/observer work and excludes unfinished turns;
summed seconds are not campaign wall time. The first 80 planned main jobs took
1013.9 s on the old shared-document campaign versus 468.5 s on the restarted
disposable infrastructure (2.16x observed throughput). This logistical
comparison is not a randomized interface effect.

The private main blinded audit packet has 104 examples and a separate key;
the restarted pilot has 25. Full human review has not occurred. The user's
punctuation adjudications are the only completed human scoring decisions.
Machine grades are provisional, especially clarification/no-op semantics,
read-only task responses and the m11 native ambiguity. The optional-period
rule accepted 149 main outcomes whose exact states differed. It does not
relax any other content, placement or style requirement.

## Scope and implementation

The study compares four static MCP interfaces over the same implementation:
A baseline, B typed insertion, C typed comment status, and D both treatments.
Insertion combines append/before/after with a discriminated target; comment
status combines resolve/reopen with an explicit action. Existing tool functions
perform the operations, retaining targeting, revisions, rich/literal content,
receipts and failures. Heading-subtree insertion and other operations stay
unchanged. Catalogs never change during a session.

See [migration/configuration](../../docs/development/tool-consolidation.md)
and [implementation validation](IMPLEMENTATION_REPORT.md).
Implementation commit: `ae597460e0cb161384fbdd1abc4dc94de904de2b`.
All arms share production source fingerprint
`24a7be585f48b91ff41368c75bbdbb2a50bc025973a9f088b8692e8444ca9990`.

| Arm | Full-drive tools | Selected-files tools | Serialized full-drive bytes |
| --- | ---: | ---: | ---: |
| A baseline | 39 | 40 | 232421 |
| B insertion | 37 | 38 | 225233 |
| C status | 38 | 39 | 230510 |
| D both | 36 | 37 | 223322 |

Byte counts are catalog measurements, not token counts or evidence of clarity.

## Frozen restart design

The approved roster is `gpt-6-luna`, `gpt-6.1-sol` and `gpt-6-astra`, all
OpenAI models requested at reasoning `medium`, without provider-model fallback.
Every session checks the effective returned settings. The user explicitly
accepted mixing GPT-6 minor versions 6 and 6.1. Model IDs do not identify
immutable provider snapshots. The originating chat uses `gpt-6.1-sol`.

Each trial starts a fresh ephemeral Codex chat with the actual variant's
function names, descriptions and input schemas. Configured unrelated MCP
servers, web/shell/browser/image/memory capabilities and multi-agent tools are
disabled for the child process. The controller enforces identical document
and operation permissions for every arm. Dynamic tool exposure does not
reproduce native MCP output-schema exposure or the host's usual approval UI.

| Phase | Cases | Models | Arms | Repeats | Levels | Planned attempts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pilot | 5 | 3 | 4 | 1 | 2 | 120 |
| Main | 20 | 3 | 4 | 2 | 2 | 960 |

Decision-only trials receive completed discovery/read context and choose one
next operation, clarification or no-op. Their success is not full completion
of a multi-operation workflow. End-to-end trials start with only the document
ID and request. First-action scoring there accepts the specified initial
discovery/read tools, so decision-only scoring is the more direct next-action
measure. All pilot actor trials use the synthetic API seam.

Main strata contain six insertion, four status, four multi-step, three
ambiguity/absent-target and three unchanged controls. Ten requests are Russian
and ten English. Pilot/main families are disjoint. Fixed paired schedules
counterbalance variants and semantic tool groups. Budgets are 16 domain calls
per end-to-end trial, one call per decision trial, 4096 output tokens, 120
seconds per synthetic turn and 240 per native turn, with one scripted user
clarification. No corrective help or replacement sessions are provided.

The first campaign was stopped for the user-requested infrastructure change:
120 pilot and 118 main sessions completed, with three interrupted reservations.
All **241** attempts remain counted and preserved separately. The user then
approved **1080 new attempts**, for a cumulative maximum of **1321**. Earlier
access/preflight checks were separate, already-completed engineering checks.
Earlier outcome data are never pooled into restart estimates. These main
scenarios were previously evaluated partially; the restart is not an unseen
independent confirmatory dataset. Its prompts and interface variants were not
tuned after the restarted pilot.

## Native execution and synthetic-state limits

Most trials run unchanged product MCP operations over a deterministic Google
API seam. This isolates interface choice from real-document setup costs.
Before restarted inference, all 25 gold trajectories passed semantic-state
comparison against actual Google Docs through isolated worktree STDIO servers.
Each calibration used a separate owned document; all 25 were verified trashed,
all MCP processes reaped, and three documents overlapped in flight.

The main stage includes 60 actual native actor trials: m01, m08, m11, m15 and
m20, end-to-end level, second repeat, every model/arm. They are part of the
960-attempt main budget. Other main trials comprise 480 decision-only and
420 synthetic end-to-end trials. Native outcomes are reported separately,
as well as in the predeclared combined analysis.

The disposable-document infrastructure came from local main `2070654`, merged
in `3ef6aee`. Each native job creates a uniquely named file in the explicitly
authorized test folder, then verifies trashing only its owned ID. There is no
permanent-document fallback or shared-document lock. Native observers snapshot
initial state, every mutating call and final state; read-only calls reuse the
last observation in the private job document.

Calibration checks text, paragraph hierarchy, explicit styles/colors and
comment state/actions. It does not establish complete Google API emulation or
equivalence of every possible erroneous trajectory and response. Default
typographic geometry is not part of cross-backend semantic projection.
Tables/cells, chips, uploads, complex lists and arbitrary Google documents are
outside this corpus. State comparisons within each backend retain the full
protected state represented by the grader. No result should be generalized
beyond this scope or these three model IDs.

## Grading and analysis

Primary state grading accepts the user's explicit rule: an optional terminal
period in unquoted inserted paragraphs and comment action text. The rule was
frozen before restarted inference and is bound to both corpus hashes. Only
the new paragraph at its gold position, or the new action-post index, may vary;
all other characters, styles, targets, status transitions and post counts remain
strict. Replacement strings are not relaxed. Exact-state matching remains a
diagnostic. Earlier strict grades and their separately labeled sensitivities
remain unchanged.

Primary contrast: D-A first-action correctness, separately by evaluation level.
Secondary B-A, C-A and factorial interaction are descriptive. Use 5000 seeded
scenario-family bootstrap draws, preserving arms, models and repeats together.
Give each model equal summary weight. Incomplete four-arm blocks are excluded
from paired effects, not imputed as failures. Report both available and used
blocks. Infrastructure failures remain outside model-error denominators;
model budget/protocol failures retain their declared unsuccessful outcomes.
No multiplicity-adjusted secondary claims are made.

The predeclared adoption criteria require at least 3 percentage points primary
improvement with a confidence interval excluding zero, final-success
noninferiority within 2 percentage points assessed per model and in summary,
and review of critical unintended changes. Twenty independent main families
provide preliminary precision. Repeats do not replace independent scenarios;
degenerate bootstrap intervals do not establish equivalence or safety.
Efficiency alone cannot establish clearer use. A blinded human trace audit is
required before any default adoption claim. Clarification tags do not validate
question relevance, and a tested model does not grade its own claimed clarity.

## Provenance and reproduction

- Frozen harness commit: `fa01992`; Codex CLI: `0.166.0-alpha.6`.
- Native identity: Python 3.14.4, FastMCP 3.3.1, worktree package source above.
- Manifest: `e6c15741378738c86ddf71fa3840ea6529d15e5f3b278ef550f1ba82d2e80b82`.
- Protocol: `afebd91f6075724711c46964825497d156dd9aad4a1a97b7c7c3c4d533d8f13b`.
- Pilot corpus: `cbe0607760752a28defd0d033500ba1090af05e9daf5a2642960fcd45b7fbee6`.
- Main corpus: `50b509596af9632ef54c5c907dafbf0ccebe152eced31471de55654a42392afb`.
- Main analysis SHA-256: `5bf083d21a39dac8b1d5f89a17d7ba7ba3fb6c163581419e2ff7adea425da289`.

Final verification matched the manifest digest, every frozen execution source,
both corpus hashes, the unchanged prior ledger and every scheduled attempt ID.
All 1080 result records carry the frozen manifest hash. Effective returned
model/effort settings matched the approved roster and `medium` in all 1079
started actors; one native setup failure never started its actor.

Validation for the restart included 2408 product tests passed, one skipped
and 138 live tests deselected; 101 research checks passed with 25 native cases
deselected, followed by 15 focused analysis tests passed after the numeric
CSV exporter was added. The 25 native gold cases ran separately and passed
before inference. Ruff and whitespace checks passed. No production source
changed during model inference. These are implementation/harness checks,
separate from the model outcomes above.

The manifest retains exact catalogs, source hashes, schedules, state references,
protocol text/hash and prior-ledger lineage. See [study commands](README.md)
and the [shared protocol](EVALUATION_PROTOCOL.md).
Run from this checkout's root Python project. Source/manifests are checked
before inference; every attempt is reserved once before model startup. SIGINT
and SIGTERM drain active work before exiting. Resume only unstarted jobs.

Full private artifacts are under
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/59-reduced-2026-11-06/`,
with the restart in `restart-001/`. They include raw events, tool calls,
post-states, usage, per-job cleanup reports and a blinded audit packet with a
separate model/arm key. Public numeric outcome tables omit account, document
and chat identifiers. Raw trace files remain untracked.
