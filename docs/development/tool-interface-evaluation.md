# Tool interface evaluation design

Status: studies planned; Study 1 has opt-in static adapters, but no model
evaluation results have been collected. See the
[implementation and validation report](tool-consolidation-report.md).
Date: 2026-11-05.

## Active resource-bounded Study 1 profile (approved 2026-11-06)

The user explicitly replaced Study 1's initial sample-size plan below with a
maximum of **1080 new model sessions**: five pilot scenarios x three approved
models x four variants x one repeat x two levels = 120; twenty held-out
scenarios x three models x four variants x two repeats x two levels = 960.
No increase beyond this cap is authorized by the original larger plan.

The five pilot cases cover one scenario per stratum. Main-stage counts are six
insertion, four comment status, four multi-step, three ambiguity/absent-target
and three unchanged controls, with ten Russian and ten English requests.
The corpus is `research/study_scenarios.py`; its pilot and main family labels
and templates are disjoint. It does not cover every edge case in the larger
design: tables/cells, uploads, chips and complex list insertion are outside
this reduced corpus and cannot be generalized from these results.

All other controls below remain applicable. Freeze corpus, runtime, catalog,
execution budgets and grading hashes before pilot model trials. Count failed
model-session attempts against the cap; preserve them and do not silently
replace them. Earlier access checks and the twelve-chat infrastructure preflight
are separate, already-completed engineering checks and must be reported as such.
Any live model confirmation sessions must be selected within the 960-session
main schedule, not added on top. The predeclared live subset is main scenarios
m01, m08, m11, m15 and m20, end-to-end level, second repeat, all models/variants:
60 native confirmation sessions, serialized under the development-Doc lock.

Five pilot cases are an execution/feasibility check, not a reliable power
estimate. Twenty independent main scenarios provide preliminary evidence.
Preserve the original effect and safety decision criteria, report paired
intervals and their small-sample limits, and keep baseline when evidence is
insufficient. More repeats cannot substitute for independent scenarios. Do
not increase the scenario count after observing outcomes. Retain a blinded
audit packet for ambiguous intent and sampled successes/failures; do not claim
human review before a human has actually reviewed it.

[Development](../development.md) · [Implementation notes](implementation-notes.md)

## Purpose and required deliverables

Evaluate whether tool consolidation and on-demand catalog exposure improve
agents' understanding and correct use of this MCP server. These are separate
implementation and evaluation projects. Implementation alone does not complete
either project: each requires a post-implementation controlled study, a report
committed to the repository, and a documented adoption decision. A negative or
inconclusive result is valid evidence; it must not be reported as an improvement.
Keep an executable baseline until the corresponding study is complete.

The primary observable proxy for understandability is the first semantically
correct action, including target and arguments. Also measure recovery-free
completion, final correctness, unnecessary actions and unintended changes.
Do not use the model's own claim that an interface is clearer as evidence.

## Model roster

Use exactly three accessible models from the same provider and generation:

| Role | Selection rule |
| --- | --- |
| Current | The model used for the originating development chat |
| Weaker | A less capable model of the same generation |
| Stronger | A more capable model of the same generation |

Before the pilot, record exact provider model identifiers or snapshots, the
generation, the date, access route, and the evidence for the capability ordering.
If the current chat model cannot be identified or accessed by the harness,
resolve that limitation explicitly; do not silently substitute a model.
Do not infer API identifiers from UI labels. Do not include other providers,
substitute an older generation, or count different reasoning settings of the
same model as three models. If the roster is unavailable, report the blocked
comparison rather than inventing results.

Fix sampling, reasoning settings and budgets within each model across variants.
Equivalent setting names across models do not imply equal computation. Estimate
interface effects within each model; cross-model absolute scores are secondary.

## Study 1: tool consolidation

Evaluate two independent changes in a 2-by-2 design:

| Variant | Append / before / after insertion | Resolve / reopen comment |
| --- | --- | --- |
| A: baseline | Separate tools | Separate tools |
| B: insertion | One typed insertion tool | Separate tools |
| C: status | Separate tools | One typed status tool |
| D: both | One typed insertion tool | One typed status tool |

All variants expose their complete catalog. Disable host-side deferred discovery
for this controlled study when possible; otherwise freeze and document its
behavior and limit the causal claim accordingly. Capture the actual catalog,
schemas and instructions for every variant. Do not assume the historical tool
count of 35: newer tools and access-mode differences may change it.

Implement thin adapters over the same application operations. Normalize calls
to semantic operations for grading. Preserve matching, heading/tab scope,
rich/literal content, revisions, receipts, atomicity, authorization, approval
policy and error behavior. A merged insertion schema must require an anchor
for before/after and disallow contradictory target fields. Keep heading-subtree
insertion unchanged in this first study and include it among plausible distractors.

