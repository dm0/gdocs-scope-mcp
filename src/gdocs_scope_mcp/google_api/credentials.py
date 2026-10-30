"""Load and refresh credentials using the established token precedence."""


import json
import logging
import os
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from gdocs_scope_mcp.google_api.oauth import PublicClientCredentials
from gdocs_scope_mcp.settings import (
    default_token_path,
    get_settings,
    optional_env,
)

log = logging.getLogger(__name__)

STANDALONE_TOKEN_PATHS = [
    Path.home() / '.google-docs-mcp' / 'token.json',
    Path.home() / '.google-drive-mcp' / 'token.json',
]
TOKEN_ENV_VAR = 'GDOCS_SCOPE_MCP_TOKEN'
CLIENT_ID_ENV_VAR = 'GDOCS_SCOPE_MCP_CLIENT_ID'
CLIENT_SECRET_ENV_VAR = 'GDOCS_SCOPE_MCP_CLIENT_SECRET'
GOG_CREDENTIALS_PATH = Path('/config/gogcli/credentials.json')
GOG_TOKEN_CACHE = Path('/tmp/docs_edit_token_cache.json')


def export_gog_token(email: str = 'david@harriethq.com') -> dict:
    """Export token from gog keyring using GOG_KEYRING_PASSWORD env var."""
    password = os.environ.get('GOG_KEYRING_PASSWORD')
    if not password:
        raise RuntimeError('GOG_KEYRING_PASSWORD not set')
    env = {**os.environ, 'GOG_KEYRING_PASSWORD': password}
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp = f.name
    try:
        result = subprocess.run(
            ['gog', 'auth', 'tokens', 'export', email, '--out', tmp,
             '--overwrite', '-y'],
            env=env, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f'gog token export failed: {result.stderr}')
        return json.loads(Path(tmp).read_text())
    finally:
        with suppress(OSError):
            Path(tmp).unlink()


def load_token() -> dict:
    """Load explicit, default, legacy-file, exported or cached token data."""
    token_file = optional_env(TOKEN_ENV_VAR)
    if token_file:
        return json.loads(Path(token_file).read_text())
    for token_path in [default_token_path(), *STANDALONE_TOKEN_PATHS]:
        if token_path.exists():
            return json.loads(token_path.read_text())
    try:
        token = export_gog_token()
        GOG_TOKEN_CACHE.write_text(json.dumps(token))
    except RuntimeError as e:
        log.warning('Gog auto-export failed: %s', e)
    else:
        return token
    if GOG_TOKEN_CACHE.exists():
        log.info('Using cached gog token')
        return json.loads(GOG_TOKEN_CACHE.read_text())
    raise RuntimeError(
        'No Google credentials found.\n'
        'Run: gdocs-scope-mcp-auth --credentials ~/credentials.json\n'
        'Or set GDOCS_SCOPE_MCP_TOKEN to your token file path.'
    )


def load_credentials():
    """Return refreshed google.oauth2.credentials.Credentials."""
    token_data = load_token()
    client_id = token_data.get('client_id') or token_data.get('_client_id')
    client_secret = token_data.get('client_secret') or token_data.get(
        '_client_secret'
    )
    token_uri = token_data.get('token_uri') or token_data.get(
        '_token_uri', 'https://oauth2.googleapis.com/token'
    )
    if not client_id:
        configured = optional_env(CLIENT_ID_ENV_VAR)
        client_id = (configured.strip() if configured
                     else get_settings().client_id)
    public_client = token_data.get('auth_method') == 'pkce-public'
    if public_client:
        client_secret = None
    else:
        client_secret = client_secret or optional_env(CLIENT_SECRET_ENV_VAR)
    if not client_id and not public_client and GOG_CREDENTIALS_PATH.exists():
        gog_creds = json.loads(GOG_CREDENTIALS_PATH.read_text())
        client_id = gog_creds.get('client_id')
        client_secret = gog_creds.get('client_secret')
    if not client_id:
        raise RuntimeError(
            'No OAuth client credentials found. Re-run gdocs-scope-mcp-auth '
            'to generate a self-contained token, '
            f'or set {CLIENT_ID_ENV_VAR}.'
        )
    scopes = [
        s for s in token_data.get('scopes', [])
        if s not in ('email', 'openid', 'profile')
    ]
    credential_class = (
        Credentials if client_secret else PublicClientCredentials
    )
    creds = credential_class(
        token=None, refresh_token=token_data['refresh_token'],
        token_uri=token_uri, client_id=client_id,
        client_secret=client_secret or '',
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds
