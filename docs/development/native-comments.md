# Native Google Docs comments

[Implementation notes](implementation-notes.md) · [Comment tools](../tools/comments.md)

The implementation uses `insertComment`, `addCommentReply`,
`updateCommentPost`, `deleteComment`, and `deleteCommentReply` through
`documents.batchUpdate`. Resolve/reopen are native reply posts with
`commentAction=RESOLVE/REOPEN`. See Google's
[request reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#InsertCommentRequest).

Creation retains the existing native text-run/UTF-16 mapper and guarded edit
executor. It scopes the native range to the selected tab. ID-based operations
read the document-wide thread map and record its revision in the same executor;
they do not select the first tab implicitly or redirect an ID to another
thread. Receipts preserve the actual anchor's tab, including null for orphans.

`comments.fetch` includes comments with `COMMENTS_VIEW_MODE_INCLUDED`, explicit
`SUGGESTIONS_INLINE`, and `includeTabsContent=True`. The installed static client
discovery schema predates the comments query parameter. We append that
documented query to the ordinary authenticated `HttpRequest.uri`, keeping
the existing client and token configuration. There is no discovery download
on every call and no dependency upgrade solely for this parameter.

Native threads live at `Document.comments`; their anchors live in each
`documentTab.commentAnchors`. Reads join them by `anchorId` and expose all
ranges with their tab IDs. Missing anchors are reported without guessing or
creating replacement metadata. Native comment IDs/post IDs are opaque;
old Drive IDs are not assumed interchangeable.

HTTP success and comment persistence are separate. Every comment batch checks
`commentUpdateState=ALL_SAVED` before constructing a success receipt. A failed
save reports `PARTIAL_WRITE`; missing/unspecified confirmation or missing new
IDs reports `WRITE_OUTCOME_UNKNOWN`. The executor does not replay these states.
Confirmed HTTP batch count does not mean comment data persisted. Google's
[persistence documentation](https://developers.google.com/workspace/docs/api/how-tos/suggestions#comment_and_suggestion_update_status)
describes this distinction.

Pagination is client-side and portable. `gcc1` checksummed cursors bind the
document, mode, arguments and the complete native thread/anchor fingerprint.
They are not authorization tokens or signed capabilities. Every call checks
Google access again; no comment snapshot is cached. This also catches comment
changes that do not advance a body revision. Thread listings omit reply bodies;
explicit `comment_id` selection pages replies without adding another tool.

The Apps Script bridge/probe and legacy bookmark inputs/results were removed.
New authorization no longer requests script scopes. Existing token files are
accepted; old grants and document metadata are not revoked/deleted implicitly.
Body revision guards remain required for guarded writes; comment-only access
without a revision can read but cannot silently bypass those guards.

## Verification

Permanent tests cover native requests and save states, unknown writes,
permissions, Unicode byte limits, inherited revision policies, nested-tab
anchors, legacy/orphan threads, state-bound pagination and migration contracts.
Existing UTF-16/race tests now assert native comment ranges instead of named
ranges. Run offline checks with `uv run --locked --no-cache pytest -q`.

`tests/test_live_native_comments.py` launches isolated STDIO servers, records
source fingerprints/PIDs/start times, creates a temporary repeated-text/emoji
region, and exercises creation, native anchor readback, replies, head/reply
editing, resolve/reopen, reply deletion and thread deletion. Cleanup restores
the original body. Reports/logs use `/tmp/gdocs-scope-mcp-table-probe-native-comments*`.

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=YOUR_TEST_DOC_ID uv run --locked --no-cache pytest -q tests/test_live_native_comments.py
```

For optional UI review, add `GDOCS_SCOPE_MCP_COMMENT_UI_WAIT=1`. The test writes
the created receipt to `/tmp/gdocs-native-comment-ui.json` and waits up to three
minutes for `/tmp/gdocs-native-comment-ui.done` before continuing cleanup.
Use an authenticated browser to inspect the ordinary comment card and native
highlight at the second occurrence, then create the acknowledgement file.
The bounded development run was checked in the user's existing Chrome tab;
the comment card and second-occurrence highlight were visible together.
