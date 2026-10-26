# gdocs-scope-mcp

> Hierarchical Google Docs editing for AI agents working with large documents.

`gdocs-scope-mcp` is an independent project based on
[dbuxton/google-docs-mcp](https://github.com/dbuxton/google-docs-mcp).
It builds on the original project's text-anchor editing approach and focuses
on **navigating and editing document sections through their heading hierarchy**.

An agent can inspect a compact outline, read only the sections it needs, and
scope replacements or insertions to a heading and its nested subsections.
This keeps unrelated content out of the agent's context and makes the server
well suited to large Google Docs with structured headings.

Another goal is **more complete formatting support** when reading and editing
documents, including richer Markdown conversion and better preservation of
Google Docs formatting. This is ongoing work: native list and table conversion
are not yet implemented by the write converter.

Typical workflow:

1. Call `docs_get_tree(doc_id)` to discover headings and their IDs.
2. Call `docs_read(doc_id, heading_ids=[...])` to read selected section subtrees.
3. Use `heading_id` with `docs_search_replace`, `docs_insert_before`, or
   `docs_insert_after` to restrict the edit to the chosen subtree.
4. Read that section again to verify the result.

Scoped reads reduce the document content sent to the agent. The server still
fetches the Google Docs document snapshot internally to resolve its structure
and edit positions.

The Python distribution and CLI are named `gdocs-scope-mcp`; the import package
is `gdocs_scope_mcp`. The server requires a Google Cloud OAuth app and runs
standalone over MCP STDIO.

For shell access to document operations, use the FastMCP client CLI against
the server rather than a separate editing interface:

```bash
uv run --locked fastmcp call --command gdocs-scope-mcp \
  --target docs_read --input-json '{"doc_id":"YOUR_DOCUMENT_ID"}' --json
```

Run this from the project checkout. Each invocation launches a separate STDIO
server process and uses the MCP tools' input validation and response contracts.
The former `python -m gdocs_scope_mcp.docs_edit` editing CLI has been removed.

The package version is derived from Git tags by
[setuptools-scm](https://setuptools-scm.readthedocs.io/). A clean checkout at
`v0.3.0` builds as `0.3.0`; commits after that tag and tracked local changes
produce development versions. Build from a Git checkout with its version tags
available, or from a generated source distribution, which preserves the version.
The server reports the version recorded when the package was built or installed;
after changing tags or commits in an editable checkout, run
`uv sync --reinstall-package gdocs-scope-mcp` to refresh it.

### Migrating from google-docs-mcp

Install this repository and update your MCP launch command to `gdocs-scope-mcp`
(or use `python -m gdocs_scope_mcp`). Authenticate with `gdocs-scope-mcp-auth`.
The old `google-docs-mcp` and `google-drive-mcp` CLI aliases are not installed,
so this project can coexist with the original package.

Existing `GOOGLE_DOCS_MCP_*` settings, legacy `GOOGLE_DRIVE_MCP_*` aliases,
and the default token path `~/.google-docs-mcp/token.json` are retained.
Existing credentials can be reused without re-authenticating just for the rename.

Indexing note: when the MCP reads document content before planning index-based edits, it requests `suggestionsViewMode=SUGGESTIONS_INLINE`. That keeps returned indices aligned for later `documents.batchUpdate` calls when the doc contains suggestions.

## MCP result contracts

All 16 tools return structured JSON objects with typed output schemas. The
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
Markdown and HTML images as described below. Batch replacements and comment
anchors use the same source-range
mapping and structural-gap check. Before/after insertion still targets whole
paragraph boundaries; native literal replace-all retains Google's matching.

### Action annotations and edit receipts

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

Deletion is idempotent in effect: repeating it cannot remove more of the
original targets, although a retry can return a not-found error. Resolution
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
writes. Native table creation/conversion remains separate work (#9).
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

## Why

The Google Docs API uses **character indices** for every edit. LLMs are bad at counting characters. Everyone ends up deleting and rewriting entire documents, which destroys version history, comments, and collaborator attribution.

This server uses the same abstraction as code editors: **search by text, not by position**. You describe *what* to change; the server finds *where* it is and handles the index arithmetic.

---

## Quick start

### 1. Run directly from GitHub

```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp gdocs-scope-mcp
```

That command downloads the package, creates an isolated environment, installs dependencies, and runs the `gdocs-scope-mcp` entry point.

No PyPI release is required. `uvx` can execute the tool straight from the GitHub repository.

To pin to a branch, tag, or commit, add a ref to the URL:

```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp@main gdocs-scope-mcp
```

If you prefer a persistent local install instead of `uvx`, use:

```bash
uv tool install git+https://github.com/dm0/gdocs-scope-mcp
# Installs both gdocs-scope-mcp and gdocs-scope-mcp-auth.
```

### 2. Create a Google Cloud OAuth app

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a project (or select an existing one)
3. Enable these APIs (**APIs & Services → Library**):
   - **Google Docs API**
   - **Google Drive API**
   - **Google Apps Script API** *(for inline-anchored comments)*
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth 2.0 Client ID**
6. Application type: **Desktop App**
7. Download the JSON file

### 3. Authenticate

**Normal — browser opens automatically:**
```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --credentials ~/credentials.json
```

**Or use env vars instead of a credentials file:**
```bash
export GOOGLE_DOCS_MCP_CLIENT_ID="your-google-client-id"
export GOOGLE_DOCS_MCP_CLIENT_SECRET="your-google-client-secret"

uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth
```

**Headless / remote server — no browser on device:**
```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --credentials ~/credentials.json --headless
# Prints a URL → open on any device (phone, laptop, etc.)
# Paste the full redirect URL back into the terminal
```

**Already have an auth code:**
```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --credentials ~/credentials.json --code "4/0Afr..."
```

`gdocs-scope-mcp-auth` resolves OAuth client credentials in this order:

1. `--credentials /path/to/credentials.json`
2. `--client-id` and `--client-secret`
3. `GOOGLE_DOCS_MCP_CLIENT_ID` and `GOOGLE_DOCS_MCP_CLIENT_SECRET`

Token is saved to `~/.google-docs-mcp/token.json` by default. Override with `--out /path/to/token.json`.

### 4. Configure your MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dm0/gdocs-scope-mcp", "gdocs-scope-mcp"],
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.google-docs-mcp/token.json"
      }
    }
  }
}
```

**OpenClaw** (gateway config):
```json
{
  "mcp": {
    "servers": {
      "gdocs-scope": {
        "command": "uvx",
        "args": ["--from", "git+https://github.com/dm0/gdocs-scope-mcp", "gdocs-scope-mcp"],
        "env": {
          "GOOGLE_DOCS_MCP_TOKEN": "~/.google-docs-mcp/token.json"
        }
      }
    }
  }
}
```

### Local development

`pyproject.toml` is the source of truth for dependencies, package modules, and
command-line entry points. From the repository directory, install and run with:

```bash
uv sync
uv run gdocs-scope-mcp
```

Alternatively, install an editable checkout with `pip install -e .` in a virtual
environment. Add or update dependencies in `pyproject.toml`.

The Python package lives in `src/gdocs_scope_mcp/`; tests live in `tests/`.
`uv sync` installs the package in editable mode and includes the development
dependencies. Run the tests with:

```bash
uv run pytest
```

For pip-based development, install the editable package and pytest with
`pip install -e . pytest`.

The server can also be started with `uv run -m gdocs_scope_mcp`.
`gdocs-scope-mcp` and `gdocs-scope-mcp-auth` are the installed commands.
Reinstall editable `uv tool` installations under the new package name
so their package paths and command entry points are refreshed.

### Server diagnostics and logging

The read-only `server_info()` tool returns the installed package version,
SHA-256 source fingerprint, process ID, startup time (UTC), package path,
Python executable/version, and FastMCP version. It does not require Google
credentials. The same package version is advertised during MCP initialization.

Identity is captured when the server module loads. Editing source files in an
editable installation does not change a running server's reported fingerprint;
restart it to load those edits. Compare the fingerprint to identify source
changes and the process ID/startup time to identify a new server process.

Tool calls log their name, duration in milliseconds, and success or failure to
stderr. Successful calls use `INFO`; failures use `ERROR` with a machine-readable
code. Internal errors retain a traceback.
Each line includes the process ID; `DEBUG` also logs when a call starts.
Edit responses with `ok: false` also log at `ERROR`, including their failure
code. Cancelled calls use `WARNING`. Arguments and returned document
contents are not included in our tool-call log messages.

Set `GOOGLE_DOCS_MCP_LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`,
or `CRITICAL`. For example:

```bash
GOOGLE_DOCS_MCP_LOG_LEVEL=DEBUG uv run gdocs-scope-mcp
```

For a Codex STDIO connection, add the variable to the server's environment:

```toml
[mcp_servers.gdocs_scope.env]
GOOGLE_DOCS_MCP_TOKEN = "/home/you/.google-docs-mcp/token.json"
GOOGLE_DOCS_MCP_LOG_LEVEL = "INFO"
```

Restart the MCP server after changing its environment. Use `INFO` to observe
successful calls; `WARNING` and higher suppress them. Our package has a separate
logger/handler, so this setting does not turn on verbose third-party logs.
Stdout remains reserved for MCP protocol traffic. Codex captures the server's
stderr in its logs.

**MCP client configuration for a local checkout:**
```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/gdocs-scope-mcp", "gdocs-scope-mcp"],
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.google-docs-mcp/token.json"
      }
    }
  }
}
```

### Optional: Apps Script bridge for bookmark-jump comments

If you want `docs_add_comment(..., bookmark_jump=true)` to append a real
`#bookmark=id...` jump URL into the comment body, set up one persistent Apps
Script bridge project and expose its script ID via an env var.

