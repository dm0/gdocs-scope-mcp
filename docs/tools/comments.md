# Comment tools

[README](../../README.md) · [Content syntax](../rich-content.md) · [Result contracts](../protocol.md)

## docs_add_comment

```text
docs_add_comment(
    doc_id,
    comment,
    anchor_text,
    occurrence=1,
    include_anchor_text=True,
    bookmark_jump=False,
    *,
    tab_id=None,
    expected_revision_id=None,
)
```
Add a comment anchored to specific text in the selected tab. `tab_id` is
optional and defaults to the first tab; discover root/nested IDs with
[docs_tabs_list](documents.md#docs_tabs_list). The named-range anchor and
optional bookmark target that same tab. Comment-thread reads/replies/resolve/
delete tools remain document-wide.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment` | string | required | Comment text |
| `anchor_text` | string | required | Text in the document to attach the comment to |
| `occurrence` | int | `1` | `1` = first occurrence of `anchor_text`; `2`, `3`, etc. select later matches |
| `include_anchor_text` | bool | `true` | Append the matched anchor text into the comment body |
| `bookmark_jump` | bool | `false` | Use the Apps Script bridge to create a bookmark and append a jump URL |
| `expected_revision_id` | string or null | `null` | Require the earlier read revision for the Docs anchor write |

Use a short, distinctive phrase for `anchor_text` — a few words that are unique enough to match exactly one location.

```
docs_add_comment(
  doc_id="...",
  anchor_text="unable to perform the Employee's duties",
  comment="Legal risk: 3-month absence threshold may not satisfy Equality Act 2010 duty to make reasonable adjustments before terminating.",
  bookmark_jump=True
)
```

Returns `ok`, `comment_id`, `anchored_to`, `at_index`, `named_range_id`, and
`comment_content`, plus `bookmark_id`, `bookmark_url`, and `apps_script_id`
(null when bookmarks are disabled).

> **Note:** The current implementation uses Drive comments plus a Docs named range. In the Docs UI these still show as *"Original content deleted"* rather than as proper inline highlights. The comments are fully readable via `docs_read_comments` and the Docs 💬 panel.
>
> When `bookmark_jump=true`, the tool additionally uses Apps Script automation to create a bookmark at the anchor text and appends a `#bookmark=id...` jump URL into the comment body. This requires the `GOOGLE_DOCS_MCP_APPS_SCRIPT_ID` env var and the [Apps Script bridge setup](#apps-script-bridge).
>
> A probe helper is included for this workstream:
>
> ```bash
> uv run -m gdocs_scope_mcp.appscript_probe inspect-comment-api --doc-id <DOC_ID>
> ```
>
> The probe now creates an API-executable deployment automatically. If account-level Apps Script access is still disabled, it stops with the settings-page message. If execution fails with a permission error, the next blocker is the shared standard Google Cloud project requirement documented at <https://developers.google.com/apps-script/guides/cloud-platform-projects>.

---

## docs_read_comments

```text
docs_read_comments(doc_id, include_resolved=False, page_token=None)
```
Read one page of up to 100 comments on a document.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `include_resolved` | bool | `false` | Include resolved/deleted comments |
| `page_token` | string or null | null | Continuation token from the previous page |

Returns `{count, comments, next_page_token, has_more}`.
Each comment has `id`, `content`, `author`,
`anchored` (bool), `named_range_id`, `quoted_text`, `resolved`, `deleted`, and
`created`. The count covers returned items after filtering; additional pages
are not fetched automatically. Continue with `page_token=next_page_token`, keeping
`doc_id` and `include_resolved` unchanged, until the token is null. A page with
no visible comments can still have `has_more=true` because filtering happens
after fetching. Invalid/expired tokens return a structured error with guidance
to restart without a token and deduplicate previously seen items.

```
docs_read_comments(doc_id="...")
```

---

## docs_reply_to_comment

```text
docs_reply_to_comment(doc_id, comment_id, reply)
```
Post a reply to an existing comment.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment_id` | string | required | Comment ID (from `docs_read_comments`) |
| `reply` | string | required | Reply text |

```
docs_reply_to_comment(
  doc_id="...",
  comment_id="AAAB1iPyaUY",
  reply="Agreed — adding Carer's Leave clause before we sign."
)
```

Returns `{ok, reply_id, comment_id, content}`.

---

## docs_resolve_comment

```text
docs_resolve_comment(doc_id, comment_id, reply='')
```
Resolve (close) a comment using one resolving reply action. Optional closing
text is included in that same request; without text, only the action is sent.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment_id` | string | required | Comment ID |
| `reply` | string | `""` | Optional closing text included in the resolving reply |

```
docs_resolve_comment(
  doc_id="...",
  comment_id="AAAB1iPyaUY",
  reply="Fixed in v2 — carer's leave clause added at 15.1."
)
```

Returns `{ok, comment_id, resolved}` with `resolved=true`.

---

## docs_delete_comment

```text
docs_delete_comment(doc_id, comment_id)
```
Permanently delete a comment.

```
docs_delete_comment(doc_id="...", comment_id="AAAB1iPyaUY")
```

Returns `{ok, comment_id}`.

---

## Apps Script bridge

If you want `docs_add_comment(..., bookmark_jump=true)` to append a real
`#bookmark=id...` jump URL into the comment body, set up one persistent Apps
Script bridge project and expose its script ID via an env var.

Required one-time setup:

1. Enable the **Apps Script API** for the Google account at
   <https://script.google.com/home/usersettings>
2. Create a standalone Apps Script project to use as the bridge
3. In that Apps Script project, open **Project Settings** and switch it to the
   **same standard Google Cloud project** as the OAuth client used by
   `gdocs-scope-mcp`
4. In that same Google Cloud project, ensure **Apps Script API** is enabled
5. Set the bridge script ID in the MCP process environment:

```bash
export GOOGLE_DOCS_MCP_APPS_SCRIPT_ID="your-apps-script-id"
```

Example `uvx` launch with both token + Apps Script bridge:

```bash
GOOGLE_DOCS_MCP_TOKEN="$HOME/.google-docs-mcp/token.json" \
GOOGLE_DOCS_MCP_APPS_SCRIPT_ID="your-apps-script-id" \
uvx --from git+https://github.com/dm0/gdocs-scope-mcp gdocs-scope-mcp
```

If the Apps Script bridge is still using its hidden default project, `scripts.run`
fails even when account-level Apps Script access is enabled.

---

`expected_revision_id` on `docs_add_comment` requires the exact earlier read revision for its Docs anchor write. Comment creation spans Docs/Drive (and optionally Apps Script) side effects; see [concurrent edits and recovery](../concurrent-edits.md).
