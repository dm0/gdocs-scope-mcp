"""Supply deterministic loopback Responses events without model inference."""

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_REQUESTS = 3


def callable_names(tools, namespace=None):
    """Read advertised function names without retaining request prompts."""
    result = []
    for tool in tools:
        if tool.get('type') == 'namespace':
            result.extend(callable_names(tool.get('tools', []), tool['name']))
        elif tool.get('type') == 'function':
            result.append((namespace, tool['name']))
    return result


def response_events(item, sequence):
    """Emit the finite SSE lifecycle consumed by the real Codex runtime."""
    response = {
        'id': f'resp_fixture_{sequence}',
        'object': 'response',
        'created_at': int(time.time()),
        'model': 'native-fixture',
        'status': 'in_progress',
        'output': [],
    }
    yield {'type': 'response.created', 'response': response}
    yield {
        'type': 'response.output_item.added',
        'output_index': 0,
        'item': item,
    }
    yield {
        'type': 'response.output_item.done',
        'output_index': 0,
        'item': item,
    }
    yield {
        'type': 'response.completed',
        'response': {
            **response,
            'status': 'completed',
            'output': [item],
            'usage': {
                'input_tokens': 0,
                'output_tokens': 0,
                'total_tokens': 0,
                'input_tokens_details': {'cached_tokens': 0},
                'output_tokens_details': {'reasoning_tokens': 0},
            },
        },
    }


@contextmanager
def provider(tool_name, nonce, *, repetitions=1):
    """Serve one native tool proposal and then a terminal assistant message."""
    records = []

    class Handler(BaseHTTPRequestHandler):
        """Accept loopback Responses requests for one test case."""

        def log_message(self, *_args):
            """Keep prompts, headers and credentials out of console output."""

        def do_POST(self):
            """Return a scripted tool call over the provider wire API."""
            if self.path != '/v1/responses' or len(records) >= MAX_REQUESTS:
                self.send_error(400, 'Unexpected fixture request')
                return
            body = json.loads(
                self.rfile.read(int(self.headers['Content-Length']))
            )
            names = callable_names(body.get('tools', []))
            matches = [
                (ns, name)
                for ns, name in names
                if name == tool_name or name.endswith('__' + tool_name)
            ]
            records.append(
                {
                    'path': self.path,
                    'functions': names,
                    'target_matches': matches,
                    'tools': body.get('tools', []),
                    'discovery_items': [i for i in body.get('input', [])
                                        if i.get('type') in (
                                            'tool_search_output',
                                            'additional_tools')],
                }
            )
            if len(records) <= repetitions:
                if len(matches) != 1:
                    self.send_error(400, 'Target tool not uniquely advertised')
                    return
                namespace, name = matches[0]
                suffix = '' if len(records) == 1 else '-repeat'
                item = {
                    'type': 'function_call',
                    'id': 'fc_fixture' + suffix,
                    'call_id': 'call_fixture' + suffix,
                    'name': name,
                    'arguments': json.dumps({'nonce': nonce + suffix}),
                }
                if namespace:
                    item['namespace'] = namespace
            else:
                item = {
                    'type': 'message',
                    'id': 'msg_fixture',
                    'role': 'assistant',
                    'status': 'completed',
                    'content': [
                        {
                            'type': 'output_text',
                            'text': 'DONE',
                            'annotations': [],
                        }
                    ],
                }
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for event in response_events(item, len(records)):
                self.wfile.write(
                    ('data: ' + json.dumps(event) + '\n\n').encode()
                )
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
            raise RuntimeError('Local provider thread did not stop')
