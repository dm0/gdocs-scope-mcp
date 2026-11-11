# Server configuration

[README](../README.md) · [Getting started](getting-started.md) · [Result contracts](protocol.md)

## Configuration file

An optional JSON config sets authorization, tools, editing, caching and formatting. By default, the
server reads `~/.config/gdocs-scope-mcp/config.json`, or
`$XDG_CONFIG_HOME/gdocs-scope-mcp/config.json` when `XDG_CONFIG_HOME` is set.
Select another file with `GDOCS_SCOPE_MCP_CONFIG=/absolute/path/config.json`.
An absent default file is allowed; an explicitly selected file must exist.

```json
{
  "client_id": null,
  "access_mode": "full_drive",
  "toolset_version": "v2",
  "write_revision_mode": "required",
  "document_cache_enabled": false,
  "document_cache_storage": "disk",
  "document_cache_directory": null,
  "document_cache_database_max_bytes": 67108864,
  "document_cache_ttl_seconds": 300,
  "document_cache_max_entries": 128,
  "document_cache_max_bytes": 33554432,
  "table_snapshot_ttl_seconds": 86400,
  "code_font_family": "Roboto Mono",
  "inline_code_color": "#188038",
  "code_block_highlighting": true,
  "code_block_style": "default",
  "code_block_line_spacing": 1.15,
  "code_block_theme_background": false,
  "code_block_named_ranges": true,
  "read_inline_code": true,
  "read_inline_code_fonts": null,
  "read_inline_code_colors": null,
  "read_inline_code_match": "both",
  "read_code_block_heuristic": true,
  "read_native_code_blocks": true,
  "read_code_block_fonts": null,
  "read_code_block_line_spacing": 1.15,
  "read_code_block_require_background": false,
  "read_code_block_min_lines": 2
}
```

