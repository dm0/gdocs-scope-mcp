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

### 2. Choose an account

The package includes the project's shared Desktop OAuth client. You do not
need to create a Google Cloud project or download credentials to use it.
While access is limited to test users, ask the project owner to add your
Google account, or [configure your own client](#choose-a-different-oauth-client).

### 3. Authenticate

Run:

```bash
gdocs-scope-mcp-auth
```

Your system browser opens. Sign in with an account that can access your
documents and approve the requested permissions. Return to the terminal and
check for **Authorisation successful** and the saved token path.

New tokens are saved to `$XDG_CONFIG_HOME/gdocs-scope-mcp/token.json`, or
`~/.config/gdocs-scope-mcp/token.json` when `XDG_CONFIG_HOME` is unset, empty or
relative. To choose another location:

```bash
gdocs-scope-mcp-auth --out /absolute/path/token.json
```

Keep your token file private. On Unix, token files are
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
        "GDOCS_SCOPE_MCP_TOKEN": "/absolute/path/to/token.json"
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
gdocs-scope-mcp-auth --headless
```

Open the printed URL in a browser, sign in and approve access. Copy the
**complete redirect URL** from the address bar and paste it into the terminal.
The browser may display a connection error for `127.0.0.1`; the URL is still
the value you need to copy. Do not share it or the pending session file.

To start and finish authorization in separate CLI invocations:

```bash
gdocs-scope-mcp-auth \
  --prepare --session /absolute/path/pending-session.json

# After approving access, replace the URL below with the full redirect URL.
gdocs-scope-mcp-auth \
  --session /absolute/path/pending-session.json \
  --callback-url 'http://127.0.0.1:PORT/oauth2/callback?code=...&state=...'
```

If using a custom client, pass its credentials to both commands. Sessions expire after
300 seconds by default; pass `--timeout SECONDS` when starting an attempt to
allow more time. Each session can be completed only once. After an expired or
failed attempt, start again. Delete an abandoned pending session file before
reusing its path.

The legacy `--code` option accepts the same complete URL as `--callback-url`.
A bare code without its original session is not supported.

## Choose a different OAuth client

To use your own Google Cloud project:

1. Select or create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Google Docs API** and **Google Drive API** under **APIs & Services → Library**.
3. Complete **Google Auth Platform → Branding** with your app name, support
   email and developer contact. Configure **Audience** and add your account
   to **Test users** while the app is in Testing.
4. Add the permissions listed in [Scopes](#scopes) under **Data Access**.
5. Create a **Desktop app** under **Clients**. Select **Use this client for an
   AI-powered agent** for agent workflows when available.
6. Download the Desktop credentials JSON, then run:

   ```bash
   gdocs-scope-mcp-auth --credentials ~/credentials.json
   ```

The authorization CLI selects the client in this order:

1. `--credentials /path/to/credentials.json`
2. `--client-id`
3. `GDOCS_SCOPE_MCP_CLIENT_ID`
4. `client_id` in the JSON settings file
5. The bundled project client ID and matching Desktop secret

For example, add this to `~/.config/gdocs-scope-mcp/config.json`, or the file
selected by `GDOCS_SCOPE_MCP_CONFIG`:

```json
{
  "client_id": "YOUR_DESKTOP_CLIENT_ID.apps.googleusercontent.com"
}
```

Selecting a custom ID does not provide its client secret. For clients that require
one, use their credentials JSON, or supply the matching secret through
`GDOCS_SCOPE_MCP_CLIENT_SECRET` together with an explicit client ID. The bundled
secret is only used with the matching bundled ID. A credentials JSON supplies
its own pair and overrides both ID and secret settings. With no client ID
override, the bundled pair is used, ignoring standalone secret overrides.

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
| The server uses an old account or client | Check `GDOCS_SCOPE_MCP_TOKEN`, then restart the MCP server. |

## Migrating from google-docs-mcp

Install this repository and change your MCP launch command to
`gdocs-scope-mcp`. The old `google-docs-mcp` and `google-drive-mcp` executable
aliases are not installed, so the packages can coexist.

Existing credentials can be reused. Explicit token environment variables take
precedence over default locations. If no explicit token path is set, the server
checks the new XDG location first, followed by `~/.google-docs-mcp/token.json`
and `~/.google-drive-mcp/token.json`. Existing files are not moved or rewritten.
Use `GDOCS_SCOPE_MCP_*` for all application environment settings. Former
`GOOGLE_DOCS_MCP_*`, `GOOGLE_DRIVE_MCP_*`, and `GOOGLE_DOCS_TOKEN_FILE` settings
are ignored. Rename existing MCP environment entries and restart the server;
the token contents, configuration JSON keys, and file locations stay unchanged.
See [migration and validation](configuration.md#environment-name-migration-and-validation).

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
2. Run `gdocs-scope-mcp-auth` again with your intended output path. If using a
   custom client, supply its credentials JSON.
3. Restart MCP processes using the new token file.

Deleting a local token file alone does not revoke the Google Account grant.
