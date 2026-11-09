"""Run the separately authorized sixty-session native loading comparison."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import signal
import sys
from pathlib import Path

from local_responses import callable_names, provider
from native_mcp_check import (
    SERVER,
    catalog,
    command,
    connection,
    native_production,
    override,
)
from probe_client import INSTRUCTIONS, MODELS, ROOT, digest, write_json

CAP = 60
PROMPT = ('Read the color palette using the available tools and report the '
          'exact hex value of Google blue.')
SOURCES = ('native_model_study.py', 'native_palette_server.py',
           'native_mcp_check.py', 'local_responses.py', 'probe_client.py')


def schedule():
    """Alternate arm order per repeat, interleaving the three models."""
    return [{'id': f'{repeat:02}-{model}-{arm}', 'model': model, 'arm': arm,
             'repeat': repeat}
            for repeat in range(10)
            for arm in (('eager', 'deferred') if repeat % 2 == 0
                        else ('deferred', 'eager'))
            for model in MODELS]


def child_command(directory, catalog_path, endpoint=None):
    """Use the native MCP route with no dynamic functions or global edits."""
    result = command(sys.executable,
                     [str(Path(__file__).with_name('native_palette_server.py'))],
                     {'GDOCS_PALETTE_RUN_DIR': str(directory.resolve()),
                      'GDOCS_SCOPE_MCP_TOOLSET_VERSION': 'v2',
                      'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive'},
                     'writes', endpoint)
    result.extend(override('model_catalog_json', str(catalog_path.resolve())))
    return result


async def start(client, model, *, local=False):
    """Verify exact model, provider and medium effort before inference."""
    await client.request('initialize', {
        'clientInfo': {'name': 'native_palette_study', 'version': '1'},
        'capabilities': {'experimentalApi': True},
    })
    await client.send({'method': 'initialized', 'params': {}})
    expected = 'native_fixture' if local else 'openai'
    result = await client.request('thread/start', {
        'model': model, 'modelProvider': expected,
        'allowProviderModelFallback': False, 'ephemeral': True,
        'experimentalRawEvents': True, 'cwd': str(ROOT),
        'sandbox': 'read-only', 'baseInstructions':
        'You are a document editing assistant. Use only the study tools.',
        'developerInstructions': INSTRUCTIONS,
        'config': {'model_reasoning_effort': 'medium'},
    })
    if (result['model'] != model or result['modelProvider'] != expected
            or result['reasoningEffort'] != 'medium'):
        raise RuntimeError('Effective model/provider/effort changed')
    return result


def verify_snapshot(native, identity, manifest):
    """Reject product or native descriptor drift before the model turn."""
    normalized = {n: {k: v for k, v in t.items() if v is not None}
                  for n, t in native['tools'].items()}
    if normalized != manifest['catalog']:
        raise RuntimeError('Native tool contracts changed')
    if (identity['source_fingerprint']
            != manifest['identity']['source_fingerprint']):
        raise RuntimeError('Product fingerprint changed')


async def reject_dynamic(_call):
    """Fail closed if a dynamic callback unexpectedly replaces native MCP."""
    raise RuntimeError('Dynamic tool bridge is forbidden')


async def trial(directory, job, manifest, *, endpoint=None):
    """Collect native calls, search items and cleanup for one fresh chat."""
    directory.mkdir()
    row = {**job, 'status': 'reserved'}
    client = None
    try:
        cmd = child_command(directory,
                            directory.parent / f"{job['arm']}-models.json",
                            endpoint)
        async with connection(directory, cmd) as client:
            client.timeout = 120
            started = await start(client, job['model'], local=bool(endpoint))
            row['effective'] = {k: started[k] for k in
                                ('model', 'modelProvider', 'reasoningEffort')}
            thread = started['thread']['id']
            native = await catalog(client, thread)
            identity = await client.request('mcpServer/tool/call', {
                'threadId': thread, 'server': SERVER, 'tool': 'server_info',
                'arguments': {},
            })
            row['identity'] = identity['structuredContent']
            verify_snapshot(native, row['identity'], manifest)
            row['result'] = await client.turn(thread, PROMPT, reject_dynamic)
            row['approvals'] = client.approvals
            row['status'] = 'completed'
    except Exception as error:  # noqa: BLE001 - retain failures and cleanup
        row.update(status='infrastructure_failure', error=str(error))
    finally:
        if client is not None:
            row['actor_reaped'] = client.process_reaped
        process = directory / 'process.json'
        if process.exists():
            pid = json.loads(process.read_text())['pid']
            row['mcp_reaped'] = not Path(f'/proc/{pid}').exists()
        journal = directory / 'calls.jsonl'
        row['server_calls'] = ([json.loads(line) for line in
                                journal.read_text().splitlines()]
                               if journal.exists() else [])
        write_json(directory / 'result.json', row)
    return row


async def prepare(output):
    """Freeze metadata and prove each native loading arm without inference."""
    if (output / 'manifest.json').exists():
        raise ValueError('Manifest already frozen')
    catalog_definitions = await native_production(output)
    production = json.loads((output / 'native-production.json').read_text())
    cache = json.loads((Path.home() / '.codex/models_cache.json').read_text())
    selected = [m for m in cache['models'] if m['slug'] in MODELS]
    if {m['slug'] for m in selected} != set(MODELS):
        raise ValueError('Approved model metadata is missing')
    for arm in ('eager', 'deferred'):
        models = [{**{k: v for k, v in m.items() if k != 'tool_mode'},
                   'supports_search_tool': arm == 'deferred'}
                  for m in selected]
        write_json(output / f'{arm}-models.json', {'models': models})
    manifest = {'cap': CAP, 'schedule': schedule(), 'prompt': PROMPT,
                'instructions': INSTRUCTIONS, 'catalog': catalog_definitions,
                'identity': production['identity']['structuredContent'],
                'effort': 'medium', 'concurrency': 3,
                'metadata_override': 'omit tool_mode in both arms; toggle '
                'only supports_search_tool', 'preflight': []}
    for model in MODELS:
        for arm in ('eager', 'deferred'):
            job = {'id': f'preflight-{model}-{arm}',
                   'model': model, 'arm': arm}
            with provider('docs_get_color_palette', 'unused',
                          search=arm == 'deferred', call_arguments={}) as (
                endpoint, requests,
            ):
                row = await trial(output / job['id'], job, manifest,
                                  endpoint=endpoint)
            write_json(output / job['id'] / 'wire.json', requests)
            if row['status'] != 'completed':
                raise RuntimeError('Local native loading preflight failed')
            event_path = output / job['id'] / 'events.json'
            events = json.loads(event_path.read_text())
            palette = [e['params']['item'] for e in events
                       if e.get('method') == 'item/completed'
                       and e['params']['item'].get('tool')
                       == 'docs_get_color_palette']
            if (len(palette) != 1 or palette[0]['status'] != 'completed'
                    or palette[0]['arguments'] != {}):
                raise RuntimeError('Preflight palette execution failed')
            first = requests[0]
            definitions = first['tools'] + [t for i in first['discovery_items']
                                            for t in i.get('tools', [])]
            native_names = [n for ns, n in callable_names(definitions)
                            if ns == 'mcp__native_probe'
                            or n.startswith('mcp__native_probe__')]
            expected = 0 if arm == 'deferred' else len(catalog_definitions)
            if len(native_names) != expected:
                raise RuntimeError('Wrong initial native schema exposure')
            if arm == 'deferred' and not any(
                i['type'] == 'tool_search_output'
                for i in requests[1]['discovery_items']
            ):
                raise RuntimeError('Runtime search output is absent')
            if not row['actor_reaped'] or not row['mcp_reaped']:
                raise RuntimeError('Preflight process cleanup failed')
            manifest['preflight'].append({**job, 'initial_schemas': expected,
                                          'requests': len(requests)})
    paths = [Path(__file__).with_name(n) for n in SOURCES]
    paths += [ROOT / 'research/tool_consolidation/codex_study_runtime.py',
              Path(__file__).with_name('NATIVE_MODEL_PROTOCOL.md')]
    paths += [output / f'{a}-models.json' for a in ('eager', 'deferred')]
    manifest['sources'] = {str(p.resolve()): hashlib.sha256(p.read_bytes())
                           .hexdigest() for p in paths}
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    write_json(output / 'ledger.json', {'cap': CAP, 'attempts': []})
    print(json.dumps({'preflights': len(manifest['preflight']),
                      'external_model_sessions': 0}), flush=True)


async def run(output):
    """Reserve sixty attempts at most; drain on interruption or failure."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Manifest changed')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen source changed: ' + name)
    ledger = json.loads((output / 'ledger.json').read_text())
    attempted = {r['id'] for r in ledger['attempts']}
    if (ledger['cap'] != CAP or manifest['cap'] != CAP
            or len(attempted) != len(ledger['attempts'])
            or not attempted <= {r['id'] for r in manifest['schedule']}):
        raise ValueError('Invalid session ledger')
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    remaining = [j for j in manifest['schedule'] if j['id'] not in attempted]
    for offset in range(0, len(remaining), 3):
        if stop.is_set():
            break
        batch = remaining[offset:offset + 3]
        if len(ledger['attempts']) + len(batch) > CAP:
            raise ValueError('Session cap exceeded')
        ledger['attempts'].extend({**j, 'status': 'reserved'} for j in batch)
        write_json(output / 'ledger.json', ledger)
        rows = await asyncio.gather(*[
            trial(output / job['id'], job, manifest) for job in batch])
        for row in rows:
            index = next(i for i, r in enumerate(ledger['attempts'])
                         if r['id'] == row['id'])
            ledger['attempts'][index] = row
            print(json.dumps({k: row[k] for k in ('id', 'status')}),
                  flush=True)
        write_json(output / 'ledger.json', ledger)
        if any(r['status'] != 'completed' or not r.get('actor_reaped')
               or not r.get('mcp_reaped') for r in rows):
            break


def main():
    """Require the explicit new sixty-session budget before real inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--authorized-sessions', type=int)
    args = parser.parse_args()
    if args.action == 'run' and args.authorized_sessions != CAP:
        parser.error('Real inference requires --authorized-sessions 60')
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'study.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(prepare(args.output) if args.action == 'prepare'
                    else run(args.output))


if __name__ == '__main__':
    main()
