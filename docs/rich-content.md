# Rich content

[README](../README.md) · [Configuration](configuration.md) · [Result contracts](protocol.md)

The [document insertion tools](tools/documents.md#shared-insertion-options)
share one Markdown/HTML converter. Use `rich=False` to preserve syntax literally.
Server defaults and theme overrides are documented in [configuration](configuration.md).
Existing-table edits use [table tools](tools/tables.md).

## Headings and inline formatting

Rich headings map `#` to TITLE, `##` to SUBTITLE, `###` to HEADING_1,
and so on. Rich insertion does not retain the source heading IDs.

All three rich insertion tools (`docs_append`, `docs_insert_before`, and
`docs_insert_after`) also accept the reader's HTML for bold (`b`), italic (`i`),
underline (`u`), and paragraph alignment (`p` with `text-align: center`, `right`,
or `justify`). Nested inline styles combine within their text ranges. Heading
ID anchors (`<a id="..."></a>`) are omitted from inserted text; new headings use
the Markdown heading level and receive their own Google Docs IDs.

Markdown links (`[label](https://example.com)`) become native Google Docs links
with their destination URLs. Bare HTTP(S) URLs recognized by the Markdown URL
plugin and angle-bracket autolinks also receive native link styles. Strikethrough
(`~~text~~`, HTML `del` or `s`) becomes native strikethrough formatting. Links
and strikethrough combine with supported inline emphasis; surrounding plain
text remains outside their formatting ranges. Reader HTML links (`a href`)
are supported, while empty heading-ID anchors remain metadata.

This is a bounded read-to-write subset, not complete HTML or formatting
round-trip support. Other wrappers retain their child text without preserving
unsupported formatting or attributes; non-text tags may contribute no content.
For example, a styled `span` retains its text but loses its styling. Tables
support the [rectangular subset](#tables). Use `rich=False` to preserve
HTML tags and Markdown literally.

### Literal reader content

Reader output distinguishes literal document characters from generated markup.
Ordinary text uses HTML character references for HTML/Markdown syntax, tabs,
and run-edge spaces. For example, literal `**stars**` is returned as
`&#42;&#42;stars&#42;&#42;`; a genuinely bold word still uses `<b>word</b>`.
Escaping applies to each native run, so adjacent runs cannot accidentally form
links, emphasis, headings, or list markers. Native soft breaks use `<br>`.
Recognized inline and fenced code retains its existing literal code encoding.

Pass this output directly to rich insertion without first unescaping it.
The shared converter decodes character references once, restoring literal
characters without treating them as new markup. This also works inside the
supported HTML table subset. Inline images use `<img src="..." alt="...">`
with escaped attributes; heading IDs and link URLs are escaped independently.
Image titles remain display metadata and are not copied into native alt text.

Search and edit anchors use the original visible document text, not its
serialized character references. For example, find `**stars**`, not
`&#42;&#42;stars&#42;&#42;`. Source maps and UTF-16 ranges always refer to native
Google Docs text. `rich=False` inserts the serialized response literally and
therefore does not decode these references.

## Tables

Markdown tables create native rows and cells in all three insertion tools.

The optional MCP parameter `table_borders` defaults to `true`: every new table
has solid black 1 pt borders. Set `table_borders=false` to hide all outer and
internal borders (0 pt). It applies to every Markdown/HTML table in that call;
existing tables and literal `rich=False` insertions are unaffected. Ordinary
Markdown table syntax has no border visibility setting; pipe and separator
characters describe structure, not border appearance.

```python
docs_append(doc_id="...", text="| A | B |\n| --- | --- |\n| C | D |",
            table_borders=False)
```

```markdown
| Name | Quantity | Notes |
| :--- | ---: | :---: |
| **Apples** | 3 | [details](https://example.com) |
| Pears | 2 | |
```

The separator row is syntax, not data. Header cells are bold. Empty cells remain
empty. Left, center and right column alignment is applied to every cell; omitted
alignment uses the native default. Supported inline emphasis, links,
strikethrough, inline code and images also work inside cells. UTF-16 cell
positions are read from the newly created table before filling it.

Simple rectangular HTML tables (`table`, `thead`/`tbody`, `tr`, `th`/`td`) use
the same conversion. Cells can declare `align="left|center|right"` or a single
`style="text-align: ..."`. Merged cells, nested tables, tables inside lists,
captions/column/footer groups, and block content inside cells (including lists,
code blocks and multiple paragraphs) are rejected before
writes. Arbitrary table styling and widths are not preserved.

Use `<br>`, `<br/>` or `<br />` inside a Markdown or HTML table cell to insert
a line break, for example `| First line<br>Second line | Value |`. Leading,
trailing and consecutive breaks are preserved as native soft line breaks in
the same cell paragraph. Formatting and links on either side keep their own
ranges. Receipts show these breaks as ordinary newlines. Raw source newlines
inside HTML cell text remain unsupported; use explicit `br` tags.

Table insertion requires several API batches: create the native structure,
read cell positions, then populate cells. Each write requires the previous
revision; concurrent edits stop the operation. The whole edit is **not atomic**:
a later API failure can leave earlier text or an empty/partly filled table.
The error instructs the agent to read the document before retrying. Existing
paragraphs are retained, and table boundaries may add blank separator paragraphs.
Receipts concatenate native cell paragraph text in row/cell order, including
cell newlines, without Markdown pipes or table structural indices.

## Code insertion

Inline code (backticks or HTML `code`) and code blocks (backtick/tilde fences,
indented Markdown code, or HTML `pre`) use the native **Roboto Mono** font in
all three insertion tools by default. Inline code is formatted only on its code
span and defaults to green **#188038**, matching Google Docs' backtick recognition,
and can combine with outer emphasis or a hyperlink. Markdown code-span whitespace
follows CommonMark normalization, including turning a source newline into a
space.

Code blocks become ordinary Google Docs paragraphs with a monospace text range,
not an editor-specific code-block object. Block line breaks, blank lines, tabs,
indentation and trailing spaces are preserved after Markdown removes the fence
or indentation syntax. One terminal newline is represented by the surrounding
paragraph boundary. Neighbouring prose stays separate and does not inherit the
code font. Code contents are literal: Markdown-looking text and escaped HTML
inside a fence are not interpreted again. A declared fence language (for example,
`python`, `json`, `bash` or `javascript`) selects a Pygments lexer and syntax
highlighting. HTML `<pre><code class="language-python">...</code></pre>` uses
the same mechanism. Blocks without a language or with an unknown language stay
plain monospace; no language guessing is performed. A lexer that transforms the
source text also falls back to plain monospace to preserve exact content.

The selected Pygments theme supplies foreground colors, bold, italic and
underline. Theme backgrounds are disabled by default. When enabled, the base
background fills the full width of every code paragraph, including blank lines,
using native paragraph shading. Token-specific backgrounds remain text styles.
Enable backgrounds when choosing a dark theme with light text. Adjacent prose is
unaffected; paragraph fills are applied after insertion to prevent inheritance.
No custom font size or native language property is written. A versioned named
range stores each inserted block's language for later reads.

Inline code works in supported list-item paragraphs. Code blocks inside
list items return `INVALID_ARGUMENT` before writing; list-item block semantics
remain outside the supported subset. `rich=False` preserves code markup
literally. Receipts count the final literal text and paragraph breaks, not fence
delimiters or language labels.

## Reading code

`docs_read` returns recognized inline code as backtick spans and blocks as fenced
Markdown. Inside recognized code, bold, italic, links, colors, and other visual
formatting are ignored: the result contains literal source rather than HTML
style wrappers. Blocks preserve indentation, tabs, blank lines, trailing spaces,
and Unicode. Delimiters grow when the source contains backticks. Inline code
follows CommonMark code-span whitespace rules; line breaks normalize to spaces
and arbitrary soft line breaks are not reconstructed as inline code.

Inline recognition is enabled by default and requires both the configured code
font and inline color. Adjacent matching text runs are combined, regardless of
differences in emphasis or other styles. Recognition stops at paragraph and
non-text element boundaries. Override the font/color lists, choose `font`,
`color`, or `both`, or disable recognition using the [configuration settings](configuration.md). A null list
follows the corresponding insertion setting; an empty list matches nothing.
Font matching is case-insensitive; colors are compared as rounded 8-bit RGB.
Only explicitly returned text-run formatting is recognized; inherited fonts
that the API omits can produce false negatives.

Newly inserted code blocks carry `gdocs-scope-mcp:code:v1:` named ranges storing
the declared language. Reads validate that a marker covers contiguous, complete
text-only normal paragraphs, including any trailing blank lines. Valid markers
take precedence over heuristics and work across server restarts and independent
processes. Malformed, split, overlapping, or incomplete markers fall back to
ordinary rendering; their covered paragraphs are excluded from block heuristics.
Markers are document metadata visible to collaborators and API clients, not
visible text. They are not automatically recreated when copying plain text.
Copying the returned Markdown through rich insertion creates fresh markers.

Set `code_block_named_ranges=false` to stop creating and reading code markers.
Existing ranges remain in the document but are ignored, including malformed
ranges that would otherwise exclude content from heuristics. Only enabled
formatting/native-block heuristics are used, without retaining a language.
This switch applies only to code metadata; comment-anchor named ranges are
unaffected. It is enabled by default.

Google can shrink or split named ranges during editing. In particular, replacing
text at a block boundary can invalidate its marker; a stale range is never
silently expanded to include neighboring prose. Deleting or clearing a block
does not leave a valid code reference. This is not a guarantee of lossless code
semantics after arbitrary manual edits. The published Docs API has no explicit
code-block/language field; blocks created in the Google Docs UI are recognized
through their exposed formatting, not a presumed native type.

**Unmarked block detection is also enabled by default.** It requires all of:

- Normal text-only paragraphs without headings or list bullets.
- Every nonempty text run uses an allowed code font (default: `code_font_family`).
- Explicit paragraph line spacing matches `read_code_block_line_spacing`
  (default `1.0`, represented by the API as `100` percent).
- Consecutive paragraphs have matching line spacing and paragraph shading,
  including consistently absent shading.
- At least `read_code_block_min_lines` paragraphs remain after trimming blank
  edges (default `2`). Internal blank lines count and are preserved when their
  paragraph spacing and shading match.

Set `read_code_block_require_background=true` to additionally require a paragraph
background. Text colors and emphasis may vary because syntax highlighting uses
them. Detection stops at incompatible formatting, structural gaps, or table-cell
boundaries. Unmarked blocks never get a guessed language. Ordinary prose with
the same formatting can be misclassified; disable `read_code_block_heuristic`
or tighten the font, spacing, background, and minimum-line settings as needed.
Neither recognition mechanism writes to the document or uses a local database.

`read_native_code_blocks` separately controls recognition of UI-created Google
Docs code blocks and defaults to `true`, independently of the generic block
heuristic. When disabled, recognized native blocks use ordinary paragraph
rendering, without fenced blocks or inline-code inference. Service boundary
runs are omitted from display; source coordinates remain unchanged. A live
check with both None and Python selected in the UI
returned paired U+E907 delimiters as separate text runs, with code-font text
between them, but no API language, line-spacing, or shading field. This rule
requires both boundary runs and contiguous normal code-font paragraphs; it
does not use spacing, background, or minimum-line checks. The service delimiters
are omitted from rendered code; source coordinates remain unchanged. A lone
delimiter, missing end, intervening heading, object, or incompatible font is
insufficient. This is observed, undocumented behavior and may change. A
normalized capture is covered by offline tests. The UI-selected language is not
inferred from colors or delimiter text.

**Native code-block creation is not supported by the public Docs API.** The
published request schema provides no native block creation or language-setting
operation. Sending the observed U+E907 boundaries through `insertText` does not
create a block: Google strips characters in U+E000–U+F8FF from inserted text.
An opt-in live capability probe verifies that behavior. Rich code insertion
therefore creates formatted ordinary paragraphs with optional named-range
metadata, rather than claiming to create a native widget. In the Google Docs
UI, the native widget's language is selected from its dropdown. A Markdown
fence language controls this MCP's Pygments highlighting and optional metadata;
it does not select a native widget language. See Google's
[InsertTextRequest reference](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request#InsertTextRequest).

Named-range behavior and limits are documented in Google's
[named ranges guide](https://developers.google.com/workspace/docs/api/how-tos/named-ranges).

## Native smart chips

`docs_read` preserves people/name chips, resource chips, dates and dropdowns
inline as HTML spans. The span's contents are the visible label; attributes
identify the native entity and the properties needed to create a copy:

```html
<span data-mcp-entity="person" data-mcp-id="kix.person"
      data-mcp-email="alice@example.com">Alice</span>
<span data-mcp-entity="richLink" data-mcp-id="kix.resource"
      data-mcp-uri="https://docs.google.com/document/d/DOCUMENT_ID/edit">Report</span>
<span data-mcp-entity="dateElement" data-mcp-id="kix.date"
      data-mcp-timestamp="2026-10-26T12:00:00Z"
      data-mcp-date-format="DATE_FORMAT_ISO8601">2026-10-26</span>
<span data-mcp-entity="dropdown" data-mcp-id="kix.instance"
      data-mcp-definition-id="kix.definition"
      data-mcp-option-id="dropdownItem.ready">Ready</span>
```

Labels and attribute values are HTML-escaped. A native resource chip is distinct
from a normal Markdown hyperlink. Changing a span's visible label does not edit
the native entity: Google resolves the person's name, resource title, date
display, or selected dropdown option. Ordinary spans without `data-mcp-entity`
keep their existing text conversion behavior.

All three rich insertion tools recognize these spans, including inline chips
in supported list paragraphs and table cells. They insert **new native
instances**, preserving the person/resource reference, timestamp/display
configuration, or dropdown definition/selection. `data-mcp-id` is a read/edit
reference and is never reused as a newly inserted instance's ID. It may be
omitted when authoring a new span. `rich=False` keeps the HTML literal.

Dates also preserve `data-mcp-time-format`, `data-mcp-time-zone` and
`data-mcp-locale` when supplied by the API. New dates default to ISO date format
without a displayed time. Imported custom date formats cannot be recreated by
this converter and fail explicitly. Resource URI support and access follow
Google's native `insertRichLink` restrictions; a generic web link is not
automatically a supported resource chip. Native chip styling is not a full
formatting round trip; the API metadata remains available for inspection.

The existing read/insertion tools operate on the first document tab. To copy
a dropdown, its definition and selected option must exist in that destination
tab. Cross-document definitions are not copied automatically. All definitions
and options are validated before any document writes or local-image uploads;
unsupported kinds and malformed required attributes fail without falling back
to ordinary text.

Insertion receipts expose `inserted_entity_count` separately from
`inserted_image_count`. Each native chip occupies one UTF-16 source slot;
previews and `inserted_char_count` use one U+FFFC object placeholder per chip,
rather than Google's resolved display-label length. Read back with `docs_read`
for the actual labels and new native IDs.

### docs_get_entity

```text
docs_get_entity(doc_id, entity_id, tab_id=None)
```

Read one chip by `data-mcp-id`. Returns `kind`, `entity_id`, `tab_id`, document
and revision IDs, original UTF-16 `start_index`/`end_index`, and complete native
`metadata`, including styles and suggestion metadata. For dropdowns,
`dropdown_definition` includes the shared definition, available option IDs,
labels and colors. Other kinds return null for that field. No duplicate entity
inventory is added to every `docs_read` response. Defaults to the first tab;
an explicit `tab_id` can select a nested tab. Missing IDs/tabs fail explicitly.
Ranges are diagnostic and must not be reused as editing handles.

### docs_create_dropdown_definition

```text
docs_create_dropdown_definition(doc_id, title, options, tab_id=None)
```

Create a shared native definition with 2-50 options. Each typed option has
`display_value`, and optional `foreground_color`/`background_color` in
`#RRGGBB` form. Returns `dropdown_definition` with generated definition and
option IDs. Creating a definition does not insert a chip or modify existing
definitions. Insert a span referencing the returned IDs with an insertion tool.

### docs_select_dropdown

```text
docs_select_dropdown(doc_id, entity_id, option_id, tab_id=None, expected_option_id=None)
```

Change the selected option of **one instance**, without modifying its shared
definition or sibling instances. `expected_option_id` optionally rejects a
selection that changed since the agent read it. Use `docs_get_entity` to discover
option IDs. Creating definitions and selecting options support explicit tab
IDs; both default to the first tab.

The two dedicated dropdown tools use `requiredRevisionId` without automatic
retries. Chip insertion through append/before/after follows the configured
`write_revision_mode` and its documented strict exceptions. Do not blindly
repeat a write after an unknown transport outcome. Definition editing/deletion,
chip deletion, and in-place person/resource/date updates are not currently
exposed. Shared definitions are not changed implicitly while selecting/copying
a chip.

Text replacement and comment anchors continue to use actual text-run positions,
not chip labels. Text edits before/after a chip retain its identity; ranges
crossing a chip fail explicitly. Paragraph deletion refuses paragraphs containing
native chips. Native replace-all does not turn immutable chip labels into text.

API references: [paragraph entities](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents#ParagraphElement),
[native insertion requests](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request),
and [dropdown definitions and instances](https://developers.google.com/workspace/docs/api/how-tos/dropdowns).

## Native lists

Markdown unordered lists (`-`, `*`, `+`) and ordered lists starting at 1 create
native Google Docs lists with separate item paragraphs. Nested lists of the
same kind retain their nesting; supported inline styles and links are preserved.
Soft-wrapped Markdown lines stay within the same item paragraph.
Unordered lists use disc/circle/square glyphs; ordered lists use decimal/alpha/
roman numbering according to nesting level. Neighbouring prose stays outside
the list. Previews and character counts describe the final text without the
temporary tabs used to set nesting.

Items may contain several ordinary paragraphs, including continuations after
homogeneous nested lists:

```markdown
1. First paragraph.

   Second paragraph of the same item, with **emphasis**.

   1. Nested item.

   Parent continuation after the nested list.

2. Second item.
```

Only the first paragraph of each logical item has a native marker. Continuation
paragraphs align with its text (36 pt per nesting level); they do not increment
numbering. Tight lists use zero paragraph spacing; loose lists use 6 pt above
each paragraph and zero below, without inserting empty items. This applies to
all three rich insertion tools. Reads preserve text and order, but indentation
alone cannot reconstruct the original Markdown item membership losslessly.

Mixed ordered/unordered nesting, custom starting numbers, empty items, and
arbitrary block content inside items return `INVALID_ARGUMENT` before writing.
Use separate homogeneous lists, ordinary paragraphs, or choose `rich=False`
to insert the original syntax literally.

## Images

Markdown images (`![label](https://example.com/image.png "title")`) and HTML
`<img src="https://example.com/image.png" alt="label" title="title">` create
native inline images in all three insertion tools, including image-only inputs,
multiple images, and images among formatted text or in supported list items.
Their positions occupy one UTF-16 index each; subsequent text and style ranges
account for those indices.

By default, use absolute public HTTP(S) URLs of at most 2048 UTF-8 bytes. Google
fetches and stores the image at insertion time. Google requires PNG, JPEG or GIF,
less than 50 MB and at most 25
megapixels. Sources without filename extensions can work if Google accepts the
response. Relative paths, data URLs, missing sources, credential-bearing
URLs and responsive `picture`/`srcset`/`sizes` fail with `INVALID_ARGUMENT`
before writing. Local paths and file URLs require the explicit opt-in below.
Google can reject inaccessible URLs or invalid image contents;
all insertions and formatting are sent in one atomic batch, with no success
receipt on rejection.

When neither dimension is supplied, images fill the available paragraph content
width in single-column, paged body paragraphs and list items. The server uses
page orientation, effective section margins, inherited paragraph styles and
indentation, and the list nesting/formatting applied by the insertion. It sends
only the width; Google computes the height while preserving the aspect ratio.
This also applies to local images uploaded through temporary Drive files.
Sizing happens at insertion time; later layout changes do not resize the image.
The calculation uses the paragraph width, not remaining space on an occupied
visual line. First-line indentation is also respected when it narrows that
width.

Table cells, multi-column sections, headers, footers, footnotes and pageless
documents are outside automatic sizing scope. If layout cannot be resolved
reliably, the request omits the size and Google uses its resolution-based
default. Body images before or after a table can still be sized automatically;
images inside its cells retain Google's default.

HTML `width` and
`height` accept positive pixel numbers, optionally suffixed `px` (96 px = 72 pt).
Supplying either dimension disables automatic sizing for that image.
One dimension preserves the aspect ratio; two specify a bounding box that
Google fits while preserving that ratio. CSS image styling and non-pixel sizes
are rejected; use the attributes instead. `alt` and `title` are accepted but
are not written as native object metadata or visible text: `insertInlineImage`
has no fields for them. Image hyperlinks and other image attributes are not
preserved. This is not a lossless HTML/image-metadata round trip.

Image receipts add `inserted_image_count` (zero in literal mode). Previews use
one U+FFFC object-replacement character per inserted native image, and
`inserted_char_count` includes those placeholders and paragraph breaks. The
placeholder is a receipt representation; it is never submitted as text.
`rich=False` keeps image markup literal and inserts no native objects.

### Local images through temporary Google Drive files

Set `upload_local_images=True` explicitly on any of the three insertion tools
to accept absolute local paths or `file:///` URLs in Markdown and HTML:

```python
docs_append(
    doc_id="...",
    text="Before ![Chart](file:///home/me/chart.png) after",
    upload_local_images=True,
)
docs_insert_before(
    doc_id="...", anchor="Results",
    text='<img src="/home/me/chart.png" width="320">',
    upload_local_images=True,
)
```

Paths refer to the machine running the MCP server, not necessarily the machine
running its client. Paths with spaces can use a file URL (URL-escaped) or a
Markdown angle-bracket destination: `![Chart](</home/me/my chart.png>)`.
URL escapes are decoded once; use `%25` for a literal percent sign in a source
path. Relative paths, remote file hosts, file URL queries/fragments and base64
data URLs remain unsupported. With `rich=False`, the upload flag is ignored:
markup remains literal and no files are uploaded.

**Enabling this flag authorizes temporary upload and anyone-with-link access.**
The server performs these steps:

1. Read the local images and validate the whole insertion before creating Drive
   files. Supported local data is PNG, JPEG or GIF, nonempty and smaller than
   50,000,000 bytes. Google performs the final image-content/dimension checks.
2. Upload each distinct local file to **My Drive root**, named
   `gdocs-scope-mcp-tmp-<random UUID>.png` (or `.jpg`/`.gif`). The original local
   filename is not used. Repeated references in one call share one upload.
3. Grant only that new file `type=anyone`, `role=reader`,
   `allowFileDiscovery=false`. It is readable without signing in by anyone
   possessing its link while this permission exists. This is not private
   storage or a hidden file. Existing Drive files and their sharing settings
   are not modified.
4. Use Drive's `webContentLink` in the existing Docs `insertInlineImage`
   requests. Text, images and styles are applied in **one atomic Docs batch**.
   Google stores its own embedded copy; the temporary Drive file is not a
   lasting dependency of the document. Its source URL remains in image metadata.
5. Attempt to **permanently delete** the temporary files immediately after the
   Docs request, on success or failure. The local originals are preserved.

This requires Google Drive API write access (`drive.file` or `drive`); a
Docs-only or Drive-read-only token is insufficient. No Apps Script setup is
needed. Workspace policies that prohibit anyone-with-link sharing make this
route fail; the tool does not bypass those restrictions or switch hosts.

Drive uploads/deletions and the Docs batch are separate operations. If source
deletion fails, the server attempts to revoke the public link permission. A
successful insertion still returns `ok=true`, with residual file IDs in
`temporary_image_cleanup_pending`; **do not repeat the insertion**. Remove
those Drive files manually. This list is normally empty. If the insertion
itself fails, cleanup errors and residual IDs are recorded in server stderr.

Cleanup is best effort: a killed server, network outage, or uncertain upload
response can leave an orphan. These files/permissions have **no automatic TTL**.
Find residual files by the `gdocs-scope-mcp-tmp-` name prefix and delete them
(or revoke sharing). A folder could organize these files, but would not hide
them. Drive's hidden `appDataFolder` cannot share its files, so it cannot serve
as the staging location. See [application data restrictions](https://developers.google.com/workspace/drive/api/guides/appdata).

See [development live verification](development.md#live-verification) for bounded image and table regressions.
