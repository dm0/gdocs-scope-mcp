"""Freeze and execute only the user-approved 1500-attempt A-versus-D stage."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import random
import re
import signal
import subprocess
import time
from html import unescape
from pathlib import Path

from codex_study_runtime import MODELS
from noninferiority_scenarios import SEED, corpus
from run_reduced_study import (
    POLICY,
    digest,
    require_frozen_source,
    run_job,
    source_hashes,
    write_json,
)
from study_execution import ROOT, fixture_backend, reference_states
from study_live import live_backend
from tool_consolidation_preflight import capture_catalog

CAP = 1500
PRIOR = 1321
ARMS = ('baseline', 'both')
EXTRA_SOURCES = ('noninferiority_scenarios.py', 'run_noninferiority.py',
                 'analyze_noninferiority.py', 'NONINFERIORITY_PROTOCOL.md')


def sources():
    """Freeze both shared execution code and stage-specific code/protocol."""
    return {**source_hashes(), **{
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes())
        .hexdigest() for name in EXTRA_SOURCES
    }}


def lineage(previous):
    """Count both previous cohorts without freeing failed reservations."""
    restart = json.loads((previous / 'manifest.json').read_text())
    paths = [Path(restart['prior_run']['directory']), previous]
    result = []
    for path in paths:
        manifest = json.loads((path / 'manifest.json').read_text())
        if digest(manifest) != (path / 'manifest.sha256').read_text().strip():
            raise ValueError('Prior manifest changed')
        raw = (path / 'ledger.json').read_bytes()
        attempts = json.loads(raw)['attempts']
        result.append({'directory': str(path.resolve()),
                       'attempts': len(attempts),
                       'ledger_sha256': hashlib.sha256(raw).hexdigest(),
                       'manifest_sha256': digest(manifest)})
    if sum(x['attempts'] for x in result) != PRIOR:
        raise ValueError('Expected the preserved 1321 prior reservations')
    return result


def schedule(cases):
    """Pair the same task/backend across arms, counterbalancing arm order."""
    rng = random.Random(SEED + 1)
    pairs = [(case, model) for case in cases for model in MODELS]
    rng.shuffle(pairs)
    jobs = []
    counts = dict.fromkeys(MODELS, 0)
    for case, model in pairs:
        arms = list(ARMS if counts[model] % 2 else ARMS[::-1])
        counts[model] += 1
        for arm in arms:
            jobs.append({
                'id': f'ni-stage1-{case["id"]}-{model}-{arm}',
                'stage': 'stage1', 'case': case['id'], 'model': model,
                'level': 'end_to_end', 'repeat': 0, 'variant': arm,
                'backend': ('live' if case['id'].endswith('-00')
                            else 'fixture'),
            })
    if len(jobs) != CAP:
        raise ValueError('The approved schedule must have 1500 attempts')
    return jobs


async def observations(backend, case):
    """Compare task-visible content and comment anchors, omitting metadata."""
    inverse = {alias: native for native, alias
               in backend.aliases.get('tabs', {}).items()}
    heading_ids = {alias: native for native, alias
                   in backend.aliases.get('headings', {}).items()}
    content = []
    for tab in case['fixture']['tabs']:
        args = {'doc_id': backend.document_id,
                'tab_id': inverse.get(tab['id'], tab['id'])}
        headings = [p['heading_id'] for p in tab['paragraphs']
                    if p.get('heading_id')]
        # Whole-tab and scoped reads must both remain available after writes.
        for scope in (None, headings) if headings else (None,):
            query = {**args}
            if scope:
                query['heading_ids'] = [heading_ids.get(h, h) for h in scope]
            response = await backend.call({'tool': 'docs_read',
                                            'arguments': query})
            if response.get('ok') is False:
                raise ValueError('Read continuation failed: '
                                 + json.dumps(response))
            text = '\n'.join(s['markdown'] for s in response['sections'])
            text = unescape(re.sub(r'<a id="[^"]*"></a>', '', text))
            content.append(re.sub(r'\s+', ' ', text).strip())
    comments = await backend.call({'tool': 'docs_read_comments', 'arguments': {
        'doc_id': backend.document_id, 'include_resolved': True,
    }})
    if comments.get('ok') is False:
        raise ValueError('Comment observation failed')
    anchors = sorted((c['content'], c['resolved'], c.get('quoted_text'),
                      backend.aliases.get('tabs', {}).get(c.get('tab_id'),
                                                         c.get('tab_id')))
                     for c in comments['comments'])
    return {'content': content, 'comment_anchors': anchors}


async def calibrate(case, output, captured):
    """Check every gold prefix and its available reads on a disposable Doc."""
    directory = output / 'live-references'
    async with live_backend(
        case, 'baseline', directory / case['id'], reference_mode=True,
    ) as (native, identity), fixture_backend(
        case, 'baseline', output / 'parity' / case['id'],
    ) as (fixture, _info):
        require_frozen_source(identity, captured)
        states = [await native.state()]
        for call in [None, *case['oracle']]:
            if call:
                for backend, action in [
                    (native, native.actual_call(call, 'baseline')),
                    (fixture, call),
                ]:
                    receipt = await backend.call(action)
                    if receipt.get('ok') is False:
                        raise ValueError('Gold action rejected')
                states.append(await native.state())
            if await native.state(semantic=True) != (
                await fixture.state(semantic=True)
            ):
                raise ValueError('Native semantic state differs')
            actual, expected = await observations(native, case), (
                await observations(fixture, case))
            if actual != expected:
                write_json(directory / (case['id'] + '-mismatch.json'),
                           {'native': actual, 'fixture': expected})
                raise ValueError('Native model-visible observations differ')
        write_json(directory / (case['id'] + '.json'), {
            'states': states, 'identity': identity,
        })


async def prepare(output, previous):
    """Calibrate and freeze all inputs before any actor starts."""
    if (output / 'manifest.json').exists():
        raise ValueError('Do not overwrite an existing frozen campaign')
    prior = lineage(previous)
    cases, catalogs, references = corpus(), {}, {}
    for arm in ARMS:
        catalogs[arm] = await capture_catalog(arm, output)
    semaphore = asyncio.Semaphore(6)

    async def reference(case):
        async with semaphore:
            references[case['id']] = await reference_states(
                case, 'baseline', output / 'reference' / case['id'],
            )
    await asyncio.gather(*(reference(c) for c in cases))
    native_cases = [c for c in cases if c['id'].endswith('-00')]
    live_semaphore = asyncio.Semaphore(3)

    async def native(case):
        async with live_semaphore:
            await calibrate(case, output, catalogs['baseline'])
            print(json.dumps({'native_calibrated': case['id']}), flush=True)
    results = await asyncio.gather(*(native(c) for c in native_cases),
                                   return_exceptions=True)
    failures = [str(r) for r in results if isinstance(r, BaseException)]
    if failures:
        write_json(output / 'preparation-errors.json', failures)
        raise ValueError('Native preparation failed: ' + json.dumps(failures))
    protocol_path = Path(__file__).parent / 'NONINFERIORITY_PROTOCOL.md'
    protocol = protocol_path.read_bytes()
    (output / 'protocol.md').write_bytes(protocol)
    manifest = {
        'version': 3, 'campaign': 'ni-stage1', 'seed': SEED,
        'session_cap': CAP, 'prior_runs': prior,
        'total_session_cap': PRIOR + CAP,
        'models': MODELS, 'effort': 'medium',
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                          cwd=ROOT, text=True).strip(),
        'codex_cli': subprocess.check_output(['codex', '--version'],
                                            cwd=ROOT, text=True).strip(),
        'protocol_sha256': hashlib.sha256(protocol).hexdigest(),
        'sources': sources(), 'datasets': {'stage1': cases},
        'dataset_hashes': {'stage1': digest(cases)},
        'catalogs': catalogs, 'references': references,
        'schedules': {'stage1': schedule(cases)},
        'policy': POLICY,
        'grading': {'rendered_exact_answers': True,
                    'terminal_period': 'user-approved scoped optional period'},
        'decision_criteria': {
            'margin': -0.02, 'early_alpha': 0.01,
            'future_alpha_reserved': 0.015, 'future_runs_authorized': False,
            'primary': 'zero A-only-success discordances; no unresolved pairs',
        },
        'budgets': {'calls': 16, 'synthetic_turn_seconds': 120,
                    'native_turn_seconds': 240, 'output_tokens': 4096,
                    'scripted_clarifications': 1, 'replacement_trials': 0},
    }
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    write_json(output / 'ledger.json', {'attempts': [], 'cap': CAP})
    print(json.dumps({'manifest_sha256': digest(manifest),
                      'attempts_planned': CAP, 'cases': len(cases)}),
          flush=True)


async def run(output, concurrency):
    """Resume only unstarted jobs and stop at the approved stage-one cap."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if (digest(manifest) != (output / 'manifest.sha256').read_text().strip()
            or manifest['sources'] != sources()
            or digest(manifest['datasets']['stage1'])
            != manifest['dataset_hashes']['stage1']):
        raise ValueError('Frozen campaign inputs changed')
    previous = Path(manifest['prior_runs'][-1]['directory'])
    if lineage(previous) != manifest['prior_runs']:
        raise ValueError('Previous campaign accounting changed')
    ledger_path = output / 'ledger.json'
    ledger = json.loads(ledger_path.read_text())
    if ledger['cap'] != CAP or manifest['session_cap'] != CAP:
        raise ValueError('Unapproved session cap')
    attempted = {x['id'] for x in ledger['attempts']}
    if len(attempted) != len(ledger['attempts']):
        raise ValueError('Duplicate reserved attempt')
    cases = {c['id']: c for c in manifest['datasets']['stage1']}
    queue = asyncio.Queue()
    for job in manifest['schedules']['stage1']:
        if job['id'] not in attempted:
            queue.put_nowait(job)
    stop, reasons = asyncio.Event(), []
    live_semaphore = asyncio.Semaphore(3)

    def request_stop(name):
        reasons.append(name)
        stop.set()

    async def worker():
        while not stop.is_set() and not queue.empty():
            job = queue.get_nowait()
            if len(ledger['attempts']) >= CAP:
                raise ValueError('Approved 1500-attempt cap reached')
            entry = {**job, 'status': 'reserved', 'started_at': time.time()}
            ledger['attempts'].append(entry)
            write_json(ledger_path, ledger)
            if job['backend'] == 'live':
                async with live_semaphore:
                    result = await run_job(job, cases[job['case']],
                                           manifest, output)
            else:
                result = await run_job(job, cases[job['case']],
                                       manifest, output)
            entry.update(status=result['status'], completed_at=time.time())
            write_json(ledger_path, ledger)
            print(json.dumps({key: result.get(key) for key in (
                'id', 'status', 'final_success', 'error',
            )}), flush=True)
            if result['status'] == 'infrastructure_failure':
                request_stop('infrastructure_failure')
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, request_stop, sig.name)
    try:
        await asyncio.gather(*(worker() for _ in range(concurrency)))
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    status = {'attempts': len(ledger['attempts']), 'cap': CAP,
              'including_prior': PRIOR + len(ledger['attempts']),
              'stop_reasons': reasons}
    write_json(output / 'stage1-run-status.json', status)
    print(json.dumps(status), flush=True)


def main():
    """Prepare or run only the explicitly authorized first stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-restart', type=Path)
    parser.add_argument('--concurrency', type=int,
                        choices=range(1, 7), default=6)
    args = parser.parse_args()
    if args.action == 'prepare' and args.previous_restart is None:
        parser.error('Preparation requires --previous-restart')
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'campaign.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':
            asyncio.run(prepare(args.output, args.previous_restart))
        else:
            asyncio.run(run(args.output, args.concurrency))


if __name__ == '__main__':
    main()
