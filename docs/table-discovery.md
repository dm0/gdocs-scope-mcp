# Table discovery

Implementation notes for [issue #26](https://github.com/dm0/gdocs-scope-mcp/issues/26).
Shared tab discovery/selection is described in
[document tab implementation notes](development/document-tabs.md).

## References and reading

The existing Google Docs HTML converter adds `data-mcp-table-ref` at each native
table's own `<table>` tag, including nested tables. It does not change editable
paragraph text/source positions or add a second table-content inventory.
`docs_tables_list` returns compact discovery metadata; `docs_table_read` returns
bounded physical-cell pages and Markdown previews. Both reuse the shared
renderer and normal OAuth/permission boundary. No read creates a named range,
binding or any other document write.

Current `gdt2` table/cell refs carry document/selected-tab scope, heading ancestry,
the table's direct-section ordinal, structural hashes and nested ordinals.
They remain valid across content/style changes and native index shifts while
the section's structural inventory stays unchanged. Identical tables are
distinguished by position, not persistent native object identity. No
process-local cache or content matching is involved. Pagination cursors retain
the exact revision and additionally bind output bounds and heading filters.
Invalid/mismatched tokens fail explicitly; changed structural guards never
fall back to another table. See the [current reference contract](table-references.md)
and [table tool reference](tools/tables.md).

The checksum is unkeyed corruption detection, not a cryptographic signature or
access credential. Decoding a token grants no extra permission. Every read
fetches a fresh authorized snapshot. Selective expected-state snapshots are
implemented without bindings; see [addresses and expected state](table-references.md#addresses-and-expected-state).

Discovery uses the same heading-root selection rules as `docs_read`: selected
ancestors subsume descendants, mixed unknown IDs are diagnosed, and an entirely
unknown selection fails. Nesting walks inherit the containing heading context.
The backend still fetches the document snapshot; compact discovery limits what
is returned to the agent rather than claiming server-side table-only fetching.

## Geometry and bounds

Physical API entries are retained separately from logical grid coordinates.
Explicit full-width rows can contain empty placeholders covered by a merged
head. Compact rows are laid out by their declared spans and previously covered
slots. A layout is valid only when dimensions, spans, nonoverlap and full grid
coverage agree. Nonempty covered placeholders, missing spans, malformed shapes
or excessive grid area make geometry unverified. Native content and span data
are retained, while logical columns and cell handles become null.

Read-only geometry validation is not a claim of persistent logical cell
identity. In particular, the [identity probes](table-identity.md) show that a
marker can survive in a physical placeholder after text moves to a merge head.
All cells in merged tables are conservatively excluded from
`simple_text_target`; complex/nested/non-text cells are also excluded. A true
flag is structural eligibility, not a blanket guarantee that any edit is
supported. [Table patching](tools/tables.md#docs_table_patch) checks its own
more restrictive text/paragraph contract before writing.

Table list pages contain at most 100 summaries, with previews capped at 200
Unicode code points. Detailed pages contain at most 200 physical cells, each
with at most 4000 Markdown code points. Defaults are 50 summaries, 100 cells and
2000 Markdown code points per cell. Rows may continue on another page;
`complete` makes this explicit. Truncated Markdown may be syntactically
incomplete. Geometry allocation is capped at 100,000 logical slots; larger
tables remain readable with unverified geometry. At most 20 immediate child
references are returned per cell, with a total count and explicit truncation
flag. Additional child refs remain discoverable through the paginated table
list and its parent-cell references.

## Validation

Offline tests cover identical/nested tables, heading scopes, empty cells,
Unicode/UTF-16 content, explicit and compact merged layouts, malformed geometry,
pagination, truncation, stale/corrupt/cross-document/wrong-kind references,
schema validation and the absence of writes. Existing table/entity readers
retain their content with the new HTML attributes.

The opt-in permanent live test launches two isolated STDIO MCP processes. It
creates synthetic tables only in the environment-selected authorized document,
shares refs/cursors between processes, checks native empty/merged cells and
stale rejection, and verifies that reading leaves revision/named ranges
unchanged. Its `finally` restores the exact initial body and reaps both servers.

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC='your-disposable-document-id' \
  uv run --locked pytest -q tests/test_live_table_identity.py \
  -k read_only_table_discovery
```

Reports/logs are `/tmp/gdocs-scope-mcp-table-probe-discovery.*`. Production
source fingerprints and the test-launcher hash are recorded separately.

Verified on 2026-10-27: 1166 offline tests passed with 52 opt-in skips; the
live discovery test passed using two independent worktree STDIO processes.
Both loaded source fingerprint
`ba944ce335e65b02f7c9ab0423eca2df0b6e3a4a67394e341cad8aae5784a5e1`
with Python 3.14.4 and FastMCP 3.3.1. The report confirms successful checks,
exact original-body restoration and process reaping. Stderr records successful
read calls and the expected `STALE_REFERENCE` rejection after a deliberate
merge. Ruff and whitespace validation passed. Nested layouts and malformed
geometry are covered offline; live geometry verification covered native
unmerged cells and a horizontal merge with explicit placeholders.

Google's [document model](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents)
defines native row/column spans and revision metadata. The default first-tab behavior
of ordinary reads follows
[documents.get](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/get).
