# A/D noninferiority: first-stage report

Date: 2026-11-06. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).
Status: frozen preparation complete; the 1500-attempt schedule is running.
No interim treatment conclusion is reported. Baseline remains the default.

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
