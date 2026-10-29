# Suggestions

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

## docs_suggest

```text
docs_suggest(doc_id, operation, *, tab_id=None, heading_id=None,
             expected_revision_id=None)
```

Create one native proposal operation per call, using a discriminated JSON
object in `operation`. The complete generated plan is preflighted and sent in
one atomic Docs batch with `writeControl.writeMode="SUGGEST"`. A logical
operation can produce several native suggestion IDs; never assume one ID per
call or API request.

| `operation` value | Required fields | Optional fields |
|---|---|---|
| `replace` | `find`, `text` | `occurrence=1` |
| `insert_before`, `insert_after` | `anchor`, `text` | `occurrence=1`, `rich=True` |
| `append` | `text` | `rich=True` |
| `delete_paragraph` | `anchor` | `occurrence=1` |
| `format_text` | `find`, `style` | `occurrence=1` |

Anchors are literal and case-sensitive. Occurrences start at 1; replace-all and
regex matching are not supported. `delete_paragraph` selects one anchor match,
not every matching paragraph. Replacement text is literal, and an empty string
proposes deletion of the match. Text matching cannot include a paragraph's
terminating newline; use paragraph deletion for that operation. The mandatory
final body newline is retained.

Insertions create separate paragraphs. Rich insertion supports Markdown
paragraphs, headings, emphasis, links, inline code, and formatted code blocks.
It uses configured formatting defaults. Plain insertion (`rich=False`) treats
its text literally. Tables, images (including local uploads), chips and list
requests are rejected before any upload or write. Code-block named ranges
cannot be suggested: the planner omits those markers, retains code formatting
and returns an explicit warning. It never creates markers as direct edits.

`format_text.style` accepts `bold`, `italic`, `underline` and `strikethrough`
booleans. Supply at least one flag; `false` proposes removing that formatting.
This is text formatting, not general named-style management.

Targets must be ordinary body paragraphs, excluding table cells, lists and
paragraphs containing non-text entities or objects. An existing proposal in the
target paragraph causes `EDIT_CONFLICT`, including formatting or inherited
changes. Unlocated open threads or unknown native proposal metadata also block
creation: inspect/decide them first. Known proposals in other paragraphs/tabs
are allowed. Paragraph deletion also guards the next paragraph when it removes
their separating break. Matching uses native source text only after validating
that its paragraph is free of proposals; preview offsets and summaries are
never used as mutation coordinates.

Omitting `tab_id` selects the first tab. `heading_id` scopes matching and
append to its accepted heading subtree; unmappable heading boundaries fail.
Writes require a usable native revision ID, even where a viewer can read a
clean projection. Required mode can replan an unchanged target after a confirmed
revision rejection; target mode delegates concurrent merging to Google.
`expected_revision_id` forces strict matching in either configuration.

```python
proposal = docs_suggest(
    doc_id='...', heading_id='heading-from-outline',
    operation={'operation': 'replace', 'find': 'old wording',
               'text': 'proposed wording'},
)
docs_suggest(
    doc_id='...',
    operation={'operation': 'format_text', 'find': 'Important',
               'style': {'bold': True}},
)
```

Receipts report `changes.created`, `updated`, `deleted`, `accepted` and
`rejected` native IDs, source tab/heading, operation, current readback revision
and warnings. Creation requires `ALL_SAVED` and a fresh native thread read
confirming the returned created/updated IDs are open. A missing ID, unconfirmed
save state or failed readback is an explicit uncertain/partial failure, never
an automatic replay. A no-change formatting request may not create a proposal;
if Google omits usable IDs, inspect current state before issuing another call.

## docs_suggestions_manage

```text
docs_suggestions_manage(doc_id, action, suggestion_ids, *,
                        expected_revision_id=None)
```

`action` is `accept`, `reject` or `delete`; `suggestion_ids` contains 1–50 unique
native IDs obtained from dedicated reading or a proposal receipt. These IDs are
document-wide, so there is no tab or heading parameter. Preflight covers the
entire list: missing/deleted IDs, unknown statuses, or already decided IDs
incompatible with the action reject the batch without sending any decisions.
An already accepted/rejected proposal matching the requested action returns
`outcome="already_decided"` without another write. Delete is initially limited
to open proposals; a missing ID is not silently considered successfully deleted.

Pending decisions are sent in one guarded atomic batch in direct `EDIT` mode.
Success requires `ALL_SAVED`, matching response IDs and native readback of each
decision. Per-ID results include `action`, `outcome` and resulting `status`.
An entirely already-decided call has `comment_update_state=null`; a saved batch
has `ALL_SAVED`. Required-mode retries reject changed proposal state. Target
mode retains Google's collaboration semantics; use `expected_revision_id` when
the caller requires a strict document revision. Unknown/partial outcomes are
never replayed automatically.

Accepting requires edit access; rejecting requires edit access or authorship;
deleting requires authorship. Google checks these permissions, and a 403 retains
action-specific guidance. Deleting an owned open proposal removes its proposed
changes too; it does not accept them. Replies and generated summary editing are
outside the initial scope.

```python
docs_suggestions_read(doc_id='...', suggestion_id='native-suggestion-id')
docs_suggestions_manage(doc_id='...', action='accept',
                        suggestion_ids=['native-suggestion-id'])
```

## Editing boundaries

Existing edit tools still make direct edits. They resolve indices using native
`SUGGESTIONS_INLINE` data, never the accepted-content projection. Ordinary
Markdown is not a review diff and does not embed pending `<ins>`/`<del>` markup
that a rich insertion might silently turn into accepted text or strikethrough.
Use the dedicated tools above when proposals are intended; there is no global
edit/suggest switch or write-mode argument on existing direct-edit tools.

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

`tests/test_suggestion_writes.py` additionally covers typed plans, unsupported
content, overlap protection, source tab scoping, paragraph boundaries, revision
policies, decision preflight, permissions, save failures, readback and uncertain
outcomes. Public creation/decisions are verified through isolated MCP processes
in both required and target modes:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=YOUR_TEST_DOCUMENT_ID uv run --locked pytest -q tests/test_live_suggestion_writes.py
```

The tests delete pending proposals before deleting their temporary tabs:
deleting a tab alone can leave unlocated OPEN threads. Existing unrelated
threads are preserved. Evidence and stderr use
`/tmp/gdocs-scope-mcp-table-probe-suggestion-writes-{required,target}.*`.
Editor/author behavior is live-verified; other-user/commenter-only permissions
and partial-save fault injection are covered only by API contracts/offline
tests, not live multi-account experiments.
