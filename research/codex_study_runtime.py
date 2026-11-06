"""Run bounded, isolated Codex chats through the local app-server protocol.

This research runner requires Python 3.11+ for reading the installed Codex
configuration. It never writes that configuration or copies credentials.
"""

import argparse
import asyncio
import json
import os
import re
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path

import tomllib

MODELS = ('gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-astra')
MAX_EVENTS = 10000
MAX_OUTPUT_TOKENS = 4096
DISABLED_FEATURES = (
    'shell_tool', 'apps', 'plugins', 'multi_agent', 'browser_use',
    'computer_use', 'in_app_browser', 'image_generation', 'memories',
    'view_image', 'sleep_tool', 'code_mode', 'code_mode_only',
    'hooks', 'shell_snapshot',
)


class StudyAgentError(RuntimeError):
    """Distinguish model errors and budgets from infrastructure failures."""


def isolated_command():
    """Disable unrelated capabilities without editing user configuration."""
    command = ['codex', 'app-server', '--stdio', '--strict-config']
    for feature in DISABLED_FEATURES:
        command.extend(['--disable', feature])
    config_path = Path.home() / '.codex/config.toml'
    if config_path.exists():
        with config_path.open('rb') as source:
            config = tomllib.load(source)
        for name in config.get('mcp_servers', {}):
            # Codex parses override paths itself, rather than as TOML keys.
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ValueError('Cannot safely override an MCP server name')
            command.extend([
                '-c', f'mcp_servers.{name}.enabled=false',
            ])
    command.extend(['-c', 'web_search="disabled"'])
    return command


class StudyClient:
    """Own one app-server and retain only its study protocol transcript."""

    def __init__(self, process, *, timeout=120):
        """Set finite infrastructure limits and request sequence numbers."""
        self.process = process
        self.timeout = timeout
        self.sequence = 0
        self.events = []
        self.process_reaped = False
        self.current_calls = []

    async def send(self, message):
        """Write one JSON-RPC message without shell interpolation."""
        self.process.stdin.write(json.dumps(message).encode() + b'\n')
        await self.process.stdin.drain()

    async def receive(self):
        """Read one bounded event and reject premature process termination."""
        line = await asyncio.wait_for(
            self.process.stdout.readline(), timeout=self.timeout,
        )
        if not line:
            raise RuntimeError('Codex app-server closed before completion')
        event = json.loads(line)
        # Startup account and quota notifications are unrelated personal data.
        if not event.get('method', '').startswith('account/'):
            self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            raise RuntimeError('Study event budget exhausted')
        return event

    async def request(self, method, params):
        """Wait for this response while retaining startup notifications."""
        self.sequence += 1
        request_id = self.sequence
        await self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            event = await self.receive()
            if event.get('id') == request_id and 'method' not in event:
                if 'error' in event:
                    raise RuntimeError(json.dumps(event['error']))
                return event['result']
            if 'id' in event and 'method' in event:
                raise RuntimeError(
                    'Unexpected server request before study turn: '
                    + event['method'],
                )

    async def start(self, *, model, tools, instructions, cwd):
        """Create a fresh ephemeral chat with an explicit static catalog."""
        if model not in MODELS:
            raise ValueError('Model is outside the approved study roster')
        await self.request('initialize', {
            'clientInfo': {'name': 'gdocs_scope_study', 'version': '1'},
            'capabilities': {'experimentalApi': True},
        })
        await self.send({'method': 'initialized', 'params': {}})
        started = await self.request('thread/start', {
            'model': model, 'modelProvider': 'openai',
            'allowProviderModelFallback': False,
            'ephemeral': True, 'cwd': str(cwd), 'sandbox': 'read-only',
            'baseInstructions': 'You are a document editing assistant. '
                                'Use only the supplied study tools.',
            'developerInstructions': instructions,
            'dynamicTools': tools,
            'config': {'model_reasoning_effort': 'medium'},
        })
        if (started.get('model') != model
                or started.get('reasoningEffort') != 'medium'
                or started.get('modelProvider') != 'openai'):
            raise RuntimeError('Effective model/settings differ from request')
        return started

    async def turn(
        self, thread_id, prompt, handler, *, action_limit=16,
        output_schema=None,
    ):
        """Execute a single bounded turn; only the supplied handler can act."""
        started = time.monotonic()
        params = {
            'threadId': thread_id, 'effort': 'medium',
            'input': [{'type': 'text', 'text': prompt, 'text_elements': []}],
        }
        if output_schema is not None:
            params['outputSchema'] = output_schema
        await self.request('turn/start', params)
        calls = self.current_calls = []
        messages = []
        # A wall-clock deadline complements each infrastructure read timeout.
        async with asyncio.timeout(self.timeout):
            while True:
                event = await self.receive()
                method = event.get('method')
                params = event.get('params', {})
                if method == 'item/tool/call':
                    calls.append({'tool': params['tool'],
                                  'arguments': params['arguments']})
                    if len(calls) > action_limit:
                        raise StudyAgentError(
                            'Semantic-action budget exhausted',
                        )
                    result = await handler(calls[-1])
                    calls[-1]['result'] = result
                    await self.send({'id': event['id'], 'result': {
                        'success': result.get('ok', True),
                        'contentItems': [{'type': 'inputText',
                                          'text': json.dumps(result)}],
                    }})
                elif 'id' in event and method:
                    # No approval, shell, browser or unrelated tool fallback.
                    await self.send({'id': event['id'], 'error': {
                        'code': -32601,
                        'message': 'Only study dynamic-tool calls are enabled',
                    }})
                    raise StudyAgentError(
                        'Unexpected study request: ' + method,
                    )
                elif method == 'thread/tokenUsage/updated':
                    usage = params['tokenUsage']['total']
                    if usage.get('outputTokens', 0) > MAX_OUTPUT_TOKENS:
                        raise StudyAgentError('Output-token budget exhausted')
                elif method == 'item/completed':
                    item = params.get('item', {})
                    if item.get('type') == 'agentMessage':
                        messages.append(item.get('text', ''))
                elif method == 'turn/completed':
                    turn = params['turn']
                    if turn.get('status') != 'completed':
                        raise RuntimeError(json.dumps(turn.get('error')))
                    return {'calls': calls, 'messages': messages,
                            'duration_seconds': time.monotonic() - started}
                elif method == 'error':
                    raise RuntimeError(json.dumps(params))


