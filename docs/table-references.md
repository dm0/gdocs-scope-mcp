# Checked table positions and selective cell snapshots

Issue [#27](https://github.com/dm0/gdocs-scope-mcp/issues/27) supplies positional
references and expected-state primitives for future table edits. It does not
yet provide cell replacement or structural editing tools. Reading, reference
creation and snapshot validation are entirely read-only, including metadata
and local state. No named ranges, local registry or signing key are used.

## Positional contract

A table ref describes the Nth top-level table in its direct heading section,
within the implicit first tab. Scope is the complete ancestor heading ID chain;
heading title changes preserve it, while changing/reparenting the ID hierarchy
invalidates it. Content before all headings uses an empty chain. Child heading
sections have separate inventories; selecting a heading subtree for discovery
does not change the underlying direct-section numbering.

Two SHA-256 hashes guard the position: the target table's structure and the
ordered list of top-level table structure hashes in that direct section. The
shape includes row/column counts, ordered physical cells and row/column spans,
plus recursively ordered nested-table structures and their containing cells.
It excludes text, text-run boundaries, paragraph counts, formatting, native
indices and heading titles. An ordinary cell content/style change therefore
preserves refs, including text length/UTF-16 shifts and clearing/refilling.

The inventory is checked before following the table ordinal. Adding/removing
a table, row/column changes, merge/unmerge or changes to nested-table layout
require fresh discovery while the shape differs. A change to another table
in the same direct section also invalidates the ref; a change in a different
section does not. Nested refs add row/physical-cell/nested-table ordinals;
they do not depend on paragraph positions within cells.

**These are position identities, not persistent native object identities.**
Swapping two structurally identical tables cannot change the structural hash.
The old reference continues to mean the same numbered position. Deletion and
identical recreation, or structure changes subsequently undone, may likewise
restore a valid position ref. Snapshot expectations reject changed selected
state; if the selected state is identical, validation accepts it. This is the
explicit contract, not a guarantee that the original native object survived.
There is no content-search fallback, similarity matching or relocation to a
different ordinal when a guard fails.

The actual first-tab ID scopes every ref and token; changing the implicit first
tab rejects it. User-selectable tabs remain #34. Pagination additionally binds
the exact document revision and output/filter options, even though table refs
are revision-independent. `STALE_REFERENCE` means restart pagination;
`TARGET_CHANGED` means reread discovery after a structural/scope change.

## Addresses and expected state

`docs_table_read` returns `address` labels such as A1, B2 and AA10. Rows are
1-based and columns use standard letters. Existing opaque `cell_ref` and
`parent_cell_ref` values retain full table context for discovery relationships;
new snapshot calls use plain A1 addresses scoped by `table_ref`.

Call `docs_table_snapshot` with 1-100 distinct uppercase addresses. It resolves
the checked table position and returns selected cell Markdown, hashes inside
an opaque `base_token`, current coordinates/revision and expiry. Markdown is
limited to 2000 Unicode code points per cell, with full lengths/truncation
flags. Prepare changes using this state, not an earlier unprotected read.
Clipped previews are not complete replacement input; hashes cover full native
state regardless of clipping.

Snapshots require verified unmerged geometry without nested tables in the
target's cells. Reading unsupported tables remains available with warnings.
There is no 200-cell binding limit; the existing geometry verifier supports
up to 100000 logical slots, and each snapshot selects at most 100 cells.

| Group | Compared state |
| --- | --- |
| `content` | Paragraph text with adjacent runs concatenated, paragraph boundaries and non-text native elements |
| `text_style` | Text-run UTF-16 lengths/styles and referenced named styles |
| `paragraph_style` | Paragraph styles, bullets and referenced named/list styles |
| `cell_style` | Native tableCellStyle properties |
| `structure` | Selected cell paragraph element kinds and spans, without indices |

Defaults are `content`, `text_style`, `paragraph_style`. Content-only snapshots
allow independent formatting changes within that cell. Adding formatting can
split runs and invalidate style/structure snapshots; content snapshots ignore
those splits. Only selected cells/groups are hashed; other cells can change
freely while the table layout guard remains valid. A baseline is bound to its
table position, exact selected cell set and field groups, not selection order.

Pass `base_token` with the same table/cells/fields to validate and renew it.
Changed selected state returns `EDIT_CONFLICT`; reread and review the affected
state rather than blindly issuing a new baseline. `SNAPSHOT_EXPIRED` requires
a fresh read/snapshot. TTL defaults to 86400 seconds; configure JSON
`table_snapshot_ttl_seconds` or `GOOGLE_DOCS_MCP_TABLE_SNAPSHOT_TTL_SECONDS`
from 1 to 604800 seconds. Table refs have no time expiry.

Snapshot validation takes no lock. A future write must resolve and validate
within its own call, then submit with requiredRevisionId from that fresh read.
A racing write must be revalidated or rejected; old native indices must never
be reused after an intervening change. These primitives do not themselves
implement a content write or promise atomicity across separate MCP calls.

## Portability and integrity

`gdt2` refs/base tokens contain versioned canonical JSON and a SHA-256 checksum.
Base tokens contain selected state digests, not cell contents. Tokens are
encoded, not encrypted or cryptographically authenticated. The checksum
detects accidental corruption, not deliberate forgery. Tokens are protocol
state rather than authorization capabilities; each call enforces Google access.
Do not alter tokens or use them as a security boundary.

No process-local state is needed. Another MCP process or a fresh startup can
resolve the same position and validate a previous base token. Reads, discovery
and snapshots never create or delete named ranges or local key files.

## Verification

Offline regressions cover duplicate tables, A1 addressing, heading hierarchy,
section inventories, nested layout, cell dependency groups, expiry, portable
encoding, malformed input and read-only boundaries. Permanent STDIO live tests
use the explicitly selected test document and independently launched processes:

```bash
uv run --locked pytest -q tests/test_table_references.py
```

With `GDOCS_SCOPE_MCP_LIVE_TEST_DOC` set to the authorized test document ID:

```bash
uv run --locked pytest -q tests/test_live_table_identity.py::test_live_positional_table_references tests/test_live_table_identity.py::test_live_positional_structure_invalidation
```

The live fixtures verify source identity, independent processes and restart,
capture stderr under `/tmp/gdocs-scope-mcp-table-probe-*`, restore the initial
document body and reap all test servers.
