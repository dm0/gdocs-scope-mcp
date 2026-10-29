# Development and diagnostics

[README](../README.md) · [Configuration](configuration.md) · [Result contracts](protocol.md)

## Local development

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

## FastMCP client CLI

For shell access to document operations, use the FastMCP client CLI against
the server rather than a separate editing interface:

```bash
uv run --locked fastmcp call --command gdocs-scope-mcp \
  --target docs_read --input-json '{"doc_id":"YOUR_DOCUMENT_ID"}' --json
```

Run this from the project checkout. Each invocation launches a separate STDIO
server process and uses the MCP tools' input validation and response contracts.
The former `python -m gdocs_scope_mcp.docs_edit` editing CLI has been removed.

For discovery and input/output schemas:

```bash
uv run --locked fastmcp list --command gdocs-scope-mcp --json
```

Use `--input-json` with `fastmcp call` for named tool arguments. Inspect both
`is_error` and `structured_content` in the CLI result. Keep protocol stdout
separate from stderr logs. Every CLI invocation starts a separate server;
independent identity calls do not identify later calls' PIDs.

## Package version

The package version is derived from Git tags by
[setuptools-scm](https://setuptools-scm.readthedocs.io/). A clean checkout at
`v0.4.0` builds as `0.4.0`; commits after that tag and tracked local changes
produce development versions. Build from a Git checkout with its version tags
available, or from a generated source distribution, which preserves the version.
The server reports the version recorded when the package was built or installed;
after changing tags or commits in an editable checkout, run
`uv sync --reinstall-package gdocs-scope-mcp` to refresh it.

## Server diagnostics and logging

### server_info

```text
server_info()
```

The read-only tool returns the installed package version,
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
GOOGLE_DOCS_MCP_TOKEN = "/home/you/.config/gdocs-scope-mcp/token.json"
GOOGLE_DOCS_MCP_LOG_LEVEL = "INFO"
```

Restart the MCP server after changing its environment. Use `INFO` to observe
successful calls; `WARNING` and higher suppress them. Our package has a separate
logger/handler, so this setting does not turn on verbose third-party logs.
Stdout remains reserved for MCP protocol traffic. Codex captures the server's
stderr in its logs.

## Live verification

The Drive-to-Docs mechanism and retained embedded copy after source deletion
were verified on the designated development document. Optional live regressions
upload only a generated fixture image, temporarily share it, edit the explicitly
selected test document and remove the source files:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_DOC='your-test-document-id' \
  uv run --locked pytest -q tests/test_live_drive_images.py tests/test_live_tables.py
```

`GDOCS_SCOPE_MCP_LIVE_TEST_DOC` both enables live tests and selects their target.
Pass the raw Google Doc ID, not a URL. There is no hard-coded target or fallback.
When the variable is unset, live tests are skipped; an empty value, URL or
whitespace fails before accessing Google. The former
`GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES` flag is no longer used.

Choose a disposable document that you are authorized to modify. Test insertions
remain in the document; temporary source images are deleted. Follow any workspace
authorization rules before opting in. Ordinary unit tests remain offline.

For linked-worktree verification, run from that worktree using its environment.
Launch an isolated STDIO process; do not reconfigure or restart a user's normal
MCP connection. Permanent multi-step tests use the shared `isolated_mcp` and
`table_probe` fixtures. Verify `server_info` package path and source fingerprint,
capture stderr, read back native properties, and always close/reap test servers.
Observe each fixture's cleanup contract: several insertion suites retain their
insertions, while table probe fixtures restore the initial body. Live tests
require authorization for the explicitly selected document.

## Implementation notes

See the [implementation notes index](development/implementation-notes.md) for
internal design, concurrency guarantees, table references and API probe results,
including links to reproduction and verification procedures. Historical
research is identified separately from current implementation contracts.
