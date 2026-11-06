# A/D noninferiority: first-stage report

Date: 2026-11-06. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).
Status: all 1500 authorized attempts finished. The prospective first-stage
noninferiority gate was not met for any model. Baseline remains the default.
No continuation, push, publication or deployment was performed.

## Result and decision

The ledger contains 1488 completed attempts, one agent timeout and 11
infrastructure failures. Exactly 500 attempts were reserved per model. All
reservations count toward the authorized 1500, bringing cumulative consumption
to 2821 including the two preserved earlier cohorts. No attempt was replaced.

Post-run trace review found a malformed m04 gold reference in six generated
instances: the request explicitly required bold text, but the generator had
randomly selected rich=False and expected literal asterisks. Frozen primary
grades remain in `stage1-analysis.json`. A separate, explicitly post-hoc
`stage1-bold-sensitivity.json` corrects only that gold flag. It converts exactly
36 false failures to successes: six instances in both arms of all three models.
All other metrics and source traces are retained; all 60 scheduled m04 outcomes
were checked, including the native references and one infrastructure failure.
The paired A/D effects and discordance counts do not change.

| Model | Frozen success A | Frozen success D | Bold-corrected success A | Bold-corrected success D |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 232/248 (93.55%) | 235/249 (94.38%) | 238/248 (95.97%) | 241/249 (96.79%) |
| gpt-6.1-sol | 242/248 (97.58%) | 241/247 (97.57%) | 248/248 (100%) | 247/247 (100%) |
| gpt-6-astra | 242/249 (97.19%) | 242/248 (97.58%) | 248/249 (99.60%) | 248/248 (100%) |

Infrastructure failures are excluded from observed success denominators;
the agent timeout is a failure. These marginal rates have different denominators.
The following effects instead use only complete matched pairs. Variance is
the sample variance of D minus A with success encoded as 1 and failure as 0,
in squared proportion units, not the variance of the estimated mean.

| Model | Evaluable pairs | A-only / D-only successes | Mean D-A, pp | Variance(D-A) | Descriptive 95% CI, pp |
| --- | ---: | ---: | ---: | ---: | ---: |
| gpt-6-luna | 248 | 7 / 9 | +0.81 | 0.064712 | [-2.40, +3.20] |
| gpt-6.1-sol | 247 | 0 / 0 | 0.00 | 0 | [0.00, 0.00] |
| gpt-6-astra | 247 | 0 / 1 | +0.40 | 0.004049 | [0.00, +1.20] |

Intervals resample the 25 semantic templates, with 5000 draws and frozen seed.
They describe this benchmark mixture. The degenerate sol interval is a ceiling
sample and does not establish equivalence. For sol and astra, zero observed
A-only successes among 247 evaluable pairs gives a one-sided 99% zero-loss
upper bound of 1.8472%, conditional on evaluability and the protocol's sampling
assumptions. It cannot waive the three missing pairs per model. Luna has two
missing pairs and seven observed A-only successes; its descriptive interval
also crosses -2 pp. All three strict gates therefore fail. This is insufficient
evidence of noninferiority, not proof that consolidation worsens correctness.

The template dependence, fixed task mixture and predominantly simulated backend
further limit interpretation of the exact binomial bound. It is not a general
Google Docs reliability guarantee. No decision is based on a pooled model mean.

## Trace review and backend checks

After the separate bold correction, 19 graded non-successes remain. Eighteen
are on luna: six failures to discover resolved comments, eight insertions
omitting requested words, one formatting call covering only part of the target
phrase, and three responses incorrectly claiming that the provided tools or
document identifier could not be used. The remaining astra baseline attempt
timed out after two read calls; its underlying cause is unestablished and its
failure grade is retained. Nine unintended mutations are the eight incomplete
insertions and the partial formatting span, all on luna (three A, six D).
There were no schema-invalid calls. All actor processes were confirmed reaped.

In particular, m11 now gives explicit permission to reopen the Reference-anchored
comment. Its remaining seven failures are discovery, omitted text or a false
capability claim, rather than the original conflicting scope instruction.
No docs_read TARGET_CHANGED failures or unsupported fixture operations occurred.
This is an unblinded assistant trace review, not independent human adjudication.
Literal words, formatting, targets and comment actions were not relaxed.

Bold-corrected observed final success by backend is:

| Model | Fixture A | Fixture D | Native A | Native D |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 213/223 | 217/224 | 25/25 | 24/25 |
| gpt-6.1-sol | 224/224 | 224/224 | 24/24 | 23/23 |
| gpt-6-astra | 223/224 | 224/224 | 25/25 | 24/24 |

Native samples cover only one instance per template and are too small for a
separate 2 pp noninferiority claim. Calibration and model execution together
created 175 distinct owned disposable documents. All 175 were verified trashed,
and all associated MCP processes were reaped, including failed attempts.

The 11 infrastructure failures include provider capacity, TLS/stream and Google
transport errors. On failure the controller stopped reservations and drained
active jobs; later invocations continued only unstarted jobs. Concurrency was
adjusted between one, three and six within the frozen maximum of six, with at
most three native jobs. No interrupted actor was replayed. Operational logs
include the initial run and resumes 001 through 006 under `/tmp/gdocs-59-ni-stage1-*`.

Recorded usage across all attempts is 185,722,935 input tokens, including
178,237,440 cached input tokens, and 342,263 output tokens. Domain calls total
5863. Summed completed-turn duration is 24,010.27 seconds, not campaign wall
time. Incomplete turns may lack usage; no monetary cost is inferred.

