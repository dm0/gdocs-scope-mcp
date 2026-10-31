"""Resolve Desktop clients and install verified credentials atomically."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gdocs_scope_mcp.google_api import oauth
from gdocs_scope_mcp.google_api.access import require_selected_scopes
from gdocs_scope_mcp.settings import (
    default_token_path,
    get_settings,
    optional_env,
)


def token_path():
    """Resolve the same explicit token destination as the server loader."""
    configured = optional_env('GDOCS_SCOPE_MCP_TOKEN')
    return (Path(configured).expanduser() if configured
            else default_token_path())


def client_pair():
    """Resolve a configured Desktop pair without rebinding saved tokens."""
    configured = optional_env('GDOCS_SCOPE_MCP_CLIENT_ID')
    client = configured.strip() if configured else get_settings().client_id
    secret = optional_env('GDOCS_SCOPE_MCP_CLIENT_SECRET')
    if not client:
        return oauth.PROJECT_CLIENT_ID, secret or oauth.PROJECT_CLIENT_SECRET
    if client == oauth.PROJECT_CLIENT_ID:
        secret = secret or oauth.PROJECT_CLIENT_SECRET
    return client, secret


def generation(path):
    """Identify destination contents without retaining credential material."""
    return (hashlib.sha256(path.read_bytes()).hexdigest()
            if path.exists() else '')


def destination_lock(path):
    """Serialize authorization attempts targeting the same credential file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path) + '.lock', timeout=0, thread_local=False)


def token_data(tokens, session, secret):
    """Build refresh data, requiring explicit narrow exchange evidence."""
    scopes = tokens.get('scope', ' '.join(session.scopes)).split()
    if session.picker:
        require_selected_scopes(tokens.get('scope', '').split())
    data = {
        'client_id': session.client_id,
        'refresh_token': tokens['refresh_token'], 'scopes': scopes,
        'token_uri': oauth.TOKEN_URI,
        'auth_method': 'pkce-secret' if secret else 'pkce-public',
    }
    if secret:
        data['client_secret'] = secret
    return data


def verify_selection(tokens, session, secret, file_ids, previous):
    """Verify account, file metadata and scopes before installing a grant."""
    data = token_data(tokens, session, secret)
    creds = Credentials(token=tokens['access_token'], scopes=data['scopes'])
    drive = build('drive', 'v3', credentials=creds, cache_discovery=False)
    account = drive.about().get(fields='user(permissionId)').execute()
    account_id = account.get('user', {}).get('permissionId')
    if not isinstance(account_id, str) or not account_id:
        raise oauth.AuthorizationError('Could not verify selected account.')
    if previous:
        require_selected_scopes(previous.get('scopes'))
        if (previous.get('client_id') != session.client_id
                or previous.get('account_id') != account_id):
            raise oauth.AuthorizationError('Account or client mismatch.')
    documents = []
    for file_id in file_ids:
        item = drive.files().get(
            fileId=file_id, fields='id,name,mimeType,webViewLink,trashed',
            supportsAllDrives=True,
        ).execute()
        if (item.get('id') != file_id or item.get('trashed')
                or item.get('mimeType')
                != 'application/vnd.google-apps.document'
                or not isinstance(item.get('name'), str)):
            raise oauth.AuthorizationError('Invalid selected document.')
        documents.append({
            'id': file_id, 'name': item['name'],
            'url': f'https://docs.google.com/document/d/{file_id}/edit',
        })
    data.update(access_mode='selected_files', account_id=account_id)
    return data, documents


def install_token(path, data, expected):
    """Replace a private token only if its generation is unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if generation(path) != expected:
        raise oauth.AuthorizationError('Credentials changed during selection.')
    descriptor, name = tempfile.mkstemp(prefix='.token-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
