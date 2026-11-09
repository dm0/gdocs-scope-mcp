"""Prepare compatibility evidence and bounded optional model canaries."""

import argparse
import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = ROOT / 'research/tool_consolidation/codex_study_runtime.py'
CORE = ('server_info', 'docs_get_tree', 'docs_read')
MODELS = ('gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-astra')
CAP = 6
INSTRUCTIONS = (
    'Compatibility canary: use only server_info or docs_get_color_palette. '
    'Do not access documents, accounts, files, browser or other tools. '
    'Discover the palette tool if needed, read it, then answer the request.'
)


def runtime():
    """Reuse the bounded app-server transport without importing study data."""
    spec = importlib.util.spec_from_file_location(
        'catalog_probe_runtime', RUNTIME_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value):
    """Bind a reproducible JSON snapshot."""
    encoded = json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path, value):
    """Persist private evidence atomically."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def model_tools(catalog, arm):
    """Change only loading policy; keep the complete callable interface."""
    if arm not in {'eager', 'deferred'}:
        raise ValueError('Unknown loading arm')
    return [{
        'type': 'function', 'name': tool['name'],
        'description': tool['description'], 'inputSchema': tool['inputSchema'],
        'deferLoading': arm == 'deferred' and tool['name'] not in CORE,
    } for tool in catalog['tools']]


def transport(log):
    """Launch the assigned worktree with a fixed v2 full-drive catalog."""
    return StdioTransport(
        command=str(Path(sys.executable).parent / 'gdocs-scope-mcp'), args=[],
        cwd=str(ROOT), env={**os.environ,
                           'GDOCS_SCOPE_MCP_TOOLSET_VERSION': 'v2',
                           'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive'},
        log_file=log, keep_alive=False,
    )


def verify_identity(info, expected):
    """Reject product drift before a canary actor starts."""
    if info['source_fingerprint'] != expected['source_fingerprint']:
        raise ValueError('Product source changed')


def validate_call(call, definitions):
    """Reject writes and document reads before any operation is dispatched."""
    name, args = call['tool'], call['arguments']
    if name not in {'server_info', 'docs_get_color_palette'}:
        raise ValueError('Canary permission scope exceeded')
    Draft202012Validator(definitions[name]['inputSchema']).validate(args)
    return name, args


async def prepare(output):
    """Capture MCP and accept two ephemeral threads without starting turns."""
    if (output / 'manifest.json').exists():
        raise ValueError('Preparation already frozen')
    async with Client(transport(output / 'mcp.stderr')) as client:
        info = (await client.call_tool('server_info', {})).structured_content
        catalog = {'instructions': client.initialize_result.instructions,
                   'tools': [t.model_dump(mode='json', exclude_none=True)
                             for t in await client.list_tools()]}
        assert catalog['tools'] == [
            t.model_dump(mode='json', exclude_none=True)
            for t in await client.list_tools()
        ]
        protocol = client.initialize_result.protocolVersion
    assert not Path(f'/proc/{info["pid"]}').exists()
    write_json(output / 'mcp-snapshot.json', {
        'identity': info, 'protocol': protocol, 'catalog': catalog,
    })
    records = []
    for arm in ('eager', 'deferred'):
        client = None
        try:
            async with runtime().isolated_client(
                output / (arm + '.stderr'), timeout=60,
            ) as client:
                started = await client.start(
                    model='gpt-6.1-sol', tools=model_tools(catalog, arm),
                    instructions=INSTRUCTIONS, cwd=ROOT,
                )
                records.append({'arm': arm, 'model': started['model'],
                                'effort': started['reasoningEffort'],
                                'thread_id': started['thread']['id']})
                assert not any(e.get('method') == 'turn/started'
                               for e in client.events)
        finally:
            if client is not None:
                write_json(output / (arm + '-handshake.json'), {
                    'events': client.events,
                    'process_reaped': client.process_reaped,
                    'model_turns_started': 0,
                })
    manifest = {
        'catalog': catalog, 'catalog_sha256': digest(catalog),
        'identity': info, 'mcp_protocol': protocol,
        'core': CORE, 'models': MODELS, 'effort': 'medium', 'session_cap': CAP,
        'handshakes': records, 'model_turns_started': 0,
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes())
                    .hexdigest() for p in (
                        Path(__file__),
                        RUNTIME_PATH,
                    )},
        'schedule': [{'id': f'{model}-{arm}', 'model': model, 'arm': arm}
                     for model in MODELS for arm in ('eager', 'deferred')],
        'authorization': 'Model canaries require separate explicit approval; '
                         'preparation starts no inference.',
    }
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    write_json(output / 'ledger.json', {'cap': CAP, 'attempts': []})
    print(json.dumps({'protocol': protocol, 'tools': len(catalog['tools']),
                      'handshakes': len(records), 'model_turns_started': 0}))


async def run(output):
    """Run each authorized canary once, preserving any failed reservation."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest changed')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen canary execution source changed')
    ledger = json.loads((output / 'ledger.json').read_text())
    if ledger['cap'] != CAP or manifest['session_cap'] != CAP:
        raise ValueError('Unexpected canary budget')
    attempted = {a['id'] for a in ledger['attempts']}
    if (len(attempted) != len(ledger['attempts'])
            or not attempted <= {j['id'] for j in manifest['schedule']}):
        raise ValueError('Invalid reservation ledger')
    definitions = {t['name']: t for t in manifest['catalog']['tools']}
    for job in manifest['schedule']:
        if job['id'] in attempted:
            continue
        if len(ledger['attempts']) >= CAP:
            raise ValueError('Six-canary budget exhausted')
        directory = output / job['id']
        directory.mkdir(exist_ok=True)
        row = {**job, 'status': 'reserved'}
        client, info = None, None
        ledger['attempts'].append(row)
        write_json(output / 'ledger.json', ledger)
        try:
            async with Client(transport(directory / 'mcp.stderr')) as mcp:
                info = (await mcp.call_tool('server_info', {})
                        ).structured_content
                verify_identity(info, manifest['identity'])

                async def dispatch(call):
                    name, args = validate_call(call, definitions)
                    return (await mcp.call_tool(name, args)).structured_content

                async with runtime().isolated_client(
                    directory / 'codex.stderr', timeout=120,
                ) as client:
                    started = await client.start(
                        model=job['model'], cwd=ROOT,
                        instructions=INSTRUCTIONS,
                        tools=model_tools(manifest['catalog'], job['arm']),
                    )
                    row.update(effective_model=started['model'],
                               effective_effort=started['reasoningEffort'],
                               thread_id=started['thread']['id'])
                    result = await client.turn(
                        started['thread']['id'],
                        'Read the color palette using the available tools and '
                        'report the exact hex value of Google blue.',
                        dispatch, action_limit=4,
                    )
                    row.update(status='completed', result=result)
        except Exception as error:
            row.update(status='failed', error=str(error))
            raise
        finally:
            if client is not None:
                row['actor_reaped'] = client.process_reaped
                write_json(directory / 'events.json', client.events)
            if info is not None:
                row['mcp_reaped'] = not Path(f'/proc/{info["pid"]}').exists()
            write_json(directory / 'result.json', row)
            write_json(output / 'ledger.json', ledger)


def main():
    """Require explicit authorization before any model turn can start."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--authorized-sessions', type=int)
    args = parser.parse_args()
    if args.action == 'run' and args.authorized_sessions != CAP:
        parser.error('Run requires explicit --authorized-sessions 6 approval')
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'probe.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(prepare(args.output) if args.action == 'prepare'
                    else run(args.output))


if __name__ == '__main__':
    main()
