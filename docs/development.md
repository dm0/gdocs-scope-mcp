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
`pip install -e . pytest pytest-socket`.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes to any branch, pull requests, and
manual dispatch. Branch pushes are sufficient; a PR is not required. Push
events for tags are excluded. A same-repository branch push followed by a PR
can produce separate runs. No package publishing, releases, or branch-protection
changes are performed.

The Ubuntu 24.04 matrix covers every stable minor version from Python 3.10
(the declared minimum) through 3.14: 3.10, 3.11, 3.12, 3.13, and 3.14.
Each job installs runtime and development dependencies from
`uv.lock`, runs the complete offline suite including architecture/MCP contract
checks, builds wheel and sdist, and verifies isolated installations of both.
The artifact helper explicitly discovers both static catalogs, `v1` and `v2`,
from source and from each installation. It checks the required and excluded
tool names for each version and compares each installed catalog with source.
Temporary MCP configurations pass the selected toolset, an empty application
config, and a missing token path directly to each child server, isolating the
checks from user settings and the CLI's filtered environment inheritance.
Checkout fetches full history and tags for setuptools-scm version discovery.
Third-party actions are pinned to full commit SHAs, uv to 0.12.18, and Ruff
to 0.17.3. Update pins deliberately and repeat the commands below.

Ruff configuration lives in `pyproject.toml` and includes the existing machine's
rule selections, ignores, 79-character line limit, single inline quotes,
NumPy docstrings, import settings, and default exclusion of `tests/`. Source
and CI scripts are linted normally; CI test infrastructure is passed as explicit
file paths to check it despite that directory exclusion. Use the same approach
for other changed tests. Ruff is installed as a standalone tool, not a project
dependency.

Run the CI commands from the repository root:

```bash
uv sync --locked
ruff check --config pyproject.toml src .github/scripts
ruff check --config pyproject.toml tests/conftest.py tests/test_ci_network.py
uv run --locked pytest -q -m "not live" --strict-markers --disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,::1
uv build
uv run --locked python .github/scripts/check_artifacts.py dist
```

Use `UV_PYTHON=3.10` through `UV_PYTHON=3.14` to select a matrix interpreter. For
parallel local runs, set `UV_PROJECT_ENVIRONMENT=.venv-ci/3.10` or
`.venv-ci/3.14` consistently on all uv commands for that run. These are separate
environments for this checkout; do not borrow another checkout's environment.
Use a clean output directory containing exactly one wheel and one sdist for
artifact checks. The helper accepts a different build output directory as its
argument.

CI supplies no Google credentials or live-test document. `pytest-socket`
restricts test-process sockets to loopback and Unix sockets, retaining real
local OAuth callback tests while blocking external connects. The CI network
regression confirms that block without contacting Google. The restriction is
not an operating-system sandbox for arbitrary child processes. STDIO discovery
smokes call only `server_info` and tool listing, with an explicit missing token
path, and never invoke document operations. Live tests require the separate
explicit development-document opt-in described below.

The artifact helper compares every Python source module with both archives,
checks their version metadata, then installs each in its own temporary virtual
environment using locked runtime constraints. It runs the authorization CLI's
help and discovers tools through the installed server's console entry point,
checking the installed package path/version and the entire catalog against the
worktree. Temporary environments are removed on completion or failure.

