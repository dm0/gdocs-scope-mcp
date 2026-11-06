"""Analyze the first stage without authorizing or running an extension."""

import argparse
import json
import random
from collections import Counter, defaultdict
from statistics import mean, variance

from analyze_reduced_study import percentile, rate_summary
from run_reduced_study import digest, write_json

EARLY_ALPHA = 0.01
MARGIN = 0.02
PAIRS_PER_MODEL = 250
GRADED = {'completed', 'agent_failure'}


def zero_loss_upper(n):
    """Return the exact one-sided zero-event risk bound, not a bootstrap."""
    return 1 - EARLY_ALPHA ** (1 / n) if n else None


def model_summary(rows, cases):
    """Retain missing pairs conservatively and bootstrap semantic families."""
    pairs = defaultdict(dict)
    for row in rows:
        pairs[row['case']][row['variant']] = row
    complete, losses, wins, missing = [], 0, 0, []
    families = defaultdict(list)
    for case, arms in pairs.items():
        if (set(arms) != {'baseline', 'both'}
                or any(r['status'] not in GRADED for r in arms.values())):
            missing.append(case)
            continue
        before = int(arms['baseline']['final_success'])
        after = int(arms['both']['final_success'])
        difference = after - before
        losses += difference == -1
        wins += difference == 1
        complete.append(difference)
        families[cases[case]['family']].append(difference)
    values = [mean(families[key]) for key in sorted(families)]
    rng = random.Random(591500)
    boot = ([mean(rng.choices(values, k=len(values))) for _ in range(5000)]
            if values else [])
    upper = zero_loss_upper(len(complete)) if not losses else None
    strict = (len(pairs) == PAIRS_PER_MODEL and not missing and not losses
              and upper is not None and upper < MARGIN
              and not any(r.get('unintended_changes') for r in rows))
    return {
        'rates': {arm: rate_summary([r for r in rows if r['variant'] == arm])
                  for arm in ('baseline', 'both')},
        'complete_pairs': len(complete),
        'missing_or_infrastructure_pairs': missing,
        'baseline_only_success': losses, 'both_only_success': wins,
        'difference_mean': mean(complete) if complete else None,
        'difference_sample_variance': (variance(complete)
                                       if len(complete) > 1 else None),
        'family_bootstrap_ci95': ([percentile(boot, .025),
                                   percentile(boot, .975)] if boot else None),
        'semantic_families': len(values),
        'zero_loss_upper99_evaluable': upper,
        'stage1_noninferiority_machine_gate': strict,
        'adoption_authorized': False,
        'note': 'Trace review required; no future sessions authorized',
    }


def analyze(output):
    """Read all scheduled outcomes, preserving failed and missing attempts."""
    manifest = json.loads((output / 'manifest.json').read_text())
    if digest(manifest) != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest changed')
    ledger = json.loads((output / 'ledger.json').read_text())['attempts']
    jobs = manifest['schedules']['stage1']
    if len(ledger) != len(jobs) or {r['id'] for r in ledger} != {
        j['id'] for j in jobs
    }:
        raise ValueError('Stage-one schedule has not finished')
    rows = []
    for job in jobs:
        path = output / 'runs' / job['id'] / 'result.json'
        row = json.loads(path.read_text())
        if row['manifest_sha256'] != digest(manifest):
            raise ValueError('Outcome belongs to another manifest')
        rows.append(row)
    cases = {c['id']: c for c in manifest['datasets']['stage1']}
    report = {
        'manifest_sha256': digest(manifest), 'attempts': len(rows),
        'statuses': dict(Counter(r['status'] for r in rows)),
        'models': {model: model_summary(
            [r for r in rows if r['model'] == model], cases,
        ) for model in manifest['models']},
        'overall_operations': rate_summary(rows),
        'future_sessions_authorized': False,
    }
    write_json(output / 'stage1-analysis.json', report)
    return report


def main():
    """Print stage-one paired evidence without starting a model actor."""
    from pathlib import Path  # noqa: PLC0415
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.output)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
