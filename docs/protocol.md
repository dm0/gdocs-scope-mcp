# MCP result contracts

[README](../README.md) · [Configuration](configuration.md) · [Document tools](tools/documents.md)

All tools return structured JSON objects with typed output schemas. The
MCP text content contains the same JSON object for text-only clients; results
are not JSON-encoded strings, and edit results have no outer `result` wrapper.

- Tool failures set MCP `isError: true` and return the same structured object
  in both result channels: `{ok: false, code, description, suggested_action}`.
  All output schemas include this error branch. Codes distinguish missing
  headings, text and occurrences, invalid JSON, authentication/access failures,
  Google API errors, and internal errors. Follow the recovery guidance; check
  document/comment state before retrying a failed write. Internal exceptions
  retain tracebacks in server logs, while clients receive a bounded generic
  description. Successful response fields are unchanged.
- `docs_list` returns `{count, documents, next_page_token, has_more}`. Document
  fields retain `id`, `name`, `modifiedTime`, and `webViewLink`; the latter two
  are nullable when Drive omits them.
- `docs_read_comments` returns `{count, comments, next_page_token, has_more}`.
  Each comment exposes its
  text, author, anchor metadata, and resolved/deleted state as typed fields.
- Existing fields such as `with` in batch changes and bookmark metadata in
  comment creation are preserved. Batch input now uses the typed
  `replacements` array; the old `replacements_json` parameter was removed.

List counts describe returned items, not the total in Drive or the document.
Each call fetches one page; pass `next_page_token` as `page_token` to continue.
Continue until the token is null, even if a page has zero returned items.
Clients using the previous JSON-string
or `result`-wrapped outputs must switch to the direct structured objects.

