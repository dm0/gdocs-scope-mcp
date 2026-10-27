# Table identity and concurrent writes

The implemented reference contract is now based on checked section positions
and structural hashes, with A1 cell addresses and selective snapshots. See
[table references](table-references.md). The named-range probes and candidate
native-identity strategy below remain research evidence; the production table
tools do not create bindings or require a local key.

Research for [issue #25](https://github.com/dm0/gdocs-scope-mcp/issues/25).
These are API observations and a proposed contract for later table tools;
this change does not introduce public table-editing tools or persistent refs.

## Reproduce

Run from the checkout being tested, with its own project environment:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC='your-disposable-document-id' \
  uv run --locked pytest -q tests/test_live_table_identity.py
```

Without the variable, only the offline tests run. A malformed target fails
before Google access. The two live tests each launch two independent FastMCP
STDIO processes from this checkout. They verify `server_info` fingerprints,
package paths and distinct PIDs, and check process exit after closing clients.
The test-only launcher `tests/probes/table_server.py` exposes a document-bound
native read and an allowlisted revision-guarded batch tool. These tools are not
part of the installed server. Existing credentials are reused without printing
their contents.

Each probe appends two identical tables and removes its own appended tail and
named ranges in `finally`. Earlier test content is retained. Use a disposable
document with no other editors during the run: cleanup deliberately owns the
entire tail after the initial append position. A killed runner or API outage
can prevent cleanup; do not assume cleanup succeeded without its report.

Reports and stderr logs are written outside the repository:

- `/tmp/gdocs-scope-mcp-table-probe-lifecycle.json`
- `/tmp/gdocs-scope-mcp-table-probe-revisions.json`
- `/tmp/gdocs-scope-mcp-table-probe-{lifecycle,revisions}.{0,1}.log`

Reports keep synthetic table values, marker presence, relative indices and
physical cell coordinates. They omit document IDs, revision IDs, named-range
IDs/names and credentials. Server identity includes local paths and PIDs;
review these before sharing reports. The checked-in observation fixture uses
only synthetic values and logical labels.

## Verified observations

Observed on 2026-10-27 using two processes authenticated as the same Google
account, with native Docs API readback after every transformation. Each table
contains repeated headers, duplicate cell text, an empty row, a non-BMP emoji
and a U+000B soft break. No visible identity markers are inserted.

The verified runtime used Python 3.14.4 and FastMCP 3.3.1. Production source
fingerprint: `3934ff44e9fbff09b63da8d4d98c126743d77f4992cbe42cc2245073c94109a8`.
Test launcher SHA-256:
`f489c0c8743fd9e939e33c2a070a25f18ab1fdf0d88cf3ab68dab18720c059a8`.
The launcher hash is recorded separately because the production fingerprint
covers package sources, not test files. Per-run PID/startup identities and
outcomes remain in the reports listed above; installed package version alone
does not establish which editable sources were loaded.

| Operation | Observed result |
| --- | --- |
| Bind an entire table | A nonempty range covering its native start/end is accepted. Two identical tables receive distinct range IDs. |
| Bind empty cell | The mandatory terminal newline accepts a one-unit range; a zero-width range is rejected with HTTP 400. |
| Insert text before tables | Named ranges move with the tables; saved character indices become stale. |
| Delete and reinsert all cell text | The text-only range disappears. The range including the terminal newline survives, contracted to that newline. |
| Clear and refill cell | The newline anchor survives both operations. It no longer covers all replacement text. |
| Insert/delete a row before target | The marker follows the same physical cell while its row coordinate changes. |
| Insert/delete a column before target | The marker follows the same physical cell while its column coordinate changes. |
| Merge target with left neighbor | Text moves into the merge head. The target marker survives in the empty physical placeholder at its old column. |
| Unmerge | Text remains in the head; the marker remains in the empty cell. It does not recover the moved content's identity. |
| Delete marked column/row | Markers inside the removed cells disappear. A separate marker checks row deletion after the other marked column was removed. |
| Delete first table | Its whole-table marker disappears. The second table's marker survives despite the changed ordinal and identical original content. |

The API retains physical `tableCells` entries after a merge in this probe,
including a head with `columnSpan=2` and an empty placeholder. Physical array
positions must not be interpreted as a validated logical grid. The probe's
containment helper intentionally reports physical positions only.

These observations do not establish that a named range is a native table or
cell ID. A surviving marker can identify a different semantic object after a
structural operation. A range can also contract or split; later resolvers must
check cardinality, containment and geometry rather than trusting existence.

## Revision behavior

- An edit through process A invalidates process B's saved
  `requiredRevisionId`. B's stale batch is rejected with HTTP 400 and no body
  mutation. B can reread, resolve the same target marker, verify the target
  cell is unchanged, recompute UTF-16 indices, and submit against the fresh
  required revision. Both independent edits then remain.
- Two simultaneous independent-cell insertions using the same required
  revision produce exactly one accepted write. The loser can validate and
  replan against a fresh snapshot, preserving both insertions exactly once.
- A batch containing a valid insertion followed by an invalid deletion is
  rejected without applying the insertion: the native body is unchanged.
- `targetRevisionId` accepts an independent stale-cell edit after another
  cell changes. It also accepts overlapping insertions in the same cell.
  Google chooses their ordering; acceptance is not semantic conflict
  detection. The probe records the resulting text without requiring a
  particular ordering.

These tests exercise real request interleaving across two processes, not two
different OAuth identities. They do not establish ordering fairness, long-term
revision retention, or behavior with simultaneous human UI edits.

## Candidate native-identity strategy (research only)

1. Discover from a fresh native snapshot. Create document-local metadata refs
   bound to native named-range IDs, never visible ID text. Names, table
   ordinals, indices and duplicate cell values are insufficient identities.
2. Consider a whole-table marker and a cell terminal-newline marker as
   candidate anchors. Record tab/segment scope and structural context. Markers
   are hints requiring validation, not permanent IDs with unconditional
   survival. Missing, split, ambiguous or out-of-bounds markers must fail
   closed; never silently rebind by text or ordinal.
3. Resolve against current native structure and verify the expected target
   state at the operation's granularity: text/style for a text edit, relevant
   geometry and spans for a structural edit. A whole-document or whole-table
   content hash would unnecessarily reject edits in independent cells.
4. Plan all indices from that exact snapshot and use `requiredRevisionId` on
   the atomic batch. No process-local lock is sufficient across MCP servers.
5. On a confirmed revision rejection, reread and repeat identity/expected-state
   checks. Replan only if the target is still valid and unchanged; bound retry
   attempts. Never blindly repeat a request after an uncertain transport result.
6. Treat merge/unmerge and target row/column deletion conservatively. The
   marker surviving a merge does not prove the original cell still exists
   semantically. Invalidate affected refs or require explicit re-discovery.
   Preserve unrelated refs only when their structure remains verifiable.

This permits nonoverlapping edits through optimistic validation and replanning,
without a global lock. Later tasks must define the ref payload, expected-state
tokens and conflict response before implementing this proposed strategy.

## Limits and documented API contracts

Not verified: nested tables, multiple tabs/segments, row-spanning merges,
copy/paste or undo/redo of tables, collaborator permissions, named-range quota,
long-lived revisions, UI-driven structural edits, or automatic ref recovery
after a merge. These require additional probes or conservative rejection.

Google documents arbitrary named ranges with distinct IDs and content-relative
adjustments, not unconditional table/cell identity:
[NamedRange reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents#NamedRange).

Google documents required-revision rejection and target-revision conflict
resolution, with a limited recent-revision window:
[WriteControl reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate#WriteControl).

Google documents concatenation into the merge head and retention of text there
when unmerging:
[mergeTableCells](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#MergeTableCellsRequest)
and [unmergeTableCells](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#UnmergeTableCellsRequest).