All fields are optional; the example shows the built-in defaults. Unknown JSON
fields and invalid values fail validation rather than silently falling back to
defaults. The reference below groups settings by purpose; the
[environment variable table](#environment-overrides) maps each JSON field to its
environment override.

## Settings reference

### Authorization and tool catalog

- **`client_id`** — Selects the Desktop OAuth client for new authorization.
  Default: `null`, which uses the bundled client. CLI options and OAuth client
  environment variables take precedence. Existing token files retain their
  originating client ID regardless of this setting. See
  [auth environment variables](#auth-environment-variables) for client secrets
  and credential precedence.
- **`access_mode`** — Controls the requested Google access scope and available
  file-selection tools. Default: `"full_drive"`, for broad Drive access.
  `"selected_files"` uses `drive.file` for files granted to or created by the
  application. Changing this setting requires a server restart and may require
  authorization; it does not revoke existing Google grants. See
  [document access modes](#document-access-modes).
- **`toolset_version`** — Selects the MCP tool catalog at startup. Default:
  `"v2"`, which exposes the consolidated `docs_insert` and
  `docs_comment_status` tools. Use `"v1"` for the legacy tool names. Restart the
  server to change the catalog.

### Concurrent editing and table expectations

- **`write_revision_mode`** — Selects how writes handle concurrent document
  changes. Default: `"required"`, with validated retries. `"target"` lets
  Google merge concurrent changes, including overlaps; it does not provide our
  local unchanged-target guarantee and never retries a rejected or expired
  target revision. An explicit `expected_revision_id` always forces strict
  required mode without retries. Multi-stage table insertion always retains
  required revisions to avoid stale cursors after a transformed stage.
  `docs_table_patch`, `docs_table_format` and `docs_table_structure` also always
  use strict required revisions, independently of this setting. See
  [concurrent edit policies and limitations](concurrent-edits.md).
- **`table_snapshot_ttl_seconds`** — Sets how long selective table expectations
  remain valid. Default: `86400` seconds (24 hours). Accepts integers from `1`
  to `604800` seconds (7 days). Table position refs have no time expiry.

### Document snapshot cache settings

These settings control reuse of native document downloads. See
[document snapshot cache](#document-snapshot-cache) for revision checks,
invalidation, privacy and performance details.

- **`document_cache_enabled`** — Enables document snapshot caching when `true`.
  Default: `false`, which bypasses both storage backends.
- **`document_cache_storage`** — Selects where enabled caching stores snapshots.
  Default: `"disk"`, shared across local MCP processes using the same cache
  directory. `"memory"` keeps snapshots only within the current process.
- **`document_cache_directory`** — Sets the disk cache directory. Default:
  `null`, which uses the platform user cache directory, such as
  `~/.cache/gdocs-scope-mcp` on Linux (respecting `XDG_CACHE_HOME`). Applies only
  to disk storage. Use a local filesystem supporting native file locks.
- **`document_cache_database_max_bytes`** — Caps the main SQLite database file,
  including database pages. Default: `67108864` bytes (64 MiB); minimum:
  `1048576` bytes (1 MiB). Applies only to disk storage and is rounded down to a
  4096-byte boundary. Small lock files and transient rollback journals are
  outside this limit; reducing it may discard snapshots.
- **`document_cache_ttl_seconds`** — Sets how long a cached snapshot can be
  retained before it expires and needs a full download. Default: `300` seconds
  (5 minutes). Accepts integers from `1` to `86399`. An unexpired entry still
  requires a Google revision check before reuse.
- **`document_cache_max_entries`** — Caps the number of cached snapshots.
  Default: `128`. Must be a positive integer; least recently used entries are
  evicted when necessary.
- **`document_cache_max_bytes`** — Caps the total serialized snapshot payloads.
  Default: `33554432` bytes (32 MiB). Must be a positive integer. Oversized
  documents are returned without being cached; least recently used entries are
  evicted when necessary. This is separate from the disk database file limit.

### Code insertion and formatting

- **`code_font_family`** — Sets the font used when inserting inline code and
  code blocks. Default: `"Roboto Mono"`. Also supplies the default font for
  code recognition when the corresponding read-font list is `null`. The name
  must be nonempty; choose a font supported by Google Docs, since the server
  validates syntax without querying font availability.
- **`inline_code_color`** — Sets the foreground color used when inserting
  inline code. Default: `"#188038"`. Does not set code-block colors. Also
  supplies the default inline-code recognition color when
  `read_inline_code_colors` is `null`. Use six-digit RGB hex syntax (`#RRGGBB`).
- **`code_block_highlighting`** — Enables syntax highlighting for code blocks
  with a recognized language label. Default: `true`. Set to `false` to keep
  language-labelled blocks plain monospace. A theme choice alone does not
  enable highlighting or identify a missing or unknown language.
- **`code_block_style`** — Selects the Pygments syntax-highlighting theme.
  Default: `"default"`; examples include `"friendly"` and `"monokai"`. An
  unknown theme fails startup validation. Preview themes in the
  [Pygments gallery](https://pygments.org/styles/). Can be overridden
  [per insertion call](#per-call-formatting-overrides).
- **`code_block_line_spacing`** — Sets the line-height multiplier for all
  inserted code blocks, including blocks with unknown languages or highlighting
  disabled. Default: `1.15`; `1.0` is single spacing and `1.5` is one-and-a-half
  spacing. Must be positive and finite. Google Docs stores it as a percentage
  (`1.15` becomes `115`). Inline code and surrounding prose are unaffected.
  Configure reading spacing separately with `read_code_block_line_spacing`.
- **`code_block_theme_background`** — Applies the theme's base background and
  token-specific backgrounds when `true`. Default: `false`. Takes effect only
  when syntax highlighting is active for a recognized language. Can be
  overridden [per insertion call](#per-call-formatting-overrides).
- **`code_block_named_ranges`** — Writes invisible named-range metadata for
  inserted code blocks and uses that metadata when reading them back. Default:
  `true`. The metadata preserves block boundaries and language labels without
  depending on line spacing. Set to `false` to disable both writing and reading
  these markers; native-block recognition and formatting heuristics have their
  own controls below.

### Reading inline code

These settings recognize formatted text as inline code in read results; they
do not change the document's formatting.

- **`read_inline_code`** — Enables recognition of inline code using the font
  and color rules below. Default: `true`. Set to `false` to disable this
  recognition.
- **`read_inline_code_fonts`** — Lists font names accepted for inline-code
  recognition, matched case-insensitively. Default: `null`, which uses
  `code_font_family`. An explicit list replaces that fallback; names must be
  nonempty.
- **`read_inline_code_colors`** — Lists foreground colors accepted for
  inline-code recognition. Default: `null`, which uses `inline_code_color`.
  An explicit list replaces that fallback. Use six-digit RGB hex strings
  (`#RRGGBB`); hex letter case does not affect matching.
- **`read_inline_code_match`** — Selects which formatting must match to
  recognize inline code. Default: `"both"`, requiring both an accepted font
  and an accepted color. `"font"` checks only the font; `"color"` checks only
  the foreground color.

### Reading code blocks

Named-range metadata, native Google Docs code-block recognition and formatting
heuristics are separate recognition paths. Heuristic thresholds below do not
restrict blocks recovered from named-range metadata or native delimiters.

- **`read_code_block_heuristic`** — Enables recognition of unmarked code blocks
  from their font, paragraph line spacing and optional background. Default:
  `true`. Set to `false` to disable formatting-based guesses while retaining
  independently enabled named-range and native-block recognition.
- **`read_native_code_blocks`** — Enables recognition of Google Docs UI code
  blocks from observed native delimiters and accepted code fonts. Default:
  `true`. Set to `false` to leave those blocks as ordinary text in read results.
  Recognition relies on observed UI formatting, not a documented API contract.
- **`read_code_block_fonts`** — Lists font names accepted by both native-block
  recognition and the formatting heuristic, matched case-insensitively.
  Default: `null`, which uses `code_font_family`. An explicit list replaces
  that fallback; names must be nonempty.
- **`read_code_block_line_spacing`** — Sets the paragraph line-height multiplier
  required by the formatting heuristic. Default: `1.15`. Must be positive and
  finite. Set to `1.0`, for example, to recognize older single-spaced blocks.
  This is independent of insertion spacing and does not affect named-range
  metadata recognition.
- **`read_code_block_require_background`** — Requires a paragraph background
  color for formatting-based block recognition when `true`. Default: `false`,
  so matching font and line spacing can suffice without a background.
- **`read_code_block_min_lines`** — Sets the minimum number of consecutive
  matching paragraphs for formatting-based block recognition after trimming
  blank edges. Default: `2`. Must be an integer of at least `1`.

## Environment overrides

Environment variables override individual file settings:

| Environment variable | JSON field | Default |
|---|---|---|
| `GDOCS_SCOPE_MCP_CLIENT_ID` | `client_id` | `null` (bundled client for new authorization) |
| `GDOCS_SCOPE_MCP_ACCESS_MODE` | `access_mode` | `full_drive` |
| `GDOCS_SCOPE_MCP_TOOLSET_VERSION` | `toolset_version` | `v2` |
| `GDOCS_SCOPE_MCP_WRITE_REVISION_MODE` | `write_revision_mode` | `required` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_ENABLED` | `document_cache_enabled` | `false` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_STORAGE` | `document_cache_storage` | `disk` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_DIRECTORY` | `document_cache_directory` | Platform cache directory |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_DATABASE_MAX_BYTES` | `document_cache_database_max_bytes` | `67108864` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_TTL_SECONDS` | `document_cache_ttl_seconds` | `300` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_MAX_ENTRIES` | `document_cache_max_entries` | `128` |
| `GDOCS_SCOPE_MCP_DOCUMENT_CACHE_MAX_BYTES` | `document_cache_max_bytes` | `33554432` |
| `GDOCS_SCOPE_MCP_TABLE_SNAPSHOT_TTL_SECONDS` | `table_snapshot_ttl_seconds` | `86400` |
| `GDOCS_SCOPE_MCP_CODE_FONT_FAMILY` | `code_font_family` | `Roboto Mono` |
| `GDOCS_SCOPE_MCP_INLINE_CODE_COLOR` | `inline_code_color` | `#188038` |
| `GDOCS_SCOPE_MCP_CODE_BLOCK_HIGHLIGHTING` | `code_block_highlighting` | `true` |
| `GDOCS_SCOPE_MCP_CODE_BLOCK_STYLE` | `code_block_style` | `default` |
| `GDOCS_SCOPE_MCP_CODE_BLOCK_LINE_SPACING` | `code_block_line_spacing` | `1.15` |
| `GDOCS_SCOPE_MCP_CODE_BLOCK_THEME_BACKGROUND` | `code_block_theme_background` | `false` |
| `GDOCS_SCOPE_MCP_CODE_BLOCK_NAMED_RANGES` | `code_block_named_ranges` | `true` |
| `GDOCS_SCOPE_MCP_READ_INLINE_CODE` | `read_inline_code` | `true` |
| `GDOCS_SCOPE_MCP_READ_INLINE_CODE_FONTS` | `read_inline_code_fonts` | `null` (insertion font) |
| `GDOCS_SCOPE_MCP_READ_INLINE_CODE_COLORS` | `read_inline_code_colors` | `null` (insertion color) |
| `GDOCS_SCOPE_MCP_READ_INLINE_CODE_MATCH` | `read_inline_code_match` | `both` |
| `GDOCS_SCOPE_MCP_READ_CODE_BLOCK_HEURISTIC` | `read_code_block_heuristic` | `true` |
| `GDOCS_SCOPE_MCP_READ_NATIVE_CODE_BLOCKS` | `read_native_code_blocks` | `true` |
| `GDOCS_SCOPE_MCP_READ_CODE_BLOCK_FONTS` | `read_code_block_fonts` | `null` (insertion font) |
| `GDOCS_SCOPE_MCP_READ_CODE_BLOCK_LINE_SPACING` | `read_code_block_line_spacing` | `1.15` |
| `GDOCS_SCOPE_MCP_READ_CODE_BLOCK_REQUIRE_BACKGROUND` | `read_code_block_require_background` | `false` |
| `GDOCS_SCOPE_MCP_READ_CODE_BLOCK_MIN_LINES` | `read_code_block_min_lines` | `2` |

Font/color lists in environment variables use JSON arrays, for example
`GDOCS_SCOPE_MCP_READ_CODE_BLOCK_FONTS='["Roboto Mono", "Consolas"]'`.

Precedence is per-call overrides (theme/background only), environment, JSON
file, then built-in defaults. Server settings are
loaded and validated at server startup and cached for that process. Restart
the MCP server after changing the file or environment. This config
includes the OAuth client ID, concurrency, table snapshots and code formatting.
Token paths, client secrets, Drive and logging environment variables retain
their separate handling. Our config does not
automatically load `.env` files.

## Per-call formatting overrides

The default `docs_insert` and `docs_insert_at_heading` tools also accept optional
agent-facing `code_block_style` and `code_block_theme_background` arguments.
The `code_block_style` input schema advertises an `enum` of available themes,
generated from the installed Pygments version when the server starts. Agents
can discover names through MCP tool listing without a separate theme-list call.
Omitting an argument or passing `null` inherits its server setting, including
environment overrides. An explicit `false` disables the background even if the
server default enables it. Each argument can be overridden independently:

```python
docs_insert(
    doc_id='...', text='```python\nprint("Hello")\n```',
    target={'position': 'append'},
    code_block_style='monokai', code_block_theme_background=True,
)
```

Overrides apply only to that call and do not change defaults or concurrent
requests, including when a write fails. Themes must be valid Pygments names;
invalid names fail before Google access. Formatting overrides have no effect
with `rich=False`. Highlighting enablement, font, inline color and line spacing
remain server settings; choosing a theme does not enable disabled highlighting
or guess a missing/unknown language.

### Passing settings to an isolated server

Set environment overrides in the MCP client's server `env` configuration.
For isolated FastMCP CLI tests, pass them explicitly to the child command:

```bash
uv run --locked fastmcp call \
  --command 'env GDOCS_SCOPE_MCP_CONFIG=/absolute/path/config.json gdocs-scope-mcp' \
  --target server_info --json
```

Setting a variable only on the parent CLI process does not guarantee it reaches
the STDIO server; FastMCP's subprocess environment is filtered.

## Auth environment variables

| Variable | Description |
|----------|-------------|
| **`GDOCS_SCOPE_MCP_TOKEN`** | Selects the token file to read and the destination for new authorization. Overrides default token paths; preferred for standalone use. |
| **`GDOCS_SCOPE_MCP_CLIENT_ID`** | Overrides JSON `client_id` for new authorization. Existing token-stored client credentials take precedence. |
| **`GDOCS_SCOPE_MCP_CLIENT_SECRET`** | Supplies the matching secret for an explicitly selected custom client. Public-client tokens do not use it. |
| **`GOG_KEYRING_PASSWORD`** | Unlocks the gog CLI keyring for automatic token export in personal/OpenClaw setups. The gog fallback is available only in `full_drive` mode. |

In `full_drive` mode, token resolution checks `GDOCS_SCOPE_MCP_TOKEN`, then
`$XDG_CONFIG_HOME/gdocs-scope-mcp/token.json`
(default root: `~/.config`), `~/.google-docs-mcp/token.json`, the older
`~/.google-drive-mcp/token.json`, then gog export/cache. New authorizations use
the XDG path unless `--out` or `GDOCS_SCOPE_MCP_TOKEN` is supplied.
Empty or relative `XDG_CONFIG_HOME`
values are ignored. Changing `GDOCS_SCOPE_MCP_CONFIG` selects the settings file,
not the token directory. Existing token files are not moved or rewritten.
Token-stored client credentials take precedence over environment client
overrides; an environment client ID takes precedence over JSON `client_id`,
followed by the existing gog credentials fallback. Public-client tokens never
consume a secret override. See [authentication](getting-started.md#3-authenticate).

Desktop authorization uses PKCE S256. Run `gdocs-scope-mcp-auth` to authorize
with the bundled Desktop client ID and matching secret. These shared Desktop
credentials are included in the source and installed package; user tokens are
private and are never included. A custom client ID never inherits the bundled secret.
For a custom client, provide the matching secret in its credentials JSON or
through `GDOCS_SCOPE_MCP_CLIENT_SECRET` together with an explicit client ID.
Existing token files retain their client credentials; changing settings does
not switch their OAuth client or document-access permissions.

### Document access modes

`access_mode` is a server setting, shared with the authorization CLI. Set it
in JSON or through `GDOCS_SCOPE_MCP_ACCESS_MODE`, then restart the MCP server.
An agent cannot override it through tool arguments.

`docs_authorize`, `docs_authorization_complete` and
`docs_authorization_status` are available in both modes.
`docs_select_files` is registered only in `selected_files`; it is absent from
the `full_drive` tool catalog. A mode change requires a server restart to
update the catalog. The old `docs_selection_status` name is not registered.

- `full_drive` preserves the existing broad authorization and token lookup.
- `selected_files` requests only `drive.file` through Desktop Google Picker.
  The default token is `selected-files-token.json` in the same XDG application
  directory. Explicit `GDOCS_SCOPE_MCP_TOKEN` paths still take precedence;
  broad legacy and gog fallbacks are disabled in this mode. The exchange and
  each refresh must confirm exactly the narrow scope; unknown or additional
  granted scopes are rejected before document operations.

Selected mode covers files granted to or created by the application, including
grants from earlier selection sessions. A document URL alone grants no access.
Google continues to enforce sharing permissions and organization policies.

Separate token paths retain each mode's saved credentials. When switching from
`selected_files` to `full_drive`, an existing narrow token requires additional
authorization.
The server returns `AUTHENTICATION_REQUIRED` with guidance to use
`docs_authorize`; the user then grants broader access in the browser. Poll
`docs_authorization_status` to confirm completion. The same configured token file
can be upgraded: replacement occurs only after sufficient scopes and the
previously bound account/client are verified. Denial or failure preserves it.
Alternatively run `gdocs-scope-mcp-auth` with `access_mode=full_drive` and the
same token destination. The CLI also verifies the upgrade.

With default token paths, the broad token is written to `token.json` while
`selected-files-token.json` stays intact. When no broad default token exists,
authorization retains the selected token's client/account binding rather than
silently changing accounts. An existing usable broad token can be reused.

Merely changing configuration does not narrow or revoke an existing Google
grant. If Google returns broad scopes,
remove the application's grant in [Google Account connections](https://myaccount.google.com/connections)
and authorize again with the intended mode. Revocation can interrupt other
tokens for the same application. Do not revoke an existing grant unless that
impact is intended. A selected-file token grants no full access until the
additional consent has been completed and verified.

For a custom Desktop client, enable the Google Picker API in its Cloud project.
Existing selected-file credentials retain their original client and account.
Later selections cannot silently replace them with another account's token.
See [selected-file onboarding](getting-started.md#access-only-selected-documents)
and the [selection protocol](protocol.md#document-access-and-selection).

### Environment name migration and validation

Application-owned environment variables exclusively use `GDOCS_SCOPE_MCP_*`.
Replace `GOOGLE_DOCS_MCP_*` names in MCP host configuration and shell commands
with their corresponding new names. The old prefix, `GOOGLE_DRIVE_MCP_*`
aliases, and `GOOGLE_DOCS_TOKEN_FILE` are ignored, including when their values
are invalid. There is no compatibility fallback to these variables.
The former `GOOGLE_DOCS_USE_DRIVE` and `GOOGLE_DOCS_DRIVE_ID` switches are now
`GDOCS_SCOPE_MCP_USE_DRIVE` and `GDOCS_SCOPE_MCP_DRIVE_ID`.

Restart the server after changing its environment. JSON keys and token/config
locations are unchanged; this migration does not move or rewrite existing
files. `XDG_CONFIG_HOME`, `GOG_KEYRING_PASSWORD`, and existing
`GDOCS_SCOPE_MCP_*` live-test controls retain their meanings. Former Apps Script
bridge settings remain unused; no replacement bridge variable is introduced.

- An explicitly empty, whitespace-only, or missing `GDOCS_SCOPE_MCP_CONFIG`
  file selection fails rather than falling back to another config.
- `GDOCS_SCOPE_MCP_LOG_LEVEL` accepts the documented levels case-insensitively,
  with surrounding whitespace ignored. Empty and unknown levels fail.
- Typed Settings overrides retain field validation and environment-over-JSON
  precedence. Empty client IDs, fonts, booleans, numeric values, enums, colors,
  and list strings are invalid; a provided override is not silently discarded.
- Empty optional `TOKEN`, `CLIENT_SECRET`, `USE_DRIVE`, and `DRIVE_ID` values
  mean unset. Whitespace-only values fail when consumed. A nonempty explicit
  token path that is unreadable or contains malformed JSON fails without
  trying another token source.
- Environment client IDs are trimmed. The authorization CLI keeps its existing
  credentials-file, CLI, environment, JSON, and bundled-client priority;
  credentials JSON supplies its own pair without consulting lower-priority
  client overrides.

## Drive listing

These environment variables affect `docs_list`; they are separate from JSON
server settings and must remain unchanged while following a pagination token:

| Variable | Default | Effect |
| --- | --- | --- |
| **`GDOCS_SCOPE_MCP_USE_DRIVE`** | `false` | Set to `true` to include shared-drive items |
| **`GDOCS_SCOPE_MCP_DRIVE_ID`** | Unset | Select one shared-drive corpus and enable shared-drive support |

`USE_DRIVE` accepts `true` or `false` case-insensitively; other nonempty values
fail before authentication. A nonempty `DRIVE_ID` enables shared-drive support
even when `USE_DRIVE=false`.

## Document snapshot cache

The document snapshot cache is disabled by default. Enable it explicitly with
`document_cache_enabled: true` in JSON configuration or
`GDOCS_SCOPE_MCP_DOCUMENT_CACHE_ENABLED=true` in the server environment.
When enabled, the server caches full native document responses on disk for
repeated reads across MCP processes and Codex chats. Before every reuse it requests only
`revisionId` from Google, validating current access and revision. An unchanged
document needs one small request; a changed document needs that revision check
followed by a full download. A cold or expired entry needs only a full download.
Google credential refresh and Markdown conversion still run; this cache avoids
repeated document downloads, not all read costs.

Revision-only requests can be nearly as slow as full reads for large documents;
when a cached document changes, the extra request can make reading slower than
with caching disabled. See the [live measurements](development/cache-validation.md).

The default limits when enabled are
300 seconds, 128 entries and 32 MiB of serialized snapshot payloads. TTL must be
between 1 and 86399 seconds, below Google's documented 24-hour revision validity
window. Entry and byte limits must be positive integers. Oversized documents
are returned normally without being cached; least recently used entries are
evicted when necessary.

The disk backend uses `snapshots-v1.sqlite3` in the platform's user cache
directory (`~/.cache/gdocs-scope-mcp` on Linux, respecting `XDG_CACHE_HOME`).
Override it with `document_cache_directory`. Document snapshots are stored as
plain native JSON in a database created with owner-only file permissions.
OAuth tokens are not stored; grant identity uses a hash of the credentials.
Use a local filesystem supporting native file locks.

`document_cache_database_max_bytes` limits the SQLite database file itself,
including database pages, to 64 MiB by default (minimum: 1 MiB). SQLite's page
limit rounds down to a 4096-byte boundary. Eviction and automatic vacuum reclaim
space; reducing this limit may discard cached snapshots. Documents that cannot
fit are returned without being cached. The separate payload limit still
applies. Small lock files and transient SQLite rollback journals are outside
the main database file limit. The file limit is enforced on every connection;
processes sharing a directory should use the same cache settings.

Set `document_cache_storage` to `memory` for process-local storage, or set
`document_cache_enabled` to `false` to bypass both backends. The database-size
setting applies only to disk storage.

Entries are isolated by OAuth grant, document ID and native request options,
including suggestion mode and whether all tabs are included. A full all-tabs
response can serve different local tab selections without caching parsed or
rendered state. Each use receives independent data, so parsing cannot mutate
the stored snapshot. Concurrent same-document reads share a full download.

Missing revisions disable reuse, including for readers without edit access.
Revision-check failures evict affected entries and propagate the error without
returning cached content. Every attempted local Docs batch invalidates all
variants for that account/document, including rejected, partial and uncertain
writes. External edits are detected at the next revision check. Existing
required/target revision guards remain in effect: the revision check is not a
lock against edits that happen after it.

Disk entries and invalidations are shared across local MCP processes using the
same directory. Document locks serialize same-document downloads and local
writes across those processes; short SQLite transactions do not hold the
database lock during Google requests. Up to 64 persistent lock files bound
coordination overhead; unrelated documents can occasionally share a lock stripe.
The memory backend shares data only within its process.

Native comment reads and field-masked requests bypass caching. With the cache
wrapper enabled, INFO logs distinguish native `document_get=revision`,
`document_get=document` and `document_get=partial` calls, with execution status
and `duration_ms`. This timer covers only the Google client's `execute()`
(including HTTP and client JSON decoding), after request construction and
outside our cache/SQLite handling and document conversion. Failed requests are
timed too. The existing `snapshot_cache=hit/miss` records report serialized
snapshot size and the broader cache-operation duration; deserialization of a
cached snapshot and subsequent Markdown conversion happen afterward. No
document IDs, revisions, URLs, content or exception details are logged by
these timings. See the [Google Docs revision contract](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents#Document).

## Logging

- **`GDOCS_SCOPE_MCP_LOG_LEVEL`** — Controls application log verbosity. Accepts
  `DEBUG`, `INFO` (default), `WARNING`, `ERROR` or `CRITICAL`, case-insensitively.
  Surrounding whitespace is ignored; empty or unknown values fail. Restart
  after changing it. See
  [diagnostics and logging](development.md#server-diagnostics-and-logging).

## Live-test target

These are test-run settings, not MCP tool arguments or ordinary server settings.

- **`GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER`** — Enables live tests and selects the
  folder for uniquely named, per-test disposable documents. Unset by default;
  without it, live tests skip.
- **`GDOCS_SCOPE_MCP_LIVE_KEEP_ON_FAILURE`** — Set to `1` to retain disposable
  test documents after failures for inspection. Otherwise the fixture moves
  them to trash.

See [live verification](development.md#live-verification).
