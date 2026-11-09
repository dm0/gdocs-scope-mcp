"""Analyze ordinary-profile loading cohorts without new inference."""

import argparse
import hashlib
import json
import random
import statistics
from functools import lru_cache
from pathlib import Path

from analyze_native_models import wilson
from ordinary_loading_study import audit
from probe_client import MODELS, digest, write_json

DRAWS = 10000
SEED = 600
METRICS = ('input_tokens', 'cached_tokens', 'output_tokens', 'turn_seconds',
           'palette_calls', 'code_exec_calls', 'metadata_discovery_calls')


@lru_cache(maxsize=100)
def indices(n):
    """Use fixed paired resampling indices for every metric at a given n."""
    rng = random.Random(SEED)
    return [rng.choices(range(n), k=n) for _ in range(DRAWS)]


def percentile(values, fraction):
    """Interpolate a sorted empirical quantile."""
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def interval(values):
    """Return the deterministic percentile bootstrap interval."""
    values = sorted(values)
    return [percentile(values, 0.025), percentile(values, 0.975)]


def continuous(values):
    """Describe repetitions with sample variance and a mean bootstrap CI."""
    n = len(values)
    if not n:
        return {'n': 0, 'mean': None, 'variance': None, 'ci95': None}
    return {'n': n, 'mean': statistics.mean(values),
            'variance': statistics.variance(values) if n > 1 else None,
            'ci95': interval([sum(values[i] for i in draw) / n
                              for draw in indices(n)]) if n > 1 else None}


def saving(eager, deferred):
    """Estimate savings as one minus the ratio of paired sample means."""
    n = len(eager)
    if not n or not sum(eager):
        return {'n': n, 'percent': None, 'ci95': None}
    draws = [(1 - sum(deferred[i] for i in draw)
              / sum(eager[i] for i in draw)) * 100 for draw in indices(n)]
    return {'n': n, 'percent': (1 - sum(deferred) / sum(eager)) * 100,
            'ci95': interval(draws) if n > 1 else None}


def analyze(output, budget_root):
    """Retain every reservation and hash raw evidence before summarization."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Manifest changed')
    ledger = json.loads((budget_root / (manifest['phase'] + '-ledger.json'))
                        .read_text())
    ids = {output.name + '-' + job['id'] for job in manifest['schedule']}
    cohort = [r for r in ledger['attempts'] if r['id'] in ids]
    rows, hashes = [], {}
    for row in cohort:
        directory = output / row['id']
        result = json.loads((directory / 'result.json').read_text())
        if row != result:
            raise ValueError('Ledger and result differ')
        events = json.loads((directory / 'events.json').read_text())
        computed = audit(row, events)
        if computed != json.loads((directory / 'analysis.json').read_text()):
            raise ValueError('Saved grade differs from raw trace audit')
        rows.append(computed)
        for name in ('result.json', 'events.json', 'calls.jsonl',
                     'models.json'):
            path = directory / name
            if path.exists():
                hashes[str(path.relative_to(output))] = hashlib.sha256(
                    path.read_bytes()).hexdigest()
    groups = {}
    for model in MODELS:
        groups[model] = {}
        for arm in ('eager', 'deferred'):
            selected = [r for r in rows if r['model'] == model
                        and r['arm'] == arm and r['status'] == 'completed']
            successes = sum(r['success'] for r in selected)
            groups[model][arm] = {
                'completed': len(selected), 'successes': successes,
                'success_ci95': wilson(successes, len(selected)),
                **{k: continuous([r[k] for r in selected if r[k] is not None])
                   for k in METRICS},
            }
        pairs = []
        for repeat in range(manifest['repeats']):
            pair = {r['arm']: r for r in rows if r['model'] == model
                    and r['repeat'] == repeat and r['status'] == 'completed'}
            if set(pair) == {'eager', 'deferred'}:
                pairs.append(pair)
        groups[model]['paired_deferred_minus_eager'] = {
            k: continuous([p['deferred'][k] - p['eager'][k] for p in pairs
                           if p['deferred'][k] is not None
                           and p['eager'][k] is not None]) for k in METRICS}
        groups[model]['input_saving'] = saving(
            [p['eager']['input_tokens'] for p in pairs],
            [p['deferred']['input_tokens'] for p in pairs])
    report = {'manifest_sha256': digest(manifest), 'reserved': len(cohort),
              'planned': len(ids), 'phase_consumed': len(ledger['attempts']),
              'phase_cap': ledger['cap'], 'groups': groups, 'rows': rows,
              'ci_method': 'Paired-repeat percentile bootstrap, 10000 draws, '
                           'seed 600; single repeated task, descriptive only',
              'hashes': hashes, 'analysis_source_sha256': hashlib.sha256(
                  Path(__file__).read_bytes()).hexdigest()}
    write_json(output / 'analysis.json', report)
    print(json.dumps({'reserved': len(cohort), 'groups': groups}, indent=2))
    return report


def main():
    """Read private cohort data without launching any model or MCP process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget-root', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.output, args.budget_root)


if __name__ == '__main__':
    main()
