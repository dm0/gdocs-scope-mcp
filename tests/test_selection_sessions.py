"""Exercise real loopback session lifecycle without Google access."""

import asyncio
import json
import socket
import webbrowser
from http import HTTPStatus
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest
from fastmcp import Client
from jsonschema import validate

from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import authorization, oauth, selection
from gdocs_scope_mcp.google_api.access import DRIVE_FILE
from gdocs_scope_mcp.server import mcp
from gdocs_scope_mcp.settings import get_settings


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
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert not tools['docs_select_files'].annotations.readOnlyHint
            assert tools['docs_selection_status'].annotations.readOnlyHint
            started = await client.call_tool('docs_select_files', {
                'open_browser': False,
            })
            validate(started.structured_content,
                     tools['docs_select_files'].outputSchema)
            session_id = started.structured_content['session_id']
            result = await client.call_tool('docs_selection_status', {
                'session_id': session_id,
            })
            assert result.structured_content['status'] == 'pending'
            validate(result.structured_content,
                     tools['docs_selection_status'].outputSchema)
            missing = await client.call_tool('docs_selection_status', {
                'session_id': 'unknown',
            }, raise_on_error=False)
            assert missing.is_error
            validate(missing.structured_content,
                     tools['docs_selection_status'].outputSchema)
    asyncio.run(run())