Required one-time setup:

1. Enable the **Apps Script API** for the Google account at
   <https://script.google.com/home/usersettings>
2. Create a standalone Apps Script project to use as the bridge
3. In that Apps Script project, open **Project Settings** and switch it to the
   **same standard Google Cloud project** as the OAuth client used by
   `gdocs-scope-mcp`
4. In that same Google Cloud project, ensure **Apps Script API** is enabled
5. Set the bridge script ID in the MCP process environment:

```bash
export GOOGLE_DOCS_MCP_APPS_SCRIPT_ID="1C6nchmQRobIwK8ELFe29k-XV2t7mUnhKiSpEKHThXOFHAL6Ahy4_Xju4"
```

Example `uvx` launch with both token + Apps Script bridge:

```bash
GOOGLE_DOCS_MCP_TOKEN="$HOME/.google-docs-mcp/token.json" \
GOOGLE_DOCS_MCP_APPS_SCRIPT_ID="your-apps-script-id" \
uvx --from git+https://github.com/dm0/gdocs-scope-mcp gdocs-scope-mcp
```

If the Apps Script bridge is still using its hidden default project, `scripts.run`
fails even when account-level Apps Script access is enabled.

---

## Tools reference

### Document reading

#### `docs_get_tree(doc_id)`

Return an object with `document_id`, `title`, `revision_id`, and a flat
`sections` array. Each section contains `title`, `id`, `level`, and
`ancestor_ids`; hierarchy is expressed through ancestor IDs rather than nested
section objects. Use the IDs to select section subtrees for reading and
editing; body paragraphs are omitted.

