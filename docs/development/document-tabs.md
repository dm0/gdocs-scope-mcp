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
identical content, heading IDs and geometry. Structural write receipts refresh
their references in the committed tab. Revision IDs and strict table CAS are
still document-wide, so unrelated-tab writes can require a retry.

Multi-stage table insertion scopes both its writes and its intermediate native
cell lookup. Smart-chip dependency checks use the destination tab's definitions.
The comment bookmark bridge chooses a native `DocumentTab` for body search,
positions and bookmarks; bookmark URLs include the tab selector. Drive comment
listing, replies, resolution and deletion remain document-wide.

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
native payload. Reports and separate stderr logs are saved under
`/tmp/gdocs-scope-mcp-table-probe-document-tabs*`; the fixture verifies process
reaping on success and failure. No normal MCP server is reconfigured.

Live coverage is bounded: Apps Script bookmark creation and every combination
of structural/formatting operation with tabs are not exhaustively exercised.
