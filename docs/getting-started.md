# Getting started

[README](../README.md) · [Configuration](configuration.md) · [Result contracts](protocol.md)

## Installation and authentication

### 1. Install

Install the server and authorization CLI with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/dm0/gdocs-scope-mcp
```

This installs `gdocs-scope-mcp` and `gdocs-scope-mcp-auth`. To install a specific
version, append a Git tag or commit to the repository URL:

```bash
uv tool install git+https://github.com/dm0/gdocs-scope-mcp@TAG_OR_COMMIT
```

Alternatively, run either command without a persistent installation:

```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp gdocs-scope-mcp-auth --help
```

The examples below use the installed commands. With `uvx`, prefix each command
with `uvx --from git+https://github.com/dm0/gdocs-scope-mcp`.

### 2. Create a Google Cloud OAuth app

Use your own Desktop OAuth credentials to authorize the server:

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or
   create a project.
2. Under **APIs & Services → Library**, enable **Google Docs API** and
   **Google Drive API**.
3. Open **Google Auth Platform → Branding** and complete the setup with your
   app name, support email and developer contact email.
4. Choose **External** if you need to sign in with accounts outside a single
   Workspace organization. While the app is in **Testing**, add the account
   you will use under **Audience → Test users**.
5. Under **Data Access**, add the permissions listed in [Scopes](#scopes).
6. Under **Clients → Create client**, select **Desktop app**. For an MCP client
   used by AI agents, select **Use this client for an AI-powered agent** when
   the option is available.
7. Download the credentials JSON and store it outside your source repository,
   for example as `~/credentials.json`.

Use a Desktop client rather than a Web application client. See Google's
[consent setup](https://developers.google.com/workspace/guides/configure-oauth-consent)
and [client creation guide](https://developers.google.com/workspace/guides/create-credentials#desktop-app)
for details.

### 3. Authenticate

Run:

```bash
gdocs-scope-mcp-auth --credentials ~/credentials.json
```

Your system browser opens. Sign in with an account that can access your
documents and approve the requested permissions. Return to the terminal and
check for **Authorisation successful** and the saved token path.

New tokens are saved to `$XDG_CONFIG_HOME/gdocs-scope-mcp/token.json`, or
`~/.config/gdocs-scope-mcp/token.json` when `XDG_CONFIG_HOME` is unset, empty or
relative. To choose another location:

```bash
gdocs-scope-mcp-auth --credentials ~/credentials.json --out /absolute/path/token.json
```

Keep the credentials JSON and token file private. On Unix, token files are
written with owner-only permissions. On Windows, restrict access to their
directory using your account's file permissions.

### 4. Configure your MCP client

Add a STDIO server entry to your MCP client's configuration. Use the absolute
token path printed by the authorization command:

```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "gdocs-scope-mcp",
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/absolute/path/to/token.json"
      }
    }
  }
}
```

If the client cannot find the executable, use its absolute path. To launch
directly from GitHub instead, replace `command` and add `args`:

```json
{
  "command": "uvx",
  "args": ["--from", "git+https://github.com/dm0/gdocs-scope-mcp", "gdocs-scope-mcp"]
}
```

For a local checkout, replace the Git URL with its absolute directory path.
Keep the same `env` entry pointing to your token. Restart or reconnect the MCP
server after changing the configuration, then ask your agent to list documents
or read one that your Google account can access.

## Authorize without a local browser

For a remote host or terminal without a browser:

```bash
gdocs-scope-mcp-auth --credentials ~/credentials.json --headless
```

Open the printed URL in a browser, sign in and approve access. Copy the
**complete redirect URL** from the address bar and paste it into the terminal.
The browser may display a connection error for `127.0.0.1`; the URL is still
the value you need to copy. Do not share it or the pending session file.

To start and finish authorization in separate CLI invocations:

```bash
gdocs-scope-mcp-auth --credentials ~/credentials.json \
  --prepare --session /absolute/path/pending-session.json

# After approving access, replace the URL below with the full redirect URL.
gdocs-scope-mcp-auth --credentials ~/credentials.json \
  --session /absolute/path/pending-session.json \
  --callback-url 'http://127.0.0.1:PORT/oauth2/callback?code=...&state=...'
```

Use the same credentials JSON for both commands. Sessions expire after
300 seconds by default; pass `--timeout SECONDS` when starting an attempt to
allow more time. Each session can be completed only once. After an expired or
failed attempt, start again. Delete an abandoned pending session file before
reusing its path.

The legacy `--code` option accepts the same complete URL as `--callback-url`.
A bare code without its original session is not supported.

## Choose a different OAuth client

The authorization CLI selects the client in this order:

1. `--credentials /path/to/credentials.json`
2. `--client-id`
3. `GOOGLE_DOCS_MCP_CLIENT_ID` (or `GOOGLE_DRIVE_MCP_CLIENT_ID`)
4. `client_id` in the JSON settings file
5. The bundled project client ID

For example, add this to `~/.config/gdocs-scope-mcp/config.json`, or the file
selected by `GOOGLE_DOCS_MCP_CONFIG`:

```json
{
  "client_id": "YOUR_DESKTOP_CLIENT_ID.apps.googleusercontent.com"
}
```

Selecting an ID does not provide its client secret. For clients that require
one, use their credentials JSON, or supply the matching secret through
`GOOGLE_DOCS_MCP_CLIENT_SECRET` together with an explicit client ID. The bundled
client ID alone is not sufficient for authorization; use the credentials-based
setup above.

Changing the configured client ID does not update an existing token's client.
To switch clients, authorize again and configure the MCP server to use the
new token file. See [configuration](configuration.md#auth-environment-variables)
for all authentication settings.

## Troubleshooting authorization

| Problem | What to do |
|---|---|
| Google requires `client_secret` | Run again with the matching Desktop credentials JSON. PKCE does not remove Google's requirement for that client. |
| Your account cannot authorize a Testing app | Add that account to the Cloud project's **Audience → Test users**. |
| Session expired or state mismatch | Start a new attempt and use the complete redirect URL from that attempt. |
| The browser did not open | Open the printed URL manually, or use `--headless`. |
| The server uses an old account or client | Check `GOOGLE_DOCS_MCP_TOKEN`, then restart the MCP server. |

## Migrating from google-docs-mcp

Install this repository and change your MCP launch command to
`gdocs-scope-mcp`. The old `google-docs-mcp` and `google-drive-mcp` executable
aliases are not installed, so the packages can coexist.

Existing credentials can be reused. Explicit token environment variables take
precedence over default locations. If no explicit token path is set, the server
checks the new XDG location first, followed by `~/.google-docs-mcp/token.json`
and `~/.google-drive-mcp/token.json`. Existing files are not moved or rewritten.
Legacy `GOOGLE_DRIVE_MCP_*` environment aliases remain supported.

## Scopes

The authorization command requests these permissions:

| Scope | Permission |
|-------|------------|
| `https://www.googleapis.com/auth/documents` | Read and write Google Docs |
| `https://www.googleapis.com/auth/drive` | View and manage Drive files |
| `https://www.googleapis.com/auth/drive.readonly` | View and download Drive files |
| `https://www.googleapis.com/auth/drive.file` | Access files created by or granted to the application |

New authorizations do not request identity scopes (`openid`, `email`, `profile`)
or Apps Script scopes. Existing tokens with these permissions remain usable.
Updating the application does not revoke previously granted access.

To replace an older grant with the current permissions:

1. Remove the application's access in
   [Google Account connections](https://myaccount.google.com/connections).
   This also interrupts other clients using the same application grant.
2. Run `gdocs-scope-mcp-auth` again with your credentials JSON and intended
   output path.
3. Restart MCP processes using the new token file.

Deleting a local token file alone does not revoke the Google Account grant.
