"""Check native MCP metadata and approvals with a local provider fixture."""

import argparse
import asyncio
import json
import os
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import Client
from local_responses import provider
from probe_client import ROOT, runtime, transport, write_json

RUNTIME = runtime()
SERVER = 'native_probe'
REPRESENTATIVES = {
    'probe_read': 'server_info',
    'probe_write': 'docs_insert',
    'probe_delete': 'docs_delete_comment',
}


def override(key, value):
    """Build one process-local override without editing config files."""
    return ['-c', key + '=' + json.dumps(value)]


def command(server_command, args, environment, mode, endpoint=None):
    """Disable unrelated servers and configure the bounded native probe."""
    result = RUNTIME.isolated_command()
    values = {
        f'mcp_servers.{SERVER}.command': server_command,
        f'mcp_servers.{SERVER}.args': args,
        f'mcp_servers.{SERVER}.enabled': True,
        f'mcp_servers.{SERVER}.required': True,
        f'mcp_servers.{SERVER}.default_tools_approval_mode': mode,
        f'mcp_servers.{SERVER}.startup_timeout_sec': 20,
        'approvals_reviewer': 'user',
        'approval_policy': 'on-request',
    }
    values.update(
        {f'mcp_servers.{SERVER}.env.{k}': v for k, v in environment.items()}
    )
    if endpoint:
        values.update(
            {
                'model_provider': 'native_fixture',
                'model_providers.native_fixture.name': 'Local fixture',
                'model_providers.native_fixture.base_url': endpoint,
                'model_providers.native_fixture.wire_api': 'responses',
                'model_providers.native_fixture.requires_openai_auth': False,
                'model_providers.native_fixture.request_max_retries': 0,
            }
        )
    for key, value in values.items():
        result.extend(override(key, value))
    return result


class NativeClient(RUNTIME.StudyClient):
    """Observe native approvals, with no server-side confirmation code."""

    def __init__(self, process, decision='decline'):
        """Default to denial for an unexpected confirmation."""
        super().__init__(process, timeout=60)
        self.decision = decision
        self.approvals = []

    async def handle_request(self, event):
        """Answer only the expected synthetic tool approval request."""
        if event['method'] != 'tool/requestUserInput':
            raise RuntimeError('Unexpected server request: ' + event['method'])
        params = event['params']
        matches = [
            e['params']['item']
            for e in self.events
            if e.get('method') == 'item/started'
            and e['params'].get('item', {}).get('id') == params['itemId']
        ]
        if not matches or matches[-1].get('server') != SERVER:
            raise RuntimeError('Approval does not identify the fixture server')
        answers = {}
        target = 'accept' if self.decision == 'accept' else 'decline'
        for question in params['questions']:
            options = [
                o['label']
                for o in question.get('options', [])
                if o['label'].lower().startswith(target)
            ]
            if len(options) != 1:
                raise RuntimeError('Expected approval option is absent')
            answers[question['id']] = {'answers': options}
        self.approvals.append({'request': params, 'decision': self.decision})
        await self.send({'id': event['id'], 'result': {'answers': answers}})

    async def request(self, method, params):
        """Keep processing elicited confirmations while waiting for an RPC."""
        self.sequence += 1
        sequence = self.sequence
        await self.send({'id': sequence, 'method': method, 'params': params})
        while True:
            event = await self.receive()
            if event.get('id') == sequence and 'method' not in event:
                if 'error' in event:
                    raise RuntimeError(json.dumps(event['error']))
                return event['result']
            if 'id' in event and 'method' in event:
                await self.handle_request(event)


@asynccontextmanager
async def connection(directory, cmd, decision='decline'):
    """Close the actual Codex process group on success or failure."""
    with (directory / 'codex.stderr').open('w') as stderr:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
            start_new_session=True,
            limit=4 * 1024 * 1024,
            env={**os.environ, 'RUST_LOG': 'error'},
        )
        client = NativeClient(process, decision)
        try:
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
            write_json(directory / 'events.json', client.events)


async def start(client, model_provider='openai'):
    """Create an ephemeral native-MCP thread with no dynamic tools."""
    await client.request(
        'initialize',
        {
            'clientInfo': {
                'name': 'native_mcp_approval_probe',
                'version': '1',
            },
            'capabilities': {'experimentalApi': True},
        },
    )
    await client.send({'method': 'initialized', 'params': {}})
    return await client.request(
        'thread/start',
        {
            'model': (
                'native-fixture'
                if model_provider == 'native_fixture'
                else 'gpt-6.1-sol'
            ),
            'modelProvider': model_provider,
            'allowProviderModelFallback': False,
            'ephemeral': True,
            'cwd': str(ROOT),
            'sandbox': 'read-only',
            'baseInstructions': 'Local native MCP approval characterization. '
            'Only the named synthetic operation is permitted.',
        },
    )