Keep descriptions equivalent in factual content and editorial quality. Do not
give only the merged variant better examples or instructions. Record serialized
schema size without padding variants to equal length. Treat changed schema size
as part of the interface treatment. If adapters cannot preserve semantics, split
out that change and revise the protocol before evaluating.

Single and batch replacement consolidation is a later candidate. It must not
introduce batching, different matching rules or atomicity into only one arm.
Do not collapse all table operations or mix reads and writes as part of this study.

The predeclared primary contrast is D minus A. B and C estimate the individual
effects and their interaction; report them even when D looks favorable.

## Study 2: dynamic catalog

Use one fixed tool interface and implementation for all arms. Prefer the
Study 1 adoption decision as the baseline. If Study 1 is incomplete, use the
existing interface and explicitly avoid attributing results to consolidation.

Compare a full static catalog with an implemented on-demand mechanism that
keeps a defined core visible and discovers additional tools when needed. Keep
the same underlying operation set, scopes and document permissions. Freeze
core membership, descriptions, search ranking, result limits, grouping and
client configuration before opening the held-out set. A mechanism that simply
removes capabilities is not an equivalent treatment.

Verify compatibility with the negotiated MCP version and the actual target
client. In particular, MCP 2026-07-28 restricts per-connection and request-side
effects on tool listings; do not assume an activation call followed by a changed
catalog is portable. Research client-side deferred loading, search/proxy-based
discovery and supported catalog notifications before selecting an implementation.
Test reconnection, isolated client state, missing search results and discovery
failure. A proxy must retain meaningful validation, errors, provenance and
approval distinctions between read, write and destructive operations.

For an explicitly implemented search mechanism, record tool discovery recall,
time to a usable definition, searches, re-searches, schema retrievals, proxy
failures and discovery loops. Grade the first correct domain action separately
from discovery calls: an expected search is not a wrong operation. Conversely,
include all discovery overhead in latency, tokens and cost. Compare cold and
previously-discovered workflows as separately defined strata, with matched
logical task history and fresh independent runs in each arm. Do not mix these
strata after observing results.

If comparing more than one discovery implementation, preregister the additional
arms and contrasts rather than choosing the best result on the held-out data.

## Tasks and evaluation levels

Maintain disjoint development/pilot and held-out datasets. Split by underlying
scenario family and document template, not just by wording. Hold-out prompts,
fixtures and answers must not be used to tune adapters, descriptions or search.

Start with 100 independent held-out scenarios:

| Stratum | Count | Examples |
| --- | ---: | --- |
| Insertion | 30 | Append, before/after, repeated anchors, tabs, cells, heading distractors |
| Comment status | 20 | Resolve, reopen, already-correct state, similar threads |
| Multi-step tasks | 20 | Find a section, insert text, resolve the matching discussion |
| Ambiguity / absent targets | 15 | Missing anchors, multiple valid targets, required clarification |
| Unchanged controls | 15 | Reading, tables, replacement, formatting and smart chips |

For Study 2, additionally balance scenarios that need only core tools, need
deferred tools, span multiple groups, or should call no tool. Freeze the scenario
mapping and weights before evaluation. Use a predeclared Russian/English mix
representative of actual use, with natural requests that do not name tools.
Include ordinary tasks and realistic edge cases. Report production-weighted
scores separately from the deliberately enriched challenge-set scores.

Each scenario defines input state, intent, permitted operations, acceptable
targets/arguments, expected final state, required invariants and when to clarify
or abstain. Accept equivalent valid trajectories. Use scripted clarification
answers and the same response policy in every arm.

Run two distinct levels; do not pool their scores:

1. Decision-only: provide the necessary document state and the catalog, then
   grade the next semantic action or clarification. This isolates interface
   interpretation from document retrieval.
2. End-to-end: supply the user request and let the agent read, act and verify
   through MCP. Grade execution traces and final native state. Study 2 must
   include realistic discovery at this level.

## Controlled execution

Use fresh sessions and matched initial state for each scenario/model/variant/
repeat. Randomize and interleave variant order within scenario/model blocks.
Counterbalance catalog order with fixed seeds so order is not confounded with
the treatment. Preserve paired assignments for analysis. Freeze harness version,
server commits, SDK versions, system prompts, budgets and tool-choice settings.

Use one model-neutral agent loop. Provider adapters must not introduce variant-
specific hints. Disable unrelated tools and alternative routes through shell,
browser or direct Google APIs. Enforce identical semantic-action budgets; do
not let a lower raw tool-call count alone make a consolidated arm more successful.
Set separate finite infrastructure, discovery and wall-clock limits and report
budget exhaustion. Do not equalize away real discovery overhead.

