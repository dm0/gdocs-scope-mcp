"""Summarize frozen study outcomes without treating repeats as scenarios."""

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean

VARIANTS = ('baseline', 'insertion', 'status', 'both')
METRICS = ('first_action_correct', 'final_success', 'recovery_free',
           'unintended_changes')
AUDIT_EXAMPLES_PER_GROUP = 2
CONTRASTS = {
    'D-A': {'both': 1, 'baseline': -1},
    'B-A': {'insertion': 1, 'baseline': -1},
    'C-A': {'status': 1, 'baseline': -1},
    'interaction': {'both': 1, 'insertion': -1, 'status': -1,
                    'baseline': 1},
}


def percentile(values, fraction):
    """Interpolate a percentile of sorted bootstrap estimates."""
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def paired_effect(rows, cases, metric, contrast, models, *, draws=5000,
                  weights=None):
    """Bootstrap whole scenario families with models and repeats paired."""
    blocks = defaultdict(dict)
    for row in rows:
        if (row['status'] in {'completed', 'agent_failure'}
                and row['model'] in models):
            blocks[(row['case'], row['model'], row['repeat'])][
                row['variant']] = row
    by_case_model = defaultdict(list)
    complete = 0
    for (case, model, _repeat), arms in blocks.items():
        if set(arms) != set(VARIANTS):
            continue
        complete += 1
        by_case_model[case, model].append(sum(
            weight * float(arms[arm].get(metric, False))
            for arm, weight in contrast.items()
        ))
    clusters = defaultdict(list)
    weights = (dict.fromkeys(models, 1 / len(models)) if weights is None
               else weights)
    for case in {key[0] for key in by_case_model}:
        if all((case, model) in by_case_model for model in models):
            effect = sum(weights[model] * mean(by_case_model[case, model])
                         for model in models)
            clusters[cases[case]['family']].append(effect)
    values = [mean(values) for values in clusters.values()]
    if not values:
        return {'estimate': None, 'ci95': None, 'families': 0,
                'complete_four_arm_blocks': complete}
    rng = random.Random(20261106)
    bootstrap = ([values[0]] if len(set(values)) == 1 else [
        mean(rng.choices(values, k=len(values))) for _ in range(draws)
    ])
    return {
        'estimate': mean(values),
        'ci95': [percentile(bootstrap, 0.025),
                 percentile(bootstrap, 0.975)],
        'families': len(values), 'complete_four_arm_blocks': complete,
        'degenerate_interval': len(set(bootstrap)) == 1,
    }


def rate_summary(rows):
    """Report observed denominators explicitly, excluding infrastructure."""
    graded = [r for r in rows
              if r['status'] in {'completed', 'agent_failure'}]
    return {
        'attempts': len(rows), 'statuses': dict(Counter(
            r['status'] for r in rows)), 'graded': len(graded),
        'rates': {metric: mean(float(r.get(metric, False)) for r in graded)
                  if graded else None for metric in METRICS},
        'schema_errors': sum(r.get('schema_errors', 0) for r in graded),
        'semantic_errors': sum(r.get('semantic_errors', 0) for r in graded),
        'unnecessary_clarifications': sum(
            r.get('unnecessary_clarification', False) for r in graded),
        'domain_calls': sum(len(r.get('trace', [])) for r in rows),
        'discovery_calls': sum(c['tool'] in {'docs_tabs_list', 'docs_get_tree'}
                               for r in rows for c in r.get('trace', [])),
        'content_read_calls': sum(c['tool'] in {'docs_read',
                                               'docs_read_comments'}
                                  for r in rows for c in r.get('trace', [])),
        'usage': dict(Counter({key: sum(r.get('usage', {}).get(key, 0)
                                       for r in rows)
                               for key in ('inputTokens',
                                           'cachedInputTokens',
                                           'outputTokens',
                                           'reasoningOutputTokens',
                                           'totalTokens')})),
        'turn_seconds': sum(t['duration_seconds'] for r in rows
                            for t in r.get('turns', [])),
        'processes_not_confirmed_reaped': [r['id'] for r in rows
                                         if r.get('thread_id')
                                         and not r.get('process_reaped')],
    }


def neutral_call(call):
    """Hide the treatment label while retaining the semantic operation."""
    name = call['tool']
    args = (dict(call['arguments'])
            if isinstance(call['arguments'], dict) else {
        'invalid_arguments': call['arguments'],
    })
    if name in {'docs_append', 'docs_insert_before', 'docs_insert_after'}:
        position = {'docs_append': 'append', 'docs_insert_before': 'before',
                    'docs_insert_after': 'after'}[name]
        target = {'position': position}
        for field in ('anchor', 'heading_id'):
            if field in args:
                target[field] = args.pop(field)
        args['target'] = target
        name = 'insert_text'
    elif name == 'docs_insert':
        name = 'insert_text'
    elif name in {'docs_resolve_comment', 'docs_reopen_comment'}:
        args['action'] = ('resolve' if name == 'docs_resolve_comment'
                          else 'reopen')
        name = 'comment_status'
    elif name == 'docs_comment_status':
        name = 'comment_status'
    return {'operation': name, 'arguments': args}


