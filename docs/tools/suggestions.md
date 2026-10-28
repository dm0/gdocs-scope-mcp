# Reading suggestions

[README](../../README.md) · [Document tools](documents.md) · [Result contracts](../protocol.md)

Ordinary `docs_read` and `docs_get_tree` return accepted document content:
proposed insertions are hidden, proposed deletions remain, and proposed
formatting is not applied. Reading never accepts or rejects a proposal.
No additional discovery call is needed when suggestions are absent.

Their `suggestions` object describes that view:

```json
{
  "view": "without_suggestions",
  "document_has_pending": true,
  "selected_content_has_pending": false,
  "suggestion_ids": [],
  "suggestion_ids_truncated": false,
  "detection": "complete",
  "unavailable_heading_ids": [],
  "warnings": []
}
```

`document_has_pending` covers all root/nested tabs and other native segments;
`selected_content_has_pending` concerns the returned body selection. It can be
false while another section or tab contains proposals. `null` means the answer
cannot be established, rather than no changes. An empty heading selection has
no affected content. Up to 100 relevant IDs are returned; use dedicated listing
when the IDs are truncated.

Hidden proposed headings do not cut accepted subtree boundaries.
`unavailable_heading_ids` lists accepted heading selectors whose native identity
cannot be verified (up to 100). A selection with an unmappable heading or
boundary fails explicitly with `TARGET_CHANGED`; whole-tab reading remains
available. Do not use those unavailable selectors for editing.

Direct text, paragraph, table and section change markers are located using
native source ranges, including proposed content hidden from the returned
view. Shared list/object definitions are associated with their known users.
Proposals to document layout affect the selected body; the exact effects of
general named-style inheritance are reported as uncertain. This does not add
style-management tools or reproduce Google's complete inheritance engine.
Unknown native change fields also produce partial detection.

When access prevents an inline suggestion read, ordinary reading tries the
accepted-content projection and reports unavailable detection. If proposal
metadata and rendered content require separate requests, their revisions must
match. Three consecutive revision races fail with `EDIT_CONFLICT`. Without a
revision ID, clean content can still be returned, but the proposal metadata is
unavailable. Safe table refs require native validation: refs that cannot be
verified are omitted with an explicit warning. The table content still renders.
`docs_tables_list` and `docs_table_read` also read accepted content, and fail
with `TARGET_CHANGED` when structural proposals prevent verified table refs.
Edit planning and selective table expectations continue using native snapshots.

## docs_suggestions_read

```text
docs_suggestions_read(doc_id, *, tab_id=None, heading_id=None,
                      suggestion_id=None, include_closed=False,
                      limit=50, page_token=None)
```

Omitted `tab_id` selects the first tab, matching ordinary document tools.
`heading_id` selects a subtree from the accepted-content outline. The default
list includes OPEN threads and native proposal IDs whose thread metadata is
unavailable. `include_closed=True` adds accepted/rejected threads. An explicit
`suggestion_id` includes its status regardless of `include_closed`.

Each item includes native `suggestion_id`, status, author, plain/HTML summary,
diagnostic locations, `scope_match`, reply count and truncation flags. Summaries
are bounded to 2000 characters each and locations to 100 entries. The full
Google-generated summary may itself be empty. Do not use summaries to invent
source ranges. Closed or otherwise unlocated threads may appear with
`scope_match="unknown"` and an explicit warning; they are not silently assigned
to the requested tab/heading. Other-tab proposals with known locations are
excluded. Whole-tab listing can include header/footer/footnote proposals;
heading scopes concern body content only.

Listing omits post/reply bodies. Select one ID to obtain the complete head post
and a page of replies. `page_kind` distinguishes thread pages from reply pages;
`count` counts returned suggestion items, while `total` counts the collection
being paginated (threads or replies). `limit` is 1–100. `has_more` and
`next_page_token` describe continuation. Keep every argument unchanged when
following a token; changes to document/thread state invalidate it with
`STALE_REFERENCE`. Restart without the token after that error.

```python
docs_read(doc_id='...', heading_ids=['heading-from-outline'])
docs_suggestions_read(doc_id='...', heading_id='heading-from-outline')
docs_suggestions_read(doc_id='...', suggestion_id='native-suggestion-id')
```

Thread inspection requires permission to read native suggestions; a permission
error is not an empty list. The tool uses fresh native thread reads, so replies
are not served from the document snapshot cache.

## Editing boundaries

Existing edit tools still make direct edits. They resolve indices using native
`SUGGESTIONS_INLINE` data, never the accepted-content projection. Ordinary
Markdown is not a review diff and does not embed pending `<ins>`/`<del>` markup
that a rich insertion might silently turn into accepted text or strikethrough.
Creating and managing suggestions is tracked separately in
[#43](https://github.com/dm0/gdocs-scope-mcp/issues/43).

## Verification

Offline cases cover view selection, source scopes, hidden insertions, proposed
headings, formatting, shared definitions, access limitations, revision races,
safe table refs, pagination and schema contracts. The opt-in live test uses two
isolated STDIO processes, a temporary tab and native proposal writes:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=YOUR_TEST_DOCUMENT_ID uv run --locked pytest -q tests/test_live_suggestions.py::test_live_accepted_content_and_scoped_inspection
```

Sanitized evidence and stderr are written under
`/tmp/gdocs-scope-mcp-table-probe-suggestion-reading.*`. Both subprocesses and
the temporary tab are cleaned up.
