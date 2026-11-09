"""Compare native loading while preserving the ordinary Codex model profile."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import re
import signal
from pathlib import Path

from analyze_native_models import raw_items, summarize
from native_loading_recovery import CAP, execute, metadata
from probe_client import MODELS, digest, write_json

PROFILE = 'model-default'
VALIDATION_REPEATS = 10
PROMPT = ('Read the color palette using the available tools and report the '
          'exact hex value of the palette entry whose English name is '
          'exactly "blue".')


def audit(row, events):
    """Observe schema exposure inside code mode and its discovery overhead."""
    result = summarize(row, events)
    items = raw_items(events)
    initial = next((i for i in items if i['type'] == 'additional_tools'), None)
    declarations = []
    if initial:
        declarations = [name for namespace in initial['tools']
                        for tool in namespace.get('tools', [])
                        if tool.get('type') == 'custom'
                        and tool.get('name') == 'exec'
                        for name in re.findall(
                            r'^### `(mcp__native_probe__[a-z0-9_]+)`$',
                            tool['description'], re.MULTILINE)]
    code = [i for i in items if i['type'] == 'custom_tool_call'
            and i.get('name') == 'exec']
    discoveries = sum('ALL_TOOLS' in i.get('input', '') for i in code)
    result.update(
        initial_native_schemas=len(declarations) if initial else None,
        exposure_verified=bool(initial) and len(declarations)
        == (36 if row['arm'] == 'eager' else 0),
        exposure_kind='code_mode_declarations', code_exec_calls=len(code),
        metadata_discovery_calls=discoveries,
        search_calls=discoveries + result['native_search_calls']
        + result['unsupported_search_calls'],
    )
    return result


def schedule(repeats):
    """Alternate arm order and interleave models in each paired repeat."""
    return [{'id': f'{repeat:03}-{model}-{arm}', 'model': model, 'arm': arm,
             'repeat': repeat, 'profile': PROFILE}
            for repeat in range(repeats)
            for arm in (('eager', 'deferred') if repeat % 2 == 0
                        else ('deferred', 'eager')) for model in MODELS]


def freeze(args):
    """Bind the ordinary profiles and protocol before any cohort inference."""
    path = args.output / 'manifest.json'
    if path.exists():
        return json.loads(path.read_text())
    reference = json.loads((args.reference / 'manifest.json').read_text())
    gate = None
    if args.phase == 'measurement':
        gate = json.loads((args.budget_root / 'validated-ordinary.json')
                          .read_text())
        models = gate['models']['deferred']['models']
    else:
        cache_path = Path.home() / '.codex/models_cache.json'
        cache = json.loads(cache_path.read_text())
        models = [m for m in cache['models'] if m['slug'] in MODELS]
    if {m['slug'] for m in models} != set(MODELS):
        raise ValueError('Exact model roster unavailable')
    for arm in ('eager', 'deferred'):
        write_json(args.output / f'{arm}-models.json',
                   metadata(models, PROFILE, arm))
    inputs = list(Path(__file__).parent.glob('*.py'))
    manifest = {
        'phase': args.phase, 'repeats': args.repeats, 'validation_gate': gate,
        'prompt': PROMPT,
        'schedule': schedule(args.repeats), 'profile': PROFILE,
        'expected': reference, 'sources': {
            str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs},
        'models': {arm: metadata(models, PROFILE, arm)
                   for arm in ('eager', 'deferred')},
        'protocol': {
            'scope': 'One fixed palette task; fresh independent native chats',
            'effort': 'medium', 'concurrency': 3,
            'intervention': 'Only supports_search_tool differs between arms; '
                            'retain tool_mode and use_responses_lite',
            'success': 'Native palette read plus returned blue in final text; '
                       'no forbidden calls or unexpected approvals',
            'stop': 'Drain on signal or infrastructure/task/exposure failure; '
                    'reserve no replacements',
            'analysis': 'Per-model paired input/cached/output tokens and turn '
                        'seconds; sample variance, 95% mean/paired CIs. '
                        'Cache state uncontrolled; no general task inference.',
            'budget': 'Separate 600-attempt validation and measurement caps. '
                      'Diagnostics consume validation. No budget transfers.',
        },
    }
    write_json(path, manifest)
    (args.output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    return manifest


def verify_frozen(args, manifest):
    """Reject drift or attempts to resize a cohort after observation."""
    if (digest(manifest)
            != (args.output / 'manifest.sha256').read_text().strip()
            or manifest['phase'] != args.phase
            or manifest['repeats'] != args.repeats):
        raise ValueError('Frozen cohort changed')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen execution source changed: ' + name)


async def run(args):
    """Run bounded cohorts against the shared phase reservation ledger."""
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = freeze(args)
    verify_frozen(args, manifest)
    path = args.budget_root / f'{args.phase}-ledger.json'
    phase = 'fix-validation' if args.phase == 'validation' else 'measurement'
    ledger = (json.loads(path.read_text()) if path.exists()
              else {'phase': phase, 'cap': CAP, 'attempts': []})
    if ledger['cap'] != CAP or ledger['phase'] != phase:
        raise ValueError('Invalid phase ledger')
    jobs = [{**job, 'id': args.output.name + '-' + job['id']}
            for job in manifest['schedule']]
    attempted = {r['id'] for r in ledger['attempts']}
    if len(attempted) != len(ledger['attempts']):
        raise ValueError('Duplicate reservation')
    remaining = [job for job in jobs if job['id'] not in attempted]
    if len(ledger['attempts']) + len(remaining) > CAP:
        raise ValueError('Phase cap would be exceeded')
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    for offset in range(0, len(remaining), 3):
        if stop.is_set():
            break
        batch = remaining[offset:offset + 3]
        ledger['attempts'].extend({**job, 'status': 'reserved'}
                                  for job in batch)
        write_json(path, ledger)
        for job in batch:
            directory = args.output / job['id']
            directory.mkdir()
            write_json(directory / 'models.json',
                       manifest['models'][job['arm']])
        rows = await asyncio.gather(*[
            execute(args.output / job['id'], job, manifest['expected'],
                    prompt=manifest['prompt'])
            for job in batch])
        passed = True
        for row in rows:
            directory = args.output / row['id']
            events = json.loads((directory / 'events.json').read_text())
            result = audit(row, events)
            write_json(directory / 'analysis.json', result)
            index = next(i for i, r in enumerate(ledger['attempts'])
                         if r['id'] == row['id'])
            ledger['attempts'][index] = row
            passed = passed and all(result[k] for k in (
                'success', 'exposure_verified', 'actor_reaped', 'mcp_reaped',
                'settings_match'))
            print(json.dumps({k: result[k] for k in (
                'id', 'success', 'exposure_verified', 'input_tokens')}),
                flush=True)
        write_json(path, ledger)
        if not passed:
            break
    results = [args.output / j['id'] / 'analysis.json' for j in jobs]
    if (args.phase == 'validation' and args.repeats >= VALIDATION_REPEATS
            and all(p.exists() for p in results)):
        audited = [json.loads(p.read_text()) for p in results]
        if all(all(r[k] for k in ('success', 'exposure_verified',
                                  'actor_reaped', 'mcp_reaped',
                                  'settings_match')) for r in audited):
            write_json(args.budget_root / 'validated-ordinary.json', {
                'manifest_sha256': digest(manifest),
                'models': manifest['models'], 'sessions': len(jobs),
                'source_fingerprint': manifest['expected']['identity']
                ['source_fingerprint'],
            })


def main():
    """Require the authorized phase cap and serialize phase-budget access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--budget-root', type=Path, required=True)
    parser.add_argument('--phase', choices=('validation', 'measurement'),
                        required=True)
    parser.add_argument('--repeats', type=int, choices=range(1, 101),
                        required=True)
    parser.add_argument('--authorized-sessions', type=int, required=True)
    args = parser.parse_args()
    if args.authorized_sessions != CAP:
        parser.error('Requires the authorized 600-attempt phase cap')
    args.budget_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.budget_root / f'{args.phase}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Diagnostics use validation.lock too; neither path can over-reserve.
        asyncio.run(run(args))


if __name__ == '__main__':
    main()
