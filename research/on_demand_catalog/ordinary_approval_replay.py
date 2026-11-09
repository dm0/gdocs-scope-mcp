"""Check native approval enforcement through ordinary code-mode execution."""

import argparse
import asyncio
import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from local_responses import response_events
from native_loading_recovery import metadata, route_command
from native_mcp_check import (
    REPRESENTATIVES,
    catalog,
    command,
    connection,
    override,
)
from native_model_study import start
from probe_client import write_json

FIRST_OPERATION_STEP = 2


async def native_turn(client, thread):
    """Route real native approval requests during a code-mode tool turn."""
    await client.request('turn/start', {
        'threadId': thread, 'effort': 'medium',
        'input': [{'type': 'text', 'text': 'Run the synthetic probe.',
                   'text_elements': []}],
    })
    async with asyncio.timeout(120):
        while True:
            event = await client.receive()
            if 'id' in event and 'method' in event:
                await client.handle_request(event)
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                if turn['status'] != 'completed':
                    raise RuntimeError('Native fixture turn failed')
                return turn


@contextmanager
def code_provider(tool, nonce, repetitions):
    """Propose discovery and native calls through the actual V8 tool host."""
    records = []

    class Handler(BaseHTTPRequestHandler):
        """Return bounded deterministic custom calls on loopback only."""

        def log_message(self, *_args):
            """Do not retain request headers or prompts."""

        def do_POST(self):
            """Emit metadata discovery, operations and a terminal message."""
            if (self.path != '/v1/responses'
                    or len(records) >= repetitions + 2):
                self.send_error(400, 'Unexpected replay request')
                return
            body = json.loads(self.rfile.read(
                int(self.headers['Content-Length'])))
            records.append({'types': [i['type']
                                      for i in body.get('input', [])]})
            step = len(records)
            if step <= repetitions + 1:
                if step == 1:
                    script = 'text(ALL_TOOLS.filter(x => x.name.endsWith('
                    script += json.dumps('__' + tool) + ')));'
                else:
                    suffix = '' if step == FIRST_OPERATION_STEP else '-repeat'
                    arguments = json.dumps({'nonce': nonce + suffix})
                    script = ('text(await tools.mcp__native_probe__' + tool
                              + '(' + arguments + '));')
                item = {'type': 'custom_tool_call', 'id': f'exec_{step}',
                        'call_id': f'exec_{step}', 'name': 'exec',
                        'input': script}
            else:
                item = {'type': 'message', 'id': 'done', 'role': 'assistant',
                        'status': 'completed', 'content': [{
                            'type': 'output_text', 'text': 'DONE',
                            'annotations': []}]}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for event in response_events(item, step):
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n')
                                 .encode())
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError('Replay server did not terminate')


async def run(output, reference):
    """Exercise the established nine-case approval matrix with no inference."""
    output.mkdir(parents=True)
    original = json.loads((reference / 'native-production.json').read_text())
    definitions = original['expected']
    spec = {name: {'source_tool': source,
                   'annotations': definitions[source]['annotations']}
            for name, source in REPRESENTATIVES.items()}
    cache = json.loads((Path.home() / '.codex/models_cache.json').read_text())
    models = [m for m in cache['models'] if m['slug'] == 'gpt-6.1-sol']
    write_json(output / 'models.json', metadata(models, 'model-default',
                                               'deferred'))
    cases = [('auto', t, 'accept', 1) for t in REPRESENTATIVES]
    cases += [('writes', 'probe_read', 'accept', 1)]
    cases += [('writes', t, d, 1)
              for t in ('probe_write', 'probe_delete')
              for d in ('accept', 'decline')]
    cases += [('writes', 'probe_write', 'accept', 2)]
    results = []
    for index, (mode, tool, decision, repetitions) in enumerate(cases):
        directory = output / f'{index}-{mode}-{tool}-{decision}'
        directory.mkdir()
        write_json(directory / 'fixture.json', spec)
        with code_provider(tool, directory.name, repetitions) as (
            endpoint, requests,
        ):
            cmd = command(sys.executable, [str(Path(__file__).with_name(
                'native_fixture_server.py'))],
                {'GDOCS_NATIVE_PROBE_DIR': str(directory.resolve())},
                mode, endpoint)
            cmd.extend(override('model_catalog_json',
                                str((output / 'models.json').resolve())))
            cmd = route_command(cmd, 'model-default')
            async with connection(directory, cmd, decision) as client:
                begun = await start(client, 'gpt-6.1-sol', local=True)
                thread = begun['thread']['id']
                native = await catalog(client, thread)

                result = await native_turn(client, thread)
                approvals = client.approvals
        journal = directory / 'executions.jsonl'
        executions = ([json.loads(line) for line in
                       journal.read_text().splitlines()]
                      if journal.exists() else [])
        process_path = directory / 'fixture-process.json'
        pid = json.loads(process_path.read_text())['pid']
        row = {'mode': mode, 'tool': tool, 'decision': decision,
               'repetitions': repetitions, 'approvals': approvals,
               'executions': executions, 'requests': requests,
               'result': result, 'actor_reaped': client.process_reaped,
               'mcp_reaped': not Path(f'/proc/{pid}').exists()}
        write_json(directory / 'result.json', row)
        read = tool == 'probe_read'
        if (len(approvals) != (0 if read else repetitions)
                or len(executions) != (repetitions if read
                                       or decision == 'accept' else 0)
                or not row['actor_reaped'] or not row['mcp_reaped']
                or not all(a['nonce_not_executed_before_response']
                           for a in approvals)
                or any(t['annotations'] != spec[name]['annotations']
                       for name, t in native['tools'].items())):
            raise RuntimeError('Ordinary approval invariant failed')
        results.append(row)
        print(json.dumps({'tool': tool, 'mode': mode, 'decision': decision,
                          'approvals': len(approvals),
                          'executions': len(executions)}), flush=True)
    write_json(output / 'summary.json', results)


def main():
    """Use private artifacts and perform no external model inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output, args.reference))


if __name__ == '__main__':
    main()