`docs_read` reports the selected `tab_id`/`tab_title` and total `tab_count`.
`partial=false` means all content in that tab, not all document tabs.
`docs_get_tree` supplies the complete compact `tabs` inventory in its usual
outline call; the single-tab workflow needs no separate tab discovery.
All table-tool success responses expose the effective `tab_id` at the top
level. Reference/selector mismatch returns `TAB_MISMATCH` with the reference
and selected tab IDs and a specific selector recovery action; it does not
report a structural change. See [document tabs](tools/documents.md#document-tabs).

Document reads accept omitted empty `lists` and `inlineObjects` collections.
Supplied list definitions retain their formatting. If a paragraph references
a missing list definition, Markdown rendering fails rather than guessing its
numbering or bullet style; the parser retains the original list ID and text.
Reads render supported inline images as Markdown image references and horizontal
rules as `---`. Plain-text rendering uses image titles when available and keeps
rule separators. Unknown paragraph elements retain the existing empty fallback.
Targeted text replacements use original text-run positions, including UTF-16
offsets, to preserve adjacent non-text elements. A match spanning an omitted
object or horizontal rule is rejected with `INVALID_ARGUMENT` before writing.
This does not implement editing the objects themselves. Rich insertion supports
Markdown and HTML images in [rich content](rich-content.md#images). Batch replacements and comment
anchors use the same source-range
mapping and structural-gap check. Before/after insertion still targets whole
paragraph boundaries; native literal replace-all retains Google's matching.

## Action annotations and edit receipts

All Google-backed tools declare `openWorldHint=true`; `server_info` is local
and declares `openWorldHint=false`. These advisory hints describe effects,
not authorization or retry guarantees. The per-operation policy is:

| Tools | Read-only | Destructive | Idempotent |
|-------|-----------|-------------|------------|
| `docs_get_tree`, `docs_read`, `docs_list`, `docs_read_comments` | true | false | true |
| `docs_search_replace`, `docs_batch_replace` | false | true | false |
| `docs_delete_paragraph`, `docs_delete_comment` | false | true | true |
| `docs_insert_before`, `docs_insert_after`, `docs_append` | false | false | false |
| `docs_create`, `docs_add_comment`, `docs_reply_to_comment` | false | false | false |
| `docs_resolve_comment` | false | false | false |
| `docs_get_entity` | true | false | true |
| `docs_create_dropdown_definition`, `docs_select_dropdown` | false | false | false |
| `docs_tables_list`, `docs_table_read`, `docs_table_snapshot` | true | false | true |
| `docs_table_patch`, `docs_table_format`, `docs_table_structure` | false | true | false |
| `server_info` | true | false | true |

Paragraph/comment deletion is advertised as idempotent in effect, although a
retry can return a not-found error. Table structural edits are non-idempotent;
do not replay an ambiguous deletion or insertion. Resolution
creates a resolving reply, so repeating it is not advertised as idempotent.
Replacements can match their own output and are not idempotent.

Successful text edits and comment mutations include `document_id`, `scope`,
and nullable `heading_id`. Scope is `heading_subtree` for a scoped replacement
or before/after insertion (including nested headings), `document` for an
unscoped text operation or new anchored comment, `document_end` for append,
and `comment` for reply/resolve/delete (identified by `comment_id`). Creation
retains its existing `{id, title, webViewLink}` result. All `at_index` fields
are API diagnostics; identify edits using document, scope, and operation IDs.

All preview lengths use Unicode code points, not bytes or Google Docs UTF-16
indices. Inserted lengths include automatically added paragraph breaks.
API positions and ranges, including `at_index`, use UTF-16 code units:
`😀` occupies two index units but counts as one character in receipt lengths.
Text search and slicing retain Python code-point offsets; targeted edits,
batch replacements, comment anchors, and rich-text formatting convert these
offsets to UTF-16 when constructing Google Docs requests.

Targeted replacement and before/after insertion also resolve individual
paragraphs inside table cells, in row/cell order under the surrounding body
heading. Insertions remain inside the selected cell. Table HTML is display
markup, not searchable cell separators; searches do not span cell paragraphs.
Replacement cannot remove a cell's mandatory final newline or span a non-text
element. Text beside an object in the same cell uses its original run positions.
Batch replacement and comment anchoring currently search body paragraphs;
matches spanning a skipped table or another source gap are rejected before
writes. Rich insertion can also create rectangular native tables (see [rich content](rich-content.md#tables)).
Before/after insertion adds `inserted_char_count`, `preview_truncated`,
`anchor_char_count`, and `anchor_preview_truncated`. The insertion preview
remains at most 200 code points and the anchor preview at most 80. Append
preserves its existing `appended`, length, and truncation semantics.

For example, a literal before-insertion of `Hello` within `nested` includes
these receipt fields (other fields omitted):

```json
{
  "document_id": "example",
  "scope": "heading_subtree",
  "heading_id": "nested",
  "inserted_text": "Hello\n",
  "inserted_char_count": 6,
  "preview_truncated": false
}
```

Replacement adds `replaced_char_count`, `preview_truncated`, and `applied`
(actual changes, distinct from matches found). `occurrences_found_complete`
is true for every targeted replacement: `occurrences_found` counts all pre-edit
matches in the effective scope, while `applied=1`, including when the replacement
is empty (deletion). Native literal replace-all reports
`occurrences_changed` and `applied`, with `occurrences_found=null` and
`occurrences_found_complete=false`. Targeted matching is case-insensitive;
native literal replace-all is case-sensitive. For native
replace-all, `replaced` previews the search string and its length, rather than
an individual matched item.

Deletion returns at most 100 `deleted` previews, each at most 80 code points,
with aligned `deleted_char_counts` and `deleted_preview_truncated` arrays.
Lengths describe full paragraph display text, excluding trailing newlines;
`deleted_count` counts removed/cleared paragraphs, including a cleared final
paragraph. `deleted_truncated` reports omitted preview entries.

Batch replacement returns at most 100 `changes` in document order, while
`applied` counts every applied change. `changes_truncated` reports omitted
entries. Each change preserves the public `with` alias (up to 200 code points)
and bounds `replaced` to 80 code points; `replaced_char_count`,
`replacement_char_count`, `preview_truncated`, and
`replacement_preview_truncated` describe their full lengths and completeness.

Compatibility: existing field names, aliases, preview limits for insertion
and replacement, and operation IDs are preserved. Metadata fields are
additive; clients must tolerate new fields. Batch text previews and the
batch/deletion collections are now bounded, so clients must check truncation
flags and use counts rather than treating preview arrays as complete logs.
Read the affected document to verify full content. Comment content fields
remain complete strings. No tool arguments or Google edit requests change.

## Indexing and suggestions

Google Docs edits use native UTF-16 character indices. Text anchors and checked
table references keep that arithmetic inside the server, allowing targeted
edits without replacing unrelated document content.

When the MCP reads content before planning indexed edits, it requests
`suggestionsViewMode=SUGGESTIONS_INLINE`. This keeps returned indices aligned
with later `documents.batchUpdate` calls when the document contains suggestions.

## Concurrent edits

By default, indexed edits use required revision guards and up to three attempts.
After a confirmed
revision race, unchanged unambiguous targets are validated and positions
recalculated; overlapping, deleted or ambiguous targets fail. Concurrent
appends use the current end. Unknown write outcomes and completed table stages
are never automatically replayed. Batch replacement remains atomic; table
insertion and Docs-anchor/Drive-comment creation span separate writes.
With `write_revision_mode="target"`, Google merges the original plan with
concurrent changes, including overlaps; local conflict validation/retries do
not apply. Google determines concurrent append order. A rejected target
revision requires a fresh read and an explicit new edit. Diagnostic indices
in target-mode receipts refer to the original planning snapshot, not positions
after Google's transformation. Multi-stage table insertion, cell patching,
table formatting and structural operations remain strict.

By default this protects the backend read-to-write window. Optionally pass
`expected_revision_id` from an earlier document read for a strict precondition
that rejects any intervening change and disables rebasing. Native replace-all
keeps execution-time matching and rejects that parameter. Errors include
`committed_batches`; an unknown pending write might also have committed.
See [concurrent edit guarantees, retry limits and recovery](concurrent-edits.md).
