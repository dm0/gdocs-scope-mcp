# Changelog

User-facing changes to `gdocs-scope-mcp` are listed in descending version order,
starting with v0.3.0. The upstream 0.2.0 baseline is documented separately for
provenance; it is not a release of this independent project.

## Unreleased

### Changed

- Application-owned environment variables now exclusively use the
  `GDOCS_SCOPE_MCP_*` prefix. Rename previous `GOOGLE_DOCS_MCP_*` and
  `GOOGLE_DRIVE_MCP_*` entries; these names and `GOOGLE_DOCS_TOKEN_FILE` are
  ignored. Shared-drive switches are `GDOCS_SCOPE_MCP_USE_DRIVE` and
  `GDOCS_SCOPE_MCP_DRIVE_ID`. JSON keys, token/configuration paths, third-party
  variables, and existing live-test controls are unchanged. See the
  [migration guide](docs/configuration.md#environment-name-migration-and-validation)
  for validation and restart requirements.

## [v0.6.1] - 2026-10-29

### Fixed

- Disable document snapshot caching by default. On large documents, checking
  only the Docs revision can be nearly as slow as downloading the full
  document, and changed cached documents require both requests. Explicit
  `document_cache_enabled=true` or
  `GOOGLE_DOCS_MCP_DOCUMENT_CACHE_ENABLED=true` still enables caching with
  native revision validation and the configured disk or memory backend.

### Added

- With caching enabled, diagnostic logs separately time native document and
  revision requests, helping distinguish Google API request latency from
  local cache handling. Logs omit document IDs, revision IDs and content.

[v0.6.1]: https://github.com/dm0/gdocs-scope-mcp/compare/v0.6.0...v0.6.1

## [v0.6.0] - 2026-10-29

### Added

- Revision-validated native document snapshot caching, shared across MCP
  processes and chats through a SQLite disk cache by default. Configurable
  limits cover lifetime, entry count, serialized payload size and database
  size; defaults are 300 seconds, 128 entries, 32 MiB of payloads and a 64 MiB
  database. Process-local memory storage and complete disabling are available.
- Automatic width fitting for unsized Markdown, HTML and locally uploaded
  images in supported paged body paragraphs. Available width accounts for page
  orientation, effective section margins and paragraph indents; native sizing
  preserves image proportions. Explicit image dimensions take precedence.
- `docs_suggestions_read` for scoped native proposal inspection, including
  IDs, status, authors, summaries, source locations and paged replies.
- `docs_suggest` for typed text replacement, before/after insertion, scoped
  append, paragraph deletion and text-formatting proposals. Plans use native
  indices and a single suggest-mode batch, preserve configured revision
  policies, and reject overlapping or uncertain targets before writing.
- `docs_suggestions_manage` for accepting, rejecting or deleting up to 50
  explicit native proposal IDs. Decisions are preflighted together and return
  per-ID outcomes, including already matching accepted/rejected states.

### Changed

- Ordinary document reads and outlines now show accepted content without
  applying pending suggestions: proposed insertions are omitted, proposed
  deletions retained and proposed formatting excluded. Suggestion metadata
  distinguishes document-wide and selected-fragment changes from unknown
  detection. Reading never accepts or rejects a proposal.
- Dedicated table reads also use accepted content. Heading selectors and table
  references are validated against native source structure; unmappable
  selections fail explicitly, and unsafe references in document Markdown are
  omitted with warnings. Writes continue using inline native coordinates.
- Proposal creation and decisions require `commentUpdateState=ALL_SAVED` and
  fresh native readback before reporting success. Missing IDs, failed saves
  and uncertain outcomes are explicit failures and are never blindly replayed.
  Existing editing tools retain direct-write behavior.
- Default caching now persists native document content locally in the user's
  platform cache directory. Cache identity includes the credential grant and
  request options; hits are checked against Google's current revision, and
  every attempted local Docs write invalidates cached snapshots. Configure
  `document_cache_storage="memory"` or `document_cache_enabled=false` when
  persistent storage is not wanted.

### Fixed

- Live tab-preservation checks tolerate rotation of temporary image download
  URLs while continuing to verify content, structure and image properties.
- Suggestion tests remove their pending proposals before deleting temporary
  tabs, avoiding leftover unlocated open threads.

### Limitations

- Cache hits still require a revision request and credential handling; reduced
  response size does not guarantee a comparable reduction in total latency.
  Temporary journal and lock files are outside the database file size limit.
- Automatic image width fitting is limited to supported single-column paged
  body paragraphs. Pageless documents, table cells and unsupported layouts
  retain Google's default image sizing.
- Proposal creation initially targets ordinary body paragraphs and validated
  text formatting. Table, image, chip and list proposal workflows and replies
  are not supported. Pending changes in the target paragraph, unlocated open
  threads or unknown proposal metadata require review before new proposals.
- Suggested code insertions retain formatting but omit named-range code
  markers with a warning, because native named ranges cannot be suggested.
  Guarded proposal writes require an available native document revision.

[v0.6.0]: https://github.com/dm0/gdocs-scope-mcp/compare/v0.5.0...v0.6.0

## [v0.5.0] - 2026-10-28

### Added

- Consistent root and nested document tab support across outlines, reading,
  text edits, tables, and smart-chip tools. `docs_tabs_list` discovers tab IDs
  and hierarchy; `docs_get_tree` includes the complete tab inventory, and
  `docs_read` reports `tab_count`. Calls without `tab_id` retain first-tab
  behavior, keeping single-tab documents free of extra required parameters.
- Read-only native table discovery and bounded cell reads with opaque table
  references, A1 addresses, geometry, nesting, and pagination.
- Selected-cell snapshots and atomic Markdown cell patches. Table references
  check section position and structure; snapshots protect selected content
  and properties while permitting compatible edits in other cells.
- Atomic table formatting with property-level conflict checks, including
  shared-border dependencies, cell styles, alignment, column widths, row
  heights, and header rows.
- Guarded table row/column insertion and deletion, whole-table deletion, and
  rectangular cell merge/unmerge operations with explicit content policies.
- Configurable `required` and `target` revision policies for document edits.
  Required mode validates original targets and retries confirmed revision
  races; target mode delegates concurrent merging to Google. Optional
  `expected_revision_id` enforces a strict revision without automatic rebasing.
- Inline-code and fenced-code reconstruction when reading documents, using
  configurable font/color matching, validated named-range metadata, native
  code-block recognition, and optional formatting heuristics.
- Native Google Docs comments with real text-range anchors, document-wide
  thread/reply reading, and confirmed comment persistence. New tools
  `docs_reopen_comment`, `docs_edit_comment`, and `docs_delete_comment_reply`
  complement creation, replies, resolution, and thread deletion.

### Changed

- Recognized code reads preserve literal source and ignore visual formatting
  inside code. Named-range metadata, native-block recognition, and heuristic
  recognition are independently configurable; unmarked languages are not
  guessed.
- Table references, snapshots, and page tokens carry tab identity. Table
  responses expose the effective `tab_id`; `TAB_MISMATCH` distinguishes a
  wrong selector from a changed table structure and provides recovery guidance.
- Comment writes use native Docs requests and require
  `commentUpdateState=ALL_SAVED` before reporting success. Comment text is plain
  text limited to 2048 UTF-8 bytes. Failed or unknown persistence is reported
  explicitly and is not automatically replayed.
- Native comment pagination uses state-bound cursors and separates thread
  summaries from paged replies. Discard old Drive comment cursors and reread
  native thread/post IDs before continuing existing workflows.
- Split the README into focused setup, configuration, tool, rich-content,
  protocol, and development guides, with a linked implementation-notes index.

### Removed

- The comment named-range/Apps Script workaround, bookmark-jump bridge, and
  obsolete Apps Script probe. Comment creation no longer accepts
  `bookmark_jump` or `include_anchor_text`, or returns `named_range_id`,
  `bookmark_id`, `bookmark_url`, or `apps_script_id`.
- New OAuth requests no longer include Apps Script scopes. Existing token
  files remain accepted; previously granted permissions are not revoked.
  The former Apps Script bridge ID settings are no longer used.

### Limitations

- Table references identify checked section positions, not persistent object
  identity. Structurally identical swaps retain position meaning; structural
  changes require fresh references and snapshots. Dedicated table edits use
  strict revision guards regardless of the general revision policy.
- Table insertion remains multi-stage and can leave partial content after a
  later-stage failure. Nested or unsupported complex table targets are rejected
  by the dedicated editing tools.
- Code recognition heuristics can produce false positives; language metadata
  is retained only where available. Insertion still creates styled code
  paragraphs rather than native Google Docs code-block objects.
- Native comment pagination bounds MCP output, not the underlying document
  download. Document revision guards are not per-post concurrency tokens;
  guarded mutations require an available document revision. Existing broken
  comment anchors and auxiliary metadata are not repaired or removed implicitly.

[v0.5.0]: https://github.com/dm0/gdocs-scope-mcp/compare/v0.4.0...v0.5.0

## [v0.4.0] - 2026-10-26

### Added

- Native Markdown ordered and unordered lists with homogeneous nesting,
  multiple paragraphs per item, and continuations after nested lists.
- Native rectangular Markdown and HTML tables with inline formatting,
  column alignment, soft line breaks, and optional borders via `table_borders`.
- Native Markdown and HTML images, including opt-in local image uploads through
  temporary, link-shared Google Drive files with cleanup after insertion.
- Inline code and code blocks with configurable fonts, inline code color,
  syntax highlighting, themes, line spacing, and paragraph background shading.
  Agents can override the code theme/background per insertion and discover
  available themes.
- Native people, resource, date, and dropdown chips in document reads and rich
  insertion. Reader HTML preserves visible labels and native identity; copying
  it creates new native instances with the corresponding properties.
- `docs_get_entity`, `docs_create_dropdown_definition`, and
  `docs_select_dropdown` for inspecting chip metadata/options, creating shared
  dropdown definitions, and changing one instance's selected option.
- Cursor pagination for document and comment listings.
- Permanent offline regressions and opt-in live MCP tests using isolated
  STDIO processes and an explicitly selected test document.

### Changed

- Partial reads return identified, non-overlapping section subtrees with
  effective selection and unknown-heading diagnostics.
- MCP inputs use strict validation, including typed batch replacements.
  Tools declare action annotations and return scoped, bounded edit receipts.
- Targeted replacements report complete pre-edit match counts.
- Package versions are derived from Git tags with `setuptools-scm`.
- Live tests use `GDOCS_SCOPE_MCP_LIVE_TEST_DOC` for the document ID instead of
  a hard-coded document or the former `GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES` flag.

### Fixed

- Correct UTF-16 source indices for emoji and other non-BMP characters in edits
  and formatting; preserve paragraph and table-cell boundaries.
- Preserve source positions around non-text elements and reject replacements
  or anchors that cross unmappable structural gaps.
- Traverse later paragraphs and nested sections during first-match regex
  searches; preserve regex semantics and original offsets when ignoring case.
- Reject unsupported scoped/regex replace-all modes before API access.
- Preserve the mandatory final newline when deleting document paragraphs.
- Accept omitted empty list metadata and retain inline images and horizontal
  rules when reading documents.
- Preserve supported reader HTML, hyperlinks, and strikethrough during rich
  insertion, and retain literal whitespace inside code blocks.
- Protect native smart chips from unsupported paragraph deletion and guard
  chip insertion/selection and definition creation with revision preconditions.

### Removed

- The redundant `python -m gdocs_scope_mcp.docs_edit` editing CLI. Use the
  FastMCP client CLI against the MCP server instead.
- The old partial-read `subset_md` field in favor of `sections` entries.

### Limitations

- Table insertion uses multiple revision-guarded batches and can leave partial
  content after a later-stage failure. Dedicated table editing tools and
  conflict-aware rebasing are not part of this release.
- Dropdown copies require the definition and selected option to exist in the
  destination tab. Definitions are not copied between documents automatically.

[v0.4.0]: https://github.com/dm0/gdocs-scope-mcp/compare/v0.3.0...v0.4.0

## [v0.3.0] - 2026-10-23

### Added

- Hierarchical document outlines, heading-ID lookup, partial document reads,
  and heading-scoped text replacement and before/after insertion.
- Pydantic models for Google Docs responses, document structure, and typed
  MCP tool outputs, including a bounded append receipt.
- Shared Markdown conversion for append/before/after insertion, supporting
  paragraphs, heading levels, and basic inline formatting.
- Structured MCP errors with stable codes and suggested recovery actions.
- `server_info` diagnostics with package path, version, source fingerprint,
  process identity, and startup time; configurable stderr tool-call logging.
- Shared-drive listing/filtering, Apps Script probes, and opt-in bookmark-jump
  comments.
- Offline fixture coverage and strict expected-failure tests for known gaps.

### Changed

- Renamed the independent project, distribution, import package, and console
  commands to `gdocs-scope-mcp` / `gdocs_scope_mcp`. Legacy authentication
  environment variables and token paths remain supported.
- Moved to the `src/` package layout and consolidated rich insertion through
  one converter, removing the legacy request builder.

### Fixed

- Honor `rich=False`, forward before-insertion heading scope, and insert after
  anchor paragraphs without joining neighbouring text or exceeding the final
  paragraph boundary.
- Handle missing inline-object metadata and resolve comments through a single
  Drive reply action.
- Fetch inline suggestions consistently so source indices remain usable.

[v0.3.0]: https://github.com/dm0/gdocs-scope-mcp/tree/v0.3.0

## Upstream baseline: 0.2.0

Version 0.2.0 belongs to the original
[`dbuxton/google-docs-mcp`](https://github.com/dbuxton/google-docs-mcp) project
from which `gdocs-scope-mcp` was created. It is not a `gdocs-scope-mcp` release.
The inherited history first records this version in package metadata at commit
[`797207f`](https://github.com/dm0/gdocs-scope-mcp/commit/797207f), dated
2026-03-10, when the upstream package used the `google-drive-mcp` name. That
commit date is not asserted to be the upstream publication date.

### Inherited functionality

- Original text-anchor Google Docs operations: reading, search/replace,
  insertion, append, paragraph deletion, and batch replacement.
- Document listing and creation.
- Text-anchored comments using named ranges, comment reading, replies,
  resolution, and deletion.
- Standalone OAuth authentication with browser, headless, and code-exchange
  modes, self-contained token files, and legacy token compatibility.
- Initial package and console entry points under the `google-drive-mcp` name.
