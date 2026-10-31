"""Verify narrow Picker authorization, account binding and atomic saves."""

import json
import stat
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from gdocs_scope_mcp import auth_setup
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import authorization, oauth
from gdocs_scope_mcp.google_api.access import DRIVE_FILE
from gdocs_scope_mcp.settings import get_settings

PRIVATE_MODE = 0o600

@pytest.fixture
def picker(monkeypatch, tmp_path):
    """Use a narrow isolated configuration and substituted Drive metadata."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'selected_files')
    get_settings.cache_clear()
    drive = Mock()
    drive.about().get().execute.return_value = {
        'user': {'permissionId': 'account'},
    }
    drive.files().get().execute.return_value = {
        'id': 'doc', 'name': 'Document',
        'mimeType': 'application/vnd.google-apps.document',
    }
    monkeypatch.setattr(authorization, 'build', Mock(return_value=drive))
    session = auth_setup.create_session(
        'client', 'http://127.0.0.1:1234/oauth2/callback', 300,
    )
    tokens = {'access_token': 'access', 'refresh_token': 'refresh',
              'scope': DRIVE_FILE}
    yield session, tokens, drive
    get_settings.cache_clear()


def callback(session, ids='doc'):
    """Construct a bounded synthetic authenticated callback."""
    return (session.redirect_uri + '?code=code&state=' + session.state
            + '&picked_file_ids=' + ids)


def test_picker_url(picker):
    """Only drive.file is requested, without incremental authorization."""
    session, _, _ = picker
    params = parse_qs(urlsplit(session.authorization_url()).query)
    assert params['scope'] == [DRIVE_FILE]
    assert params['trigger_onepick'] == ['true']
    assert params['prompt'] == ['consent']
    assert params['allow_multiple'] == ['true']
    assert params['include_granted_scopes'] == ['false']
    assert params['code_challenge_method'] == ['S256']
    assert session.picked_files(callback(session)) == ['doc']


@pytest.mark.parametrize('ids', ['', 'doc,doc', 'a/b', ',doc',
                              ','.join(str(i) for i in range(101))])
def test_invalid_selection(picker, ids):
    """Reject empty, duplicate, malformed and oversized selections."""
    with pytest.raises(oauth.AuthorizationError):
        picker[0].picked_files(callback(picker[0], ids))


def test_selected_save_checks_account(picker, tmp_path):
    """Store account binding without access tokens or PKCE material."""
    session, tokens, _ = picker
    out = tmp_path / 'token.json'
    auth_setup.save_token(tokens, session, 'secret', out, ['doc'])
    data = json.loads(out.read_text())
    assert data['account_id'] == 'account'
    assert data['access_mode'] == 'selected_files'
    assert data['scopes'] == [DRIVE_FILE]
    assert not {'access_token', 'state', 'verifier'} & data.keys()
    assert stat.S_IMODE(out.stat().st_mode) == PRIVATE_MODE


@pytest.mark.parametrize('failure', ['account', 'client', 'scope', 'mime'])
def test_bad_selection_never_replaces_token(picker, tmp_path, failure):
    """A mismatched callback credential cannot replace an existing grant."""
    session, tokens, drive = picker
    out = tmp_path / 'token.json'
    auth_setup.save_token(tokens, session, 'secret', out, ['doc'])
    before = out.read_bytes()
    if failure == 'account':
        drive.about().get().execute.return_value = {
            'user': {'permissionId': 'other'},
        }
    elif failure == 'client':
        session.client_id = 'other'
    elif failure == 'mime':
        drive.files().get().execute.return_value['mimeType'] = 'text/plain'
    else:
        tokens['scope'] += ' openid'
    with pytest.raises((oauth.AuthorizationError, ToolFailureError)):
        auth_setup.save_token(tokens, session, 'secret', out, ['doc'])
    assert out.read_bytes() == before


def test_atomic_generation_guard(tmp_path):
    """A stale result cannot overwrite another writer's credentials."""
    path = tmp_path / 'token.json'
    expected = authorization.generation(path)
    path.write_text('new contents')
    with pytest.raises(oauth.AuthorizationError, match='changed'):
        authorization.install_token(path, {'refresh_token': 'old'}, expected)
    assert path.read_text() == 'new contents'
    assert list(tmp_path.glob('.token-*')) == []


@pytest.mark.parametrize('mode', ['headless', 'saved'])
def test_cli_picker_completion(picker, tmp_path, monkeypatch, mode):
    """Both headless CLI variants retain Picker metadata through exchange."""
    _, tokens, _ = picker
    out = tmp_path / 'new.json'
    pending = tmp_path / 'pending.json'
    def complete(_):
        saved = oauth.AuthorizationSession(**json.loads(pending.read_text()))
        return callback(saved)
    monkeypatch.setattr(oauth, 'Request', lambda: Mock(return_value=
        SimpleNamespace(status=200, data=json.dumps(tokens).encode())))
    args = ['auth', '--client-id', 'client', '--client-secret', 'secret',
            '--out', str(out), '--session', str(pending)]
    if mode == 'saved':
        auth_setup.prepare_headless('client', pending, 300)
        args += ['--callback-url', complete(None)]
    else:
        args += ['--headless']
        monkeypatch.setattr('builtins.input', complete)
    monkeypatch.setattr(auth_setup.sys, 'argv', args)
    auth_setup.main()
    assert json.loads(out.read_text())['account_id'] == 'account'
    assert not pending.exists()
