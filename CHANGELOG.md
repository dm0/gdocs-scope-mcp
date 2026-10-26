# Changelog

User-facing changes are listed in descending version order. Historical entries
are reconstructed from Git history; an explicit note identifies untagged
baselines whose publication date is not established.

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

## v0.2.0 - Historical upstream baseline

This version first appears in package metadata at commit
[`797207f`](https://github.com/dm0/gdocs-scope-mcp/commit/797207f), dated
2026-03-10. There is no `v0.2.0` tag in this repository; this entry describes the
recorded baseline, not a verified publication date.

### Added

- Original text-anchor Google Docs operations: reading, search/replace,
  insertion, append, paragraph deletion, and batch replacement.
- Document listing and creation.
- Text-anchored comments using named ranges, comment reading, replies,
  resolution, and deletion.
- Standalone OAuth authentication with browser, headless, and code-exchange
  modes, self-contained token files, and legacy token compatibility.
- Initial package and console entry points under the `google-drive-mcp` name.

[v0.4.0]: https://github.com/dm0/gdocs-scope-mcp/compare/v0.3.0...v0.4.0
[v0.3.0]: https://github.com/dm0/gdocs-scope-mcp/tree/v0.3.0
