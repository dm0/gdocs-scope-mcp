# Native comment tools

[README](../../README.md) · [Document tools](documents.md) · [Result contracts](../protocol.md)

Comments use the Google Docs API directly. New threads attach to native text
ranges and appear as ordinary anchored comments in the Docs UI. No named range,
bookmark, Apps Script bridge, or script permission is required.

## docs_add_comment

```text
docs_add_comment(
    doc_id,
    comment,
    anchor_text,
    occurrence=1,
    *,
    tab_id=None,
    expected_revision_id=None,
)
```

Create a comment on an exact text match. `occurrence` is 1-based; the default
selects the first match. Matching respects UTF-16 source positions, including
emoji and text split across runs. Cross-table structural gaps and non-text
objects cannot be treated as contiguous ordinary text.

Omit `tab_id` for the first tab, as in other text tools. Use
[docs_get_tree](documents.md#docs_get_tree) to discover root/nested tab IDs.
The native range carries the chosen tab ID. The comment body is the supplied
plain text; the native anchor supplies the document quote.

All comment/post content is limited to **2048 UTF-8 bytes**, rather than 2048
Python characters. Creation, ordinary replies, and edited content must be
nonempty. Resolve/reopen messages may be omitted.

Returns `comment_id`, head `post_id`, `anchor_id`, `anchored_to`,
diagnostic `at_index`, `comment_content`, `document_id`, `tab_id`,
`revision_id`, and `comment_update_state="ALL_SAVED"`.

```python
created = docs_add_comment(
    doc_id="...",
    anchor_text="Please review this paragraph",
    comment="Please clarify the expected behavior.",
)
```

## docs_read_comments

```text
docs_read_comments(
    doc_id,
    include_resolved=False,
    page_token=None,
    *,
    limit=100,
    comment_id=None,
)
```

This read is **document-wide across all tabs**. Thread IDs identify their
target directly; subsequent ID-based operations do not need a tab selector.

Without `comment_id`, return up to `limit` thread summaries (1–100):
`id`, `head_post_id`, `content`, `author`, `anchor_id`, `anchored`,
`tab_id`, diagnostic `ranges`, `quoted_text`, `resolved`, `deleted`,
`created`, and `reply_count`. Reply bodies are omitted from the summary.
`include_resolved=True` includes resolved threads and deleted head posts.
A missing/currently orphaned anchor returns `anchored=False`, an empty range
list, and `tab_id=None`; it is not silently repaired or reanchored.

To inspect replies, pass `comment_id`. The single returned thread entry
repeats its head and anchor metadata and includes up to `limit` replies with
`post_id`, plain `content`, `author`, `deleted`, `created`, `updated`,
and `action`. Explicit selection also reads resolved threads, irrespective
of the listing filter.

The response contains `document_id`, nullable `revision_id`, `comments`,
`count`, `page_kind` (`threads` or `replies`), `next_page_token`, and
`has_more`. `count` is returned **thread entries**; it is one in reply mode,
even if that thread has no replies.

Continue with identical arguments and the returned `page_token`. Tokens
bind document ID, filters, limit, mode, and the full native comment/anchor
state. Changes return `STALE_REFERENCE`; restart pagination and deduplicate.
Body revision IDs alone do not identify a stable comment snapshot.

Google's native document read has no server-side comment pagination. Every
page fetches current native data; this pagination bounds MCP output, not the
download from Google. The read uses `COMMENTS_VIEW_MODE_INCLUDED`,
`SUGGESTIONS_INLINE`, and `includeTabsContent=True`. Permission failures
remain errors; there is no fallback to a differently scoped Drive listing.

```python
threads = docs_read_comments(doc_id="...")
thread_id = threads["comments"][0]["id"]
replies = docs_read_comments(doc_id="...", comment_id=thread_id, limit=20)
```

## docs_reply_to_comment

```text
docs_reply_to_comment(
    doc_id,
    comment_id,
    reply,
    *,
    expected_revision_id=None,
)
```

Post a plain-text reply. Returns `reply_id` (the native post ID), `content`,
and the shared mutation metadata described below.

## docs_resolve_comment

```text
docs_resolve_comment(doc_id, comment_id, reply='', *, expected_revision_id=None)
```

Resolve a thread with one native `RESOLVE` action post. Optional closing text
belongs to the same post. Returns `resolved=True` and its `reply_id`.

## docs_reopen_comment

```text
docs_reopen_comment(doc_id, comment_id, reply='', *, expected_revision_id=None)
```

Reopen a thread with one `REOPEN` action post and optional text. Returns
`resolved=False` and its `reply_id`.

## docs_edit_comment

```text
docs_edit_comment(
    doc_id,
    comment_id,
    content,
    *,
    post_id=None,
    expected_revision_id=None,
)
```

Edit the head post when `post_id` is omitted, or a specific reply when supplied.
Discover IDs with `docs_read_comments`. Google permits only the post's author
to edit it. Returns `post_id` and the new plain-text `content`.

## docs_delete_comment_reply

```text
docs_delete_comment_reply(
    doc_id,
    comment_id,
    reply_id,
    *,
    expected_revision_id=None,
)
```

Delete one ordinary reply. Head posts, resolve/reopen action posts, and
assignment posts are ineligible. Google also requires the reply's author.
Returns the deleted `reply_id`.

## docs_delete_comment

```text
docs_delete_comment(doc_id, comment_id, *, expected_revision_id=None)
```

Delete the entire native thread. Google requires the head post's author.
A missing thread returns `RESOURCE_NOT_FOUND`; an unknown outcome must be
inspected before repeating the call.

## Persistence and concurrency

Every successful mutation includes `document_id`, `comment_id`, actual
`tab_id` (nullable for an orphan anchor), `scope`, `heading_id`,
`revision_id`, and `comment_update_state="ALL_SAVED"`.

Comment persistence is separate from HTTP success and document model updates.
Every comment batch checks `commentUpdateState`. `ALL_FAILED_UNKNOWN_REASON`
returns `PARTIAL_WRITE`; missing/unspecified state or missing required new
IDs returns `WRITE_OUTCOME_UNKNOWN`. Neither result is automatically replayed.
`committed_batches` counts confirmed Docs HTTP batches; it does not assert
that the associated comment data persisted. Inspect current threads first.

The configured required/target revision policy applies, and
`expected_revision_id` enforces strict required mode without automatic rebasing.
Creation protects the native text target across confirmed revision races.
ID-based operations reread the thread and preserve its native identity.
Document revision guards do not provide a per-post content compare-and-swap.
When Google omits the document revision, guarded mutations fail with
`REVISION_UNAVAILABLE` rather than silently weakening protection; reading
comments can still return a null revision.

## Migration from the previous comment implementation

- Removed `bookmark_jump` and `include_anchor_text` inputs, and the backend's
  `apps_script_id` option. Unknown legacy inputs are rejected.
- Removed `named_range_id`, `bookmark_id`, `bookmark_url`, and
  `apps_script_id` result fields. Native results expose `anchor_id` and post IDs.
- Removed the Apps Script probe and bridge. The old
  `GOOGLE_DOCS_MCP_APPS_SCRIPT_ID` setting and its Drive-prefixed alias have no effect.
- Discard old Drive pagination tokens. Reread native comment and post IDs;
  old Drive IDs are not assumed interchangeable with native IDs.
- Existing threads exposed by the native API remain readable/manageable subject
  to Google's permissions. Existing broken anchors are not retroactively
  repaired. Old auxiliary named ranges/bookmarks are not removed automatically.
- New authorization requests no `script.*` scopes. Existing token files remain
  accepted, and prior grants are not revoked by this code change. Docs and
  Drive scopes are retained; identity-scope cleanup and per-file access are
  separate tasks.

See [native comment implementation notes](../development/native-comments.md)
for API details, regression tests and live verification.
