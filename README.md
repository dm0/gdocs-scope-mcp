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
This does not implement editing the objects themselves or inserting images
from Markdown. Batch replacements and comment anchors use the same source-range
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

#### `docs_insert_after(doc_id, anchor, text, heading_id=None, rich=True)`
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

#### `docs_insert_before(doc_id, anchor, text, heading_id=None, rich=True)`
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

#### `docs_append(doc_id, text, rich=True)`
Append Markdown paragraphs or literal text at the end of the document, adding
a paragraph break before the content. With `rich=True`, separate paragraphs
with blank lines; headings and emphasis use the shared converter. Native lists
and tables are not implemented. Set `rich=False` to preserve text literally.

All three rich insertion tools (`docs_append`, `docs_insert_before`, and
`docs_insert_after`) also accept the reader's HTML for bold (`b`), italic (`i`),
underline (`u`), and paragraph alignment (`p` with `text-align: center`, `right`,
or `justify`). Nested inline styles combine within their text ranges. Heading
ID anchors (`<a id=...></a>`) are omitted from inserted text; new headings use
the Markdown heading level and receive their own Google Docs IDs.

This is a bounded read-to-write subset, not complete HTML or formatting
round-trip support. Other wrappers retain their child text without preserving
unsupported formatting or attributes; non-text tags may contribute no content.
For example, a styled `span` retains its text but loses its styling. Native
links, lists, tables, images, and code formatting still have separate insertion
limitations. Use `rich=False` to preserve HTML tags and Markdown literally.

```
docs_append(doc_id="...", text="Document last updated: March 2026.")
```

Returns `ok`, `document_id`, `rich`, diagnostic `at_index`, `appended` (a
plain-text preview of up to 200 Unicode code points), `inserted_char_count`
(including added paragraph breaks), and `preview_truncated`.

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
