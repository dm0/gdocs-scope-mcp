# Suggestions API investigation

[Implementation notes](implementation-notes.md) · [Indexing](../protocol.md#indexing-and-suggestions)

Investigated on 2026-10-28. This is research, not a supported MCP tool contract.
Production tools and defaults were not changed by the investigation. The
subsequent implementation of [reading support](../tools/suggestions.md) adds
clean ordinary views and a dedicated native proposal reader. The baseline
reader observations below describe behavior before that implementation.

## API contract

Google announced general availability of native comment and suggestion
management on September 30, 2026. Older localized or cached pages can still
describe a developer preview. See the [release announcement](https://developers.google.com/workspace/release-notes#September_30_2026).

`documents.batchUpdate` accepts `writeControl.writeMode: "SUGGEST"` alongside
either revision guard. Omitting the mode applies direct edits. Mode applies to
the whole batch, not individual operations. `suggestionResponses` identifies
created or affected suggestions per operation. `commentUpdateState` reports
thread persistence; HTTP success alone does not establish that suggestions
saved. See the [batch API](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate).

`SUGGESTIONS_INLINE` provides native write indices. Accepted and rejected
previews are read projections, not document mutations; their indices must not
drive writes. Native insertion/deletion IDs and suggested style maps describe
the differences. Thread metadata comes from `suggestions` when
`commentsViewMode=COMMENTS_VIEW_MODE_INCLUDED`, with inline suggestions and
all-tab content. See the [document schema](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents).

Accepting requires edit access; rejecting requires edit access or authorship;
deleting requires authorship. Replies can target `suggestionId`, while the
generated head post cannot be edited. See the [request schemas](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#AcceptSuggestionRequest).

Suggest mode excludes tab creation/deletion/updates, named-range creation and
deletion, header/footer deletion and table-column width updates. Some document
format/header settings are also excluded. See the [supported-operation limitations](https://developers.google.com/workspace/docs/api/how-tos/suggestions#unsupported_requests_in_suggest_mode).

## Live observations

The permanent opt-in test uses two fresh STDIO MCP processes, verifies their
source identity, operates on a temporary tab in the explicitly configured
development document, and deletes that tab afterward. It does not use UI
automation or a second account.

- Native insertion suggestions saved with `ALL_SAVED` and returned IDs.
- Inline, accepted-preview and rejected-preview reads behaved distinctly.
- Suggestion threads included ID, head post, status and plain/HTML summaries.
- Accept and reject changed content as expected. Deleting an owned pending
  insertion removed its proposed text in the observed case.
- Bold formatting could be suggested, with native style-change metadata.
- An insert/delete replacement produced one suggestion in the observed case;
  rejected-preview content retained the original, and rejecting the proposal
  restored the inline original. Do not assume one ID per request in general.
- Required and target revision controls accepted suggest-mode requests.
  A stale required revision was rejected. Stale-target collaboration was not
  exercised by this investigation.
- A batch combining insertion and forbidden named-range creation returned
  HTTP 400 without inserting the text.

Further observations and sanitized measurements are written to
`/tmp/gdocs-scope-mcp-table-probe-suggestions.json`; process-specific stderr
files have the same basename and `.0.log` / `.1.log` suffixes.

## Implications for this MCP

At the investigation baseline, the reader requested inline suggestions for
correct source indices, but ordinary text-run models did not retain suggestion
IDs or style-change maps. Thread reading exposed comments only. Adding a
write-mode switch alone would leave agents without a clear review workflow.
The live `docs_read` observation confirmed that the proposed insertion was
rendered without its native suggestion ID. Reading support now addresses these
gaps through an accepted-content view and separate proposal inspection;
proposal creation/management remains tracked in #43.

The agreed implementation sequence is tracked in two issues:

1. [Reading support (#42)](https://github.com/dm0/gdocs-scope-mcp/issues/42):
   ordinary reads show PREVIEW_WITHOUT_SUGGESTIONS, preserving accepted content
   and formatting. Report whether pending proposals affect the document and
   selected fragment, including inherited effects and explicit uncertainty.
   Keep heading discovery consistent with that view. Preserve native inline
   metadata internally for proposal detection and write indices; never use
   preview indices for writes. A dedicated `docs_suggestions_read` tool exposes
   proposal IDs, status, author, summaries, affected tabs/ranges and replies.
2. [Writing and management (#43)](https://github.com/dm0/gdocs-scope-mcp/issues/43):
   add `docs_suggest` with typed edit operations and `docs_suggestions_manage`
   for accept/reject/delete. Existing edit tools continue making direct edits,
   without a write-mode parameter or global edit/suggest switch. Return
   affected suggestion IDs in proposal receipts. Initially support text edits
   and explicitly validated formatting; defer complex content and reply writes.
3. Validate the complete generated request plan before side effects. Code
   block markers use forbidden named ranges: skip them explicitly for suggest
   mode or reject the incompatible request. Never create them as silent direct
   edits. Table-column width changes need an explicit unsupported-operation
   error; multi-stage table insertion needs separate live validation.
4. Preserve revision controls and cache invalidation. Inspect save state and
   read back outcomes; do not replay partial or uncertain writes.
5. Define editing around existing suggestions, including overlapping ranges
   and formatting proposals. Matching a flattened inline text string is not
   enough to distinguish accepted content from proposed insertions/deletions.

Not verified: commenter-only permissions, another author's suggestions,
suggested images/chips/lists/tables, complex style changes, partial-save fault
injection, notifications or visual UI behavior.

## Reproduction

From the worktree's Python project:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=YOUR_TEST_DOCUMENT_ID uv run --locked pytest -q tests/test_live_suggestions.py
```

The helper tools live only in `tests/probes/table_server.py` and are restricted
to that environment-selected document. They are not registered by the normal
server entry point.
