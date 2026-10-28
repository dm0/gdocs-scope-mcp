# Server configuration

[README](../README.md) · [Getting started](getting-started.md) · [Result contracts](protocol.md)

An optional JSON config sets editing behavior and code formatting. By default, the
server reads `~/.config/gdocs-scope-mcp/config.json`, or
`$XDG_CONFIG_HOME/gdocs-scope-mcp/config.json` when `XDG_CONFIG_HOME` is set.
Select another file with `GOOGLE_DOCS_MCP_CONFIG=/absolute/path/config.json`.
An absent default file is allowed; an explicitly selected file must exist.

```json
{
  "write_revision_mode": "required",
  "table_snapshot_ttl_seconds": 86400,
  "code_font_family": "Roboto Mono",
  "inline_code_color": "#188038",
  "code_block_highlighting": true,
  "code_block_style": "default",
  "code_block_line_spacing": 1.0,
  "code_block_theme_background": false,
  "code_block_named_ranges": true,
  "read_inline_code": true,
  "read_inline_code_fonts": null,
  "read_inline_code_colors": null,
  "read_inline_code_match": "both",
  "read_code_block_heuristic": true,
  "read_native_code_blocks": true,
  "read_code_block_fonts": null,
  "read_code_block_line_spacing": 1.0,
  "read_code_block_require_background": false,
  "read_code_block_min_lines": 2
}
```

All fields are optional; the example shows the built-in defaults.
`write_revision_mode` selects `required` (validated retries, default) or
`target` (Google merges concurrent changes, including overlaps). Target mode
does not provide our local unchanged-target guarantee and never retries a
rejected/expired target revision. `expected_revision_id` always forces strict
required mode without retries. Multi-stage table insertion always retains
required revisions to avoid using stale cursors after a transformed stage.
`docs_table_patch`, `docs_table_format` and `docs_table_structure` also always
use strict required revisions, independently of this general setting.
See [concurrent edit policies and limitations](concurrent-edits.md).

`table_snapshot_ttl_seconds` sets the lifetime of selective table expectations,
from 1 to 604800 seconds (default: 86400). Table position refs have no time expiry.

The font applies to inline code and blocks; `inline_code_color` applies only
to inline code.
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
| `GOOGLE_DOCS_MCP_WRITE_REVISION_MODE` | `write_revision_mode` | `required` |
| `GOOGLE_DOCS_MCP_TABLE_SNAPSHOT_TTL_SECONDS` | `table_snapshot_ttl_seconds` | `86400` |
| `GOOGLE_DOCS_MCP_CODE_FONT_FAMILY` | `code_font_family` | `Roboto Mono` |
| `GOOGLE_DOCS_MCP_INLINE_CODE_COLOR` | `inline_code_color` | `#188038` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_HIGHLIGHTING` | `code_block_highlighting` | `true` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_STYLE` | `code_block_style` | `default` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_LINE_SPACING` | `code_block_line_spacing` | `1.0` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_THEME_BACKGROUND` | `code_block_theme_background` | `false` |
| `GOOGLE_DOCS_MCP_CODE_BLOCK_NAMED_RANGES` | `code_block_named_ranges` | `true` |
| `GOOGLE_DOCS_MCP_READ_INLINE_CODE` | `read_inline_code` | `true` |
| `GOOGLE_DOCS_MCP_READ_INLINE_CODE_FONTS` | `read_inline_code_fonts` | `null` (insertion font) |
| `GOOGLE_DOCS_MCP_READ_INLINE_CODE_COLORS` | `read_inline_code_colors` | `null` (insertion color) |
| `GOOGLE_DOCS_MCP_READ_INLINE_CODE_MATCH` | `read_inline_code_match` | `both` |
| `GOOGLE_DOCS_MCP_READ_CODE_BLOCK_HEURISTIC` | `read_code_block_heuristic` | `true` |
| `GOOGLE_DOCS_MCP_READ_NATIVE_CODE_BLOCKS` | `read_native_code_blocks` | `true` |
| `GOOGLE_DOCS_MCP_READ_CODE_BLOCK_FONTS` | `read_code_block_fonts` | `null` (insertion font) |
| `GOOGLE_DOCS_MCP_READ_CODE_BLOCK_LINE_SPACING` | `read_code_block_line_spacing` | `1.0` |
| `GOOGLE_DOCS_MCP_READ_CODE_BLOCK_REQUIRE_BACKGROUND` | `read_code_block_require_background` | `false` |
| `GOOGLE_DOCS_MCP_READ_CODE_BLOCK_MIN_LINES` | `read_code_block_min_lines` | `2` |

Font/color lists in environment variables use JSON arrays, for example
`GOOGLE_DOCS_MCP_READ_CODE_BLOCK_FONTS='["Roboto Mono", "Consolas"]'`.

Precedence is per-call overrides (theme/background only), environment, JSON
file, then built-in defaults. Server settings are
loaded and validated at server startup and cached for that process. Restart
the MCP server after changing the file or environment. This config
includes concurrency, table snapshot lifetime and code formatting. Authentication, Drive and logging
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

## Auth environment variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_DOCS_MCP_TOKEN` | Path to token file (preferred for standalone use) |
| `GOOGLE_DOCS_MCP_CLIENT_ID` | Optional OAuth client ID override |
| `GOOGLE_DOCS_MCP_CLIENT_SECRET` | Optional OAuth client secret override |
| `GOOGLE_DOCS_TOKEN_FILE` | Legacy alias |
| `GOG_KEYRING_PASSWORD` | Auto-export from gog CLI (for personal/OpenClaw use) |

Legacy `GOOGLE_DRIVE_MCP_*` env var aliases still work for retained settings.
The removed Apps Script bridge IDs (`GOOGLE_DOCS_MCP_APPS_SCRIPT_ID` and its
Drive-prefixed alias) are no longer used; native comments need no bridge.

Token resolution checks the preferred token environment variables, the legacy
`GOOGLE_DOCS_TOKEN_FILE`, `~/.google-docs-mcp/token.json`, the older
`~/.google-drive-mcp/token.json`, then gog export/cache. OAuth client overrides
accept the corresponding legacy `GOOGLE_DRIVE_MCP_CLIENT_ID` and
`GOOGLE_DRIVE_MCP_CLIENT_SECRET` aliases. See [authentication](getting-started.md#3-authenticate).

## Drive listing

These environment variables affect `docs_list`; they are separate from JSON
server settings and must remain unchanged while following a pagination token:

| Variable | Default | Effect |
| --- | --- | --- |
| `GOOGLE_DOCS_USE_DRIVE` | `false` | Set to `true` to include shared-drive items |
| `GOOGLE_DOCS_DRIVE_ID` | Unset | Select one shared-drive corpus and enable shared-drive support |

## Logging

Set `GOOGLE_DOCS_MCP_LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR` or `CRITICAL`. Restart after changing it. See [diagnostics and logging](development.md#server-diagnostics-and-logging).

## Live-test target

`GDOCS_SCOPE_MCP_LIVE_TEST_DOC` enables live tests and selects their Google Doc ID. It is a test-run setting, not an MCP tool argument or ordinary server setting. See [live verification](development.md#live-verification).
