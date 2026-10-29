# Literal reader content verification

[Implementation notes](implementation-notes.md) · [Rich content](../rich-content.md#literal-reader-content)

## Contract

Issue #48 separates literal native characters from generated Markdown/HTML.
HTML character references protect text, including punctuation split across
independently styled runs. Quoted HTML attributes protect link URLs, heading
IDs, image labels, and image URLs. Native soft breaks use `br`; recognized
inline and fenced code retains its existing encoding. Native source maps and
write coordinates do not use the escaped display representation.

`tests/test_literal_rendering.py` checks literal tags, entities, Markdown
punctuation, URLs, indentation, soft breaks, adjacent runs, UTF-16 ranges,
formatting, heading metadata, image attributes, and HTML table cells. The
refactor behavior fixture deliberately updates only its rendered text;
conversion requests, receipts, failures, and the frozen MCP catalog are
unchanged.

## Verification on 2026-10-29

- Complete offline suite: 1756 passed, 92 skipped.
- Global Ruff and `git diff --check`: passed.
- `test_live_literal_read_copy`: passed through two isolated STDIO processes
  against the explicitly authorized development document. It seeded native
  text, read through `docs_read`, copied through `docs_append`, and compared
  native characters, heading style, bold, italic, links, and a table cell.
  A subsequent literal-text replacement verified native coordinate targeting.
- Both temporary tabs were deleted, all pre-existing tabs were checked for
  unchanged content/structure/styles, and both subprocesses were reaped.
- Existing `test_live_code_reads` scenarios for append, insert-before, and
  insert-after: 3 passed. These fixtures intentionally retain their test content
  and confirm code reads after starting another isolated server process.
- Wheel and sdist included all 90 Python source modules. An isolated installed
  wheel exposed the same 32-tool catalog as the worktree, its server entry
  point started successfully, and its authorization CLI help worked.

The source fingerprint verified in the live and installed-wheel processes was
`a0c36ccfb92cce5b492f770580ad2c74d2b4915ba4b79f60a85272f6f2d15258`.
The user's configured MCP server was not restarted or reconfigured.

## Reproduction and logs

```bash
uv run --locked pytest -q tests/test_literal_rendering.py
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=AUTHORIZED_DOC_ID uv run --locked pytest -q tests/test_live_literal_rendering.py
GDOCS_SCOPE_MCP_LIVE_TEST_DOC=AUTHORIZED_DOC_ID uv run --locked pytest -q tests/test_live_code_reading.py -k live_code_reads
```

The new live probe writes its identity, completion, cleanup, and process-reaping
report to `/tmp/gdocs-scope-mcp-table-probe-literal-rendering.json`; its two
server stderr logs use the same stem with `.0.log` and `.1.log`. Existing code
probe reports/logs use `/tmp/gdocs-scope-mcp-code-docs_*`. Reports are local
development artifacts and are not packaged verification guarantees.
