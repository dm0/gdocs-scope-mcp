"""Check study isolation and grading budgets without starting Codex."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('tomllib', reason='Research runner requires Python 3.11+')

MODULE_PATH = Path(__file__).parents[1] / 'research/codex_study_runtime.py'
SPEC = importlib.util.spec_from_file_location(
    'codex_study_runtime', MODULE_PATH,
)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class Sink:
    """Collect only messages sent by the study transport."""

    def __init__(self):
        """Start with an empty JSON message collection."""
        self.messages = []

    def write(self, line):
        """Parse exactly one JSON line."""
        self.messages.append(json.loads(line))

    async def drain(self):
        """Provide an immediately writable fake pipe."""


def client_for(events):
    """Provide deterministic app-server events without external access."""
    reader = asyncio.StreamReader()
    for event in events:
        reader.feed_data(json.dumps(event).encode() + b'\n')
    reader.feed_eof()
    return runtime.StudyClient(SimpleNamespace(stdout=reader, stdin=Sink()))


def test_isolation_disables_every_configured_mcp_without_leaking_secrets(
    monkeypatch, tmp_path,
):
    """Only server names influence overrides; credentials never enter argv."""
    config_dir = tmp_path / '.codex'
    config_dir.mkdir()
    (config_dir / 'config.toml').write_text(
        '[mcp_servers.docs]\ncommand="server"\n'
        '[mcp_servers.docs.env]\nTOKEN="synthetic-secret"\n'
        '[mcp_servers.other-server]\nurl="https://example.invalid"\n',
    )
    monkeypatch.setattr(runtime.Path, 'home', lambda: tmp_path)
    command = runtime.isolated_command()
    assert 'mcp_servers.docs.enabled=false' in command
    assert 'mcp_servers.other-server.enabled=false' in command
    assert 'synthetic-secret' not in ' '.join(command)
    assert 'web_search="disabled"' in command
    for feature in runtime.DISABLED_FEATURES:
        index = command.index(feature)
        assert command[index - 1] == '--disable'


def test_unsafe_configuration_names_fail_closed(monkeypatch, tmp_path):
    """Reject a server name that cannot be safely overridden."""
    config_dir = tmp_path / '.codex'
    config_dir.mkdir()
    (config_dir / 'config.toml').write_text(
        '[mcp_servers."server.with.dots"]\ncommand="server"\n',
    )
    monkeypatch.setattr(runtime.Path, 'home', lambda: tmp_path)
    with pytest.raises(ValueError, match='safely override'):
        runtime.isolated_command()


def test_rpc_retains_notifications_and_handles_errors():
    """Startup notifications cannot be mistaken for a request's response."""
    async def run():
        events = [
            {'method': 'notice', 'params': {}},
            {'id': 1, 'result': {'ok': True}},
            {'id': 2, 'error': {'code': -1, 'message': 'test failure'}},
        ]
        client = client_for(events)
        assert await client.request('first', {}) == {'ok': True}
        with pytest.raises(RuntimeError, match='test failure'):
            await client.request('second', {})
        assert client.events == events
    asyncio.run(run())


def test_account_notifications_are_not_retained():
    """Exclude account identifiers from synthetic study traces."""
    async def run():
        client = client_for([
            {'method': 'account/updated', 'params': {'private': 'synthetic'}},
            {'method': 'account/rateLimits/updated', 'params': {}},
            {'id': 1, 'result': {}},
        ])
        await client.request('first', {})
        assert client.events == [{'id': 1, 'result': {}}]
    asyncio.run(run())


def test_action_budget_blocks_the_next_operation():
    """An over-budget attempted action never reaches the execution handler."""
    async def run():
        client = client_for([
            {'id': 1, 'result': {}},
            {'id': 10, 'method': 'item/tool/call', 'params': {
                'tool': 'allowed', 'arguments': {'value': 1},
            }},
            {'id': 11, 'method': 'item/tool/call', 'params': {
                'tool': 'allowed', 'arguments': {'value': 2},
            }},
        ])
        executed = []

        async def handler(call):
            executed.append(call['arguments']['value'])
            return {'ok': True}

        with pytest.raises(RuntimeError, match='budget exhausted'):
            await client.turn('thread', 'prompt', handler, action_limit=1)
        assert executed == [1]
    asyncio.run(run())


def test_unrelated_requests_are_rejected():
    """No shell, approval or other fallback can enter the study loop."""
    async def run():
        client = client_for([
            {'id': 1, 'result': {}},
            {'id': 10, 'method': 'item/commandExecution/requestApproval',
             'params': {}},
        ])

        async def handler(_call):
            pytest.fail('Unrelated requests must never execute')

        with pytest.raises(RuntimeError, match='Unexpected study request'):
            await client.turn('thread', 'prompt', handler)
        assert client.process.stdin.messages[-1]['error'] == {
            'code': -32601,
            'message': 'Only study dynamic-tool calls are enabled',
        }
    asyncio.run(run())
