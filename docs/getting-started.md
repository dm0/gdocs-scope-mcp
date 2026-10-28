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

**Or use env vars instead of a credentials file:**
```bash
export GOOGLE_DOCS_MCP_CLIENT_ID="your-google-client-id"
export GOOGLE_DOCS_MCP_CLIENT_SECRET="your-google-client-secret"

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

**Already have an auth code:**
```bash
uvx --from git+https://github.com/dm0/gdocs-scope-mcp \
  gdocs-scope-mcp-auth --credentials ~/credentials.json --code "4/0Afr..."
```

`gdocs-scope-mcp-auth` resolves OAuth client credentials in this order:

1. `--credentials /path/to/credentials.json`
2. `--client-id` and `--client-secret`
3. `GOOGLE_DOCS_MCP_CLIENT_ID` and `GOOGLE_DOCS_MCP_CLIENT_SECRET`

Token is saved to `~/.google-docs-mcp/token.json` by default. Override with `--out /path/to/token.json`.

### 4. Configure your MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "gdocs-scope": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/dm0/gdocs-scope-mcp", "gdocs-scope-mcp"],
      "env": {
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.google-docs-mcp/token.json"
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
          "GOOGLE_DOCS_MCP_TOKEN": "/home/you/.google-docs-mcp/token.json"
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
        "GOOGLE_DOCS_MCP_TOKEN": "/Users/you/.google-docs-mcp/token.json"
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
and the default token path `~/.google-docs-mcp/token.json` are retained.
Existing credentials can be reused without re-authenticating just for the rename.

## Scopes

The auth setup requests these scopes:

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/documents` | Read and write Google Docs |
| `https://www.googleapis.com/auth/drive` | Access Drive files |
| `https://www.googleapis.com/auth/drive.readonly` | Read Drive file metadata |
| `https://www.googleapis.com/auth/drive.file` | Per-file Drive access |
| `openid`, `email`, `profile` | Identity |

---

New authorizations no longer request Apps Script scopes. Existing token files
remain usable; this change does not revoke previously granted permissions.
Native comments use the Docs API. Identity-scope cleanup and per-file access
are separate work.

See [configuration](configuration.md#auth-environment-variables) for token and
OAuth environment variables, [development](development.md) for a source
checkout, and [native comment tools](tools/comments.md) for comment workflows.