## Scope

The user authorized exactly 1500 additional attempts, with any continuation
requiring separate approval. Earlier campaigns retain 1321 reservations;
the cumulative maximum for this stage is 2821. Failed and interrupted
reservations consume the cap and are never replaced. Prior outcomes are not
pooled. The runner has no stage-two action.

Compare full-task execution on baseline A and fully consolidated D only.
Each of gpt-6-luna, gpt-6.1-sol and gpt-6-astra runs 250 matched task pairs,
reasoning medium, for 500 attempts per model. Every trial is a fresh isolated
Codex chat with the actual static catalog. Models, effective effort, tool
callbacks, usage, state and process cleanup are recorded. Product source is
identical across arms; only catalog registration differs.

The target is the declared fixed benchmark mixture: 250 new task instances
from 25 existing semantic templates, ten per template. New labels, protected
context, read answers and insertion paths vary. These are not 250 new semantic
families. Per-template instances and arm order are fixed before inference.
The design contains 150 native attempts and 1350 synthetic API-seam attempts;
paired arms always use the same backend. It does not establish an all-native
or arbitrary-document noninferiority claim.

See the prospective [protocol](NONINFERIORITY_PROTOCOL.md), [commands](README.md)
and the [retrospective audit](AUDIT.md) motivating this separate campaign.

## Repairs and validation before inference

Commit `e1bce6b` clears inherited headingId when the simulator resets a paragraph
to NORMAL_TEXT. Scoped reads after m05/m16 plain insertions now succeed. The
m11 request explicitly permits reopening the comment even if anchored in
Reference, while preserving that tab's text and formatting. No model-visible
comment anchor is hidden to remove the ambiguity.

Before the first actor, all 250 fixture gold trajectories passed. All 25 native
representatives passed every gold prefix's semantic state plus whole-tab/scoped
read and comment-anchor/content/status comparisons. The m05/m16 representatives
force the previously failing plain path. All 25 calibration documents had
distinct owned IDs, verified trashing, and reaped MCP processes.

The full separate research suite passed **116 tests**, with 27 native cases
deselected, in 72.15 seconds. Four focused prospective-controller checks passed,
including reserve-before-dispatch, no replacement on resume, hard cap rejection,
missing-pair handling, exact zero-loss gate and native heading-alias grading.
Ruff and whitespace checks passed. These engineering checks used no actor models.

The post-run generator repair is commit `934981e`. It forces rich=True for
explicit-bold m04 while consuming the same random draw, preserving all other
generated tasks. The frozen manifest, protocol and executed source revision
were not rewritten. New regression checks execute all ten m04 references,
require bold characters without literal markup, and reject the literal-star
alternative. Five focused controller/generator checks passed in 28.75 seconds.
The separate audit records all 1500 raw result hashes, corrected references,
per-outcome metric changes and the frozen primary analysis hash. No additional
model session or native document was used for this correction.
The complete separate research suite then passed **118 tests, 27 deselected**
in 104.71 seconds (`/tmp/gdocs-59-ni-final-research.log`). Global Ruff,
explicit changed-test lint and `git diff --check` passed. Final verification
matched all 1500 raw result hashes, the frozen primary analysis, audit source,
six corrected references and 36 changed grades against the separate audit.

## Prospective decision rule

The product benefit is a smaller catalog; a positive correctness effect is not
required. The noninferiority margin is -2 percentage points per supported model.
At this first stage, require all 250 pairs evaluable, zero A-success/D-failure
discordances, and no observed critical unintended mutation. The exact one-sided
99% upper bound for zero losses in 250 pairs is 1.8252%, below 2%. Missing or
infrastructure pairs block this strict machine gate. Trace review remains
required before adoption. Empirical bootstrap intervals are descriptive and
cannot replace the exact gate, especially if degenerate.

First-stage alpha is 0.01; 0.015 is reserved for a possible separately approved
future stage. The current budget does not authorize that stage. The independence
and fixed-mixture assumptions, generator limits and provider drift remain
material limitations. The protocol freezes the user's scoped optional-period
and exact displayed-line rules before inference, preserving all raw outcomes.

## Frozen provenance

- Harness/protocol commit: `3ba7208ec8ef2535bcbda3f1d78bd96a1ae58cd9`.
- Manifest SHA-256: `a8251f283b652e79b60f61bdfcb74319a861195ca57ab990cf93e5d70a4ce648`.
- Corpus SHA-256: `bb68780a9232a65ba5a7d2b44840ad91c9ab83d0a7c8c93b819bd376da23dc9b`.
- Protocol SHA-256: `e1b305915d2b9f19c602fda0bdcc832b292831e2be892851142c9e5fd683a18c`.
- Product source fingerprint: `24a7be585f48b91ff41368c75bbdbb2a50bc025973a9f088b8692e8444ca9990`.

Private artifacts are under
`/home/lapin/projects/sandboxes/gdocs-scope-mcp/study-artifacts/59-ni-stage1-2026-11-06/`.
They retain the exact source hashes, two actual catalogs, state references,
observations, frozen schedule, ledger, raw events and lifecycle evidence.
Preparation log: `/tmp/gdocs-59-ni-stage1-prepare.log`.
Actor log: `/tmp/gdocs-59-ni-stage1-run.log`.
No real Google folder/document IDs are stored in repository files.
