"""Exercise PKCE validation, one-use sessions and real google-auth refresh."""

import base64
import hashlib
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import pytest
from google.auth.exceptions import RefreshError

from gdocs_scope_mcp import auth_setup
from gdocs_scope_mcp.google_api import credentials, oauth
from gdocs_scope_mcp.settings import default_token_path, get_settings


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Separate client configuration from the developer's actual settings."""
    monkeypatch.delenv('GOOGLE_DOCS_MCP_CONFIG', raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def session():
    """Create one bounded attempt with no real credential material."""
    return oauth.AuthorizationSession.create(
        'client', 'http://127.0.0.1:12345/oauth2/callback', ['scope'],
    )


def callback(session, query='code=code'):
    """Construct a callback tied to a test attempt."""
    return session.redirect_uri + '?' + query + '&state=' + session.state


def test_pkce_uses_fresh_independent_randomness(session):
    """Each attempt sends an S256 challenge without exposing the verifier."""
    other = oauth.AuthorizationSession.create(
        'client', session.redirect_uri, ['scope'],
    )
    values = [session.verifier, other.verifier, session.state, other.state]
    assert len(set(values)) == len(values)
    params = parse_qs(urlsplit(session.authorization_url()).query)
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(session.verifier.encode()).digest(),
    ).rstrip(b'=').decode()
    assert params['code_challenge'] == [expected]
    assert params['code_challenge_method'] == ['S256']
    assert session.verifier not in session.authorization_url()
    assert session.verifier not in repr(session)


@pytest.mark.parametrize('query', [
    'code=x', 'code=x&state=wrong', 'code=x&state=é',
    'code=x&code=y&state={state}',
    'code=x&state={state}&state={state}', 'code=&state={state}',
    'error=access_denied&state={state}',
    'error=denied&code=x&state={state}', 'state={state}',
])
def test_invalid_callback_never_yields_code(session, query):
    """Missing, ambiguous and denied responses fail before token exchange."""
    with pytest.raises(oauth.AuthorizationError):
        session.callback_code(session.redirect_uri + '?'
                              + query.format(state=session.state))


@pytest.mark.parametrize('part,replacement', [
    ('127.0.0.1', 'example.com'), ('12345', '12346'),
    ('/oauth2/callback', '/wrong'), ('http:', 'https:'),
])
def test_callback_destination_is_exact(session, part, replacement):
    """A matching state cannot authorize a different redirect destination."""
    with pytest.raises(oauth.AuthorizationError):
        session.callback_code(callback(session).replace(part, replacement))


def test_expired_session_cannot_exchange(session, monkeypatch):
    """Expiration is checked before any outbound token request."""
    session.expires_at = 0
    request = Mock()
    monkeypatch.setattr(oauth, 'Request', request)
    with pytest.raises(oauth.AuthorizationError):
        oauth.exchange_code(session, 'code')
    request.assert_not_called()


def test_session_is_private_and_consumed_once(session, tmp_path):
    """Concurrent CLI completions cannot both consume the same verifier."""
    path = tmp_path / 'session.json'
    oauth.save_session(session, path)
    assert not path.stat().st_mode & 0o077
    with pytest.raises(FileExistsError):
        oauth.save_session(session, path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(oauth.consume_session, path, callback(session))
                   for _ in range(2)]
    assert sum(f.exception() is None for f in futures) == 1
    assert not path.exists()


def test_invalid_saved_callback_consumes_session(session, tmp_path):
    """A failed completion must restart consent instead of reusing material."""
    path = tmp_path / 'session.json'
    oauth.save_session(session, path)
    with pytest.raises(oauth.AuthorizationError):
        oauth.consume_session(path, callback(session) + '&state=wrong')
    assert not path.exists()


