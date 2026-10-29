# Getting started

[README](../README.md) · [Configuration](configuration.md) · [Result contracts](protocol.md)

## Installation and authentication

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

**Or provide a Desktop client ID without a secret:**
```bash
export GOOGLE_DOCS_MCP_CLIENT_ID="your-google-client-id"

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

**Complete authorization in a separate CLI invocation:**
```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --client-id YOUR_DESKTOP_CLIENT_ID \
  --prepare --session ~/.config/gdocs-scope-mcp/pending-session.json

# Open the printed URL, consent, then copy the FULL loopback redirect URL.
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --session ~/.config/gdocs-scope-mcp/pending-session.json \
  --callback-url 'http://127.0.0.1:PORT/oauth2/callback?code=...&state=...'
```

All modes use PKCE S256 and a fresh, independent state. Local browser mode
binds only to `127.0.0.1` on an available port. The listener closes on success,
failure, cancellation, or timeout (300 seconds by default; set `--timeout`).
Use the system browser, not an embedded webview.

Headless mode keeps the original verifier and state in a private session file.
The default path is next to the output token, with suffix `.oauth-session.json`;
override it with `--session`. The full redirect URL is required even if the
browser cannot connect to that loopback address. Expired sessions cannot be
completed. Completion consumes the session once, including on a rejected
callback; interrupted interactive input deletes its session. An abandoned
`--prepare` file can be deleted manually before starting again.

The old `--code` option is an alias for `--callback-url`; a bare authorization
code without its original PKCE session is rejected. Session files contain a
verifier and must not be shared, logged or committed. Token files contain no
verifier or state. On Windows, restrict their directory to your OS account;
POSIX modes do not replace Windows ACLs.

`gdocs-scope-mcp-auth` resolves the client in this order:

1. `--credentials /path/to/credentials.json`
2. `--client-id`
3. `GOOGLE_DOCS_MCP_CLIENT_ID` (or its legacy Drive alias)
4. `client_id` in the JSON settings file
5. The project-managed Desktop client

The distribution includes the project's public Desktop client ID. Run
`gdocs-scope-mcp-auth` without client options to use it. While its Google Cloud
project is in Testing, the account used for consent must be an allowed test user.

A secret is optional for a custom client (`--client-secret`, environment, or
the credentials JSON); existing secret-bearing token files remain supported.
For ID-only authorization, neither code exchange nor refresh sends
`client_secret`. A failed exchange is reported without falling back to a flow
without PKCE. Tokens marked `pkce-public` ignore ambient secret overrides when
refreshed. Live acceptance of ID-only login and refresh must be checked against
the actual registered Desktop client before distributing it as the default.

New tokens are saved to `$XDG_CONFIG_HOME/gdocs-scope-mcp/token.json`, falling
back to `~/.config/gdocs-scope-mcp/token.json` when `XDG_CONFIG_HOME` is absent,
empty or relative. Override the authorization output with `--out` and point
the server at that file with `GOOGLE_DOCS_MCP_TOKEN`.
The session examples above assume the default XDG directory.

The CLI and server share the JSON settings path (including
`GOOGLE_DOCS_MCP_CONFIG`). To override the built-in client, add:

```json
{
  "client_id": "YOUR_DESKTOP_CLIENT_ID.apps.googleusercontent.com"
}
```

Existing tokens retain their originating client ID; changing the setting does
not migrate a refresh token to another client. The server uses configuration
only when a token file contains no client ID. Legacy default token files in
`~/.google-docs-mcp/` and `~/.google-drive-mcp/` remain readable after the new
default location is checked. No old token files are moved or rewritten.

### Project-managed client distribution

Register a **Desktop app** client in the application's Google Cloud project,
enable Docs API and Drive API, and configure the consent screen, audience and
test users. The public client ID may be distributed in source; never commit a
client secret or a user's token. Custom client overrides remain available.
Registration is independent of where the MCP process runs.

The project owner manages OAuth branding, production verification, quotas and
client lifecycle. Multiple installations using the shared project consume its
project-level API quotas, in addition to per-user limits. Use a separate
development client/project when appropriate; changing the default client does
not migrate existing user grants or refresh tokens.

Publishing the consent screen and completing verification are separate steps.
The current broad Drive scopes include restricted access, so public
distribution requires reviewing Google's applicable verification requirements.
PKCE does not change the scope classification. Selected-file access belongs to
the separate Google Picker/access-mode work.

See Google's [Desktop OAuth flow](https://developers.google.com/identity/protocols/oauth2/native-app),
[production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview),
and [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

### 4. Configure your MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dm0/gdocs-scope-mcp", "gdocs-scope-mcp"],
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.config/gdocs-scope-mcp/token.json"
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
          "GOOGLE_DOCS_MCP_TOKEN": "/home/you/.config/gdocs-scope-mcp/token.json"
        }
      }
    }
  }
}
```

## Local checkout client configuration

```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/gdocs-scope-mcp", "gdocs-scope-mcp"],
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.config/gdocs-scope-mcp/token.json"
      }
    }
  }
}
```

## Migrating from google-docs-mcp

Install this repository and update your MCP launch command to `gdocs-scope-mcp`.
Authenticate with `gdocs-scope-mcp-auth`.
The old `google-docs-mcp` and `google-drive-mcp` CLI aliases are not installed,
so this project can coexist with the original package.

Existing `GOOGLE_DOCS_MCP_*` settings, legacy `GOOGLE_DRIVE_MCP_*` aliases,
and reading the legacy token path `~/.google-docs-mcp/token.json` are retained.
Existing credentials can be reused without re-authenticating just for the rename.

## Scopes

The auth setup requests these scopes:

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/documents` | Read and write Google Docs |
| `https://www.googleapis.com/auth/drive` | Access Drive files |
| `https://www.googleapis.com/auth/drive.readonly` | Read Drive file metadata |
| `https://www.googleapis.com/auth/drive.file` | Per-file Drive access |

---

New authorizations request neither identity scopes (`openid`, `email`,
`profile`) nor Apps Script scopes. Authorization does not fetch account profile
data, store an email address, or require identity data to report success.
Native comments use the Docs API. Configurable per-file access is separate work.

Existing token files, including those with identity scopes and an `email` field,
remain usable without modification. Changing requested scopes does not revoke
previously granted permissions. To obtain a fresh grant without identity scopes:

1. Remove this application's access in your
   [Google Account connections](https://myaccount.google.com/connections).
   This interrupts other clients using the same application grant.
2. Run the updated `gdocs-scope-mcp-auth` command with your OAuth client settings
   and the intended `--out` token path, then complete consent again.
3. Restart MCP processes using that token file so they load the new credentials.

Deleting a local token file alone does not revoke the Google Account grant.

See [configuration](configuration.md#auth-environment-variables) for token and
OAuth environment variables, [development](development.md) for a source
checkout, and [native comment tools](tools/comments.md) for comment workflows.
