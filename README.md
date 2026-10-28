# gdocs-scope-mcp

> Hierarchical Google Docs editing for AI agents working with large documents.

See [CHANGELOG.md](CHANGELOG.md) for version history and compatibility changes.

`gdocs-scope-mcp` is an independent project based on
[dbuxton/google-docs-mcp](https://github.com/dbuxton/google-docs-mcp).
It builds on the original project's text-anchor editing approach and focuses
on **navigating and editing document sections through their heading hierarchy**.

An agent can inspect a compact outline, read only the sections it needs, and
scope replacements or insertions to a heading and its nested subsections.
This keeps unrelated content out of the agent's context and makes the server
well suited to large Google Docs with structured headings.

## Features

- **Native comments:** attach comments directly to text, read their anchors,
  reply, edit, resolve/reopen, and delete through the Docs API.

- **Document tabs:** discover root and nested tabs, select one consistently
  across reading, text edits, tables and smart chips; references stay scoped
  to that tab. Existing calls default to the first tab.

- **Navigate large documents by section.** Discover a compact heading tree,
  read selected section subtrees, and scope replacements and insertions to a
  heading and its nested subsections. Keep unrelated content out of the agent's
  context, even when the same text appears in several chapters.
- **Edit using text anchors.** Identify text to replace or paragraphs to insert
  around without asking the agent to calculate Google Docs character indices.
  Source mapping handles UTF-16 offsets and protects structural gaps around
  non-text elements from unsupported replacements.
- **Read and write rich content.** Read documents as Markdown with HTML for
  supported formatting, and insert headings, emphasis, links, strikethrough,
  and supported reader-generated HTML through one shared converter.
- **Create native lists and tables.** Write homogeneous nested lists with
  multiple paragraphs per item and continuations after nested lists. Insert
  rectangular Markdown or HTML tables with column alignment, inline formatting,
  line breaks, and optional borders.
- **Discover and inspect tables.** Follow opaque references in document HTML,
  list compact heading-scoped table previews, and page structured cells with
  merged geometry, empty cells and explicit truncation metadata. Reads create
  no bindings or document changes.
- **Validate independent table edits.** Use checked table positions and A1 cell
  addresses across MCP processes. Selective snapshots detect changed cell
  properties while allowing independent edits, without document metadata writes.
- **Patch table cells atomically.** Replace selected cells with inline Markdown
  in one guarded batch, preserving cell/paragraph properties. Revision races
  trigger bounded revalidation; overlapping changes fail without overwriting.
- **Format tables selectively.** Set cell backgrounds, borders, padding and
  alignment, column widths, minimum row heights and pinned header rows in one
  guarded batch. Property-level expectations allow independent text and style
  edits, including changes to different borders of the same cell.
- **Change table structure safely.** Insert or delete rows and columns, or
  explicitly remove a table. Merge and unmerge complete cell rectangles with
  protected content and formatting. Unrelated text edits can proceed through
  bounded revision retries.
- **Insert images.** Use Markdown or HTML image references, or explicitly enable
  local image uploads through temporary, link-shared Google Drive files that
  are cleaned up after insertion. Unsized images fit the available paragraph
  width in supported paged body paragraphs and lists.
- **Format code for readability.** Use inline code and fenced code blocks with
  syntax highlighting, configurable fonts, themes, line spacing, and optional
  paragraph backgrounds. Agents can discover available themes and override the
  theme and background per insertion.
- **Work with native smart chips.** Read and insert people, resource, date,
  and dropdown chips. Inspect their metadata, create dropdown definitions, and
  change an individual dropdown's selected option.
- **Use structured MCP contracts.** Typed inputs and outputs, structured errors
  with recovery guidance, and action annotations make tool calls easier to
  validate and handle. Bounded edit receipts expose counts and truncation flags;
  document and comment listings support cursor pagination.
- **Diagnose the running server.** Inspect the package version, source
  fingerprint, package path, PID, and startup time with `server_info`. Configurable
  stderr logs record tool outcomes and durations without logging document content.

Supported content has explicit limits: arbitrary table writes and cross-document
dropdown definition copying are not supported. Table positions are guarded by
section structure; table pagination tokens bind the document revision.
See the [tool reference](docs/tools/documents.md) for operation-specific details.

## Quick start

1. [Create a Google Cloud OAuth app](docs/getting-started.md#2-create-a-google-cloud-oauth-app)
   and download its Desktop App credentials.
2. Authenticate:

   ```bash
   uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
     gdocs-scope-mcp-auth --credentials ~/credentials.json
   ```

3. Configure your MCP client to run:

   ```bash
   uvx --from git+https://github.com/dm0/gdocs-scope-mcp gdocs-scope-mcp
   ```

   Set `GOOGLE_DOCS_MCP_TOKEN` to the absolute path of the saved token file
   (default: `~/.google-docs-mcp/token.json`).

See [Getting started](docs/getting-started.md) for client configuration examples,
headless authentication, scopes and migration.

## Section editing workflow

Typical workflow:

1. Call `docs_get_tree(doc_id)` to discover headings and their IDs.
2. Call `docs_read(doc_id, heading_ids=[...])` to read selected section subtrees.
3. Use `heading_id` with `docs_search_replace`, `docs_insert_before`, or
   `docs_insert_after` to restrict the edit to the chosen subtree.
4. Read that section again to verify the result.

Scoped reads reduce the document content sent to the agent. The server still
fetches the Google Docs document snapshot internally to resolve its structure
and edit positions.

## Documentation

| Guide | Contents |
| --- | --- |
| [Getting started](docs/getting-started.md) | Installation, OAuth, authentication and client setup |
| [Configuration](docs/configuration.md) | JSON settings, environment variables, defaults and overrides |
| [Document tools](docs/tools/documents.md) | Reading, searching, inserting, replacing and creating documents |
| [Table tools](docs/tools/tables.md) | Discovery, snapshots, cell patches, formatting and structure |
| [Comment tools](docs/tools/comments.md) | Native anchored comments, replies, editing and resolution |
| [Rich content](docs/rich-content.md) | Markdown/HTML, lists, images, code and smart chips |
| [MCP result contracts](docs/protocol.md) | Structured results, errors, annotations, receipts and pagination |
| [Development](docs/development.md) | Local setup, testing, FastMCP CLI, diagnostics and logging |
| [Implementation notes](docs/development/implementation-notes.md) | Internal design, concurrency, table references and API research |

## License

MIT.
