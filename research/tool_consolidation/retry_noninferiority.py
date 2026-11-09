"""Run the twelve explicitly authorized infrastructure follow-ups once each."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import signal
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path

from analyze_noninferiority import model_summary
from run_reduced_study import digest, run_job, source_hashes, write_json

CAP = 12
PRIOR = 2821


def sources():
    """Bind the unchanged execution engine and this follow-up controller."""
    return {**source_hashes(), 'retry_noninferiority.py': hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()}


def load_manifest(directory):
    """Reject changes to a previously frozen campaign manifest."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    if digest(manifest) != (directory / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest changed')
    return manifest


def prepare(output, parent):
    """Freeze failed IDs without changing any original ledger or grade."""
    if (output / 'manifest.json').exists():
        raise ValueError('Follow-up already prepared')
    original = load_manifest(parent)
    original_hash = digest(original)
    selected, hashes, statuses = [], {}, Counter()
    for job in original['schedules']['stage1']:
        raw = (parent / 'runs' / job['id'] / 'result.json').read_bytes()
        row = json.loads(raw)
        if row['status'] not in {'infrastructure_failure', 'agent_failure'}:
            continue
        if row['manifest_sha256'] != original_hash:
            raise ValueError('Original result has a different manifest')
        statuses[row['status']] += 1
        hashes[job['id']] = hashlib.sha256(raw).hexdigest()
        selected.append({**job, 'original_id': job['id'],
                         'id': 'infra-followup-' + job['id']})
    if statuses != {'infrastructure_failure': 11, 'agent_failure': 1}:
        raise ValueError('Expected eleven infrastructure failures and timeout')
    manifest = deepcopy(original)
    manifest.update(
        session_cap=CAP, sources=sources(),
        parent_directory=str(parent.resolve()),
        parent_manifest_sha256=original_hash, parent_result_hashes=hashes,
        authorization='User requested infrastructure reruns with timeout; '
                      'twelve new reservations, no replacements.',
        interpretation='Separate follow-up; prospective gate unchanged',
        schedules={'stage1': selected},
        followup_protocol=Path(__file__).with_name(
            'INFRA_FOLLOWUP.md').read_text(),
    )
    reference_hashes = {}
    for job in selected:
        if job['backend'] == 'live':
            name = job['case'] + '.json'
            raw = (parent / 'live-references' / name).read_bytes()
            destination = output / 'live-references' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            reference_hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest['native_reference_hashes'] = reference_hashes
    write_json(output / 'manifest.json', manifest)
    (output / 'manifest.sha256').write_text(digest(manifest) + '\n')
    write_json(output / 'ledger.json', {'cap': CAP, 'attempts': []})
    print(json.dumps({'prepared': len(selected), 'cap': CAP}), flush=True)