```python
docs_get_tree(doc_id="...")
```

#### `docs_read(doc_id, heading_ids=None)`

Return document content as `sections: [{heading_id, markdown}]`, alongside
`document_id`, `title`, `revision_id`, `selected_headings`,
`unknown_heading_ids`, and `partial`. This replaces the former `subset_md` field;
use each section's `markdown` and explicit `heading_id` instead.
Pass heading IDs from the outline to return only those section subtrees,
including their nested subsections. Omit `heading_ids` to read the whole document.
Heading lines include HTML anchors carrying their structural IDs.

Omitted or null `heading_ids` returns the whole document (`partial=false`,
`selected_headings=null`), including any preamble before the first heading as
an entry with `heading_id=null`. A document without headings has only that
preamble entry; an empty document may have no sections.

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

---

#### `docs_list(query, limit, page_token=None)`
List Google Docs from Drive, optionally filtered by a search query.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | `""` | Search terms (searches title and content) |
| `limit` | int | `20` | Positive per-page maximum; values above 100 are capped |
| `page_token` | string or null | null | Continuation token from the previous page |

Returns `{count, documents, next_page_token, has_more}`.
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

### Document editing

All editing tools use **text anchors**, never character indices. The server finds the text and handles the indices internally.

#### `docs_search_replace(doc_id, find, replace, occurrence=1, heading_id=None, regex=False)`
Find text in a document and replace a specific occurrence.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `find` | string | required | Text to find |
| `replace` | string | required | Replacement text |
| `occurrence` | int | `1` | Which occurrence: `1` = first, `2` = second, `0` = **all** |
| `heading_id` | string or null | `null` | Restrict search to this heading and its nested subsections |
| `regex` | bool | `false` | Treat `find` as a Python regex |

