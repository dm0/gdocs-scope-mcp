# Document tools

[README](../../README.md) · [Content syntax](../rich-content.md) · [Result contracts](../protocol.md)

## Document tabs

All document read/edit tools accept optional `tab_id`. Omit it or pass null
for the first top-level tab. Explicit IDs can select nested tabs. Missing IDs
fail without falling back. Heading IDs, text matches, table references, chip
definitions and named ranges are resolved only in the selected tab.
Read/outline responses include `tab_id` and `tab_title`; scoped edit receipts
include `tab_id`. Revision IDs remain document-wide. Even native replace-all
is restricted to the selected tab. Drive document listing/creation and
comment-thread operations remain document-wide.

Start with `docs_get_tree(doc_id)`: one call returns the first tab's headings
and the complete tab inventory. If there is one tab, continue reading and
editing with `tab_id` omitted. No separate `docs_tabs_list` call is needed.
For several tabs, reuse this outline for the first tab. To work in another
tab, call `docs_get_tree(doc_id, tab_id=...)` to obtain its own heading IDs,
then retain that `tab_id` on subsequent calls. Selection is stateless: omitting
`tab_id` always chooses the first tab, even after a call selected another one.

### docs_tabs_list

```text
docs_tabs_list(doc_id)
```

Return `document_id`, `title`, `revision_id`, `default_tab_id`, and a flat
`tabs` array. Each entry has `tab_id`, `title`, `parent_tab_id`, `depth` and
sibling `index`. Entries follow document order, parents before children.
Discovery performs no writes. This tool is optional when only tab metadata
is needed; `docs_get_tree` already includes the same inventory:

```python
docs_get_tree(doc_id="...")
docs_read(doc_id="...")  # Usual single-tab path; no extra discovery needed.
```

## Shared insertion options

The three insertion tools accept the same rich-content options:

| Parameter | Default | Effect |
| --- | --- | --- |
| `rich` | `True` | Parse supported Markdown/HTML; `False` inserts literal text |
| `upload_local_images` | `False` | Explicitly authorize temporary Drive upload/link sharing for local images |
| `table_borders` | `True` | Show borders on newly inserted tables |
| `code_block_style` | `None` | Override the configured Pygments theme for this call |
| `code_block_theme_background` | `None` | Override theme backgrounds for this call |
| `expected_revision_id` | `None` | Require the agent's earlier read revision, without automatic rebasing |

See [rich-content syntax and limitations](../rich-content.md) for tables,
images, lists, code and chips, and [configuration](../configuration.md) for
server defaults. Theme/background nulls inherit their server defaults.

## Revision preconditions

`docs_search_replace`, `docs_batch_replace`, `docs_delete_paragraph`,
`docs_append`, `docs_insert_before` and `docs_insert_after` accept optional
`expected_revision_id`. Omitting it uses the configured write policy;
providing it requires that exact revision and disables rebasing. Native
single-tool replace-all (`occurrence=0`) rejects this parameter.
See [concurrent edits](../concurrent-edits.md) for guarantees and recovery.

Signatures below use Python notation for defaults and keyword-only arguments.
MCP calls pass named JSON arguments; `None`, `True` and `False` correspond
to JSON `null`, `true` and `false`.

## Reading

`docs_get_tree` and `docs_read` show accepted content without applying pending
suggestions. Proposed insertions are hidden, proposed deletions retained, and
suggested formatting omitted. Their `suggestions` metadata reports pending
changes document-wide and in the returned scope; `null` means unknown. Inspect
proposals separately with [docs_suggestions_read](suggestions.md). Reading
never accepts or rejects changes.

### docs_get_tree

```text
docs_get_tree(doc_id, *, tab_id=None)
```

Return an object with `document_id`, `title`, `revision_id`, and a flat
`sections` array. Each section contains `title`, `id`, `level`, and
`ancestor_ids`; hierarchy is expressed through ancestor IDs rather than nested
section objects. Use the IDs to select section subtrees for reading and
editing; body paragraphs are omitted.

The response also includes `tab_id`, `tab_title` and `tabs`: the complete
inventory of root and nested tabs, including the selected one. Each tab has
`tab_id`, `title`, `parent_tab_id`, `depth` and sibling `index`, in document
order. One entry means the document has only one tab. Use the returned IDs to
select another tab without a separate discovery call. The inventory and the
selected tab's sections come from the same Google API read; other tabs' body
content is not returned.