async def run(output):
    """Reserve once, drain on interruption and never replay a reservation."""
    manifest = load_manifest(output)
    if manifest['session_cap'] != CAP or manifest['sources'] != sources():
        raise ValueError('Follow-up budget or execution sources changed')
    parent = Path(manifest['parent_directory'])
    if digest(load_manifest(parent)) != manifest['parent_manifest_sha256']:
        raise ValueError('Original campaign changed')
    for name, expected in manifest['parent_result_hashes'].items():
        raw = (parent / 'runs' / name / 'result.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Original outcome changed')
    for name, expected in manifest['native_reference_hashes'].items():
        if hashlib.sha256((output / 'live-references' / name).read_bytes()
                          ).hexdigest() != expected:
            raise ValueError('Native reference changed')
    ledger_path = output / 'ledger.json'
    ledger = json.loads(ledger_path.read_text())
    jobs = manifest['schedules']['stage1']
    attempted = {r['id'] for r in ledger['attempts']}
    if (ledger['cap'] != CAP or len(jobs) != CAP
            or len(attempted) != len(ledger['attempts'])
            or not attempted <= {j['id'] for j in jobs}):
        raise ValueError('Invalid follow-up ledger')
    queue = asyncio.Queue()
    for job in jobs:
        if job['id'] not in attempted:
            queue.put_nowait(job)
    cases = {c['id']: c for c in manifest['datasets']['stage1']}
    stopped = asyncio.Event()

    def stop(*_args):
        stopped.set()

    async def worker():
        while not stopped.is_set() and not queue.empty():
            job = queue.get_nowait()
            if len(ledger['attempts']) >= CAP:
                raise ValueError('Twelve-attempt follow-up cap reached')
            entry = {**job, 'status': 'reserved', 'started_at': time.time()}
            ledger['attempts'].append(entry)
            write_json(ledger_path, ledger)
            result = await run_job(job, cases[job['case']], manifest, output)
            entry.update(status=result['status'], completed_at=time.time())
            write_json(ledger_path, ledger)
            print(json.dumps({k: result.get(k) for k in (
                'id', 'status', 'final_success', 'error',
            )}), flush=True)
            if result['status'] == 'infrastructure_failure':
                stopped.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    try:
        await asyncio.gather(*(worker() for _ in range(3)))
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    print(json.dumps({'reserved': len(ledger['attempts']), 'cap': CAP,
                      'including_prior': PRIOR + len(ledger['attempts'])}),
          flush=True)


def analyze(output):
    """Report follow-ups and explicitly post-hoc combined estimates."""
    manifest = load_manifest(output)
    parent = Path(manifest['parent_directory'])
    original = load_manifest(parent)
    sensitivity = json.loads(
        (parent / 'stage1-bold-sensitivity.json').read_text())
    changes = {r['id']: r['metrics'] for r in sensitivity['changes']}
    replacements = {}
    manifest_hash = digest(manifest)
    for job in manifest['schedules']['stage1']:
        row = json.loads(
            (output / 'runs' / job['id'] / 'result.json').read_text())
        if row['manifest_sha256'] != manifest_hash:
            raise ValueError('Follow-up belongs to a different manifest')
        if row['status'] not in {
            'completed', 'agent_failure', 'infrastructure_failure',
        }:
            raise ValueError('Follow-up is unfinished')
        replacements[job['original_id']] = row
    rows = []
    for job in original['schedules']['stage1']:
        raw = (parent / 'runs' / job['id'] / 'result.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != (
            sensitivity['raw_result_sha256'][job['id']]
        ):
            raise ValueError('Original audit input changed')
        row = json.loads(raw)
        for key, values in changes.get(job['id'], {}).items():
            row[key] = values['reviewed']
        rows.append(replacements.get(job['id'], row))
    cases = {c['id']: c for c in original['datasets']['stage1']}
    models = {model: model_summary(
        [r for r in rows if r['model'] == model], cases,
    ) for model in manifest['models']}
    for result in models.values():
        result['complete_data_gate_diagnostic'] = result.pop(
            'stage1_noninferiority_machine_gate')
        result['note'] = 'Post-hoc replacement; prospective gate unchanged'
    report = {'interpretation': manifest['interpretation'],
              'manifest_sha256': manifest_hash,
              'attempts': CAP, 'including_prior': PRIOR + CAP,
              'followup_statuses': dict(Counter(
                  r['status'] for r in replacements.values())),
              'models': models, 'adoption_authorized': False,
              'future_sessions_authorized': False}
    write_json(output / 'followup-analysis.json', report)
    print(json.dumps(report, indent=2))


def main():
    """Prepare, run or analyze only the twelve authorized follow-ups."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'analyze'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parent', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.output / 'campaign.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'prepare':
            if args.parent is None:
                parser.error('Preparation requires --parent')
            prepare(args.output, args.parent)
        elif args.action == 'run':
            asyncio.run(run(args.output))
        else:
            analyze(args.output)


if __name__ == '__main__':
    main()
