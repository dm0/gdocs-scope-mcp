# Table cell merge and unmerge

[Implementation notes](implementation-notes.md) · [Table tools](../tools/tables.md#docs_table_structure)

## Logical ownership

`Grid` reuses the reader's bounded geometry verifier and indexes real merged
heads, covered logical slots and physical placeholder entries separately.
Full-width native rows and compact rows are both understood. A snapshot
address must name a real head; covered slots are never silently redirected.
Ranges may end at a covered slot when their rectangle includes its whole owner.
Selections cutting any merged cell are rejected, rather than expanded.
Unmerge guards only merged heads; unmerged cells inside its range are ignored
by the native operation and retain independent content expectations.

The `merge` field hashes each head's physical members, full native content,
referenced metadata, effective named styles, intersecting named ranges,
associated row/column/table formatting and enclosing content direction.
Perimeter dependencies include every neighboring border segment, resolving
the neighbor's logical head across merged spans. Other cells' text is excluded.
Absolute indices are excluded, so unrelated text shifts remain compatible.

## Verified native behavior

Bounded live MCP probes on 2026-10-28 verified horizontal and two-dimensional
merges, merging an already merged head with adjacent cells, and unmerging the
result. Nonempty head paragraphs concatenate in row-major head order into the
upper-left head. Soft breaks and inline bold/italic runs survive. Empty cells
add no extra paragraph. Covered physical entries become empty placeholders.
Unmerge retains the entire concatenated paragraph sequence in the original
head and leaves the other cells empty; it cannot restore prior distribution.

Google's [merge/unmerge request contract](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#MergeTableCellsRequest)
defines direction-dependent heads and rejects nonrectangular merge ranges.
This implementation deliberately supports LTR sections and normal text-only
paragraphs initially. Lists, headings, objects/chips, tracked suggestions,
intersecting named ranges and nested tables are rejected before any write.
Cell presentation follows native API rules; full pre-merge formatting recovery
is not promised. The public [tool contract](../tools/tables.md#merge-and-unmerge)
describes limits, examples and recovery.

## Revision and receipt behavior

One native merge/unmerge request commits under strict `requiredRevisionId`,
independently of the general target mode. Confirmed revision rejections can
retry at most three times, rechecking the original `merge` expectations and
resolving fresh indices. Changed participating state returns `EDIT_CONFLICT`;
changed section structure returns `TARGET_CHANGED`. Unknown outcomes are never
replayed, and successful transformations never silently acquire a new baseline.

Native merged-cell representation is read back rather than guessed. A new
ref is issued only if the post-write snapshot has exactly the batch's confirmed
revision and intended selected tab. Otherwise the successful receipt still reports
one committed batch, but sets `reference_refresh_required=true` and leaves its
ref null. The agent must rediscover/snapshot, not repeat the transformation.
This is a supplementary read, not a second write stage or a partial failure.

All old snapshots and direct-section refs are deliberately invalidated by a
changed shape. Native named-range bindings are not used for table identity.
Selected named ranges are rejected instead of claiming that their identity
survives movement to a merge head. Position refs can become valid again if a
shape is restored; state expectations still compare the actual current content.

## Verification

Offline regressions cover full-width/compact and horizontal/vertical geometry,
covered slots, incomplete rectangles, existing merges, logical coordinates,
empty-cell expectations, formatting/metadata/border overlap, unsupported input,
strict retries, unknown outcomes and post-write read failures.

```bash
uv run --locked pytest -q tests/test_table_merge.py
```

With `GDOCS_SCOPE_MCP_LIVE_TEST_DOC` set to an explicitly authorized Doc ID:

```bash
uv run --locked pytest -q tests/test_live_table_merge.py
```

The permanent tests use independent worktree STDIO servers, source identity
checks and the shared test-document fixture. They verify native paragraphs,
formatting, spans, updated refs, atomic API failure, outside/overlapping text
edits, shared borders, structural races and a collaborator write between commit
and reference readback. Fixtures restore the initial document body and reap
both processes. Reports and stderr live under
`/tmp/gdocs-scope-mcp-table-probe-merge-*`.
