"""Verify profile-free authorization and legacy token compatibility."""

import json
import stat
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest

from gdocs_scope_mcp import auth_setup
from gdocs_scope_mcp.google_api import credentials

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
    query = parse_qs(urlparse(auth_setup.build_auth_url('client')).query)
    assert query['scope'][0].split() == document_scopes


@pytest.mark.parametrize('mode', ['local', 'headless', 'code'])
def test_authorization_saves_token_without_identity(
    tmp_path, monkeypatch, capsys, document_scopes, mode,
):
    """Every CLI flow completes with only the token exchange HTTP request."""
    out = tmp_path / 'new' / 'token.json'
    args = ['gdocs-scope-mcp-auth', '--client-id', 'client',
            '--client-secret', 'secret', '--out', str(out)]
    if mode == 'code':
        args += ['--code', 'test-code']
    elif mode == 'headless':
        args += ['--headless']
        monkeypatch.setattr('builtins.input', lambda _: (
            auth_setup.REDIRECT_URI + '?code=test-code'
        ))
    else:
        monkeypatch.setattr(auth_setup, 'HTTPServer', Mock())
        monkeypatch.setattr(auth_setup.webbrowser, 'open', Mock())
        monkeypatch.setattr(auth_setup._CallbackHandler, 'code', 'test-code')
        monkeypatch.setattr(auth_setup._CallbackHandler, 'error', None)
    monkeypatch.setattr(auth_setup.sys, 'argv', args)
    response = Mock()
    response.read.return_value = b'{"refresh_token": "refresh"}'
    transport = Mock()
    transport.return_value.__enter__ = Mock(return_value=response)
    transport.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(auth_setup.urllib.request, 'urlopen', transport)

    auth_setup.main()

    transport.assert_called_once()
    request = transport.call_args.args[0]
    assert request.full_url == 'https://oauth2.googleapis.com/token'
    assert parse_qs(request.data.decode())['code'] == ['test-code']
    assert json.loads(out.read_text()) == {
        'client_id': 'client', 'client_secret': 'secret',
        'refresh_token': 'refresh', 'scopes': document_scopes,
    }
    assert stat.S_IMODE(out.stat().st_mode) == OWNER_READ_WRITE
    output = capsys.readouterr().out
    assert 'Authorisation successful' in output
    assert 'Scopes: ' + ', '.join(document_scopes) in output
    assert 'email' not in output
    assert 'appscript' not in output


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
    monkeypatch.setenv('GOOGLE_DOCS_MCP_TOKEN', str(path))
    refresh = Mock()
    monkeypatch.setattr(credentials.Credentials, 'refresh', refresh)

    loaded = credentials.load_credentials()

    assert loaded.client_id == 'client'
    assert loaded.refresh_token == 'refresh'
    assert list(loaded.scopes) == document_scopes
    refresh.assert_called_once()
    assert path.read_bytes() == before