def test_public_exchange_omits_secret_and_checks_verifier(
    session, monkeypatch,
):
    """The token request carries the original verifier, URI and client ID."""
    def token_endpoint(url, **kwargs):
        assert url == oauth.TOKEN_URI
        data = parse_qs(kwargs['body'].decode(), keep_blank_values=True)
        assert data == {
            'client_id': ['client'], 'code': ['code'],
            'redirect_uri': [session.redirect_uri],
            'code_verifier': [session.verifier],
            'grant_type': ['authorization_code'],
        }
        return SimpleNamespace(status=200, data=(
            b'{"access_token":"access","refresh_token":"refresh"}'
        ))
    monkeypatch.setattr(oauth, 'Request', lambda: token_endpoint)
    assert oauth.exchange_code(session, 'code')['refresh_token'] == 'refresh'


def test_failed_exchange_has_no_fallback_or_sensitive_error(
    session, monkeypatch,
):
    """Invalid grants cause one failure, without exposing the server body."""
    request = Mock(return_value=SimpleNamespace(
        status=400, data=session.verifier.encode(),
    ))
    monkeypatch.setattr(oauth, 'Request', lambda: request)
    with pytest.raises(oauth.AuthorizationError) as error:
        oauth.exchange_code(session, 'code')
    assert session.verifier not in str(error.value)
    request.assert_called_once()


@pytest.mark.parametrize('payload,expected', [
    (b'{"error":"invalid_client","error_description":"secret-value"}',
     'invalid_client'),
    (b'{"error":"invalid_request",'
     b'"error_description":"client_secret is missing."}',
     'client_secret is required by Google for this client'),
    (b'{"error":"secret-value"}', 'unrecognized response'),
    (b'not-json', 'unrecognized response'),
    (b'[]', 'unrecognized response'),
])
def test_token_error_diagnostics_are_allowlisted(payload, expected):
    """Expose recognized causes without reflecting arbitrary response data."""
    assert oauth.token_error_reason(payload) == expected


@pytest.mark.parametrize('legacy_secret', [None, 'legacy-secret'])
def test_real_google_auth_refresh_and_reload(
    legacy_secret, tmp_path, monkeypatch,
):
    """Real refresh omits public secrets and retains legacy ones."""
    path = tmp_path / 'token.json'
    data = {'client_id': 'client', 'refresh_token': 'refresh',
            'scopes': ['scope'], 'auth_method': 'pkce-public'}
    if legacy_secret:
        data['client_secret'] = legacy_secret
        data.pop('auth_method')
    path.write_text(json.dumps(data))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_TOKEN', str(path))
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CLIENT_SECRET', 'unrelated-secret')
    requests = []

    def request(url, method, body, **_kwargs):
        assert url == oauth.TOKEN_URI
        assert method == 'POST'
        params = parse_qs(body.decode(), keep_blank_values=True)
        requests.append(params)
        assert params['grant_type'] == ['refresh_token']
        assert params['refresh_token'] == ['refresh']
        if legacy_secret:
            assert params['client_secret'] == [legacy_secret]
        else:
            assert 'client_secret' not in params
        return SimpleNamespace(status=200, data=(
            b'{"access_token":"access","expires_in":3600,"scope":"scope"}'
        ))

    monkeypatch.setattr(credentials, 'Request', lambda: request)
    first = credentials.load_credentials()
    first.refresh(request)
    second = credentials.load_credentials()
    assert first.token == second.token == 'access'
    assert first.refresh_token == second.refresh_token == 'refresh'
    assert first.valid and second.valid
    assert requests == [requests[0]] * 3
    assert json.loads(path.read_text()) == data


def test_public_refresh_failure_does_not_retry_with_secret():
    """A rejected public client remains a failure in the real library."""
    request = Mock(return_value=SimpleNamespace(
        status=400, data=b'{"error":"invalid_client"}',
    ))
    creds = oauth.PublicClientCredentials(
        token=None, refresh_token='refresh', client_id='client',
        client_secret='', token_uri=oauth.TOKEN_URI,
    )
    with pytest.raises(RefreshError):
        creds.refresh(request)
    request.assert_called_once()


