"""Diagnose native loading profiles within separately bounded phase budgets."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import sys
from pathlib import Path

from analyze_native_models import summarize
from native_mcp_check import SERVER, catalog, command, connection, override
from native_model_study import PROMPT, reject_dynamic, start, verify_snapshot
from probe_client import MODELS, write_json

CAP = 600
PROFILES = ('function-lite', 'function-full', 'code-native', 'code-local')


def metadata(models, profile, arm):
    """Keep profile interventions explicit and identical between arms."""
    result = []
    for model in models:
        item = {**model, 'supports_search_tool': arm == 'deferred'}
        if profile.startswith('function-'):
            item.pop('tool_mode', None)
        if profile == 'function-full':
            item['use_responses_lite'] = False
        result.append(item)
    return {'models': result}


def native_command(directory, profile, endpoint=None):
    """Preserve native MCP execution and process-local approval policy."""
    result = command(
        sys.executable,
        [str(Path(__file__).with_name('native_palette_server.py'))],
        {'GDOCS_PALETTE_RUN_DIR': str(directory.resolve()),
         'GDOCS_SCOPE_MCP_TOOLSET_VERSION': 'v2',
         'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive'}, 'writes', endpoint)
    result.extend(override('model_catalog_json',
                           str((directory / 'models.json').resolve())))
    if profile.startswith('code-'):
        # The original runtime intentionally disables these features. Remove
        # only those pairs so the model's native code-mode profile can apply.
        result = [part for index, part in enumerate(result)
                  if not (part == '--disable' and index + 1 < len(result)
                          and result[index + 1] in ('code_mode',
                                                    'code_mode_only'))
                  and not (index > 0 and result[index - 1] == '--disable'
                           and part in ('code_mode', 'code_mode_only'))]
        for name, value in {'code_mode': True, 'code_mode_only': True,
                            'code_mode_tool_search': profile == 'code-local'
                            }.items():
            result.extend(override('features.' + name, value))
    return result


async def execute(directory, job, expected, *, endpoint=None):
    """Execute one reserved native turn and retain cleanup on every path."""
    row = {**job, 'status': 'reserved'}
    client = None
    try:
        async with connection(directory, native_command(
                directory, job['profile'], endpoint)) as client:
            client.timeout = 120
            effective = await start(client, job['model'], local=bool(endpoint))
            row['effective'] = {k: effective[k] for k in (
                'model', 'modelProvider', 'reasoningEffort')}
            thread = effective['thread']['id']
            descriptors = await catalog(client, thread)
            identity = await client.request('mcpServer/tool/call', {
                'threadId': thread, 'server': SERVER, 'tool': 'server_info',
                'arguments': {},
            })
            row['identity'] = identity['structuredContent']
            verify_snapshot(descriptors, row['identity'], expected)
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
        path = directory / 'calls.jsonl'
        row['server_calls'] = ([json.loads(line) for line in
                                path.read_text().splitlines()]
                               if path.exists() else [])
        write_json(directory / 'result.json', row)
    return row


async def run(args):
    """Reserve adaptive diagnostic trials from the validation budget only."""
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = args.output / 'validation-ledger.json'
    ledger = (json.loads(path.read_text()) if path.exists()
              else {'phase': 'fix-validation', 'cap': CAP, 'attempts': []})
    if ledger['cap'] != CAP or len(ledger['attempts']) >= CAP:
        raise ValueError('Validation budget exhausted or changed')
    index = len(ledger['attempts'])
    job = {'id': f'{index:03}-{args.model}-{args.profile}-{args.arm}',
           'model': args.model, 'profile': args.profile,
           'arm': args.arm, 'repeat': index}
    directory = args.output / job['id']
    directory.mkdir()
    cache = json.loads((Path.home() / '.codex/models_cache.json').read_text())
    models = [m for m in cache['models'] if m['slug'] == args.model]
    if len(models) != 1:
        raise ValueError('Exact model metadata missing')
    write_json(directory / 'models.json', metadata(models, args.profile,
                                                  args.arm))
    original = json.loads((args.reference / 'manifest.json').read_text())
    write_json(directory / 'request.json', {
        'job': job, 'prompt': PROMPT, 'reference': str(args.reference),
        'sources': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in Path(__file__).parent.glob('*.py')},
    })
    ledger['attempts'].append({**job, 'status': 'reserved'})
    write_json(path, ledger)
    row = await execute(directory, job, original)
    ledger['attempts'][-1] = row
    write_json(path, ledger)
    events = json.loads((directory / 'events.json').read_text())
    result = summarize(row, events)
    write_json(directory / 'analysis.json', result)
    print(json.dumps({'consumed': len(ledger['attempts']),
                      'result': result, 'error': row.get('error')}, indent=2))


def main():
    """Require explicit phase authorization and serialize budget mutations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--arm', choices=('eager', 'deferred'),
                        default='deferred')
    parser.add_argument('--authorized-sessions', type=int, required=True)
    args = parser.parse_args()
    if args.authorized_sessions != CAP:
        parser.error('Validation phase requires --authorized-sessions 600')
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'validation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(run(args))


if __name__ == '__main__':
    main()
