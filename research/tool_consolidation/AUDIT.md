# Retrospective audit of restart 001

Date: 2026-11-06. Issue: [#59](https://github.com/dm0/gdocs-scope-mcp/issues/59).

## Conclusion

After the user's rendered-text adjudication, combined treatment D and baseline
A have the same observed end-to-end success: **95.83%**, with paired D-A
**0.00 pp [−2.50, +2.50]**. Excluding the entire ambiguous m11 family gives
**99.12% versus 99.12%**, D-A **0.00 pp [−2.63, +2.63]**. The apparent aggregate
loss in the original report is sensitive to scoring and scenario ambiguity.
There is no established deterioration, but these intervals still do not rule
out a loss greater than 2 pp, particularly for Luna.

The product objective is a smaller catalog subject to acceptable correctness,
not necessarily higher correctness. Catalog reduction from 39 to 36 tools is
a benefit. The original improvement criterion remains part of the historical
preregistration; requiring a positive correctness effect is not necessary for
the user's clarified product decision. This audit does not change the default
or claim confirmatory noninferiority.

## Scope and limits of review

This is a retrospective **assistant-led audit**, not an independent human
review. The auditor knew previous results and uses a model from the tested
roster. Treatment-neutral review IDs were used to examine the 104-item main
packet before consulting its key, but request details and native identifiers
can reveal scenario/backend. No claim of complete auditor blinding is made.

Reviewed the 104 sampled request/action/message/final-state summaries, all 49
graded main non-successes, both main infrastructure failures, and all 31 error
responses. Follow-up inspected raw read observations and the owning fixture,
parser and grader code. The sample contains 80 successful and 24 unsuccessful
records; it is stratified for review, not a prevalence sample. Broader automated
checks cover all 1080 frozen result records and their manifest lineage.

The original primary grades, traces, schedules, prior ledger and main analysis
remain unchanged. No new model sessions were started; the cumulative count
remains 1321. Two native engineering continuations were checked separately
through isolated worktree MCP processes; they are not new model trials.

## Findings

| Original graded non-success category | Main records | Disposition |
| --- | ---: | --- |
| Correct-looking verbal action without an actual tool call | 28 | Retain protocol failure; distinguish action intent from tool invocation |
| Question about reopening a Reference-anchored thread while preserving Reference | 9 | Scenario ambiguity; do not treat as demonstrated interface confusion |
| Resolved thread not discovered because reads omitted include_resolved=true | 4 | Retain incomplete execution; visible empty results did not prove absence |
| HTML character references in an otherwise exact answer | 4 | Accept only in separate user-adjudicated displayed-text analysis |
| Unsupported access/capability claim without trying available read tools | 2 | Retain failure |
| Incorrectly transcribed native document ID | 1 | Retain failure; controller correctly prevented foreign-document access |
| Agent wall-time budget exhausted | 1 | Retain frozen budget failure; cause is not established semantic confusion |

These categories total the 49 graded non-successes. Two additional main
infrastructure failures remain excluded from model-error denominators.

### Ambiguity exists in both backends

The earlier report incorrectly said the synthetic fixture lacked an equivalent
comment anchor. Both `FixtureAPI` and `LiveBackend.seed` anchor the m11 thread
to **Protected reference** in **Reference**. Synthetic read observations expose
that anchor too. The nine safety questions comprise two synthetic Sol traces,
four native Sol traces and three native Astra traces. The shared request both
asks to reopen that thread and says to leave Reference unchanged.

This is a common scenario ambiguity. The observed backend gap is not proof of
an anchor mismatch or native-only model failure. Neither final-state gold
calibration nor an oracle that silently chooses one interpretation resolves
the user's intent. Sensitivity therefore removes **all m11 records**, both
levels/backends, all models/arms/repeats, not just unsuccessful native runs.
The four unresolved-thread discovery failures are kept in the original data;
removing the family is not reclassifying them as successes.

### Synthetic scoped-read error

Of 31 recorded semantic error responses, **27 are synthetic docs_read
TARGET_CHANGED responses**: 13 in m05 and 14 in m16, affecting 25 sessions.
The remaining responses are two wrong-document permission denials and two
controller-enforced TARGET_AMBIGUOUS rejections before user clarification.

For the rich=False insertion trajectory, `FixtureAPI.insertText` copies the
next paragraph's headingId into inserted characters. Resetting the inserted
paragraph to NORMAL_TEXT retains that ID. Native heading-scope validation then
sees the same ID twice and refuses a scoped read. Canonical state grading drops
headingId from normal paragraphs, hiding this invalid fixture detail. The
gold calibration used the default rich=True trajectory; it did not exercise
this otherwise equivalent continuation.

Two local MCP reproductions confirmed the duplicate ID and scoped-read error.
The matching native m05/m16 rich=False continuations both passed scoped reads.
Source fingerprint was
`24a7be585f48b91ff41368c75bbdbb2a50bc025973a9f088b8692e8444ca9990`,
FastMCP 3.3.1, using this worktree's environment. The fixture remains frozen;
no actor trial was rerun or repaired.

A separate diagnostic removes only those 27 read errors from the recovery
metric, never from final-success grading. Recovery-free A/B/C/D becomes
95.00/95.81/95.83/94.17%, compared with original
90.00/90.73/89.91/89.17%. Its paired D-A effect is
−0.83 pp [−5.83, +3.33]. Final success is unchanged. The original count of
31 error responses must not be described as 31 demonstrated model mistakes.

### Decision-only measurement

All 28 omitted-call records describe a plausible intended next action; none
contains an emitted wrong mutating call. The prompt says to "choose the next
action" and that a "recorded decision" ends the task, while the grader requires
an actual tool callback for action cases. Some replies even print a complete
tool call as text. This introduces a measurement ambiguity: the original
metric combines semantic selection with invocation of the study protocol.
Keep the frozen failures, but do not present their treatment difference as
pure evidence of choosing the wrong operation. A future decision-only study
should explicitly require a tool call, or collect a structured tool-and-args
decision without executing it, consistently across all arms.

### Read answers and clarification quality

The user explicitly approved a displayed m18 line identical after HTML entity
decoding. The separate adjudication accepts four outcomes: one decision-only
and three end-to-end, all Luna. It requires exactly `Batch: WH-7294-Z` after
one character-reference decode, a final noop, no state changes and only allowed
scoped reads. Extra text, markup stripping and other tasks are not relaxed.
The user decision is preserved in
[rendered-verbatim-answer.json](adjudications/rendered-verbatim-answer.json).

All 19 originally successful end-to-end m18 traces read only h.delivery;
no m18 trace mutated state. The two unsupported access/capability claims remain
failures: read tools were available. Sample review-065 incorrectly says Reviews
is a heading rather than a body paragraph although both exist; its clarification
still obtains the intended subtree placement. A successful state score does
not guarantee an accurate explanation. Future review must keep message quality
separate from mutation correctness.

## Sensitivity estimates

All intervals use the existing 5000 seeded scenario-family bootstrap with equal
model weights and complete four-arm blocks. These are post-hoc analyses, not
a replacement preregistration or independent confirmation. Do not select only
the most favorable row.

| Analysis | End-to-end D-A final success, pp | Families / used blocks |
| --- | --- | --- |
| Original frozen grades | −1.67 [−5.83, +1.67] | 20 / 118 |
| Exclude entire m11, otherwise strict | −1.75 [−6.14, +1.75] | 19 / 113 |
| User-adjudicated rendered m18 answers | 0.00 [−2.50, +2.50] | 20 / 118 |
| Rendered answers and exclude entire m11 | 0.00 [−2.63, +2.63] | 19 / 113 |

Per-model final-success effects for rendered answers are Luna
−2.50 [−10.00, +5.00], Sol +2.50 [0, +7.50], Astra 0 [0, 0]. With m11 also
excluded they are Luna 0 [−7.89, +7.89], Sol 0 [0, 0], Astra 0 [0, 0]. Zero
empirical intervals for Sol/Astra are degenerate and do not prove equivalence.
The combined corrected summary is reassuring, but cannot certify the -2 pp
margin for each supported model.

Without m11, A and D each have one remaining unsuccessful end-to-end attempt:
A has the Luna wrong-document ID in m08; D has the Luna timeout in m02.
There are no demonstrated unintended mutations. These two different scenario
failures explain the nonzero interval despite equal aggregate success.
Controls and the timeout stay in the sensitivity; they were not removed to
force equality.

## Reproduction and validation

Run from the root Python project:

```bash
uv run --locked python research/tool_consolidation/audit_reduced_study.py --output ARTIFACTS/restart-001
uv run --locked pytest research/tool_consolidation/tests/test_study_audit.py research/tool_consolidation/tests/test_study_analysis.py -m 'not live' -q
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER=1j5SqJ2Iu95te9-u_9y_A0DyLcPbOheWt uv run --locked pytest research/tool_consolidation/tests/test_study_audit.py -m live -q
```

Private evidence is in the existing restart directory under
`analysis/retrospective-audit.json`, including hashes of every original result,
failure categories and all model-specific sensitivity estimates. Original main
analysis SHA-256 remains
`5bf083d21a39dac8b1d5f89a17d7ba7ba3fb6c163581419e2ff7adea425da289`.
Audit SHA-256:
`81913b030b30c0f9212a27c1bada9a21dea98d2666a7db489e5b25d06164d0db`.
Main review-packet SHA-256:
`3095b829dbc111e50478f8f079d29117f4ee8acb06cdbeac1c6d826724da9acb`.

Checks: 22 focused offline tests passed, two live tests passed, Ruff and
whitespace checks passed. Initial native test setup failed because it tried
to load campaign references from pytest's temporary directory; reference mode
corrected that engineering test. All four documents created across the failed
setup and successful continuations were verified trashed, with both MCP
children reaped per case. Logs: `/tmp/gdocs-59-audit-checks-final.log` and
`/tmp/gdocs-59-audit-native-continuations{,-resume}.log`; owned cleanup reports
are under `/tmp/pytest-of-lapin/pytest-{125,127}/`. No model budget was used.

Before a future campaign, repair normal-paragraph heading identity in the
fixture, make comment target/protection intent explicit, calibrate model-visible
reads after supported alternative writes, and clarify decision-call recording.
Plan an A-versus-D noninferiority comparison around a user-chosen margin rather
than requiring higher correctness. No further model runs are authorized here.
