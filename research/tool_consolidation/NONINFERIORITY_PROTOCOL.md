# A versus D noninferiority: stage one

Prospective protocol, 2026-11-06, issue #59. This is a new campaign; prior
outcomes inform planning only. The approved stage is exactly 1500 attempt
reservations in fresh chats. No continuation, replacement actor, extra pilot
or automatic stage two is authorized. Prior reservations remain 1321; the
new cumulative maximum is 2821. Failed/setup/interrupted reservations consume
the cap. Resume only unstarted scheduled jobs, with the frozen inputs unchanged.

## Objective and estimand

Reduce the catalog from 39 to 36 full-drive tools while limiting a loss in
full-task success to less than 2 percentage points for each model. Positive
correctness improvement is not required. Compare only baseline A and both
consolidations D. Keep unchanged product adapters, implementation fingerprint,
tool policy and permissions across arms. No decision-only trials are included.

Models: gpt-6-luna, gpt-6.1-sol and gpt-6-astra, reasoning medium. Model IDs
are not immutable provider snapshots; no model/provider fallback is allowed.
Each trial checks effective returned model/effort, captures the actual complete
input catalog, and starts an isolated ephemeral Codex actor with unrelated
capabilities disabled. Dynamic-tool output-schema/approval-UI limitations of
the earlier study remain. No tested actor grades its own success.

## Cases and pairing

The deterministic generator samples ten fresh task instances from each of the
25 existing semantic templates, with new labels, read answers, protected context
length and insertion paths. There are 250 distinct task instances, not 250 new
independent semantic families. This is a fixed, stratified benchmark mixture;
results do not establish noninferiority on arbitrary documents, unseen task
families, tables, chips, uploads, complex lists or suggestions.

For each model, each task is run once with A and once with D: 250 pairs, 500
actors per model, 1500 total. Fresh chats and documents/fixtures prevent state
sharing. Pair arms use the same request, initial state and backend; arm order
is counterbalanced and pair order shuffled before inference. Repeating one
task in many chats does not manufacture new semantic families.

The first generated instance of every template uses real disposable Docs for
all models/arms: 150 native actor attempts. The other 1350 use the deterministic
API seam under unchanged production MCP operations. Report native and synthetic
outcomes separately. The primary target is this declared backend mixture, not
an all-native Google Docs claim. Real IDs exist only in private artifacts and
explicit runtime environment variables, never repository files.

Before inference: create all 250 fixture gold trajectories; calibrate all 25
native representative trajectories at every prefix, including model-visible
whole-tab/scoped reads and comment content/status/anchor tab/quote. Ignore
timestamps, author identity, generated IDs, offsets and whitespace-only rendering
differences when comparing observations. Compare semantic protected state too.
Force plain insertion in m05/m16 native representatives. Check every emitted
operation's success. Preparation consumes no actor sessions.

## Repairs and primary grading

The simulator clears headingId when a paragraph becomes NORMAL_TEXT. Both
m05/m16 scoped-read continuations must pass on fixture and native backends.
m11 explicitly permits reopening its comment even when anchored in Reference,
while requiring Reference text and formatting unchanged. This removes the
common scenario ambiguity without hiding comment anchors from the model.

Primary success requires the final gold-equivalent document/comment state,
including protected tabs, explicit styles and action-post count. Equivalent
tool trajectories are accepted. Ordered requests retain prefix checks. Actual
mutations are observed initially, after every write and finally. Model claims
of completion are not sufficient. A correct verbal plan without calls does
not complete an editing request.

Freeze the user's optional-terminal-period rule for unquoted inserted text
and action text, with exact placement/style/other text retained. Read-only
batch answers must match the source line exactly after one HTML entity decode;
only the specified heading may be read. Extra response text, markup stripping
and broader normalization are not accepted. This incorporates the user's
explicit adjudication before new inference. Preserve raw messages and exact
state matching as diagnostics. Clarification/no-op message quality and all
non-successes require retrospective trace review before any adoption claim.

Budgets: 16 domain calls, 4096 output tokens, 120 seconds per synthetic turn,
240 per native turn, at most one scripted clarification. Budget/protocol
failures count as unsuccessful. Authentication/quota/transport failures are
separate infrastructure outcomes, never replaced. Any infrastructure failure
stops new reservations and drains active jobs; resume only unstarted jobs after
inspection. SIGINT/SIGTERM have the same draining behavior. Maximum six actor
jobs, at most three native jobs, in parallel. Native cleanup confirms trashing
only owned IDs and reaps the isolated MCP processes on success/failure.

## Fixed first-stage decision

Finish all scheduled attempts before a statistical decision. Operational
progress checks do not inspect interim treatment estimates or authorize
stopping for apparent success. Analyze each model separately.

Let H be an A-success/D-failure discordance. A conservative sufficient condition
for noninferiority is P(H) < 0.02, since D-A = P(D-only success) - P(H).
If zero H occurs in n independent evaluable pairs, the exact one-sided 99%
upper bound is 1 - 0.01^(1/n). At n=250 it is approximately 1.8252%, below 2%.
The same zero-event bound is conservative for independent heterogeneous pairs
at the fixed mixture's average risk. It still assumes independent actor
outcomes conditional on tasks; shared provider drift is a limitation.

The stage-one machine gate requires all 250 pairs per model evaluable, zero H,
and no observed critical unintended mutation. Missing/infrastructure/unresolved
pairs prevent the strict gate; also report the evaluable-pair bound and a
worst-case missing-pair interpretation. Do not silently exclude difficult tasks
or declare a failed arm successful. Require all supported models to pass for
an all-model adoption claim, plus trace review. Passing this conservative gate
does not assert equality or safety on untested task types.

Allocate one-sided alpha 0.01 to this first-stage gate. Reserve 0.015 for a
possible future stage, whose design/budget require separate user approval.
No such continuation is executed or implied here. More observations cannot
guarantee noninferiority when a real loss exceeds the margin. The planning
power estimates are approximate and do not promise all models will pass.

Report arm success, paired wins/losses, sample variance, schema/semantic errors,
unintended mutations, recovery/clarification, usage/cached subsets, completed
turn latency, cleanup and every infrastructure failure. Provide descriptive
95% paired template-family bootstrap intervals (25 clusters, 5000 seeded draws),
separately from the exact first-stage gate. Degenerate bootstrap intervals do
not prove equivalence. Preserve all machine grades, raw traces, checksums and
any later adjudications as separate analyses. Never pool earlier campaigns.

Freeze source/protocol/corpus/catalog hashes, both prior ledgers, shuffled
schedule, references, model settings and budgets before the first actor.
Commit implementation steps and validation before inference; do not push or
publish without authorization. Leave baseline as default pending the results
and a concrete adoption decision.