async def catalog(client, thread):
    """Fetch the actual native client inventory for the configured thread."""
    result = await client.request(
        'mcpServerStatus/list',
        {
            'threadId': thread,
            'serverName': SERVER,
            'detail': 'toolsAndAuthOnly',
        },
    )
    return next(s for s in result['data'] if s['name'] == SERVER)


async def native_production(output):
    """Compare the complete product catalog through SDK and native Codex."""
    async with Client(transport(output / 'sdk.stderr')) as sdk:
        expected = {
            t.name: t.model_dump(mode='json', exclude_none=True)
            for t in await sdk.list_tools()
        }
    cmd = command(
        str(Path(sys.executable).parent / 'gdocs-scope-mcp'),
        [],
        {
            'GDOCS_SCOPE_MCP_TOOLSET_VERSION': 'v2',
            'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive',
        },
        'writes',
    )
    async with connection(output, cmd) as client:
        started = await start(client)
        thread = started['thread']['id']
        actual = await catalog(client, thread)
        info = await client.request(
            'mcpServer/tool/call',
            {
                'threadId': thread,
                'server': SERVER,
                'tool': 'server_info',
                'arguments': {},
            },
        )
        report = {
            'expected': expected,
            'native': actual,
            'identity': info,
            'approvals': client.approvals,
            'model_turns': 0,
        }
    report['codex_reaped'] = client.process_reaped
    write_json(output / 'native-production.json', report)
    return expected


async def fixture_case(output, spec, mode, tool, decision):
    """Drive the native executor with a deterministic tool proposal."""
    output.mkdir(parents=True)
    write_json(output / 'fixture.json', spec)
    nonce = output.name
    prompt = f'Call {tool} once with nonce {nonce}.'
    report = {
        'tool': tool,
        'mode': mode,
        'decision': decision,
        'external_model_turns': 0,
    }
    try:
        with provider(tool, nonce) as (endpoint, requests):
            cmd = command(
                sys.executable,
                [str(Path(__file__).with_name('native_fixture_server.py'))],
                {
                    'GDOCS_NATIVE_PROBE_DIR': str(output.resolve()),
                },
                mode,
                endpoint,
            )
            async with connection(output, cmd, decision) as client:
                started = await start(client, 'native_fixture')
                thread = started['thread']['id']
                report['native_catalog'] = await catalog(client, thread)
                await client.request(
                    'turn/start',
                    {
                        'threadId': thread,
                        'input': [
                            {
                                'type': 'text',
                                'text': prompt,
                                'text_elements': [],
                            }
                        ],
                    },
                )
                async with asyncio.timeout(60):
                    while True:
                        event = await client.receive()
                        if 'id' in event and 'method' in event:
                            await client.handle_request(event)
                        if event.get('method') == 'turn/completed':
                            report['turn'] = event['params']['turn']
                            break
                report['approvals'] = client.approvals
            report['codex_reaped'] = client.process_reaped
            report['provider_requests'] = requests
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        journal = output / 'executions.jsonl'
        report['executions'] = (
            [json.loads(line) for line in journal.read_text().splitlines()]
            if journal.exists()
            else []
        )
        process = output / 'fixture-process.json'
        if process.exists():
            pid = json.loads(process.read_text())['pid']
            report['mcp_reaped'] = not Path(f'/proc/{pid}').exists()
        write_json(output / 'report.json', report)
    return report


async def run(output):
    """Characterize native transport and configured approval decisions."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    original = await native_production(output)
    spec = {
        name: {
            'source_tool': source,
            'annotations': original[source]['annotations'],
        }
        for name, source in REPRESENTATIVES.items()
    }
    cases = [('auto', tool, 'accept') for tool in REPRESENTATIVES]
    cases += [('writes', 'probe_read', 'accept')]
    cases += [
        ('writes', tool, decision)
        for tool in ('probe_write', 'probe_delete')
        for decision in ('accept', 'decline')
    ]
    results = []
    for index, (mode, tool, decision) in enumerate(cases):
        result = await fixture_case(
            output / f'{index}-{mode}-{tool}-{decision}',
            spec,
            mode,
            tool,
            decision,
        )
        results.append(result)
        print(
            json.dumps(
                {
                    'tool': tool,
                    'mode': mode,
                    'decision': decision,
                    'approvals': len(result['approvals']),
                    'executions': len(result['executions']),
                }
            ),
            flush=True,
        )
    write_json(
        output / 'summary.json', {'cases': results, 'external_model_turns': 0}
    )


def main():
    """Run native-MCP checks without external models or document access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    asyncio.run(run(parser.parse_args().output))


if __name__ == '__main__':
    main()
