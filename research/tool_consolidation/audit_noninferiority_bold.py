"""Preserve frozen grades and separately correct m04's explicit bold oracle."""

import argparse
import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from analyze_noninferiority import model_summary
from analyze_reduced_study import rate_summary
from run_reduced_study import digest, write_json
from study_execution import reference_states
from terminal_period_adjudication import regrade

METRICS = ('final_success', 'first_action_correct', 'semantic_errors',
           'unintended_changes', 'recovery_free')


async def audit(output):
    """Regrade all m04 traces, changing only the six malformed references."""
    manifest = json.loads((output / 'manifest.json').read_text())
    manifest_hash = digest(manifest)
    if manifest_hash != (output / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest changed')
    cases = {c['id']: c for c in manifest['datasets']['stage1']}
    references, corrections = {}, {}
    for case in cases.values():
        if case['template'] != 'm04':
            continue
        corrected = deepcopy(case)
        corrected['oracle'][0]['arguments']['rich'] = True
        reference = await reference_states(
            corrected, 'baseline', output / 'bold-audit' / case['id'],
        )
        references[case['id']] = reference['states']
        if corrected != case:
            corrections[case['id']] = corrected
        elif reference['states'] != (
            manifest['references'][case['id']]['states']
        ):
            raise ValueError('An unaffected fixture reference changed')
    rows, changes, source_hashes = [], [], {}
    for job in manifest['schedules']['stage1']:
        path = output / 'runs' / job['id'] / 'result.json'
        raw = path.read_bytes()
        row = json.loads(raw)
        if row['manifest_sha256'] != manifest_hash:
            raise ValueError('Outcome belongs to another manifest')
        source_hashes[job['id']] = hashlib.sha256(raw).hexdigest()
        reviewed = row
        if row['case'] in references:
            case = corrections.get(row['case'], cases[row['case']])
            expected = references[row['case']]
            if row['backend'] == 'live':
                if row['case'] in corrections:
                    raise ValueError('Native correction needs native gold')
                expected = json.loads((output / 'live-references' / (
                    row['case'] + '.json')).read_text())['states']
            reviewed = regrade(row, case, expected)
        differences = {key: {'frozen': row.get(key),
                             'reviewed': reviewed.get(key)}
                       for key in METRICS if row.get(key) != reviewed.get(key)}
        if differences:
            changes.append({'id': row['id'], 'metrics': differences})
        rows.append(reviewed)
    if len(rows) != 1500:  # noqa: PLR2004
        raise ValueError('Incomplete stage-one schedule')
    report = {
        'label': 'Post-hoc explicit-bold oracle correction; not primary',
        'manifest_sha256': manifest_hash,
        'frozen_analysis_sha256': hashlib.sha256(
            (output / 'stage1-analysis.json').read_bytes()).hexdigest(),
        'audit_source_sha256': hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        'raw_result_sha256': source_hashes,
        'corrected_cases': corrections,
        'reference_states': references,
        'changes': changes,
        'models': {model: model_summary(
            [r for r in rows if r['model'] == model], cases,
        ) for model in manifest['models']},
        'backend_rates': {backend: {
            model: {arm: rate_summary([
                r for r in rows if r['backend'] == backend
                and r['model'] == model and r['variant'] == arm
            ]) for arm in ('baseline', 'both')}
            for model in manifest['models']
        } for backend in ('fixture', 'live')},
        'overall_operations': rate_summary(rows),
        'future_sessions_authorized': False,
    }
    write_json(output / 'stage1-bold-sensitivity.json', report)
    print(json.dumps({'changed_outcomes': len(changes),
                      'models': report['models']}, indent=2))


def main():
    """Run local reference operations only; never invoke an actor model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(audit(parser.parse_args().output))


if __name__ == '__main__':
    main()
