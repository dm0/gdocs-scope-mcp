"""Exercise real loopback session lifecycle without Google access."""

import asyncio
import json
import logging
import os
import socket
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from threading import Barrier
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest
from fastmcp import Client, FastMCP
from jsonschema import validate

from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import (
    authorization,
    credentials,
    oauth,
    selection,
)
from gdocs_scope_mcp.google_api.access import (
    DRIVE_FILE,
    DRIVE_FULL,
)
from gdocs_scope_mcp.settings import default_token_path, get_settings
from gdocs_scope_mcp.tool_logging import ToolCallLoggingMiddleware, logger
from gdocs_scope_mcp.tools import access as access_tools


def access_server():
    """Register a fresh catalog using the test's configured startup mode."""
    app = FastMCP('access-tests', middleware=[ToolCallLoggingMiddleware()])
    access_tools.register(app)
    return app


@pytest.fixture
def sessions(monkeypatch, tmp_path):
    """Isolate token destinations and replace only outbound Google seams."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_CONFIG', raising=False)
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'selected_files')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_TOKEN', str(tmp_path / 'token.json'))
    get_settings.cache_clear()
    manager = selection.SelectionManager()
    exchange = Mock(return_value={'access_token': 'never-exposed',
                                  'refresh_token': 'refresh',
                                  'scope': DRIVE_FILE})
    monkeypatch.setattr(oauth, 'exchange_code', exchange)
    monkeypatch.setattr(authorization, 'verify_selection', Mock(return_value=(
        {'client_id': 'client', 'account_id': 'account',
         'scopes': [DRIVE_FILE], 'refresh_token': 'refresh'},
        [{'id': 'doc', 'name': 'Document', 'url': 'https://example.com/doc'}],
    )))
    yield manager, exchange, tmp_path / 'token.json'
    manager.close()
    assert not any(worker.is_alive() for worker in manager.workers)
    get_settings.cache_clear()


def callback(public, **params):
    """Build a synthetic callback from the public authorization URL."""
    query = parse_qs(urlsplit(public.authorization_url).query)
    return query['redirect_uri'][0] + '?' + urlencode({
        'state': query['state'][0], 'code': 'code', 'picked_file_ids': 'doc',
        **params,
    })


def finish(manager, public):
    """Wait for the bounded worker without performing another operation."""
    for worker in list(manager.workers):
        worker.join(timeout=3)
        assert not worker.is_alive()
    return manager.status(public.session_id)


def test_completion_and_read_only_polling(sessions):
    """One exchange installs a token; subsequent polling never repeats it."""
    manager, exchange, path = sessions
    public = manager.start(open_browser=False)
    assert public.status == 'pending'
    assert not public.browser_opened
    url = callback(public)
    with urlopen(url, timeout=2) as response:
        assert response.status == HTTPStatus.OK
    result = finish(manager, public)
    assert result.status == 'completed'
    assert result.authorization_url is None
    assert result.documents[0].id == 'doc'
    assert 'never-exposed' not in result.model_dump_json()
    assert json.loads(path.read_text())['account_id'] == 'account'
    manager.status(public.session_id)
    exchange.assert_called_once()
    target = urlsplit(url)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((target.hostname, target.port))


@pytest.mark.parametrize('params', [{'state': 'wrong'}, {'code': ''}])
def test_invalid_callback_does_not_consume_attempt(sessions, params):
    """Unrelated local traffic cannot replace an authenticated selection."""
    manager, exchange, _ = sessions
    public = manager.start(open_browser=False)
    with pytest.raises(HTTPError):
        urlopen(callback(public, **params), timeout=2)
    assert manager.status(public.session_id).status == 'pending'
    exchange.assert_not_called()
    with urlopen(callback(public), timeout=2):
        pass
    assert finish(manager, public).status == 'completed'


def test_cancel_and_expiry(sessions):
    """Denial and expiry leave existing credentials untouched."""
    manager, exchange, path = sessions
    public = manager.start(open_browser=False)
    url = callback(public).split('&code=')[0] + '&error=access_denied'
    with pytest.raises(HTTPError):
        urlopen(url, timeout=2)
    assert finish(manager, public).status == 'cancelled'
    expired = manager.start(open_browser=False, timeout=1)
    assert finish(manager, expired).status == 'expired'
    exchange.assert_not_called()
    assert not path.exists()


def test_destination_exclusion_and_shutdown(sessions):
    """Separate managers cannot authorize the same token concurrently."""
    manager, exchange, path = sessions
    public = manager.start(open_browser=False)
    other = selection.SelectionManager()
    try:
        with pytest.raises(ToolFailureError) as raised:
            other.start(open_browser=False)
        assert raised.value.failure.code == 'EDIT_CONFLICT'
        manager.close()
        assert manager.status(public.session_id).status == 'cancelled'
        next_attempt = other.start(open_browser=False)
        assert next_attempt.status == 'pending'
    finally:
        other.close()
    exchange.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize('reason', ['ACCOUNT_MISMATCH', 'CREDENTIALS_CHANGED'])
def test_completion_failure_is_sanitized(sessions, monkeypatch, reason):
    """Stable failure codes expose neither tokens nor exception payloads."""
    manager, _, path = sessions
    monkeypatch.setattr(authorization, 'verify_selection', Mock(
        side_effect=authorization.SelectionError(reason),
    ))
    public = manager.start(open_browser=False)
    with urlopen(callback(public), timeout=2):
        pass
    result = finish(manager, public)
    assert result.status == 'failed'
    assert result.failure_code == reason
    assert not path.exists()


def test_manual_fallback_and_unknown_session(sessions, monkeypatch):
    """Browser launch failure retains a URL, and unknown IDs fail clearly."""
    manager, _, _ = sessions
    monkeypatch.setattr(selection.webbrowser, 'open', Mock(
        side_effect=webbrowser.Error('unavailable'),
    ))
    public = manager.start()
    assert not public.browser_opened
    assert public.authorization_url.startswith('https://accounts.google.com/')
    with pytest.raises(ToolFailureError) as raised:
        manager.status('unknown')
    assert raised.value.failure.code == 'RESOURCE_NOT_FOUND'


def test_mcp_selection_contract(sessions, monkeypatch):
    """Adapters expose schemas and side-effect annotations deliberately."""
    manager, _, _ = sessions
    monkeypatch.setattr(selection, 'manager', manager)
    async def run():
        async with Client(access_server()) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert not tools['docs_select_files'].annotations.readOnlyHint
            assert tools['docs_authorization_status'].annotations.readOnlyHint
            started = await client.call_tool('docs_select_files', {
                'open_browser': False,
            })
            validate(started.structured_content,
                     tools['docs_select_files'].outputSchema)
            session_id = started.structured_content['session_id']
            result = await client.call_tool('docs_authorization_status', {
                'session_id': session_id,
            })
            assert result.structured_content['status'] == 'pending'
            validate(result.structured_content,
                     tools['docs_authorization_status'].outputSchema)
            missing = await client.call_tool('docs_authorization_status', {
                'session_id': 'unknown',
            }, raise_on_error=False)
            assert missing.is_error
            validate(missing.structured_content,
                     tools['docs_authorization_status'].outputSchema)
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['success', 'denied', 'insufficient',
                                   'other_account'])
def test_mcp_full_drive_upgrade(sessions, monkeypatch, outcome):
    """Upgrade a narrow token only after valid same-account consent."""
    manager, exchange, path = sessions
    original = {
        'client_id': 'original-client', 'account_id': 'account',
        'access_mode': 'selected_files', 'auth_method': 'pkce-public',
        'refresh_token': 'narrow-refresh', 'scopes': [DRIVE_FILE],
    }
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'full_drive')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_CLIENT_ID', 'ambient-other-client')
    get_settings.cache_clear()
    with pytest.raises(ToolFailureError) as raised:
        credentials.load_credentials()
    assert 'docs_authorize' in raised.value.failure.suggested_action
    drive = Mock()
    drive.about().get().execute.return_value = {
        'user': {'permissionId': ('other' if outcome == 'other_account'
                                  else 'account')},
    }
    monkeypatch.setattr(authorization, 'build', Mock(return_value=drive))
    exchange.return_value = {
        'access_token': 'new-access', 'refresh_token': 'broad-refresh',
        'scope': DRIVE_FILE if outcome == 'insufficient' else DRIVE_FULL,
    }
    monkeypatch.setattr(selection, 'manager', manager)
    async def start():
        async with Client(access_server()) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert not tools['docs_authorize'].annotations.readOnlyHint
            result = await client.call_tool('docs_authorize', {
                'open_browser': False,
            })
            validate(result.structured_content,
                     tools['docs_authorize'].outputSchema)
            return selection.SelectionStatus(**result.structured_content)
    public = asyncio.run(start())
    query = parse_qs(urlsplit(public.authorization_url).query)
    assert query['client_id'] == ['original-client']
    assert query['scope'][0].split() == [DRIVE_FULL]
    assert 'trigger_onepick' not in query
    assert query['prompt'] == ['consent']
    if outcome == 'denied':
        url = (query['redirect_uri'][0] + '?' + urlencode({
            'state': query['state'][0], 'error': 'access_denied',
        }))
        with pytest.raises(HTTPError):
            urlopen(url, timeout=2)
    else:
        with urlopen(callback(public, picked_file_ids=''), timeout=2):
            pass
    result = finish(manager, public)
    if outcome == 'success':
        assert result.status == 'completed'
        assert result.documents == []
        saved = json.loads(path.read_text())
        assert saved['scopes'] == [DRIVE_FULL]
        assert saved['access_mode'] == 'full_drive'
        assert saved['account_id'] == 'account'
        assert saved['client_id'] == 'original-client'
        def refresh(self, _request):
            self._granted_scopes = [DRIVE_FULL]
        monkeypatch.setattr(credentials.PublicClientCredentials,
                            'refresh', refresh)
        assert credentials.load_credentials().refresh_token == 'broad-refresh'
    else:
        assert path.read_bytes() == before
        assert result.status == (
            'cancelled' if outcome == 'denied' else 'failed'
        )
        if outcome == 'insufficient':
            assert result.failure_code == 'INVALID_SCOPES'
        if outcome == 'other_account':
            assert result.failure_code == 'ACCOUNT_MISMATCH'


def test_default_upgrade_account(sessions, monkeypatch):
    """Separate default paths retain the selected account and client."""
    manager, _, explicit = sessions
    original = {'client_id': 'selected-client', 'account_id': 'account',
                'scopes': [DRIVE_FILE], 'refresh_token': 'selected-refresh'}
    monkeypatch.delenv('GDOCS_SCOPE_MCP_TOKEN')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(explicit.parent))
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', 'full_drive')
    get_settings.cache_clear()
    narrow = default_token_path('selected_files')
    narrow.parent.mkdir(parents=True)
    narrow.write_text(json.dumps(original))
    before = narrow.read_bytes()
    public = manager.start(open_browser=False, selection_only=False)
    query = parse_qs(urlsplit(public.authorization_url).query)
    assert query['client_id'] == ['selected-client']
    manager.close()
    assert narrow.read_bytes() == before
    assert not default_token_path('full_drive').exists()


@pytest.mark.parametrize('mode', ['full_drive', 'selected_files'])
def test_mcp_initial_authorization(sessions, monkeypatch, mode):
    """Authorization starts without credentials in either configured mode."""
    manager, exchange, path = sessions
    assert not path.exists()
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', mode)
    get_settings.cache_clear()
    expected = DRIVE_FULL if mode == 'full_drive' else DRIVE_FILE
    exchange.return_value = {
        'access_token': 'initial-access', 'refresh_token': 'initial-refresh',
        'scope': expected,
    }
    drive = Mock()
    drive.about().get().execute.return_value = {
        'user': {'permissionId': 'account'},
    }
    monkeypatch.setattr(authorization, 'build', Mock(return_value=drive))
    monkeypatch.setattr(selection, 'manager', manager)
    async def start():
        async with Client(access_server()) as client:
            result = await client.call_tool('docs_authorize', {
                'open_browser': False,
            })
            return selection.SelectionStatus(**result.structured_content)
    public = asyncio.run(start())
    assert public.status == 'pending'
    query = parse_qs(urlsplit(public.authorization_url).query)
    assert ('trigger_onepick' in query) == (mode == 'selected_files')
    assert query['scope'][0].split() == [expected]
    with urlopen(callback(public), timeout=2):
        pass
    result = finish(manager, public)
    assert result.status == 'completed'
    assert json.loads(path.read_text())['scopes'] == [expected]


@pytest.mark.parametrize('mode', ['full_drive', 'selected_files'])
def test_stdio_catalog_matches_mode(isolated_mcp, tmp_path, mode):
    """Fresh STDIO servers advertise only tools available in their mode."""
    config = tmp_path / 'config.json'
    config.write_text('{}')
    environment = {
        **os.environ,
        'GDOCS_SCOPE_MCP_CONFIG': str(config),
        'GDOCS_SCOPE_MCP_ACCESS_MODE': mode,
        'GDOCS_SCOPE_MCP_TOKEN': str(tmp_path / 'missing-token.json'),
    }
    async def check():
        async with isolated_mcp(tmp_path / 'server.stderr',
                                environment=environment) as (client, info):
            assert info['access_mode'] == mode
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert 'docs_authorize' in tools
            assert 'docs_authorization_status' in tools
            assert 'docs_authorization_complete' in tools
            assert 'docs_selection_status' not in tools
            assert ('docs_select_files' in tools) == (mode == 'selected_files')
            assert tools['docs_authorization_status'].annotations.readOnlyHint
            assert not tools['docs_authorize'].annotations.readOnlyHint
    asyncio.run(check())
    assert not (tmp_path / 'missing-token.json').exists()


@pytest.mark.parametrize('mode', ['full_drive', 'selected_files'])
def test_remote_mcp_authorization(sessions, monkeypatch, caplog, mode):
    """A copied callback completes OAuth without contacting a loopback URL."""
    manager, exchange, path = sessions
    monkeypatch.setenv('GDOCS_SCOPE_MCP_ACCESS_MODE', mode)
    get_settings.cache_clear()
    expected = DRIVE_FULL if mode == 'full_drive' else DRIVE_FILE
    exchange.return_value = {
        'access_token': 'access', 'refresh_token': 'refresh',
        'scope': expected,
    }
    drive = Mock()
    drive.about().get().execute.return_value = {
        'user': {'permissionId': 'account'},
    }
    monkeypatch.setattr(authorization, 'build', Mock(return_value=drive))
    monkeypatch.setattr(selection, 'manager', manager)
    caplog.set_level(logging.INFO, logger='gdocs_scope_mcp')
    logger.addHandler(caplog.handler)
    async def run():
        async with Client(access_server()) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            hints = tools['docs_authorization_complete'].annotations
            assert not hints.readOnlyHint
            started = await client.call_tool('docs_authorize', {
                'open_browser': False,
            })
            public = selection.SelectionStatus(**started.structured_content)
            url = callback(public, code='REMOTE_PRIVATE_CODE')
            bad = await client.call_tool('docs_authorization_complete', {
                'session_id': public.session_id,
                'callback_url': url.replace('state=', 'state=wrong'),
            }, raise_on_error=False)
            assert bad.is_error
            assert bad.structured_content['code'] == 'INVALID_ARGUMENT'
            submitted = await client.call_tool('docs_authorization_complete', {
                'session_id': public.session_id, 'callback_url': url,
            })
            validate(submitted.structured_content,
                     tools['docs_authorization_complete'].outputSchema)
            assert 'REMOTE_PRIVATE_CODE' not in submitted.content[0].text
            assert finish(manager, public).status == 'completed'
            duplicate = await client.call_tool('docs_authorization_complete', {
                'session_id': public.session_id, 'callback_url': url,
            }, raise_on_error=False)
            assert duplicate.is_error
            assert duplicate.structured_content['code'] == 'EDIT_CONFLICT'
    try:
        asyncio.run(run())
    finally:
        logger.removeHandler(caplog.handler)
    assert 'docs_authorization_complete' in caplog.text
    assert 'REMOTE_PRIVATE_CODE' not in caplog.text
    exchange.assert_called_once()
    assert json.loads(path.read_text())['scopes'] == [expected]


@pytest.mark.parametrize('invalid', [
    'bare', 'wrong_state', 'wrong_destination', 'fragment',
    'duplicate_state', 'oversized', 'malformed_host',
])
def test_manual_callback_validation(sessions, invalid):
    """Manual completion retains exact destination, state and size checks."""
    manager, exchange, path = sessions
    public = manager.start(open_browser=False)
    url = callback(public)
    bad = {
        'bare': 'bare-code',
        'wrong_state': url.replace('state=', 'state=wrong'),
        'wrong_destination': url.replace('/oauth2/callback', '/other'),
        'fragment': url + '#fragment',
        'duplicate_state': url + '&state=duplicate',
        'oversized': url + '&padding=' + 'x' * oauth.MAX_CALLBACK_LENGTH,
        'malformed_host': 'http://[invalid',
    }[invalid]
    with pytest.raises(ToolFailureError) as raised:
        manager.complete(public.session_id, bad)
    assert raised.value.failure.code == 'INVALID_ARGUMENT'
    assert manager.status(public.session_id).status == 'pending'
    exchange.assert_not_called()
    assert not path.exists()
    manager.complete(public.session_id, url)
    assert finish(manager, public).status == 'completed'


def test_manual_denial_and_expiry(sessions):
    """Expired and cancelled remote sessions cannot exchange credentials."""
    manager, exchange, path = sessions
    public = manager.start(open_browser=False)
    url = callback(public).split('&code=')[0] + '&error=access_denied'
    manager.complete(public.session_id, url)
    assert finish(manager, public).status == 'cancelled'
    expired = manager.start(open_browser=False, timeout=1)
    assert finish(manager, expired).status == 'expired'
    with pytest.raises(ToolFailureError) as raised:
        manager.complete(expired.session_id, callback(expired))
    assert raised.value.failure.code == 'EDIT_CONFLICT'
    exchange.assert_not_called()
    assert not path.exists()
    assert not manager.callbacks


def test_callback_channels_accept_only_one_submission(sessions):
    """HTTP and manual delivery share one atomic callback receiver."""
    manager, exchange, _ = sessions
    public = manager.start(open_browser=False)
    receiver = manager.callbacks[public.session_id]
    barrier = Barrier(2)
    def submit():
        barrier.wait(timeout=2)
        try:
            receiver.submit(callback(public))
        except ToolFailureError as error:
            return error.failure.code
        return 'accepted'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=3)
                   for future in [pool.submit(submit), pool.submit(submit)]]
    assert sorted(results) == ['EDIT_CONFLICT', 'accepted']
    assert finish(manager, public).status == 'completed'
    exchange.assert_called_once()
    assert not manager.callbacks