@asynccontextmanager
async def isolated_client(log_path, *, timeout=120):
    """Close and reap the app-server process group on every exit path."""
    with log_path.open('w') as stderr:
        process = await asyncio.create_subprocess_exec(
            *isolated_command(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=stderr,
            env={**os.environ, 'RUST_LOG': 'error'},
            start_new_session=True, limit=4 * 1024 * 1024,
        )
        try:
            client = StudyClient(process, timeout=timeout)
            yield client
        finally:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
            client.process_reaped = True


async def probe(model, output):
    """Verify actual dynamic-tool dispatch without accessing Google Docs."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {'model': model, 'effort': 'medium', 'status': 'running'}

    async def echo(call):
        if call != {'tool': 'study_echo', 'arguments': {'text': 'isolated'}}:
            raise ValueError('Unexpected probe call')
        return {'ok': True, 'text': 'isolated'}

    client = None
    try:
        async with isolated_client(output / 'stderr.log') as client:
            started = await client.start(
                model=model, cwd=Path.cwd(),
                instructions='This is an infrastructure probe, not a model '
                             'trial. Do not edit files or use external tools.',
                tools=[{
                    'type': 'function', 'name': 'study_echo',
                    'description': 'Echo the supplied synthetic text.',
                    'deferLoading': False,
                    'inputSchema': {
                        'type': 'object', 'properties': {'text': {
                            'type': 'string',
                        }}, 'required': ['text'],
                        'additionalProperties': False,
                    },
                }],
            )
            report['thread_start'] = started
            report['result'] = await client.turn(
                started['thread']['id'],
                'Call study_echo with text isolated exactly once, then reply '
                'ACCESS_OK. Do not perform any other action.', echo,
            )
            assert len(report['result']['calls']) == 1
            report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        if client is not None:
            report['process_reaped'] = client.process_reaped
            (output / 'events.json').write_text(
                json.dumps(client.events, indent=2),
            )
        (output / 'report.json').write_text(json.dumps(report, indent=2))


def main():
    """Run an explicit infrastructure probe on one approved model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(probe(args.model, args.output))


if __name__ == '__main__':
    main()