```
# Replace the first occurrence within one section subtree
docs_search_replace(
    doc_id="...", find="Q1 2024", replace="Q2 2024",
    heading_id="heading-id-from-outline",
)

# Replace all occurrences (whole document, literal search only)
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

#### `docs_insert_after(doc_id, anchor, text, heading_id=None, rich=True, upload_local_images=False)`
Insert Markdown or literal text after the paragraph containing `anchor`.
Pass `heading_id` to search only that section subtree; `rich=False` inserts literal text.
Rich heading mapping: `# -> TITLE`, `## -> SUBTITLE`, `### -> HEADING_1`,
and so on. Native list/table conversion is not implemented.

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

---

#### `docs_insert_before(doc_id, anchor, text, heading_id=None, rich=True, upload_local_images=False)`
Insert Markdown or literal text before the paragraph containing `anchor`.
Pass `heading_id` to search only that section subtree; `rich=False` inserts literal text.
Rich heading mapping: `# -> TITLE`, `## -> SUBTITLE`, `### -> HEADING_1`,
and so on. Native list/table conversion is not implemented.

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

#### `docs_delete_paragraph(doc_id, anchor)`
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

#### `docs_append(doc_id, text, rich=True, upload_local_images=False)`
Append Markdown paragraphs or literal text at the end of the document, adding
a paragraph break before the content. With `rich=True`, separate paragraphs
with blank lines; headings, emphasis and native lists use the shared converter.
Native tables are not implemented. Set `rich=False` to preserve text literally.

All three rich insertion tools (`docs_append`, `docs_insert_before`, and
`docs_insert_after`) also accept the reader's HTML for bold (`b`), italic (`i`),
underline (`u`), and paragraph alignment (`p` with `text-align: center`, `right`,
or `justify`). Nested inline styles combine within their text ranges. Heading
ID anchors (`<a id=...></a>`) are omitted from inserted text; new headings use
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
For example, a styled `span` retains its text but loses its styling. Native
tables still have separate insertion limitations. Use `rich=False` to preserve
HTML tags and Markdown literally.

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
No custom font size or native language metadata is written.

Inline code works in supported single-paragraph list items. Code blocks inside
list items return `INVALID_ARGUMENT` before writing; list-item block semantics
remain outside the supported subset. `rich=False` preserves code markup
literally. Receipts count the final literal text and paragraph breaks, not fence
delimiters or language labels. Reads do not reconstruct code fences/backticks
from font metadata, so this does not promise a lossless code round trip.

### Code formatting configuration

An optional JSON config sets code formatting and highlighting. By default, the
server reads `~/.config/gdocs-scope-mcp/config.json`, or
`$XDG_CONFIG_HOME/gdocs-scope-mcp/config.json` when `XDG_CONFIG_HOME` is set.
Select another file with `GOOGLE_DOCS_MCP_CONFIG=/absolute/path/config.json`.
An absent default file is allowed; an explicitly selected file must exist.

```json
{
  "code_font_family": "Roboto Mono",
  "inline_code_color": "#188038",
  "code_block_highlighting": true,
  "code_block_style": "default",
  "code_block_line_spacing": 1.0,
  "code_block_theme_background": false
}
```

