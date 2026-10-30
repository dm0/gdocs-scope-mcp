# Table tools

[README](../../README.md) · [Content syntax](../rich-content.md) · [Result contracts](../protocol.md)

Use [document reading](documents.md#docs_read) to obtain inline table references,
or start with `docs_tables_list`. These tools use checked table positions,
not text anchors. Creation syntax belongs to [rich content](../rich-content.md#tables).

All table tools accept optional `tab_id`; omit it for the first tab. Use
[docs_tabs_list](documents.md#docs_tabs_list) for root and nested tab IDs.
Refs, snapshots and page tokens belong to the selected tab: pass the same
selector throughout an operation. Another tab, a removed tab or an omitted
selector resolving elsewhere cannot reuse those references.

Every table tool returns the effective `tab_id` at the top level, including
snapshots and write receipts. Listing/read responses also retain it inside
`snapshot`. Omission still selects the first tab; it does not infer a tab
from `table_ref` or remember an earlier selection. This keeps calls for the
usual single-tab document free of extra required parameters.

`TAB_MISMATCH` means the reference and selected tab differ. The error names
both IDs and suggests the correct `tab_id`; retrying with that selector can
reuse the reference when it is still valid. If the currently selected tab
was intended, obtain its own references instead. This is distinct from a
structural `TARGET_CHANGED` or revision `STALE_REFERENCE` error. Never edit
opaque references or tokens to change their tab.

See [table references and expectations](../table-references.md) for the position
contract, [discovery implementation](../table-discovery.md) for geometry and
pagination, and [concurrent edits](../concurrent-edits.md) for revision policies.

## docs_tables_list

```text
docs_tables_list(
    doc_id,
    heading_ids=None,
    limit=50,
    page_token=None,
    *,
    tab_id=None,
)
```

Discover tables in the selected tab without returning surrounding document
text. Each summary includes `table_ref`, nearest heading ID/title and ancestor IDs,
dimensions, nesting depth, `parent_cell_ref` for nested tables, merge/geometry
flags, unsupported-edit reasons and a preview of at most 200 Unicode code
points with `preview_truncated`. Tables are returned in preorder: parent before
its nested tables. Heading titles in summaries are limited to 80 characters.
Heading selection follows `docs_read`, including empty/mixed selections and
descendant deduplication.

`limit` is 1-100 tables. `count` describes this page; `total_count` covers all
matching tables. Continue with `next_page_token`, preserving the exact
`heading_ids`, `limit` and `tab_id`. `snapshot` contains the native revision,
actual `tab_id`, `scope` (`first_tab` when omitted, `selected_tab` when explicit),
and `reference_lifetime="same_structure_only"`. Page cursors still require
the exact revision.

## docs_table_read

```text
docs_table_read(
    doc_id,
    table_ref,
    limit=100,
    max_cell_chars=2000,
    page_token=None,
    *,
    tab_id=None,
)
```

Read one table using a reference from document HTML or `docs_tables_list`.
The response contains the summary/snapshot, `total_cells`, and structured
`rows`/`cells`. Cells include zero-based logical `row`/`column`, native
`row_span`/`column_span`, a physical cell-array position, A1 `address`,
`cell_ref`, Markdown and explicit clipping metadata. Nested table HTML carries references;
`nested_table_refs` identifies up to 20 immediate children of a cell, with
`nested_table_count` and `nested_table_refs_truncated` disclosing omissions.
Use paginated table discovery for additional children (`parent_cell_ref`
identifies their containing cell).

`limit` counts **physical cells**, including covered merged slots, not rows
(1-200, default 100). A wide row can span pages; `rows.complete` indicates
whether all its physical cells are included. Pages include rows with returned
cells; rows with no physical cells are described through dimensions/spans.
`count` is returned cells and `total_cells` is the table's physical-cell count.
Continue with the same `table_ref`, `limit` and `max_cell_chars`.

`max_cell_chars` bounds each Markdown preview to 1-4000 Unicode code points,
default 2000. `markdown_char_count` is the full length and
`markdown_truncated` discloses clipping. A clipped preview can cut HTML or code
syntax; do not treat it as complete replacement content.

Merged heads preserve spans. Covered physical slots have `covered_by` but no
independent `cell_ref`. Unsupported or inconsistent geometry is flagged, with
null logical columns/cell handles. Geometry verification is limited to grids
of at most 100,000 logical slots. Their content remains readable in pages.
`simple_text_target` describes conservative structural eligibility; the patch
tool also validates snapshots and native target details. Cells in merged
tables, nested/complex cells and non-text content are explicitly flagged.

References describe checked **section positions**: heading ID ancestry, the
table's ordinal in its direct section, and hashes of its structure and the
section's ordered table structures. Text/style edits and native index shifts
preserve refs. Insertion/deletion or a structural change to a table in that
direct section returns `TARGET_CHANGED` and requires fresh discovery. Changes
inside child heading sections have independent inventories. Nested references
add a cell/nested-table position checked against the parent structure.

Swapping or replacing structurally identical tables preserves the reference's
**position meaning**. It does not establish persistent native object identity
or prove edit history. Use selective snapshots below to detect changed target
content/properties. Identical replacement with identical selected state is
accepted under this positional contract. Table summaries expose
`reference_semantics="section_position"`, `section_table_number` (1-based
top-level ordinal, also the root ordinal for nested tables), and
`reference_lifetime="same_structure_only"`. Cells include an `address` such
as `A1`, `Z3` or `AA2`, alongside their opaque scoped `cell_ref`.

All page cursors still require the exact revision: a revision change returns
`STALE_REFERENCE`. Refs/tokens work across independent MCP processes with no
local registry, signing key or binding step. SHA-256 checksums detect
corruption, not forgery; these are not authorization capabilities. Each call
checks normal Google permissions. Reads and snapshots never create named
ranges or local files, and write no metadata.
Native revision metadata is required; Google exposes it only to editors, so
unavailable metadata returns `REVISION_UNAVAILABLE`.

```python
page = docs_tables_list(doc_id="...", heading_ids=["heading-id"], limit=10)
details = docs_table_read(doc_id="...", table_ref=page["tables"][0]["table_ref"])
```

## docs_table_snapshot

```text
docs_table_snapshot(
    doc_id,
    table_ref,
    cells,
    fields=None,
    base_token=None,
    *,
    tab_id=None,
)
```

Reads and issues expected-state tokens for 1-100 selected uppercase A1 addresses,
for example `cells=["A1", "B2"]`. Snapshots require verified geometry without
nested tables in the target's cells. Ordinary groups require unmerged geometry.
The exclusive `fields=["merge"]` mode also accepts merged tables: select real
logical head addresses, not covered positions. Each response cell includes
`row_span` and `column_span`. The default field
groups are `content`, `text_style` and `paragraph_style`; `cell_style`,
`structure`, `deletion` and the granular formatting fields documented below are
optional. `deletion` protects full native removed-cell state for structural
deletion, including referenced metadata and relevant formatting dependencies.
`merge` protects participating head content/styles, physical placeholders,
referenced metadata, enclosing content direction and every adjacent border
segment. It cannot be combined with other field groups in one snapshot.
Snapshots allow at most 1000 cell/field pairs. Selected granular values appear
in each cell's `formatting` object using native Google Docs representations.
Pass a previous `base_token` with the same cell set
and fields to validate and renew it. Only selected cells/properties are
compared, allowing independent cell edits anywhere while the section table
structure inventory remains unchanged. The response includes selected Markdown
from the same read (up to 2000 Unicode code points per cell, full lengths and
truncation flags), current coordinates, revision and renewed expectations.
Prepare an edit from that returned state; if clipped, obtain complete content
before preparing a replacement. The token hashes complete native state even
when the preview is clipped. A snapshot does not reserve cells or perform
writes. `docs_table_patch` revalidates inside its call and uses strict CAS
against that fresh revision. Its baseline must include `content` and
`text_style`; the default snapshot fields include both. A content-only snapshot
can be validated but cannot guard a Markdown replacement that changes styles.

```python
table_ref = page["tables"][0]["table_ref"]
base = docs_table_snapshot(doc_id="...", table_ref=table_ref,
                           cells=["A2"], fields=["content"])
# Inspect base["cells"] and prepare the intended change.
# Independent edits to other cells are allowed between these calls.
checked = docs_table_snapshot(doc_id="...", table_ref=table_ref,
                              cells=["A2"], fields=["content"],
                              base_token=base["base_token"])
```

Table refs have no time expiry. Snapshot tokens expire after 86,400 seconds by
default; set JSON
`table_snapshot_ttl_seconds` or `GDOCS_SCOPE_MCP_TABLE_SNAPSHOT_TTL_SECONDS`
to an integer between 1 and 604,800 seconds.

See [positional references, dependency groups and limits](../table-references.md).

Merged-cell warnings and `simple_text_target` describe text-patch eligibility;
they do not rule out the separately validated merge/unmerge operations below.

## docs_table_patch

```text
docs_table_patch(doc_id, table_ref, base_token, changes, *, tab_id=None)
```

Replace 1-100 cells with typed changes such as
`[{"address": "A2", "markdown": "New **value**<br>next line"}]`.
Use the content returned by a default `docs_table_snapshot` to prepare the
replacement. The patch may select a subset of the snapshot's cells; unused
cells do not create conflicts. Every field group included in the baseline
is checked for affected cells. The baseline must include `content` and
`text_style` because a Markdown replacement changes both.

```python
base = docs_table_snapshot(doc_id="...", table_ref=table_ref, cells=["A2", "B2"])
# Inspect base["cells"] and prepare the complete replacements.
result = docs_table_patch(
    doc_id="...", table_ref=table_ref, base_token=base["base_token"],
    changes=[{"address": "A2", "markdown": "**Updated** 🦷<br>second line"},
             {"address": "B2", "markdown": ""}],
)
```

The initial subset is one ordinary text paragraph per target, unmerged table
geometry and no nested tables in the target table's cells. Bold, italic,
underline, strikethrough, links, inline code, superscript/subscript and HTML
`br` are supported. Markdown soft source wraps become spaces. Use `br` for a
native U+000B soft break. Empty Markdown clears the cell's text. Images, smart
chips, lists, block content, tracked suggestions and unsupported native
structures fail before any write. Full text and inline styles are replaced;
unspecified inline styles reset to inherited defaults. Paragraph properties,
cell background/borders/padding and the mandatory final newline are retained.
An independent background change therefore remains compatible unless the
caller explicitly included `cell_style` among its snapshot expectations.
Characters that Google silently strips from inserted text are rejected,
including decoded HTML entities, to keep UTF-16 style ranges correct.
See Google's [text insertion rules](https://developers.google.com/workspace/docs/api/concepts/rules-behavior#insert_text).

All changed cells are planned from the same fresh snapshot, in descending
native index order, and submitted in **one atomic batchUpdate**. The tool
always uses `requiredRevisionId`, including with server revision mode `target`.
A confirmed revision race causes a fresh read, structural/state revalidation
and UTF-16 replanning, with at most three attempts. It never replaces the
agent's baseline with a new one during retries. Nonintersecting cell edits and
ordinary text shifts can succeed; genuine overlap returns `EDIT_CONFLICT`,
changed structure returns `TARGET_CHANGED`, expired expectations return
`SNAPSHOT_EXPIRED`. Repeated contention returns `REVISION_RETRY_EXHAUSTED`:
retry later with the same token if still valid. `WRITE_OUTCOME_UNKNOWN` means
the write may have committed and **must not be blindly repeated**; inspect the
document first.

Receipts include `document_id`, `table_ref`, resulting `revision_id`,
`applied_count`, `attempts`, `committed_batches` and per-cell text previews
(up to 200 Unicode code points), full text lengths, truncation flags and native
UTF-16 inserted/deleted counts. Counts exclude the preserved final newline;
preview soft breaks display as ordinary line breaks. An all-empty-to-empty
patch sends no write and reports `committed_batches=0`; otherwise one batch
commits all cells or none. Inputs are limited to 100000 total Markdown
characters and 1000 generated native requests. Positional reference semantics
and identical-structure swap/replacement limits remain unchanged.

## docs_table_format

```text
docs_table_format(doc_id, table_ref, base_token, changes, *, tab_id=None)
```

Apply explicit formatting to an unmerged table without replacing its contents.
First snapshot the properties you intend to change; the default content/style
groups alone cannot guard this tool. Only requested properties are compared,
even when the baseline includes additional fields. Text edits, different cell
properties and changes elsewhere can proceed concurrently.

| Snapshot field | Property in `changes` | Values |
| --- | --- | --- |
| `cell.background_color` | `cells[].background_color` | `#RRGGBB` or `transparent` |
| `cell.vertical_alignment` | `cells[].vertical_alignment` | `TOP`, `MIDDLE`, `BOTTOM` |
| `cell.padding_top`, `cell.padding_bottom`, `cell.padding_left`, `cell.padding_right` | Corresponding `cells[].padding_*` | Points, 0–10000 |
| `cell.border_top`, `cell.border_bottom`, `cell.border_left`, `cell.border_right` | Corresponding `cells[].border_*` | Object with `color`, `width`, `dash_style` |
| `paragraph.alignment` | `cells[].horizontal_alignment` | `START`, `CENTER`, `END`, `JUSTIFIED` |
| `column.width` | `columns[].width` | Points, 5–10000, or `auto` |
| `row.min_height` | `rows[].min_height` | Points, 0–10000 |
| `table.header_rows` | `header_rows` | Number of leading pinned header rows; 0 unpins |

```python
base = docs_table_snapshot(
    doc_id="...", table_ref=table_ref, cells=["A1", "B1"],
    fields=["cell.background_color", "cell.padding_top", "column.width",
            "table.header_rows"],
)
# Inspect base["cells"][...]["formatting"] before choosing changes.
result = docs_table_format(
    doc_id="...", table_ref=table_ref, base_token=base["base_token"],
    changes={
        "cells": [{"address": "A1", "background_color": "#D9EAF7",
                   "padding_top": 8}],
        "columns": [{"column": "B", "width": 120}],
        "header_rows": 1,
    },
)
```

Use uppercase cell/column addresses and 1-based row numbers. A column change
needs at least one snapshot cell in that column; a row change needs one in
that row; header pinning needs any cell in the table. A call accepts 1–100
targets across cells, columns, rows and the optional header count. Duplicate
targets, explicit nulls, empty changes and unknown properties are rejected.
Omitted properties are preserved. Horizontal alignment applies to every
paragraph in the selected cell. Header pinning repeats leading rows across
pages; available space and other Google Docs layout constraints still apply.

Each border accepts `color="#RRGGBB"`, `width` in points (0 hides it), and
`dash_style="SOLID"`, `"DOT"` or `"DASH"`. Google writes a whole border at once,
so a concurrent change to any component of that border conflicts. An interior
edge includes the neighboring cell's opposite border in its expected state.
Different edges remain independent. Partial border changes preserve known,
consistent components; if Google omits inherited values or the two sides
disagree, supply all three components explicitly. Contradictory requests for
the same shared edge fail before writing; compatible requests are coalesced.

All changes use one atomic native batch with strict `requiredRevisionId`,
including under the general `target` mode. Confirmed revision races get at
most three attempts, each resolving current positions and rechecking the
original property expectations. The same conflict, expiry, structural-change,
contention and unknown-outcome rules as `docs_table_patch` apply. Unknown write
outcomes are never replayed automatically. Relevant tracked style suggestions,
merged geometry and tables nested inside cells are unsupported.

The receipt returns `applied_count` (requested targets), `updated_properties`,
`revision_id`, `attempts` and `committed_batches=1`. It makes no claim that
text changed. Formatting uses this dedicated tool; no additional Markdown
syntax is required.

## docs_table_structure

```text
docs_table_structure(doc_id, table_ref, base_token, operation, *, tab_id=None)
```

Insert empty rows/columns, delete consecutive rows/columns or an entire table,
or merge/unmerge cells. Each call accepts **one** typed operation, applied in
one strict, atomic native batch. Row/column counts default to 1 and are limited
to 1–100.

| `operation.type` | Required fields | Meaning |
| --- | --- | --- |
| `insert_rows` | `row`, `position` | Insert `count` rows `before` or `after` an existing 1-based row |
| `insert_columns` | `column`, `position` | Insert `count` columns `before` or `after` an existing uppercase column, e.g. `B` |
| `delete_rows` | `row` | Delete `count` rows starting at that row |
| `delete_columns` | `column` | Delete `count` columns starting at that column |
| `delete_table` | None | Remove the whole table, retaining its preceding paragraph |
| `merge_cells` | `start_cell`, `end_cell` | Merge the inclusive logical rectangle into its upper-left head |
| `unmerge_cells` | `start_cell`, `end_cell` | Split complete merged cells in the inclusive rectangle |

Insertions require any cell snapshot for the checked table; content and style
fields do not reserve existing cells. The table reference guards the selected
row/column and insertion boundary against structural changes. Empty cells use
Google Docs' native inherited formatting. Insertion permits independent cell
text edits and changes before the table that shift native indices.

Deletions require `docs_table_snapshot(fields=["deletion"])` for **every cell
being removed**, at most 100 cells per call. This field hashes full native
cell state, referenced object/list/dropdown metadata, footnote/positioned-object
data, intersecting named ranges, effective named styles and row/column/table
formatting. Shared borders also include the neighbor's opposite edge.
It is intentionally stronger than a content-only snapshot. Unused snapshot
cells do not create dependencies, and other cells' contents may change.
Some formatting dependencies are conservative: a table-wide style change, or
width/row-style change associated with a removed cell, requires review.

```python
# Remove row 2 from a two-column table after inspecting its current contents.
base = docs_table_snapshot(
    doc_id="...", table_ref=table_ref, cells=["A2", "B2"], fields=["deletion"],
)
result = docs_table_structure(
    doc_id="...", table_ref=table_ref, base_token=base["base_token"],
    operation={"type": "delete_rows", "row": 2},
)
table_ref = result["table_ref"]
# Take a NEW snapshot before the next operation.
```

Row/column/table operations require top-level tables with verified unmerged
geometry and no nested tables in their cells. Insertions may produce at most 100000 logical
cells. Removing every row or every column is rejected: use `delete_table`
explicitly, with expectations covering the entire table. For tables larger
than the deletion limit, remove reviewed subsets first when a row/column fits
the limit, taking fresh refs and snapshots between calls. Tables whose smallest
removable row/column exceeds 100 cells cannot be deleted through this initial
tool. A series of calls is not atomic as a whole.

### Merge and unmerge

Both operations support verified logical grids, including tables already
containing horizontal or vertical merges. A rectangle must include each
intersecting merged cell's **entire** span. Its logical area is limited to 100
slots. Obtain `fields=["merge"]` expectations for every participating head,
including empty cells; covered physical positions are not separate heads.
For unmerge, only existing merged heads participate: already unmerged cells
inside the rectangle are ignored and do not need snapshot expectations.
`docs_table_read` reports spans and `covered_by_cell_ref` to identify them.

```python
base = docs_table_snapshot(
    doc_id="...", table_ref=table_ref, cells=["A1", "B1"], fields=["merge"],
)
result = docs_table_structure(
    doc_id="...", table_ref=table_ref, base_token=base["base_token"],
    operation={"type": "merge_cells", "start_cell": "A1", "end_cell": "B1"},
)
# Check reference_refresh_required; rediscover if true. Never repeat a
# confirmed transformation merely because its new reference is unavailable.
```

Merge concatenates each head's existing paragraphs in row-major head order
into the upper-left head. Text-run formatting, paragraph boundaries and soft
breaks are preserved; an empty cell adds no extra paragraph. There is no
custom separator or hidden text rewrite. Already merged contents remain an
intact paragraph sequence when their head joins another merge. Native Google
Docs rules determine resulting cell/background/border formatting; the tool
does not promise to restore pre-merge presentation.

Unmerge keeps the **entire current contents** of each merged cell in its own
upper-left head; the other resulting cells are empty. It does not recover the
original cell contents or distribution. A selection with no merged cells is
rejected. After a merge, take a new snapshot of the head before unmerging:

```python
base = docs_table_snapshot(
    doc_id="...", table_ref=new_table_ref, cells=["A1"], fields=["merge"],
)
result = docs_table_structure(
    doc_id="...", table_ref=new_table_ref, base_token=base["base_token"],
    operation={"type": "unmerge_cells", "start_cell": "A1", "end_cell": "B1"},
)
```

The initial supported content is normal text paragraphs in top-level tables
within LTR sections. Multiple paragraphs, supported inline formatting and
soft breaks are allowed. Nested tables, headings, lists, images/chips/other
objects, positioned objects, tracked suggestions and named ranges intersecting
the selection are rejected before writing. Full native state and shared-border
dependencies are still compared; compatible text edits outside the rectangle
can succeed after a revision retry. Associated row/column/table formatting
dependencies are conservative. Text patching and targeted formatting retain
their existing unmerged-table scope.

Every attempt resolves fresh native indices and uses `requiredRevisionId`,
even under the general `target` mode. Confirmed revision races get at most
three attempts with the original expectations. Changed deleted state returns
`EDIT_CONFLICT`; changed participating merge state also conflicts. Structural
changes in the same heading section return
`TARGET_CHANGED`, including concurrent insertion at the same boundary. No
content matching or guessing is used to relocate rows/columns. Changes in
other sections remain compatible while this section's structural guard holds.
Expired snapshots and unknown outcomes follow the same rules as table patching;
an ambiguous structural write is **never automatically replayed**.

Receipts include `previous_table_ref`, updated `table_ref`, committed
`revision_id`, `rows`, `columns`, `operation`, `affected_count` (rows/columns,
or 1 table; changed head count for merge/unmerge), `deleted_cell_count`,
`attempts` and `committed_batches=1`. Merge/unmerge also return original
`affected_cells`, `result_head_cell` (merge only), and `content_policy`
(`row_major_paragraphs` or `keep_in_heads`). They report zero deleted cells.
After whole-table deletion, `table_ref` is null and dimensions are zero.
Row/column operations calculate new refs from the planned shape before writing.
Merge/unmerge use an authoritative post-write read, and issue a ref only when
its revision matches the confirmed batch revision. If this read fails or
another write intervenes, the operation remains successful (`ok=true`,
`committed_batches=1`) with `table_ref=null` and
`reference_refresh_required=true`. Rediscover and take fresh expectations;
**do not repeat the committed operation**. Dimensions and committed revision
still describe this batch. A null ref means deletion only for `delete_table`.
Subsequent structural changes can invalidate returned refs normally.
`snapshots_invalidated` and `section_references_invalidated` are always true:
take a fresh snapshot and rediscover other tables in the same section before
further edits. There is no multi-stage write or partial-success path within
one call.

See the [merge implementation notes](../development/table-cell-merging.md)
for verified native behavior, logical ownership and race tests.
