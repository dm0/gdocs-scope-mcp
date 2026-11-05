# Text colors, highlights and paragraph fills

Call `docs_get_color_palette` once to discover all 80 standard Google Docs
English color names and their HEX values. The result contains eight rows in
editor order: grayscale, base hues, light 3/2/1, dark 1/2/3. No document ID,
credentials or Google request is needed. The mapping was verified against
the live English Google Docs highlight picker on 2026-11-03 using each cell's
accessible label and its swatch RGB style. In particular, `light yellow 1`
is `#FFD966` and `light yellow 2` is `#FFE599`.

Names use Google's palette, not CSS: `green` is `#00FF00`, `orange` is
`#FF9900`, and `gray` is `#CCCCCC`. Names ignore case and extra whitespace.
Custom colors use exactly six hexadecimal digits, `#RRGGBB`. Unknown names,
malformed values and conflicting HTML declarations fail before document writes
or temporary image uploads. The fixed mapping does not depend on document
theme, UI language or server settings. Custom colors have no invented names.

## Reading and rich insertion

Readers emit the same attributes accepted by rich insertion:

```html
<span data-mcp-color="green">Colored text</span>
<span data-mcp-background-color="yellow">Highlighted text</span>
<span data-mcp-color="dark red 1" data-mcp-background-color="#FFF59D">Both</span>
<p data-mcp-background-color="light orange 2">Paragraph fill</p>
<h3 data-mcp-background-color="light blue 2">Heading fill</h3>
```

Text background and highlighting are the same native text property. Paragraph
fill covers the paragraph area and is independent of text highlighting and
table-cell fill. A list paragraph can use `<li><p data-mcp-background-color=...>`.
New table cells may contain one such paragraph; multiple cell paragraphs remain
unsupported. Inline color spans also work in table-cell patches; patches retain
existing paragraph properties. Use `docs_format_paragraph` to change an existing
cell paragraph's fill and `docs_table_format` for the cell's own background.

Nested spans inherit colors; the closest explicit color wins. Colors combine
with supported emphasis and links. Paragraph background does not become text
highlighting. For explicit RGB, CSS `color: #RRGGBB` and
`background-color: #RRGGBB` are also accepted; CSS names are rejected to avoid
ambiguity with Google names. There is no `<mark>` shorthand.

Reads normalize RGB to eight-bit channels and emit a Google name only for an
exact palette match, otherwise uppercase HEX. They do not select the nearest
palette shade. Unset/inherited colors do not acquire guessed theme colors.
Recognized inline/fenced code retains the existing semantic Markdown rendering;
arbitrary code colors are not serialized inside code spans or fences. Disable
the relevant code recognition settings to read those runs as ordinary styled
text. This feature does not provide a full Google Docs formatting round trip.

## Formatting existing content

`docs_format_text` formats only the matched ordinary-text fragment:

```json
{
  "doc_id": "DOCUMENT_ID",
  "anchor_text": "Important warning",
  "foreground_color": "dark red 1",
  "background_color": "yellow"
}
```

`docs_format_paragraph` changes only the fill of the single paragraph containing
the anchor, including headings, list paragraphs and table-cell paragraphs:

```json
{
  "doc_id": "DOCUMENT_ID",
  "anchor_text": "Important warning",
  "background_color": "light orange 2"
}
```

Text formatting requires at least one color property. Omitted/null properties
are preserved. The explicit string `reset` removes the requested direct color;
foreground can then inherit from named styles, while a reset background has no
direct highlight/fill. Reset does not mean white or black. It is available only
in formatting tools, not insertion markup. Other styles and content remain
unchanged. Paragraph formatting preserves other shading properties.

Anchors are literal and case-insensitive, confined to ordinary source text in
one paragraph. They cannot cross images, smart chips or omitted source structure.
An omitted `occurrence` requires a unique text match; a positive integer selects
the 1-based occurrence in document order. There is no implicit format-all.
`heading_id` restricts the search to that heading's subtree. `tab_id` selects a
tab; omitted means the first tab. Returned receipts identify the effective tab,
scope, match count and updated native properties; no edit indices are required.

Both writes use the existing revision policy. Required mode revalidates target
content/styles before bounded replanning. Target mode delegates concurrent merge
behavior to Google without local retries. `expected_revision_id` forces a strict
required precondition and disables retries. Unknown write outcomes are never
automatically replayed. Read the document before deciding to repeat a failed call.