```python
docs_get_tree(doc_id="...")
```

### docs_read

```text
docs_read(doc_id, heading_ids=None, *, tab_id=None)
```

Return document content as `sections: [{heading_id, markdown}]`, alongside
`document_id`, `title`, `revision_id`, `selected_headings`,
`unknown_heading_ids`, and `partial`. This replaces the former `subset_md` field;
use each section's `markdown` and explicit `heading_id` instead.
Pass heading IDs from the outline to return only those section subtrees,
including their nested subsections. Omit `heading_ids` to read the whole
selected tab.
Heading lines include HTML anchors carrying their structural IDs.

Native lists prefer Markdown with four spaces per nesting level. Explicit
nested HTML `ol`/`ul`/`li` is used for runs with ambiguous group boundaries,
incomplete ancestors and lists inside HTML tables. Reusing supported content
with rich insertion preserves item order, marker kind and nesting. Unmarked paragraphs
end groups; continuation membership, non-default numbering and original native
IDs are not copied losslessly. See [native list limits](../rich-content.md#native-lists).

Omitted or null `heading_ids` returns the whole selected tab (`partial=false`,
`selected_headings=null`), including any preamble before the first heading as
an entry with `heading_id=null`. A document without headings has only that
preamble entry; an empty document may have no sections.

`tab_count` is the total number of root and nested tabs, including the selected
one. One means this is the document's only tab; zero denotes unavailable tab
metadata in a legacy response. `partial` concerns heading selection within
the selected tab: `partial=false` does not mean all tabs were read. Use
`docs_get_tree` for names/IDs if `tab_count` indicates other tabs exist.

An explicit empty list returns no sections (`partial=true`,
`selected_headings=[]`). Other selections return effective root IDs and their
subtrees in document order. Duplicate IDs and descendants of selected ancestors
are collapsed, so content appears once. Unknown IDs are reported separately,
deduplicated in request order. Mixed valid/unknown selections return valid
content; if every requested ID is unknown, the tool returns `HEADING_NOT_FOUND`
with MCP `isError=true`. Refresh IDs with `docs_get_tree` before retrying.

```python
docs_read(doc_id="...", heading_ids=["heading-id-from-outline"])
```

Native tables, including nested ones, contain `data-mcp-table-ref` attributes
when their meaning can be verified against native inline structure. Unsafe
refs are omitted with an explicit `suggestions.warnings` entry; table content
still renders. Safe refs appear
in their HTML. Pass these opaque references to [docs_table_read](tables.md#docs_table_read); no duplicate
table inventory is added to `docs_read`. References belong to the selected tab;
pass the same `tab_id` to all subsequent table calls.

### docs_list

```text
docs_list(query='', limit=20, page_token=None)
```
List Google Docs from Drive, optionally filtered by a search query.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | `""` | Literal search text (searches title and content), not a raw Drive query |
| `limit` | int | `20` | Positive per-page maximum; values above 100 are capped |
| `page_token` | string or null | null | Continuation token from the previous page |

Returns `{count, documents, next_page_token, has_more}`.
The search text is passed as one escaped `fullText contains` value. Apostrophes
and backslashes are escaped automatically; expression-like text cannot add
query clauses or change the document-type and trash filters. Empty input omits
the text filter. Matching still follows Google's full-text search rules,
including double-quoted phrases; this is not a literal substring search.
See [Drive search syntax](https://developers.google.com/workspace/drive/api/guides/search-files).

Each document has `id`, `name`, `modifiedTime`,
and `webViewLink`; the last two can be null. Only one page is fetched, and
`count` is the number returned, not the total number of matching documents.
`has_more` indicates an API continuation token, not an estimated remaining count.
Preserve query, limit, and shared-drive settings when continuing. If Google
rejects an invalid/expired token, restart without it and deduplicate items.

```
docs_list(query="board deck 2026", limit=5)
```

For example, a Python MCP client can traverse pages using the same arguments:

```python
documents = []
page_token = None
while True:
    result = await client.call_tool("docs_list", {
        "query": "board deck 2026", "limit": 5, "page_token": page_token,
    })
    page = result.structured_content
    documents.extend(page["documents"])
    page_token = page["next_page_token"]
    if page_token is None:
        break
```

---

## Editing

Existing-text editing uses **text anchors**; appends use the document end.
The server resolves native indices internally. Structural table operations
have their own [checked-reference tools](tables.md).

### docs_search_replace

```text
docs_search_replace(
    doc_id,
    find,
    replace,
    occurrence=1,
    heading_id=None,
    regex=False,
    *,
    tab_id=None,
    expected_revision_id=None,
)
```
Find text in a document and replace a specific occurrence.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `find` | string | required | Text to find |
| `replace` | string | required | Replacement text |
| `occurrence` | int | `1` | Which occurrence: `1` = first, `2` = second, `0` = **all** |
| `heading_id` | string or null | `null` | Restrict search to this heading and its nested subsections |
| `regex` | bool | `false` | Treat `find` as a Python regex |
| `expected_revision_id` | string or null | `null` | Require the earlier read revision; reject any intervening change without rebasing |

```
# Replace the first occurrence within one section subtree
docs_search_replace(
    doc_id="...", find="Q1 2024", replace="Q2 2024",
    heading_id="heading-id-from-outline",
)

# Replace all occurrences (selected tab, literal search only)
docs_search_replace(doc_id="...", find="ACME Corp", replace="Initech", occurrence=0)

# Regex replace
docs_search_replace(doc_id="...", find=r"\bDraft\b", replace="Final", regex=True)
```

Returns document/scope metadata, `ok`, `replaced` (up to 80 code points),
`replaced_char_count`, `preview_truncated`, diagnostic `at_index`, `applied`,
`occurrences_found`, `occurrences_found_complete`, and `occurrences_changed`.
Targeted replacements populate `at_index` and the complete pre-edit count
`occurrences_found`, including when replacing the first occurrence. Whole-document
literal replace-all populates `occurrences_changed`. Unused index/count fields
are null. Replace-all requires `regex=False` and `heading_id=None`.

---

### docs_insert_after

```text
docs_insert_after(
    doc_id,
    anchor,
    text,
    heading_id=None,
    rich=True,
    *,
    tab_id=None,
    upload_local_images=False,
    table_borders=True,
    code_block_style=None,
    code_block_theme_background=None,
    expected_revision_id=None,
)
```
Insert Markdown or literal text after the paragraph containing `anchor`.
Pass `heading_id` to search only that section subtree; `rich=False` inserts literal text.
Rich heading mapping: `# -> TITLE`, `## -> SUBTITLE`, `### -> HEADING_1`,
and so on. Native lists with homogeneous or mixed nesting and rectangular tables
are supported.

```
docs_insert_after(
  doc_id="...",
  anchor="Executive Summary",
  text="Updated as of March 2026 following board review."
)
```

Returns document/scope metadata, `ok`, `anchor` (up to 80 code points),
`anchor_char_count`, `anchor_preview_truncated`, `insert_position`, diagnostic
`at_index`, `rich`, `inserted_text` (up to 200 code points),
`inserted_char_count`, and `preview_truncated`.
Rich insertion receipts also include `inserted_image_count`,
`inserted_entity_count` and `temporary_image_cleanup_pending`.

---

### docs_insert_before

```text
docs_insert_before(
    doc_id,
    anchor,
    text,
    heading_id=None,
    rich=True,
    *,
    tab_id=None,
    upload_local_images=False,
    table_borders=True,
    code_block_style=None,
    code_block_theme_background=None,
    expected_revision_id=None,
)
```
Insert Markdown or literal text before the paragraph containing `anchor`.
Pass `heading_id` to search only that section subtree; `rich=False` inserts literal text.
Rich heading mapping: `# -> TITLE`, `## -> SUBTITLE`, `### -> HEADING_1`,
and so on. Native lists with homogeneous or mixed nesting and rectangular tables
are supported.

```
docs_insert_before(
  doc_id="...",
  anchor="Appendix A",
  text="See the following appendix for supporting data."
)
```

Returns the same receipt fields as `docs_insert_after`, with
`insert_position="before"`.

---

### docs_delete_paragraph

```text
docs_delete_paragraph(
    doc_id,
    anchor,
    *,
    tab_id=None,
    expected_revision_id=None,
)
```
Delete all paragraphs containing `anchor` text (case-insensitive).

```
docs_delete_paragraph(doc_id="...", anchor="[PLACEHOLDER — DELETE ME]")
```

Returns document/scope metadata, `ok`, `deleted_count`, and up to 100 `deleted`
paragraph previews of up to 80 code points in reverse document order, plus
`deleted_char_counts`, `deleted_preview_truncated`, and `deleted_truncated`.
The final Body newline is preserved;
clearing a final paragraph counts as one deletion, while an already-empty
final paragraph is skipped.

---

### docs_append

```text
docs_append(
    doc_id,
    text,
    rich=True,
    *,
    tab_id=None,
    upload_local_images=False,
    table_borders=True,
    code_block_style=None,
    code_block_theme_background=None,
    expected_revision_id=None,
)
```
Append Markdown paragraphs or literal text at the end of the document, adding
a paragraph break before the content. With `rich=True`, separate paragraphs
with blank lines; headings, emphasis and native lists use the shared converter.
Rectangular native tables are also supported. Set `rich=False` to preserve text
literally.

[Supported rich content](../rich-content.md) covers tables, images, lists,
code and smart chips. Formatting overrides and local uploads use the
[shared insertion options](#shared-insertion-options).

```
docs_append(doc_id="...", text="Document last updated: March 2026.")
```

Returns `ok`, `document_id`, `rich`, diagnostic `at_index`, `appended` (a
plain-text preview of up to 200 Unicode code points), `inserted_char_count`
(including added paragraph breaks and object placeholders),
`inserted_image_count`, `inserted_entity_count`, `temporary_image_cleanup_pending`, and
`preview_truncated`.

---

### docs_batch_replace

```text
docs_batch_replace(
    doc_id,
    replacements,
    *,
    tab_id=None,
    expected_revision_id=None,
)
```
Apply multiple find→replace operations **atomically** in a single API call. Either all changes succeed or none do.

```
docs_batch_replace(
  doc_id="...",
  replacements=[
    {"find": "[CLIENT]", "replace": "Acme Corp", "occurrence": 0},
    {"find": "[DATE]", "replace": "10 March 2026", "occurrence": 0},
    {"find": "DRAFT", "replace": "FINAL"}
  ]
)
```

Each item in the array:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `find` | string | required | Nonempty text or regex pattern to find |
| `replace` | string | required | Replacement text; empty string deletes matches |
| `occurrence` | int | `1` | Nonnegative; `1` = first, `0` = all |
| `regex` | bool | `false` | Regex mode |

Returns document/scope metadata, `ok`, `applied`, up to 100 `changes`, and
`changes_truncated`. Each change has bounded `replaced` and `with` previews,
their full lengths and truncation flags, and diagnostic `at_index`;
changes are returned in document order.
Pass a native, nonempty array of objects. `replacements_json` was removed;
migrate by passing its decoded array as `replacements`. Every item is validated
before credentials are loaded or a document is read. Unknown item fields,
missing required fields, invalid regex syntax, and incorrect types are rejected.
Numbers and booleans are not accepted as strings; integer fields reject strings,
floats and booleans, and `regex` requires a boolean. Batch `occurrence=0` supports
both literal and regex replace-all. All matches are planned from the original
document and submitted together in one `batchUpdate`.

Search phrases (`find`), insertion/deletion anchors, and comment `anchor_text`
must be nonempty strings. Whitespace is preserved and counts as nonempty, so it
can intentionally match document whitespace. Targeted replacement occurrences
are nonnegative integers; comment occurrences start at 1. Listing limits are
positive integers, with values above 100 still capped at 100. Invalid inputs
return `INVALID_ARGUMENT`, recovery guidance, and MCP `isError=true` before
Google API access. Empty replacement text remains valid. The single-replacement
tool retains its restriction: `occurrence=0` requires literal, unscoped matching.

---

### docs_create

```text
docs_create(title, initial_text='')
```
Create a new Google Doc.

```
docs_create(title="Q2 Board Deck", initial_text="Confidential — not for distribution.")
```

Returns `{id, title, webViewLink}`.

---

## Typical workflows

### Contract review
```
1. docs_read         — read the document
2. docs_add_comment  — flag issues with anchor_text pointing to specific clauses
3. docs_read_comments — audit what's been flagged
4. docs_search_replace — fix straightforward issues directly
5. docs_resolve_comment — close comments as they're addressed
```

### Bulk document update
```
1. docs_list         — find all relevant documents
2. docs_batch_replace — apply changes atomically (e.g. rebrand, date update)
3. docs_read         — verify the result
```

### Collaborative review
```
1. docs_add_comment  — add review notes
2. docs_reply_to_comment — respond to collaborator comments
3. docs_resolve_comment  — close resolved threads
```