def audit_packet(rows, cases):
    """Select blinded clarification and failure examples for human review."""
    ranked = sorted(rows, key=lambda r: hashlib.sha256(
        r['id'].encode()).hexdigest())
    selected = []
    counts = Counter()
    for row in ranked:
        category = ('clarification' if cases[row['case']]['clarification']
                    else 'unintended' if row.get('unintended_changes')
                    else 'success' if row.get('final_success') else 'failure')
        group = (row['case'], row['level'], category)
        if (row['status'] != 'completed'
                or counts[group] >= AUDIT_EXAMPLES_PER_GROUP):
            continue
        counts[group] += 1
        selected.append((category, row))
    random.Random(591080).shuffle(selected)
    packet, key = [], {}
    for index, (category, row) in enumerate(selected, 1):
        identifier = f'review-{index:03}'
        case = cases[row['case']]
        packet.append({
            'id': identifier, 'request': case['request'],
            'level': row['level'],
            'scripted_user_reply': case['clarification'],
            'messages': [neutral_text(m) for t in row['turns']
                         for m in t['messages']],
            'actions': [neutral_call(call) for call in row['trace']],
            'review_questions': [
                'Was the clarification necessary and specific enough?',
                'Did the actions preserve the intended target and content?',
                'Did the final message accurately describe the outcome?',
            ],
        })
        key[identifier] = {'run': row['id'], 'selection_category': category}
    return packet, key


def neutral_text(text):
    """Hide interface names that appear in a model's natural-language reply."""
    for name in ('docs_insert_before', 'docs_insert_after', 'docs_append',
                 'docs_insert', 'docs_resolve_comment', 'docs_reopen_comment',
                 'docs_comment_status'):
        operation = ('comment_status' if 'comment' in name else 'insert_text')
        text = text.replace(name, operation)
    return text


def analyze(directory, stage, draws=5000):
    """Analyze a complete or partial stage without imputing missing trials."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    ledger = json.loads((directory / 'ledger.json').read_text())
    cases = {case['id']: case for case in manifest['datasets'][stage]}
    attempts = [a for a in ledger['attempts'] if a['stage'] == stage]
    rows = []
    missing = []
    for attempt in attempts:
        path = directory / 'runs' / attempt['id'] / 'result.json'
        if path.exists():
            rows.append(json.loads(path.read_text()))
        else:
            missing.append(attempt['id'])
    report = {
        'stage': stage, 'manifest_sha256': (
            directory / 'manifest.sha256').read_text().strip(),
        'analysis_source_sha256': hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        'scheduled': len(manifest['schedules'][stage]),
        'reserved_attempts': len(attempts), 'missing_results': missing,
        'overall': rate_summary(rows), 'groups': {}, 'paired_effects': {},
        'treatment_by_model': {},
        'error_taxonomy': {
            'omitted_required_tool': sum(
                r['status'] == 'completed' and not r.get('trace')
                and bool(cases[r['case']]['oracle'])
                and cases[r['case']]['expected_decision'] != 'clarify'
                for r in rows),
            'agent_budget_or_protocol_failures': sum(
                r['status'] == 'agent_failure' for r in rows),
            'infrastructure_failures': sum(
                r['status'] == 'infrastructure_failure' for r in rows),
        },
        'limitations': [
            'Machine grades are provisional pending blinded human review.',
            'Clarification semantics are not validated by decision tags.',
            'Infrastructure failures are separate; incomplete paired blocks '
            'are excluded from paired effects, never imputed as failures.',
            'Repeats are not independent scenarios. Degenerate bootstrap '
            'intervals do not establish equivalence or safety.',
            'Secondary contrasts and strata are descriptive without '
            'multiplicity-adjusted claims.',
            'Turn latency includes controller work and native observer reads; '
            'summed seconds are not elapsed campaign wall time.',
            'Cached input tokens are a subset of input tokens. No monetary '
            'cost is inferred.',
        ],
    }
    for level in ('decision', 'end_to_end'):
        for model in ['equal_model_summary', *manifest['models']]:
            models = (manifest['models'] if model == 'equal_model_summary'
                      else [model])
            for stratum in ['all', *sorted({c['stratum']
                                           for c in cases.values()})]:
                subset = [r for r in rows if r['level'] == level
                          and r['model'] in models
                          and (stratum == 'all'
                               or cases[r['case']]['stratum'] == stratum)]
                group = '/'.join([level, model, stratum])
                report['groups'][group] = {
                    arm: rate_summary([r for r in subset
                                       if r['variant'] == arm])
                    for arm in VARIANTS
                }
                report['paired_effects'][group] = {
                    metric: {name: paired_effect(subset, cases, metric,
                                                contrast, models, draws=draws)
                             for name, contrast in CONTRASTS.items()}
                    for metric in METRICS
                }
        subset = [r for r in rows if r['level'] == level]
        for left, right in combinations(manifest['models'], 2):
            report['treatment_by_model'][f'{level}/{left}-{right}'] = {
                metric: paired_effect(
                    subset, cases, metric, CONTRASTS['D-A'], [left, right],
                    draws=draws, weights={left: 1, right: -1},
                ) for metric in METRICS
            }
    packet, key = audit_packet(rows, cases)
    output = directory / 'analysis'
    output.mkdir(exist_ok=True, mode=0o700)
    for name, value in [(stage + '.json', report),
                        (stage + '-blinded-audit.json', packet),
                        (stage + '-audit-key.json', key)]:
        (output / name).write_text(json.dumps(value, indent=2,
                                            ensure_ascii=False))
    return report


def main():
    """Write analysis alongside private campaign artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['pilot', 'main'], required=True)
    args = parser.parse_args()
    report = analyze(args.output, args.stage)
    print(json.dumps({key: report[key] for key in (
        'stage', 'scheduled', 'reserved_attempts', 'missing_results',
        'overall',
    )}, indent=2))


if __name__ == '__main__':
    main()
