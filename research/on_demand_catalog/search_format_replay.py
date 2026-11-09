"""Replay documented search items and the observed incompatible call."""

import argparse
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from local_responses import callable_names, response_events
from native_loading_recovery import execute, metadata
from probe_client import write_json

MAX_REQUESTS = 3
CALL_STEP = 2


def search_item(observed):
    """Preserve the real response shape without silently repairing it."""
    arguments = {'query': 'docs_get_color_palette', 'limit': 1}
    if observed:
        return {'type': 'function_call', 'id': 'search_fixture',
                'call_id': 'search_fixture', 'namespace': 'tool_search',
                'name': 'tool_search_tool', 'arguments': json.dumps(arguments)}
    return {'type': 'tool_search_call', 'id': 'search_fixture',
            'call_id': 'search_fixture', 'execution': 'client',
            'status': 'completed', 'arguments': arguments}


@contextmanager
def replay_provider(observed, *, terminal_only=False):
    """Serve bounded local SSE and retain only tool/discovery wire evidence."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        """Keep all transport activity on loopback and omit headers/prompts."""

        def log_message(self, *_args):
            """Suppress HTTP logging."""

        def do_POST(self):
            """Return search, a loaded palette call, and a terminal answer."""
            if (self.path != '/v1/responses'
                    or len(requests) >= MAX_REQUESTS):
                self.send_error(400, 'Unexpected replay request')
                return
            body = json.loads(self.rfile.read(
                int(self.headers['Content-Length'])))
            inputs = [i for i in body.get('input', []) if i.get('type') in (
                'additional_tools', 'tool_search_output',
                'function_call_output')]
            tools = body.get('tools', []) + [
                t for i in inputs for t in i.get('tools', [])]
            requests.append({'tools': body.get('tools', []), 'items': inputs})
            matches = [(ns, name) for ns, name in callable_names(tools)
                       if name == 'docs_get_color_palette'
                       or name.endswith('__docs_get_color_palette')]
            if len(requests) == 1 and not terminal_only:
                item = search_item(observed)
            elif (len(requests) == CALL_STEP and len(matches) == 1
                  and not terminal_only):
                namespace, name = matches[0]
                item = {'type': 'function_call', 'id': 'palette_fixture',
                        'call_id': 'palette_fixture', 'name': name,
                        'arguments': '{}'}
                if namespace:
                    item['namespace'] = namespace
            else:
                item = {'type': 'message', 'id': 'answer_fixture',
                        'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text',
                                     'text': '#0000FF', 'annotations': []}]}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for event in response_events(item, len(requests)):
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n')
                                 .encode())
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError('Replay HTTP thread did not stop')


async def run(output, reference):
    """Reproduce the mismatch in the actual native client without a model."""
    original = json.loads((reference / 'manifest.json').read_text())
    cache = json.loads((Path.home() / '.codex/models_cache.json').read_text())
    models = [m for m in cache['models'] if m['slug'] == 'gpt-6.1-sol']
    results = []
    for profile in ('function-lite', 'function-full'):
        for observed in (False, True):
            directory = output / f'{profile}-{observed}'
            directory.mkdir(parents=True)
            write_json(directory / 'models.json', metadata(
                models, profile, 'deferred'))
            job = {'id': directory.name, 'profile': profile,
                   'model': 'gpt-6.1-sol', 'arm': 'deferred', 'repeat': 0}
            with replay_provider(observed) as (endpoint, requests):
                row = await execute(directory, job, original,
                                    endpoint=endpoint)
            write_json(directory / 'wire.json', requests)
            palette = [c for c in row['server_calls'] if
                       c['tool'] == 'docs_get_color_palette' and c['allowed']]
            unsupported = [i for request in requests for i in request['items']
                           if i.get('output')
                           == 'unsupported call: tool_searchtool_search_tool']
            if (row['status'] != 'completed'
                    or bool(palette) == observed
                    or bool(unsupported) != observed
                    or not row['actor_reaped'] or not row['mcp_reaped']):
                raise RuntimeError('Search format replay invariant failed')
            results.append({'profile': profile, 'observed': observed,
                            'palette_calls': len(palette),
                            'unsupported': len(unsupported)})
    write_json(output / 'summary.json', results)
    print(json.dumps(results, indent=2))


def main():
    """Use a new private directory; no external inference is performed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output, args.reference))


if __name__ == '__main__':
    main()