References: [uv GitHub Actions integration](https://docs.astral.sh/uv/guides/integration/github/),
[pytest-socket](https://github.com/miketheman/pytest-socket).

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

Set `GDOCS_SCOPE_MCP_LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`,
or `CRITICAL`. For example:

```bash
GDOCS_SCOPE_MCP_LOG_LEVEL=DEBUG uv run gdocs-scope-mcp
```

For a Codex STDIO connection, add the variable to the server's environment:

```toml
[mcp_servers.gdocs_scope.env]
GDOCS_SCOPE_MCP_TOKEN = "/home/you/.config/gdocs-scope-mcp/token.json"
GDOCS_SCOPE_MCP_LOG_LEVEL = "INFO"
```

Restart the MCP server after changing its environment. Use `INFO` to observe
successful calls; `WARNING` and higher suppress them. Our package has a separate
logger/handler, so this setting does not turn on verbose third-party logs.
Stdout remains reserved for MCP protocol traffic. Codex captures the server's
stderr in its logs.

## Live verification

Live scenarios have the registered `live` pytest marker. Ask pytest for their
collected node IDs, including every parameter combination, or select the offline
suite explicitly:

```bash
uv run --locked pytest --collect-only -q -m live --strict-markers
uv run --locked pytest -q -m "not live" --strict-markers
```

The marker selects tests; it does not grant Google access or replace the
existing opt-in environment variables. Fixture-configuration tests remain
offline even though their module name includes `live`. The table-identity probe
module also keeps its two pure helper tests in the offline selection.

The Drive-to-Docs mechanism and retained embedded copy after source deletion
were verified on the designated development document. Optional live regressions
upload only a generated fixture image, temporarily share it, edit a per-test
disposable document and remove the source files:

```bash
GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER='your-test-folder-id' \
  uv run --locked pytest -q -m live --strict-markers
```

`GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER` is required for all live tests. Pass a raw
folder ID, not a URL. When unset, live tests skip; an empty value, URL or
whitespace fails before accessing Google. The folder must be accessible to the
test credentials and allow adding children. With selected-file access, the
folder must also be available to the app. No folder is selected implicitly.
The old `GDOCS_SCOPE_MCP_LIVE_TEST_DOC` and `GDOCS_SCOPE_MCP_LIVE_CREATE`
settings no longer enable tests. The document ID variable is now populated
internally for each test's isolated probe servers. Older examples elsewhere
that set only a document ID must instead set the folder variable above.

The bounded search smoke additionally requires `GDOCS_SCOPE_MCP_LIVE_SEARCH=1`.
The folder opt-in authorizes fixture-owned document creation and trashing.
Optional manual UI waits remain disabled
unless explicitly enabled. Release verification runs both the complete offline
suite and every authorized automated live scenario; use unfiltered `pytest`
with the corresponding opt-ins for the final combined release run.

Each document-based test receives a fresh Google Doc with a UTC timestamp and
UUID in its name. The fixture creates it directly in the configured folder
through Drive API and records the confirmed ID before validating metadata.
The dedicated creation and interactive additional-selection scenarios use
`docs_create` over isolated STDIO MCP instead, then move their confirmed IDs
into the folder. Folder support is test infrastructure only;
`docs_create` has no new arguments. Concurrent runs use independent documents.
The interactive additional-selection scenario needs two documents and obtains
both through the same factory. Read-only listing tests do not need a document.

After each test and its dependent fixture teardowns, cleanup verifies the
created ID, name and MIME type, moves the document to trash and reads back
`trashed=true`. Setup failures and handled interruption also trigger cleanup.
Set `GDOCS_SCOPE_MCP_LIVE_KEEP_ON_FAILURE=1` to retain documents when setup,
the test or fixture teardown fails; successful tests still trash their documents.
The default is `0`; other values fail before Google access. Existing per-test
content restoration still runs, so retention does not promise an exact snapshot
of the failure. A killed process or host failure cannot execute cleanup.

The JUnit test property `live_document_report` points to
`/tmp/gdocs-scope-mcp-live-test-*/report.json`. Reports include confirmed IDs,
unique titles and cleanup/retention status. MCP-based creation also records
server identity and process reaping, with stderr in the same directory.
IDs are recorded even if
initial insertion or folder placement fails. If creation times out without
returning an ID, inspect the folder and My Drive by the unique name; creation
is never replayed. Follow workspace authorization rules before opting in.
Temporary source images retain their own fixture cleanup.

For linked-worktree verification, run from that worktree using its environment.
Launch an isolated STDIO process; do not reconfigure or restart a user's normal
MCP connection. Permanent multi-step tests use the shared `isolated_mcp` and
`table_probe` fixtures. Verify `server_info` package path and source fingerprint,
capture stderr, read back native properties, and always close/reap test servers.
Within a session, individual fixtures still verify their local contracts:
table probes restore their initial body and temporary-tab tests verify other
tabs are unchanged. Session teardown then removes all remaining insertions.
Live tests require authorization to erase the explicitly selected document.

## Implementation notes

See the [implementation notes index](development/implementation-notes.md) for
internal design, concurrency guarantees, table references and API probe results,
including links to reproduction and verification procedures. Historical
research is identified separately from current implementation contracts.
