# Document tab selection

[Implementation notes](implementation-notes.md) · [Document tools](../tools/documents.md#document-tabs)

`document_tabs.select` normalizes a complete native document into one tab view.
It walks root and child tabs in API order, preserves shared document identity
and revision, and reads body, styles, lists, entities and named ranges only
from the selected `documentTab`. Omitted selectors choose the first root tab;
explicit missing IDs fail. Legacy API-shaped offline fixtures without tabs
remain usable only with the default selector.

Every production document fetch requests `includeTabsContent=true`. The compact
discovery tool returns hierarchy metadata, but its underlying fetch currently
includes body content. It does not promise reduced API transfer or caching.
`docs_get_tree` also returns this complete compact inventory in `tabs`,
alongside the selected tab's outline. It reuses the same native snapshot and
makes no additional Google API request for tab discovery.
Single-tab calls can omit `tab_id` throughout. A different tab requires its
own outline/heading IDs and an explicit selector on subsequent calls;
selection is stateless. The shared parameter schema documents these rules.
`docs_read.tab_count` counts root and nested tabs without an extra request;
`partial` continues to describe heading selection within the chosen tab.

Guarded text edits retain the chosen tab across revision retries, including
when the original call omitted `tab_id`. Ranges, locations, table locations
and named ranges carry native tab IDs. Native `replaceAllText` uses explicit
`tabsCriteria`: Google's omitted criterion would replace across all tabs.
Matching remains execution-time matching and uses no revision guard, as before.
The native criteria contract is documented in Google's
[request reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#ReplaceAllTextRequest).

Table position refs, cell refs, snapshot expectations and pagination tokens
carry the actual tab ID. Every table call resolves its explicit/default tab
before validating those references. A mismatch fails even if both tabs have
identical content, heading IDs and geometry. Every table response returns
the effective `tab_id`. A reference/selector mismatch returns `TAB_MISMATCH`
with both IDs and selector-specific recovery, before cursor revision checks;
it does not imply the reference's structure changed. Structural receipts refresh
their references in the committed tab. Revision IDs and strict table CAS are
still document-wide, so unrelated-tab writes can require a retry.

Multi-stage table insertion scopes both its writes and its intermediate native
cell lookup. Smart-chip dependency checks use the destination tab's definitions.
Native comment creation attaches an insertComment range to the selected tab.
Comment reading and ID-addressed thread/post mutations remain document-wide;
read results join document-level threads with per-tab native comment anchors.
See [native comment implementation](native-comments.md).

## Verification

`tests/test_document_tabs.py` covers duplicate content/headings/layouts,
root/nested/default selection, invalid IDs, metadata isolation, read-only
discovery, text request scoping, tab-bound refs/snapshots/pages and MCP schemas.
Existing text, entity and table regressions exercise the shared pipelines.

Run the bounded live regression in the worktree:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=YOUR_TEST_DOC_ID uv run --locked --no-cache pytest -q tests/test_live_document_tabs.py
```

It launches two isolated STDIO processes, checks their source identity, creates
a temporary root tab with a child, and exercises discovery, heading selection,
code-marker reads, native replace-all, table insertion/patching, formatting, merge receipt refresh and chip reads.
It removes both temporary tabs in `finally` and compares every original tab's
native payload. The shared cleanup assertion ignores only the values of native
inline/positioned image `imageProperties.contentUri` fields: these are temporary
download URLs and can rotate without an image edit. Image IDs, URL presence,
source URLs, dimensions, cropping, text, styles and tab structure remain checked.
Failures report changed field paths rather than document content or signed URLs.
Reports and separate stderr logs are saved under
`/tmp/gdocs-scope-mcp-table-probe-document-tabs*`; the fixture verifies process
reaping on success and failure. No normal MCP server is reconfigured.

Live coverage is bounded: every combination of structural/formatting operation
with tabs is not exhaustively exercised. Native comments have a separate
live lifecycle regression.
