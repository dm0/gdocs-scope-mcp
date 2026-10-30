# Native list read-to-write validation

Issue: [#51](https://github.com/dm0/gdocs-scope-mcp/issues/51).

The former renderer emitted one space per nesting level before `-` or `1.`.
Permanent native fixtures reproduced three structural failures through the
actual supported Markdown parser: nested items flattened to level 0, adjacent
independent lists merged, and following prose joined the last list item.

## Representation

Contiguous native list paragraphs now form explicit nested HTML `ol`/`ul`/`li`
groups within the returned Markdown. Native list ID, native nesting level and
the level's marker kind determine group transitions. A changed ID at the same
depth starts a separate list; returning from descendants resumes the enclosing
frame. Prose, headings, tables and table-cell boundaries close the frames.

Fragments are cached only in excluded presentation state. Native paragraphs,
definitions, source runs and UTF-16 edit coordinates remain unchanged. Inline
code uses HTML `code` inside a list rather than Markdown backticks that an HTML
block would treat as literal text. Other inline styles and literals reuse the
existing escaped HTML rendering.

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

On 2026-10-30, ordered and unordered live round trips passed, as did the mixed
insertion regression from #47. Both round-trip fixtures confirmed exact body
restoration and subprocess cleanup. Reports and separate stderr logs are under
`/tmp/gdocs-scope-mcp-table-probe-list-read-roundtrip-{ordered,unordered}.*`;
no warnings, errors or tracebacks were found in those server logs.

Final checks on 2026-10-30:

- Complete offline suite: 1916 passed, 104 opt-in skips.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
- Wheel and sdist included 90 identical source modules. Both passed isolated
  CLI/auth entry-point checks and discovery of all 32 MCP tools.
- The frozen behavior snapshot remains unchanged. The MCP catalog fingerprint
  changes intentionally to describe the new list-read representation and limits.
