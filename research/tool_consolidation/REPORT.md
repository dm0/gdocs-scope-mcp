# Tool consolidation model study

Date: 2026-11-06. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).
Status: restart pilot complete; fixed main schedule still running.
The baseline remains the default. Main estimates and the adoption decision
will be reported after all planned attempts finish, without interim stopping.

## Scope and implementation

The study compares four static MCP interfaces over the same implementation:
A baseline, B typed insertion, C typed comment status, and D both treatments.
Insertion combines append/before/after with a discriminated target; comment
status combines resolve/reopen with an explicit action. Existing tool functions
perform the operations, retaining targeting, revisions, rich/literal content,
receipts and failures. Heading-subtree insertion and other operations stay
unchanged. Catalogs never change during a session.

See [migration/configuration](../../docs/development/tool-consolidation.md)
and [implementation validation](../../docs/development/tool-consolidation-report.md).
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

The manifest retains exact catalogs, source hashes, schedules, state references,
protocol text/hash and prior-ledger lineage. See [study commands](README.md)
and the [shared protocol](../../docs/development/tool-interface-evaluation.md).
Run from this checkout's root Python project. Source/manifests are checked
before inference; every attempt is reserved once before model startup. SIGINT
and SIGTERM drain active work before exiting. Resume only unstarted jobs.

Full private artifacts are under
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/59-reduced-2026-11-06/`,
with the restart in `restart-001/`. They include raw events, tool calls,
post-states, usage, per-job cleanup reports and a blinded audit packet with a
separate model/arm key. Public numeric outcome tables omit account, document
and chat identifiers. Raw trace files remain untracked.