Use deterministic fixtures for bulk evaluation, verified against real server
behavior. Confirm finalists on a predeclared, stratified subset through actual
STDIO MCP processes and authorized disposable Google Docs. Record server
identity and source fingerprint. A mocked or in-process run is not live MCP
evidence. Serialize use of the shared authorized development document under its
existing lock; do not create additional remote documents without authorization.
Restore state between runs and verify cleanup and subprocess reaping.

Log catalog exposure, calls, arguments, results, errors, scripted user replies,
final state, usage and timings. Protect credentials and real user content.
Separate infrastructure failures from agent errors using fixed classification
and rerun rules. Report excluded/rerun attempts; retain original traces. A
discovery failure caused by the treatment is an outcome, not an exclusion.

## Grading and metrics

Prefer deterministic state and trace assertions. Use a blinded human reviewer
for ambiguous intents and a fixed, sampled audit of successes and failures.
Hide arm labels and normalize operation names where possible. Reviewers must
not require an exact canonical trajectory. Any model-assisted grader is
secondary and must be calibrated against human judgments; do not let a tested
model grade its own claimed clarity or success.

| Metric | Definition |
| --- | --- |
| Primary: first-action correctness | Correct first semantic operation, target and arguments, or required clarification/abstention |
| Recovery-free completion | Correct result with no invalid or semantically wrong attempted actions and no corrective assistance |
| Final success | Required native state reached within the fixed budgets |
| Unintended changes | Any violation of protected content, tab, formatting, comment or permission invariants |
| Clarification quality | Appropriate clarification or abstention, scored separately from unnecessary questions |
| Schema errors | Invalid names/arguments, including attempted calls rejected before execution |
| Semantic errors | Schema-valid wrong operation, target, scope, value or status transition |
| Efficiency | Repairs, redundant domain operations, raw calls, discovery calls, tokens, latency and cost |

Count blocked harmful attempts as agent errors, even if server guards prevent
mutation. Report attempted errors and actual damage separately. Do not count
syntax validity as understanding, or measure only eventual success after many
repairs. Report all task outcomes, including clarification and no-op tasks.

## Sample size and analysis

For each evaluation level, the starting pilot for Study 1 is 20 development
scenarios x 3 models x 4 variants x 2 repeats = 480 runs. Its initial held-out
plan is 100 scenarios x 3 models x 4 variants x 3 repeats = 3,600 runs.
For Study 2 with two arms, the corresponding counts are 240 pilot and 1,800
held-out runs per level. These are planning counts, not evidence of adequate
power. Record projected and actual model usage and cost separately.

Use the pilot's discordant paired outcomes and scenario-level variability to
calculate sample size for the predeclared meaningful effect and noninferiority
margin. Increase independent scenarios when necessary. More repeats or prompt
paraphrases do not replace independent scenarios. Freeze final sample size and
stopping rules before inspecting held-out results; do not stop when significant.

Analyze paired differences with 95% confidence intervals using scenario/family
cluster bootstrap or an appropriate paired model. Keep variants, models and
repeats paired within each sampled cluster. Report per-model and per-stratum
effects, an equally weighted three-model summary, and treatment-by-model
interaction. Do not assume repeated calls are independent. Prespecify handling
of multiple contrasts, for example a primary contrast and Holm-adjusted
secondary tests. Do not generalize beyond the three tested models.

Before the held-out run, freeze adoption thresholds. Suggested initial targets
are a primary improvement of at least 3 percentage points with a confidence
interval excluding zero, and final-success noninferiority within 2 percentage
points, assessed per model as well as in the summary. These are decision
targets subject to pilot-based feasibility and user agreement, not guaranteed
achievable precision at the starting sample size. No significant difference
does not establish equivalence. Any new critical unintended-change pattern
blocks default adoption pending review; zero observed events does not prove
zero risk. A win on only some models supports a scoped choice, not a universal
improvement claim. Efficiency alone does not establish clearer tool use.

## Completion evidence

Each implementation issue must link a committed report containing:

- Frozen protocol/manifest, baseline and treatment commits, exact model roster,
  client/runtime versions, settings, sample sizes and dataset hashes.
- Catalog/schema snapshots and semantic-equivalence tests.
- Per-model/per-stratum results, paired effects and intervals, error taxonomy,
  interaction analysis and the predeclared decision criteria.
- Reproducible commands, access-controlled trace locations, audit findings,
  infrastructure exclusions and live verification/cleanup evidence.
- Limitations, inconclusive results and an explicit adopt / keep opt-in /
  revise / reject decision. Retain the baseline if evidence is insufficient.

Do not close either issue after implementation alone or replace model trials
with unit tests. Do not change both treatments together and attribute the result
to one. This document records planned research; it does not establish completed
model trials or deployment.

## References

- [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [Testing agent skills with execution traces](https://developers.openai.com/blog/eval-skills)
- [MCP 2026-07-28 tool catalog rules](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [FastMCP tool search](https://gofastmcp.com/servers/transforms/tool-search)
