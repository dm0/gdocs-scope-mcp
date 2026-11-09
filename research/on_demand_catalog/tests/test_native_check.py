"""Validate local replay and fail-closed approval routing."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from .test_probe_client import probe


@pytest.fixture
def modules(monkeypatch):
    """Load study helpers without changing global module search paths."""
    monkeypatch.setitem(sys.modules, 'probe_client', probe)
    result = []
    for name in ('local_responses', 'native_mcp_check'):
        path = Path(__file__).parents[1] / (name + '.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, name, module)
        result.append(module)
    return result


def test_local_provider_emits_native_call_then_terminal_message(modules):
    """Exercise the Responses wire without any external inference provider."""
    provider, _native = modules
    with provider.provider('probe_write', 'test-nonce') as (endpoint, records):
        payload = {'tools': [{'type': 'function',
                             'name': 'mcp__native_probe__probe_write'}]}
        items = []
        for _ in range(2):
            request = Request(endpoint + '/responses',
                              data=json.dumps(payload).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=5) as response:
                events = [json.loads(line[6:]) for line in response.read()
                          .decode().splitlines() if line.startswith('data: ')]
            items.append(events[-1]['response']['output'][0])
        assert len(records) == 2  # noqa: PLR2004
        assert items[0]['type'] == 'function_call'
        assert json.loads(items[0]['arguments']) == {'nonce': 'test-nonce'}
        assert items[1]['type'] == 'message'


@pytest.mark.parametrize('decision,label', [
    ('accept', 'Accept'), ('decline', 'Decline'),
])
def test_only_correlated_fixture_approval_is_answered(modules, decision, label):
    """Accept/decline remains a client decision before server execution."""
    _provider, native = modules
    client = native.NativeClient(None, decision)
    client.events = [{'method': 'item/started', 'params': {'item': {
        'id': 'operation', 'type': 'mcpToolCall', 'server': native.SERVER,
    }}}]
    replies = []

    async def send(message):
        replies.append(message)

    client.send = send
    request = {'id': 9, 'method': 'tool/requestUserInput', 'params': {
        'itemId': 'operation', 'questions': [{
            'id': 'approval', 'options': [{'label': 'Accept'},
                                        {'label': 'Decline'}],
        }],
    }}
    asyncio.run(client.handle_request(request))
    assert replies[0]['result']['answers']['approval']['answers'] == [label]
    client.events[0]['params']['item']['server'] = 'unrelated-server'
    with pytest.raises(RuntimeError, match='fixture server'):
        asyncio.run(client.handle_request(request))
    assert len(replies) == 1


def test_native_command_only_overrides_child_configuration(modules, monkeypatch):
    """No global configuration or approval-bypass mode is introduced."""
    _provider, native = modules
    monkeypatch.setattr(native.RUNTIME, 'isolated_command', lambda: ['codex'])
    command = native.command('python', [], {}, 'writes',
                             'http://127.0.0.1:12345/v1')
    assert 'mcp_servers.native_probe.default_tools_approval_mode="writes"' in command
    assert 'approvals_reviewer="user"' in command
    assert 'approval_policy="on-request"' in command
    assert 'model_providers.native_fixture.requires_openai_auth=false' in command
    assert not any('danger-full-access' in part for part in command)


@pytest.mark.parametrize('decision', ['accept', 'decline'])
def test_native_mcp_elicitation_is_correlated_and_one_shot(modules, decision):
    """Only Codex tool-call approval for this fixture may be answered."""
    _provider, native = modules
    client = native.NativeClient(None, decision)
    client.events = [{'method': 'item/started', 'params': {'item': {
        'id': 'call', 'type': 'mcpToolCall', 'server': native.SERVER,
        'tool': 'probe_write', 'arguments': {'nonce': 'local'},
    }}}]
    replies = []

    async def send(message):
        replies.append(message)

    client.send = send
    request = {'id': 0, 'method': 'mcpServer/elicitation/request', 'params': {
        'serverName': native.SERVER, 'mode': 'form',
        'message': 'Allow tool "probe_write"?',
        'requestedSchema': {'type': 'object', 'properties': {}},
        '_meta': {'codex_approval_kind': 'mcp_tool_call',
                  'tool_params': {'nonce': 'local'},
                  'persist': ['session', 'always']},
    }}
    asyncio.run(client.handle_request(request))
    assert replies[0]['result'] == {
        'action': decision, 'content': {} if decision == 'accept' else None,
    }
    request['params']['_meta']['codex_approval_kind'] = 'unrelated'
    with pytest.raises(RuntimeError, match='Unrecognized'):
        asyncio.run(client.handle_request(request))
    assert len(replies) == 1
