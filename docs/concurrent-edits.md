# Concurrent edits

Implementation for [issue #32](https://github.com/dm0/gdocs-scope-mcp/issues/32),
building on the [table identity probes](table-identity.md).

## Policy selection

Set `write_revision_mode` in the normal server JSON configuration:

```json
{"write_revision_mode": "target"}
```

Or set `GOOGLE_DOCS_MCP_WRITE_REVISION_MODE=target` in the MCP server's
environment. Environment overrides JSON; the default is `required`. Invalid
values fail settings validation. Restart the MCP process to apply changes.
This is a server policy, not a per-call agent argument. It applies to the
seven indexed edit tools described below. Native replace-all keeps its
execution-time matching; dedicated dropdown tools retain their own required
revision guards.

In `required` mode, the executor below validates the original target and
replans after confirmed revision rejection. In `target` mode, it sends the
original plan with `targetRevisionId` from the original native read. Google
transforms operations against concurrent changes and resolves overlaps. The
local unchanged-target and conflict-rejection guarantees do not apply in this
mode. No fresh revision is substituted automatically after a rejected or
expired target revision; the caller must inspect, reread and decide on a new
operation. `TARGET_REVISION_REJECTED` distinguishes that outcome from an
ordinary input failure. Unknown transport/server outcomes remain unsafe to
retry in both modes.

Concurrent target-mode appends follow Google's transformed ordering, which
can differ from required mode's current-end replanning. Receipt indices are
diagnostic coordinates from the original planning snapshot, not transformed
positions. Target mode does not bypass native smart-entity validation.

Two strict exceptions apply in either configured mode:

- An explicit `expected_revision_id` always requires an exact revision match
  and disables automatic replanning. It is never weakened into a merge.
- Multi-stage table insertion always uses required revisions, including body
  paragraph stages belonging to a table-containing plan. A transformed stage
  can move the cursor or newly created table; later stages cannot safely use
  guessed positions. Before the first commit these plans may use the existing
  bounded, validated required-mode retry; after a commit they report a partial
  result on interruption. This is an intentional limit, not a silent fallback
  to guessed table identity.

## Executor and dependencies

`revision_guards.guarded_edit` owns a call-scoped read/validate/plan/write
executor. `remember_snapshot` retains the native first read of each attempt;
`depend_on` declares the operation's selected source ranges; `submit` chooses
the required or target revision field. Context variables isolate calls without
locks or coordination between production MCP processes. Future table planners
can reuse `submit` and supply narrower table-specific identity/dependencies.

In required mode, indexed search/replace, batch replacement, paragraph deletion,
before/after insertion and comment-anchor creation declare their original
targets before writing. Dependencies retain the affected native paragraph's text,
text-run styles, paragraph styles, bullets, non-text elements and heading-ID
ancestry, plus metadata for referenced lists, objects and dropdown definitions.
Effective named styles and document style must also remain unchanged. Native
absolute indices are excluded; the selected range's relative offsets are
retained and checked. Multi-paragraph ranges declare each touched unit.

On a confirmed revision rejection, the executor reads a fresh snapshot and
requires each original unit to still exist uniquely in both snapshots.
It then runs the original planner, preserving heading scope, case/regex
semantics, matching order and occurrence selection. The freshly selected
targets and relative offsets must agree with the baseline. A new earlier match
cannot silently become the replacement target. Added/removed matching members
of a batch/delete-all target set cause a conflict instead of expanding or
shrinking the operation silently. All UTF-16 indices come from the fresh
snapshot; requests from the rejected attempt are not submitted unchanged.

This first implementation deliberately uses paragraph-level dependencies,
not substring-level merging: concurrent changes to different parts of one
paragraph conflict. A paragraph inside a table depends conservatively on its
entire containing top-level table. Independent ordinary paragraphs can rebase;
independent cells await the table-specific references and expected-state
contracts in later tasks. Duplicate identical paragraphs/tables are ambiguous
on retry, even if a human could infer their identity from surrounding text.

These are snapshot/expected-state checks, not access to edit history. A
delete/recreate sequence yielding exactly the same unique native state cannot
be distinguished from uninterrupted existence. No unconditional persistent
paragraph identity or automatic recovery of structural identity is claimed.

Required-mode append has a different dependency: **the current document end**.
After a rejected append, it replans at the newly read end, preserving both
appends. It does not preserve an old absolute insertion index or old end style.
The resulting order follows the successful guarded commits, not call start
order.

## Retries and write outcomes

There are at most three planning attempts, with 50 ms then 100 ms backoff.
Only an explicit required-revision HTTP 400 rejection, or an entity preflight
that detects a revision change before submission, permits automatic replay.
Ordinary HTTP 400 input failures, permissions/quota errors, lost connections,
and server errors are not treated as revision races. The Google client's
write requests do not enable transport retries.

An HTTP 5xx or transport exception during submission becomes
`WRITE_OUTCOME_UNKNOWN`: the batch might have committed. Do not repeat it
without inspecting the document. The executor never retries a committed edit.
Errors remain MCP `isError=true` with typed recovery guidance:

| Code | Meaning |
| --- | --- |
| `EDIT_CONFLICT` | Original content/style, scope, target set or occurrence changed; or an explicit caller revision no longer matches. |
| `TARGET_DELETED` | A source unit was removed, or the original target/scope can no longer be resolved. |
| `TARGET_AMBIGUOUS` | Duplicate native units or unsupported source containment prevent safe resolution. |
| `REVISION_RETRY_EXHAUSTED` | Three confirmed revision rejections prevented completion. |
| `TARGET_REVISION_REJECTED` | Google rejected the original target revision; no automatic retry or revision substitution occurred. |
| `REVISION_UNAVAILABLE` | A native read supplied no usable revision; no unguarded indexed batch is sent. |
| `WRITE_OUTCOME_UNKNOWN` | An in-flight write/side effect might have committed; automatic replay is unsafe. |
| `PARTIAL_WRITE` | Earlier stages committed but later work failed; inspect before a new edit. |

`committed_batches` counts confirmed completed Docs batches, including a
comment-anchor batch. It excludes an unknown pending batch and does not count
Drive/Apps Script side effects. Zero therefore does not prove that an unknown
write had no effect.

## Atomicity and side effects

Batch replacements remain one atomic Docs batch per attempt. All original
targets must validate before it is submitted. Native `replaceAllText`
(`docs_search_replace(occurrence=0)`) keeps execution-time matching, with no
preceding read/rebase; uncertain responses are still never replayed.

Rich/literal ordinary insertions now always carry a required revision.
Temporary local-image uploads/sharing are prepared once per tool call, reused
across rejected attempts and cleaned up after the entire executor exits.
Rebased requests use the same temporary URIs at fresh positions. Cleanup
failures still populate `temporary_image_cleanup_pending` on success; cleanup
does not turn a confirmed edit into a request to repeat it.

Native table insertion still requires multiple committed batches. A confirmed
revision rejection before its first successful stage can replan. After a stage
commits, this implementation does not replay table creation, speculate about
identity, or resume at stale indices. A changed revision before cell lookup or
a rejected later stage returns an explicit partial result. This conservative
boundary remains until table-specific identity and stage recovery are proven.

Comment-anchor creation is guarded, but posting the Drive comment and optional
Apps Script bookmark remain separate side effects. Failures after the anchor
report completed Docs batches. A missing comment response can mean the comment
was created; inspect comments/bookmarks before issuing another request.

## Agent read preconditions

The default protection covers the backend read-to-write window for this call.
It does **not** establish that content is unchanged since an agent's earlier
`docs_read` call. Pass `expected_revision_id` from that earlier read when a
strict document-wide precondition is required. All seven indexed edit tools
accept it; a mismatch fails before writing, and any write-time revision race
fails instead of rebasing. This intentionally rejects independent intervening
changes too. Native replace-all rejects this parameter rather than ignoring
it or silently changing its matching semantics. Dropdown selection separately
supports the existing `expected_option_id` precondition.

## Verification

Offline regressions force a collaborator commit between the original read and
the attempted write. They cover UTF-16 shifts, scoped matches, independent
paragraphs, changed text/styles, deleted/duplicate/newly matching targets,
concurrent appends, bounded exhaustion, unknown responses, strict revision
preconditions, image upload reuse/cleanup, and interrupted table stages.

Opt-in live tests use two independent STDIO processes and public editing tools.
A test-only read gate makes the interleaving deterministic. The table-stage
gate pauses after the creation batch, letting the other process edit before
cell lookup. These gates do not exist in the packaged server and are not
production locks. Each run validates source fingerprints, records identities,
reads back native content, restores the original document body, and reaps both
processes.

Initial required-mode verification on 2026-10-27: the full offline suite passed with 1123 tests and
45 opt-in skips; the combined table/concurrency probe file passed all eight
tests (six live scenarios and two offline checks). Every live scenario
reported successful checks, exact original-body restoration and subprocess
reaping. Both processes in every scenario loaded source fingerprint
`9e52416ea6f0d2272aaf37ddd44919c9b18c2481fed4b961229b71e93512c31f`.
Ruff and whitespace validation passed. Expected conflict/partial-write
failures were observed in stderr alongside successful revision retries.

Both-policy verification on 2026-10-27: 1132 offline tests passed. Ten public
live scenarios passed across required/target modes: shifted targets, overlapping
replacements, concurrent appends, interrupted table stages, and strict caller
revision preconditions. Every scenario restored the exact initial document
body and reaped both STDIO processes. All ten loaded source fingerprint
`024ad07081dbec025950d398a3fd353e62267136caa110badf299f5471799a33`.
Configuration tests cover defaults, JSON/environment precedence and invalid
values; offline regressions also verify target rejection without replay,
unknown outcomes, entity preflight, and required-only table stages.

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC='your-disposable-document-id' \
  uv run --locked pytest -q tests/test_live_table_identity.py -k public_edit
```

Only use an authorized disposable document without other editors. These tests
own their appended tail, including both processes' synthetic changes; cleanup
must not race unrelated human writes. Reports and logs use
`/tmp/gdocs-scope-mcp-table-probe-public-{shift,overlap,append,table,strict}-{required,target}.*`.

Google's [batchUpdate/WriteControl contract](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate)
documents required-revision rejection, batch atomicity and target-revision
conflict resolution. Required mode uses our dependency checks; target mode
explicitly delegates conflict resolution to Google instead.