All fields are optional; the example shows the built-in defaults. The font
applies to inline code and blocks; `inline_code_color` applies only to inline code.
Set `code_block_highlighting` to `false` to keep language-labelled blocks plain
monospace. `code_block_style` selects a Pygments theme such as `default`,
`friendly` or `monokai`; an unknown theme fails startup validation. Themes can
be previewed in the [Pygments gallery](https://pygments.org/styles/).
`code_block_line_spacing` sets a positive finite line-height multiplier: `1.0`
is single spacing, `1.5` is one-and-a-half spacing. It applies to all code blocks,
including unlabelled/unknown languages and blocks with highlighting disabled;
inline code and surrounding prose are unaffected. Google Docs stores this as
a percentage (`1.0` becomes `100`). `code_block_theme_background` controls both
the theme's base background and token-specific backgrounds; it takes effect only
when syntax highlighting is active for a recognised language.
Font names must be nonempty, and colors must use six-digit RGB hex syntax
(`#RRGGBB`). Choose a font supported by Google Docs; the server validates the
name's syntax but does not query font availability. Unknown JSON fields and
invalid values fail validation, rather than silently falling back to defaults.

Environment variables override individual file settings:

| Environment variable | JSON field | Default |
|---|---|---|
| `GOOGLE_DOCS_MCP_CODE_FONT_FAMILY` | `code_font_family` | `Roboto Mono` |
| `GOOGLE_DOCS_MCP_INLINE_CODE_COLOR` | `inline_code_color` | `#188038` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_HIGHLIGHTING` | `code_block_highlighting` | `true` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE` | `code_block_style` | `default` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_LINE_SPACING` | `code_block_line_spacing` | `1.0` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_THEME_BACKGROUND` | `code_block_theme_background` | `false` |

Precedence is per-call overrides (theme/background only), environment, JSON
file, then built-in defaults. Server settings are
loaded and validated at server startup and cached for that process. Restart
the MCP server after changing the file or environment. This config
currently covers code formatting; existing authentication, Drive and logging
environment variables retain their separate handling. Our config does not
automatically load `.env` files.

`docs_append`, `docs_insert_before` and `docs_insert_after` also accept optional
agent-facing `code_block_style` and `code_block_theme_background` arguments.
The `code_block_style` input schema advertises an `enum` of available themes,
generated from the installed Pygments version when the server starts. Agents
can discover names through MCP tool listing without a separate theme-list call.
Omitting an argument or passing `null` inherits its server setting, including
environment overrides. An explicit `false` disables the background even if the
server default enables it. Each argument can be overridden independently:

```python
docs_append(
    doc_id='...', text='```python\nprint("Hello")\n```',
    code_block_style='monokai', code_block_theme_background=True,
)
```

Overrides apply only to that call and do not change defaults or concurrent
requests, including when a write fails. Themes must be valid Pygments names;
invalid names fail before Google access. Formatting overrides have no effect
with `rich=False`. Highlighting enablement, font, inline color and line spacing
remain server settings; choosing a theme does not enable disabled highlighting
or guess a missing/unknown language.

Set environment overrides in the MCP client's server `env` configuration.
For isolated FastMCP CLI tests, pass them explicitly to the child command:

```bash
uv run --locked fastmcp call \
  --command 'env GOOGLE_DOCS_MCP_CONFIG=/absolute/path/config.json gdocs-scope-mcp' \
  --target server_info --json
```

Setting a variable only on the parent CLI process does not guarantee it reaches
the STDIO server; FastMCP's subprocess environment is filtered.

### Native lists

Markdown unordered lists (`-`, `*`, `+`) and ordered lists starting at 1 create
native Google Docs lists with separate item paragraphs. Nested lists of the
same kind retain their nesting; supported inline styles and links are preserved.
Soft-wrapped Markdown lines stay within the same item paragraph.
Unordered lists use disc/circle/square glyphs; ordered lists use decimal/alpha/
roman numbering according to nesting level. Neighbouring prose stays outside
the list. Previews and character counts describe the final text without the
temporary tabs used to set nesting.

Each item currently requires one nonempty paragraph. Mixed ordered/unordered
nesting, custom starting numbers, empty items, and multi-paragraph items return
`INVALID_ARGUMENT` before writing. Use separate homogeneous lists, simplify
items, or choose `rich=False` to insert the original syntax literally.

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

By default Google chooses the image size from its resolution. HTML `width` and
`height` accept positive pixel numbers, optionally suffixed `px` (96 px = 72 pt).
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

##### Local images through temporary Google Drive files

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

The Drive-to-Docs mechanism and retained embedded copy after source deletion
were verified on the designated development document. Optional live regressions
upload only a generated fixture image, temporarily share it, edit the explicitly
selected test document and remove the source files:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC='your-test-document-id' \
  uv run --locked pytest -q tests/test_live_drive_images.py
```

`GDOCS_SCOPE_MCP_LIVE_TEST_DOC` both enables live tests and selects their target.
Pass the raw Google Doc ID, not a URL. There is no hard-coded target or fallback.
When the variable is unset, live tests are skipped; an empty value, URL or
whitespace fails before accessing Google. The former
`GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES` flag is no longer used.

Choose a disposable document that you are authorized to modify. Test insertions
remain in the document; temporary source images are deleted. Follow any workspace
authorization rules before opting in. Ordinary unit tests remain offline.

```
docs_append(doc_id="...", text="Document last updated: March 2026.")
```

Returns `ok`, `document_id`, `rich`, diagnostic `at_index`, `appended` (a
plain-text preview of up to 200 Unicode code points), `inserted_char_count`
(including added paragraph breaks and image placeholders),
`inserted_image_count`, `temporary_image_cleanup_pending`, and
`preview_truncated`.

---

#### `docs_batch_replace(doc_id, replacements)`
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

#### `docs_create(title, initial_text)`
Create a new Google Doc.

```
docs_create(title="Q2 Board Deck", initial_text="Confidential — not for distribution.")
```

Returns `{id, title, webViewLink}`.

---

### Comments

#### `docs_add_comment(doc_id, comment, anchor_text, occurrence, include_anchor_text, bookmark_jump)`
Add a comment anchored to specific text in the document.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment` | string | required | Comment text |
| `anchor_text` | string | required | Text in the document to attach the comment to |
| `occurrence` | int | `1` | `1` = first occurrence of `anchor_text`; `2`, `3`, etc. select later matches |
| `include_anchor_text` | bool | `true` | Append the matched anchor text into the comment body |
| `bookmark_jump` | bool | `false` | Use the Apps Script bridge to create a bookmark and append a jump URL |

Use a short, distinctive phrase for `anchor_text` — a few words that are unique enough to match exactly one location.

```
docs_add_comment(
  doc_id="...",
  anchor_text="unable to perform the Employee's duties",
  comment="Legal risk: 3-month absence threshold may not satisfy Equality Act 2010 duty to make reasonable adjustments before terminating.",
  bookmark_jump=True
)
```

Returns `ok`, `comment_id`, `anchored_to`, `at_index`, `named_range_id`, and
`comment_content`, plus `bookmark_id`, `bookmark_url`, and `apps_script_id`
(null when bookmarks are disabled).

> **Note:** The current implementation uses Drive comments plus a Docs named range. In the Docs UI these still show as *"Original content deleted"* rather than as proper inline highlights. The comments are fully readable via `docs_read_comments` and the Docs 💬 panel.
>
> When `bookmark_jump=true`, the tool additionally uses Apps Script automation to create a bookmark at the anchor text and appends a `#bookmark=id...` jump URL into the comment body. This requires the `GOOGLE_DOCS_MCP_APPS_SCRIPT_ID` env var and the Apps Script bridge setup documented above.
>
> A probe helper is included for this workstream:
>
> ```bash
> uv run -m gdocs_scope_mcp.appscript_probe inspect-comment-api --doc-id <DOC_ID>
> ```
>
> The probe now creates an API-executable deployment automatically. If account-level Apps Script access is still disabled, it stops with the settings-page message. If execution fails with a permission error, the next blocker is the shared standard Google Cloud project requirement documented at <https://developers.google.com/apps-script/guides/cloud-platform-projects>.

---

#### `docs_read_comments(doc_id, include_resolved=False, page_token=None)`
Read one page of up to 100 comments on a document.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `include_resolved` | bool | `false` | Include resolved/deleted comments |
| `page_token` | string or null | null | Continuation token from the previous page |

Returns `{count, comments, next_page_token, has_more}`.
Each comment has `id`, `content`, `author`,
`anchored` (bool), `named_range_id`, `quoted_text`, `resolved`, `deleted`, and
`created`. The count covers returned items after filtering; additional pages
are not fetched automatically. Continue with `page_token=next_page_token`, keeping
`doc_id` and `include_resolved` unchanged, until the token is null. A page with
no visible comments can still have `has_more=true` because filtering happens
after fetching. Invalid/expired tokens return a structured error with guidance
to restart without a token and deduplicate previously seen items.

```
docs_read_comments(doc_id="...")
```

---

#### `docs_reply_to_comment(doc_id, comment_id, reply)`
Post a reply to an existing comment.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment_id` | string | required | Comment ID (from `docs_read_comments`) |
| `reply` | string | required | Reply text |

```
docs_reply_to_comment(
  doc_id="...",
  comment_id="AAAB1iPyaUY",
  reply="Agreed — adding Carer's Leave clause before we sign."
)
```

Returns `{ok, reply_id, comment_id, content}`.

---

#### `docs_resolve_comment(doc_id, comment_id, reply)`
Resolve (close) a comment using one resolving reply action. Optional closing
text is included in that same request; without text, only the action is sent.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `doc_id` | string | required | Google Doc ID |
| `comment_id` | string | required | Comment ID |
| `reply` | string | `""` | Optional closing text included in the resolving reply |

```
docs_resolve_comment(
  doc_id="...",
  comment_id="AAAB1iPyaUY",
  reply="Fixed in v2 — carer's leave clause added at 15.1."
)
```

Returns `{ok, comment_id, resolved}` with `resolved=true`.

---

#### `docs_delete_comment(doc_id, comment_id)`
Permanently delete a comment.

```
docs_delete_comment(doc_id="...", comment_id="AAAB1iPyaUY")
```

Returns `{ok, comment_id}`.

---

## Typical workflows

### Contract review
```
1. docs_get          — read the document
2. docs_add_comment  — flag issues with anchor_text pointing to specific clauses
3. docs_read_comments — audit what's been flagged
4. docs_search_replace — fix straightforward issues directly
5. docs_resolve_comment — close comments as they're addressed
```

### Bulk document update
```
1. docs_list         — find all relevant documents
2. docs_batch_replace — apply changes atomically (e.g. rebrand, date update)
3. docs_get          — verify the result
```

### Collaborative review
```
1. docs_add_comment  — add review notes
2. docs_reply_to_comment — respond to collaborator comments
3. docs_resolve_comment  — close resolved threads
```

---

## Auth environment variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_DOCS_MCP_TOKEN` | Path to token file (preferred for standalone use) |
| `GOOGLE_DOCS_MCP_CLIENT_ID` | Optional OAuth client ID override |
| `GOOGLE_DOCS_MCP_CLIENT_SECRET` | Optional OAuth client secret override |
| `GOOGLE_DOCS_MCP_APPS_SCRIPT_ID` | Apps Script bridge project ID for `bookmark_jump=true` |
| `GOOGLE_DOCS_TOKEN_FILE` | Legacy alias |
| `GOG_KEYRING_PASSWORD` | Auto-export from gog CLI (for personal/OpenClaw use) |

Legacy `GOOGLE_DRIVE_MCP_*` env var aliases still work for backward compatibility.

---

## Scopes

The auth setup requests these scopes:

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/documents` | Read and write Google Docs |
| `https://www.googleapis.com/auth/drive` | Access Drive files and comments |
| `https://www.googleapis.com/auth/drive.readonly` | Read Drive file metadata |
| `https://www.googleapis.com/auth/drive.file` | Per-file Drive access |
| `https://www.googleapis.com/auth/script.projects` | Create Apps Script projects for comment-path experiments |
| `https://www.googleapis.com/auth/script.deployments` | Deploy Apps Script functions |
| `https://www.googleapis.com/auth/script.processes` | View script execution |
| `openid`, `email`, `profile` | Identity |

---

## License

MIT
