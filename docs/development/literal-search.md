# Literal document search (#50)

## Query policy

`docs_list.query` is search text, never a raw Drive query. The backend wraps
nonempty input in a single-quoted `fullText contains` value, escaping
backslashes first and apostrophes second. Double quotes remain part of the
value so Drive's documented phrase-search behavior continues to work. Empty
input omits the text clause; whitespace is preserved.

The fixed Google Docs MIME-type and `trashed=false` filters are unchanged.
Shared-drive settings, ordering, page-size limits and continuation tokens are
unchanged. No new search mode or network retry behavior is introduced.

References checked on 2026-10-30:

- [Drive search examples and escaping](https://developers.google.com/workspace/drive/api/guides/search-files)
- [Search terms and full-text matching](https://developers.google.com/workspace/drive/api/guides/ref-search-terms)

## Verification

Backend and serialized MCP tests cover ordinary text, empty input, whitespace,
double-quoted phrases, apostrophes, backslashes (including trailing and adjacent
to an apostrophe), Unicode and expression-like input. Pagination tests use
escaped text on both pages with and without a shared drive.

On 2026-10-30, `tests/test_live_document_search.py` sent three read-only queries
through one isolated STDIO server from the assigned worktree. Each contained a
unique synthetic marker plus either an apostrophe and backslash, a quoted
phrase, or expression-like text. All three were accepted and returned zero
documents. No document content was read or modified. These checks verify API
acceptance; they do not measure search recall or indexing behavior.

The fixture verified the server source fingerprint and package path and
confirmed subprocess cleanup. Stderr contained successful calls without
warnings, errors or tracebacks. The report and stderr are available locally at
`/tmp/gdocs-scope-mcp-literal-search.json` and
`/tmp/gdocs-scope-mcp-literal-search.log`.

Reproduce the bounded live check from the repository root:

```bash
GDOCS_SCOPE_MCP_LIVE_SEARCH=1 uv run --locked pytest -q tests/test_live_document_search.py
```

This opt-in test searches for newly generated synthetic text and fetches at
most one metadata result per query. It does not create a test document.

Final local checks on 2026-10-30:

- Targeted backend, MCP, environment and frozen-contract tests: 307 passed.
- Complete offline suite with external sockets blocked: 1949 passed,
  106 opt-in skips. The network-blocking test emitted its expected warning.
- Global Ruff, explicit changed-test lint and `git diff --check` passed.
- Wheel and sdist contain 90 identical source modules. Both isolated installs
  passed CLI/auth checks and discovery of all 32 MCP tools.

Full logs are under `/tmp/gdocs-50-{offline,live,build,artifacts}.log`.
