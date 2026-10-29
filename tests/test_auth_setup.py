"""Verify profile-free authorization and legacy token compatibility."""

import json
import socket
import stat
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest

from gdocs_scope_mcp import auth_setup
from gdocs_scope_mcp.google_api import credentials, oauth

OWNER_READ_WRITE = 0o600


@pytest.fixture
def document_scopes():
    """Return the document permissions retained by identity cleanup."""
    return [
        'https://www.googleapis.com/auth/documents',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/drive.file',
    ]


def test_consent_requests_only_document_scopes(document_scopes):
    """New consent retains document access without requesting identity."""
    session = oauth.AuthorizationSession.create(
        'client', 'http://127.0.0.1:1234/oauth2/callback', document_scopes,
    )
    query = parse_qs(urlparse(session.authorization_url()).query)
    assert query['scope'][0].split() == document_scopes


@pytest.mark.parametrize('mode', ['local', 'headless', 'code'])
def test_authorization_saves_token_without_identity(
    tmp_path, monkeypatch, capsys, document_scopes, mode,
):
    """Every CLI flow completes with only the token exchange HTTP request."""
    out = tmp_path / 'new' / 'token.json'
    args = ['gdocs-scope-mcp-auth', '--client-id', 'client',
            '--client-secret', 'secret', '--out', str(out)]
    session_path = tmp_path / 'session.json'

    def callback_from_file(_):
        data = json.loads(session_path.read_text())
        return data['redirect_uri'] + '?code=test-code&state=' + data['state']

    pool = ThreadPoolExecutor(max_workers=1)
    requests = []

    def browser(url):
        query = parse_qs(urlparse(url).query)
        callback = (query['redirect_uri'][0] + '?code=test-code&state='
                    + query['state'][0])
        requests.append(pool.submit(urlopen, callback, timeout=3))
        return True

    if mode == 'code':
        auth_setup.prepare_headless('client', session_path, 300)
        args += ['--code', callback_from_file(None),
                 '--session', str(session_path)]
    elif mode == 'headless':
        args += ['--headless', '--session', str(session_path)]
        monkeypatch.setattr('builtins.input', callback_from_file)
    else:
        monkeypatch.setattr(auth_setup.webbrowser, 'open', browser)
    monkeypatch.setattr(auth_setup.sys, 'argv', args)
    response = SimpleNamespace(status=200, data=json.dumps({
        'refresh_token': 'refresh', 'access_token': 'access',
    }).encode())
    transport = Mock(return_value=response)
    monkeypatch.setattr(oauth, 'Request', lambda: transport)
    try:
        auth_setup.main()
    finally:
        pool.shutdown(wait=True)
    for request in requests:
        request.result().close()

    transport.assert_called_once()
    assert transport.call_args.args[0] == oauth.TOKEN_URI
    body = parse_qs(transport.call_args.kwargs['body'].decode())
    assert body['code'] == ['test-code']
    assert body['code_verifier']
    assert json.loads(out.read_text()) == {
        'client_id': 'client', 'client_secret': 'secret',
        'refresh_token': 'refresh', 'scopes': document_scopes,
        'token_uri': oauth.TOKEN_URI, 'auth_method': 'pkce-secret',
    }
    assert stat.S_IMODE(out.stat().st_mode) == OWNER_READ_WRITE
    output = capsys.readouterr().out
    assert 'Authorisation successful' in output
    if mode != 'code':
        assert 'Scopes: ' + ', '.join(document_scopes) in output
    assert 'email' not in output
    assert 'appscript' not in output
    assert body['code_verifier'][0] not in output
    assert not session_path.exists()

    # The listener must already be closed when the CLI returns.
    redirect = urlparse(body['redirect_uri'][0])
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', redirect.port))


@pytest.mark.parametrize('legacy', [False, True])
def test_new_and_legacy_token_files_refresh(
    tmp_path, monkeypatch, document_scopes, legacy,
):
    """Real credential construction accepts both formats without rewriting."""
    token = {'client_id': 'client', 'client_secret': 'secret',
             'refresh_token': 'refresh', 'scopes': document_scopes.copy()}
    if legacy:
        token['email'] = 'old@example.com'
        token['scopes'] += ['openid', 'email', 'profile']
    path = tmp_path / 'token.json'
    path.write_text(json.dumps(token))
    before = path.read_bytes()
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', str(path))
    refresh = Mock()
    monkeypatch.setattr(credentials.Credentials, 'refresh', refresh)

    loaded = credentials.load_credentials()

    assert loaded.client_id == 'client'
    assert loaded.refresh_token == 'refresh'
    assert list(loaded.scopes) == document_scopes
    refresh.assert_called_once()
    assert path.read_bytes() == before
