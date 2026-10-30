# Native list read-to-write validation

Issue: [#51](https://github.com/dm0/gdocs-scope-mcp/issues/51).

The former renderer emitted one space per nesting level before `-` or `1.`.
Permanent native fixtures reproduced three structural failures through the
actual supported Markdown parser: nested items flattened to level 0, adjacent
independent lists merged, and following prose joined the last list item.

## Representation

Native list paragraphs use Markdown with four-space nesting when their
available ancestors and group transitions are unambiguous. A contiguous run
falls back to nested HTML `ol`/`ul`/`li` if Markdown could merge independent
groups of the same kind, or ancestor levels are incomplete. Native blank
paragraphs cannot silently merge neighboring groups. Lists in HTML table cells
always use HTML because Markdown syntax inside a raw HTML table is not parsed
as lists. Raw HTML blocks before a Markdown list receive a separating blank
line. Native list ID, nesting level and marker kind determine group transitions;
returning from descendants resumes the enclosing frame. Prose, headings, tables
and table-cell boundaries close the frames. Only affected runs use HTML.

Fragments are cached only in excluded presentation state. Native paragraphs,
definitions, source runs and UTF-16 edit coordinates remain unchanged. Inline
code uses ordinary code spans in Markdown lists and HTML `code` inside HTML
lists. Other inline styles and literals reuse escaped inline HTML rendering.

Remaining limits are explicit in [rich content](../rich-content.md#native-lists):
unmarked continuation membership is not inferred, missing ancestor levels are
normalized without synthetic items, and native IDs/custom numbering/visual
spacing are not losslessly copied. This change does not add list support to
new table cells.

## Permanent verification

`tests/test_list_read_roundtrip.py` exercises native model and section reads,
the supported Markdown/HTML parser, and the native request compiler against an
independent UTF-16 replay observer. It covers both marker kinds, three levels,
sibling transitions, adjacent independent groups and kind changes, styles,
links, non-BMP characters, inline code, soft breaks, headings, table-cell
isolation, orphan fragments and unchanged source targeting.

`tests/test_live_list_read_roundtrip.py` launches two isolated STDIO servers
from the assigned worktree against the explicitly authorized development Doc.
It inserts two adjacent lists, reads only their heading section through the
other process, and reinserts the returned markup. Native readback must match
the original item order, absolute depths, marker kinds and normalized native
identity groups. Inline styles and links must survive. A heading-scoped emoji
replacement in the copy must use the expected native UTF-16 index and leave
the original unchanged.

On 2026-10-30, ordered and unordered live round trips passed for both Markdown
and HTML fallback (four scenarios). The earlier mixed insertion regression
from #47 also passed. Fixtures confirmed exact body restoration and subprocess
cleanup. Reports and separate stderr logs are under
`/tmp/gdocs-scope-mcp-table-probe-list-read-roundtrip-{ordered,unordered}-{markdown,html}.*`.

## Token measurements

Measured on 2026-10-30 with `tiktoken==0.12.0`, encoding `o200k_base`. These are
estimates for this encoding, not exact counts for the current agent model.
Only raw list fragments are counted: no MCP/JSON envelope, instructions,
surrounding document or terminal paragraph separator.
The synthetic inputs are English-only; token counts depend on language.

"Short" and "long" describe the text length of each item, not item count:

- Short: **24 Unicode characters per item**, using the synthetic text
  `Check the input document`.
- Long: **787 characters per item**, using a synthetic English paragraph
  repeated four times. The exact paragraph is in the measurement script.
- Nested: eight short items at levels `0, 1, 2, 1, 0, 1, 2, 0`.

All cases are one ordered native list. Character totals below include markers,
indentation and inter-item line breaks in Markdown, or tags in compact HTML.

| Case | Items | Characters/item | Markdown chars | HTML chars | Markdown tokens | HTML tokens | HTML increase | Selective reader tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Short | 10 | 24 | 279 | 339 | 69 | 95 | +37.7% | 69 |
| Long | 10 | 787 | 7909 | 7969 | 1349 | 1365 | +1.2% | 1349 |
| Nested short | 8 | 24 | 251 | 309 | 65 | 93 | +43.1% | 65 |

The compact HTML reference represents unconditional HTML rendering. With
selective rendering, these unambiguous examples use Markdown and incur no
additional list-format tokens compared with the Markdown reference. Ambiguous
groups still pay the HTML overhead to retain their boundaries. Relative cost
depends on item length, nesting and the rest of the document; these synthetic
examples are not a representative document corpus.

Reproduce from the repository root:

```bash
uv run --locked --with tiktoken==0.12.0 python research/measure_list_tokens.py
```

The script renders a synthetic native document through the current reader,
compares it with Markdown and compact HTML references, and prints character
and token counts as JSON. The optional tokenizer uses a temporary uv environment;
project dependencies are unchanged. Research scripts live under `research/`,
not under `docs/`.

Final selective-rendering checks on 2026-10-30:

- Complete offline suite: 1928 passed, 106 opt-in skips.
- Four native read-to-write scenarios (both marker kinds, Markdown and HTML
  fallback) and two mixed-list append regressions passed with body restoration
  and subprocess cleanup. Server stderr contained no warnings or errors.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
- Wheel and sdist included 90 identical source modules. Both passed isolated
  CLI/auth entry-point checks and discovery of all 32 MCP tools.
- The sdist includes `research/measure_list_tokens.py` and its usage README.
  No scripts remain under `docs/`.
- The frozen behavior snapshot remains unchanged. The MCP catalog fingerprint
  changes intentionally to describe the new list-read representation and limits.