@pytest.mark.parametrize('action', ['timeout', 'cancel', 'browser_failure'])
def test_local_listener_closes_on_failure(action, monkeypatch, tmp_path):
    """Timeout, cancellation and browser errors release the selected port."""
    ports = []

    def browser(url):
        params = parse_qs(urlsplit(url).query)
        ports.append(urlsplit(params['redirect_uri'][0]).port)
        if action == 'cancel':
            raise KeyboardInterrupt
        if action == 'browser_failure':
            raise OSError('browser unavailable')
        return False

    monkeypatch.setattr(auth_setup.webbrowser, 'open', browser)
    request = Mock()
    monkeypatch.setattr(oauth, 'Request', request)
    with pytest.raises((oauth.AuthorizationError, KeyboardInterrupt, OSError)):
        auth_setup.run_local_flow('client', None, tmp_path / 'token', 0.05)
    request.assert_not_called()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', ports[0]))


def test_bare_code_is_rejected(monkeypatch, capsys):
    """The legacy code option cannot bypass original PKCE session context."""
    monkeypatch.setattr(auth_setup.sys, 'argv', ['auth', '--code', 'bare'])
    with pytest.raises(SystemExit):
        auth_setup.main()
    assert 'require --session' in capsys.readouterr().err


def test_headless_cancellation_removes_session(monkeypatch, tmp_path):
    """Interrupted manual input does not leave a reusable verifier behind."""
    path = tmp_path / 'session.json'
    monkeypatch.setattr('builtins.input', Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        auth_setup.run_headless_flow('client', None, tmp_path / 'token',
                                     300, path)
    assert not path.exists()


@pytest.mark.parametrize('source', ['project', 'json', 'env', 'cli', 'file'])
def test_client_selection_precedence(source, monkeypatch, tmp_path):
    """Explicit clients override defaults without requiring a secret."""
    monkeypatch.setattr(oauth, 'PROJECT_CLIENT_ID', 'project')
    for name in (*auth_setup.CLIENT_ID_ENV_ALIASES,
                 *auth_setup.CLIENT_SECRET_ENV_ALIASES):
        monkeypatch.delenv(name, raising=False)
    args = ['auth']
    if source in {'json', 'env', 'cli', 'file'}:
        config = tmp_path / 'config.json'
        config.write_text('{"client_id":"json"}')
        monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', str(config))
    if source in {'env', 'cli', 'file'}:
        monkeypatch.setenv('GOOGLE_DOCS_MCP_CLIENT_ID', 'env')
    if source in {'cli', 'file'}:
        args += ['--client-id', 'cli']
    if source == 'file':
        path = tmp_path / 'client.json'
        path.write_text(json.dumps({'installed': {'client_id': 'file'}}))
        args += ['--credentials', str(path)]
    monkeypatch.setattr(auth_setup.sys, 'argv', args)
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    auth_setup.main()
    assert run.call_args.args[:2] == (source, None)


def test_cli_default_output_follows_xdg(monkeypatch, tmp_path):
    """New authorization writes under XDG without touching legacy paths."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(auth_setup.sys, 'argv', ['auth', '--client-id', 'id'])
    run = Mock()
    monkeypatch.setattr(auth_setup, 'run_local_flow', run)
    auth_setup.main()
    assert run.call_args.args[2] == tmp_path / 'gdocs-scope-mcp/token.json'


@pytest.mark.parametrize('xdg', [None, '', 'relative/path'])
def test_default_token_path_ignores_invalid_xdg(xdg, monkeypatch, tmp_path):
    """Unset and nonabsolute XDG paths use the home configuration directory."""
    monkeypatch.setenv('HOME', str(tmp_path))
    if xdg is None:
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    else:
        monkeypatch.setenv('XDG_CONFIG_HOME', xdg)
    expected = tmp_path / '.config/gdocs-scope-mcp/token.json'
    assert default_token_path() == expected


def test_token_path_precedence_preserves_legacy_files(monkeypatch, tmp_path):
    """Prefer explicit paths, then XDG, retaining legacy read fallback."""
    for name in (*credentials.TOKEN_ENV_ALIASES, 'GOOGLE_DOCS_TOKEN_FILE'):
        monkeypatch.delenv(name, raising=False)
    old = tmp_path / 'old-token.json'
    older = tmp_path / 'older-token.json'
    old.write_text('{"source":"old"}')
    older.write_text('{"source":"older"}')
    monkeypatch.setattr(credentials, 'STANDALONE_TOKEN_PATHS', [old, older])
    assert credentials.load_token() == {'source': 'old'}
    new = default_token_path()
    new.parent.mkdir(parents=True)
    new.write_text('{"source":"xdg"}')
    assert credentials.load_token() == {'source': 'xdg'}
    monkeypatch.setenv('GOOGLE_DOCS_MCP_TOKEN', str(older))
    assert credentials.load_token() == {'source': 'older'}
    assert old.read_text() == '{"source":"old"}'
    assert older.read_text() == '{"source":"older"}'


@pytest.mark.parametrize('stored_client', [None, 'original-client'])
def test_server_uses_config_only_when_token_has_no_client(
    stored_client, monkeypatch, tmp_path,
):
    """Configuration cannot rebind an existing refresh token's client."""
    for name in credentials.CLIENT_ID_ENV_ALIASES:
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / 'config.json'
    config.write_text('{"client_id":"configured-client"}')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_CONFIG', str(config))
    token = {'refresh_token': 'refresh', 'client_secret': 'secret'}
    if stored_client:
        token['client_id'] = stored_client
    monkeypatch.setattr(credentials, 'load_token', lambda: token)
    constructor = Mock()
    monkeypatch.setattr(credentials, 'Credentials', constructor)
    credentials.load_credentials()
    assert constructor.call_args.kwargs['client_id'] == (
        stored_client or 'configured-client'
    )


def test_saved_session_client_mismatch_never_exchanges(
    session, tmp_path, monkeypatch,
):
    """Client overrides cannot be applied to another client's verifier."""
    path = tmp_path / 'session.json'
    oauth.save_session(session, path)
    monkeypatch.setattr(auth_setup.sys, 'argv', [
        'auth', '--session', str(path), '--callback-url', callback(session),
        '--client-id', 'other-client',
    ])
    exchange = Mock()
    monkeypatch.setattr(oauth, 'exchange_code', exchange)
    with pytest.raises(SystemExit):
        auth_setup.main()
    exchange.assert_not_called()


def test_web_client_is_rejected(tmp_path):
    """A web client JSON cannot silently enter the Desktop flow."""
    path = tmp_path / 'web.json'
    path.write_text('{"web":{"client_id":"web-client"}}')
    with pytest.raises(oauth.AuthorizationError):
        auth_setup.load_client_config(path)


def test_public_token_contains_no_secret_or_verifier(session, tmp_path):
    """Persist actual granted scopes with a public-client refresh marker."""
    path = tmp_path / 'token.json'
    auth_setup.save_token(
        {'refresh_token': 'refresh', 'access_token': 'access',
         'scope': 'granted'}, session, None, path,
    )
    data = json.loads(path.read_text())
    assert data['auth_method'] == 'pkce-public'
    assert data['scopes'] == ['granted']
    private = {'client_secret', 'verifier', 'state', 'access_token'}
    assert not private & data.keys()


@pytest.mark.parametrize('query', ['code=x&state=wrong',
                                  'error=access_denied&state={state}'])
def test_loopback_rejection_closes_before_exchange(
    query, monkeypatch, tmp_path,
):
    """Actual rejected callbacks close the socket and never exchange a code."""
    pool = ThreadPoolExecutor(max_workers=1)
    ports = []
    futures = []

    def browser(url):
        params = parse_qs(urlsplit(url).query)
        redirect = params['redirect_uri'][0]
        ports.append(urlsplit(redirect).port)
        target = redirect + '?' + query.format(state=params['state'][0])
        futures.append(pool.submit(urlopen, target, timeout=3))
        return True

    monkeypatch.setattr(auth_setup.webbrowser, 'open', browser)
    exchange = Mock()
    monkeypatch.setattr(oauth, 'exchange_code', exchange)
    try:
        with pytest.raises(oauth.AuthorizationError):
            auth_setup.run_local_flow('client', None, tmp_path / 'token', 3)
    finally:
        pool.shutdown(wait=True)
    for future in futures:
        with pytest.raises(HTTPError):
            future.result()
    exchange.assert_not_called()
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('127.0.0.1', ports[0]))
