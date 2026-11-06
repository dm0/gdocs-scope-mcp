"""Summarize frozen study outcomes without treating repeats as scenarios."""

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations, groupby
from pathlib import Path
from statistics import mean

VARIANTS = ('baseline', 'insertion', 'status', 'both')
METRICS = ('first_action_correct', 'final_success', 'recovery_free',
           'unintended_changes')
AUDIT_EXAMPLES_PER_GROUP = 2
RESTART_MANIFEST_VERSION = 2
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
    for case in sorted({key[0] for key in by_case_model}):
        if all((case, model) in by_case_model for model in models):
            effect = sum(weights[model] * mean(by_case_model[case, model])
                         for model in models)
            clusters[cases[case]['family']].append(effect)
    values = [mean(clusters[family]) for family in sorted(clusters)]
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
        'accepted_optional_period_outcomes': sum(
            r.get('final_state_has_optional_period_difference', False)
            for r in graded),
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
            'initial_fixture': case['fixture'],
            'scripted_user_reply': case['clarification'],
            'messages': [neutral_text(m) for t in row['turns']
                         for m in t['messages']],
            'actions': [neutral_call(call) for call in row['trace']],
            'observations': [
                {'operation': call['tool'], 'result': call['result']}
                for call in row['trace'] if call.get('read_only')
            ],
            'final_state': compact_state(row.get('final_state')),
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


def compact_state(state):
    """Coalesce character runs for review while preserving styles and posts."""
    if state is None:
        return None
    tabs = []
    for tab in state['tabs']:
        paragraphs = []
        for paragraph in tab['paragraphs']:
            if 'characters' not in paragraph:
                paragraphs.append(paragraph)
                continue
            paragraphs.append({
                'style': paragraph['style'],
                'runs': [{'text': ''.join(char[0] for char in chars),
                          'style': style}
                         for style, chars in groupby(
                             paragraph['characters'], key=lambda c: c[1])],
            })
        tabs.append({**tab, 'paragraphs': paragraphs})
    return {**state, 'tabs': tabs}


def m09_state(state):
    """Apply only the user's explicit terminal-period adjudication."""
    state = deepcopy(state)
    if state is not None:
        for thread in state['comments']:
            if thread['id'] != 'c.citation':
                continue
            for post in thread['replies']:
                if (post['action'] == 'RESOLVE'
                        and post['text'] == 'Verified against the original.'):
                    post['text'] = 'Verified against the original'
    return state


def m09_sensitivity(row, reference):
    """Regrade all m09 arms identically without changing any raw trace."""
    if row['case'] != 'm09' or row['status'] != 'completed':
        return row
    row = deepcopy(row)
    before = reference[0]
    prefix, errors, unintended = 0, 0, False
    advances = []
    for call in row['trace']:
        after = m09_state(call['post_state'])
        advance = (prefix + 1 < len(reference)
                   and after == reference[prefix + 1])
        wrong = before != after and not advance
        errors += bool(call['schema_valid']
                       and (call['result'].get('ok') is False or wrong))
        unintended |= wrong
        prefix += int(advance)
        advances.append(advance)
        before = after
    if row['level'] == 'decision':
        row['first_action_correct'] = bool(
            row['trace'] and row['trace'][0]['schema_valid'] and advances[0])
        row['final_success'] = row['first_action_correct']
    else:
        first = row['trace'][0] if row['trace'] else None
        row['first_action_correct'] = bool(
            first and first['schema_valid']
            and first['result'].get('ok') is not False
            and (first['tool'] in {'docs_get_tree', 'docs_read',
                                  'docs_read_comments', 'docs_tabs_list'}
                 or advances[0]))
        row['final_success'] = m09_state(row['final_state']) == reference[-1]
    row['semantic_errors'] = errors
    row['unintended_changes'] = unintended
    row['recovery_free'] = (row['final_success'] and not row['schema_errors']
                            and not errors
                            and not row['unnecessary_clarification'])
    return row


def analyze(directory, stage, draws=5000, *, human_sensitivity=False,
            terminal_periods=False):
    """Analyze a complete or partial stage without imputing missing trials."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    manifest_hash = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    if manifest_hash != (directory / 'manifest.sha256').read_text().strip():
        raise ValueError('Frozen study manifest changed')
    if manifest.get('version', 1) >= RESTART_MANIFEST_VERSION and (
        human_sensitivity or terminal_periods
    ):
        raise ValueError('The restart already uses the period rule as primary')
    ledger = json.loads((directory / 'ledger.json').read_text())
    cases = {case['id']: case for case in manifest['datasets'][stage]}
    attempts = [a for a in ledger['attempts'] if a['stage'] == stage]
    rows = []
    missing = []
    for attempt in attempts:
        path = directory / 'runs' / attempt['id'] / 'result.json'
        if path.exists():
            row = json.loads(path.read_text())
            if row['manifest_sha256'] != manifest_hash:
                raise ValueError('A result belongs to another manifest')
            rows.append(row)
        else:
            missing.append(attempt['id'])
    adjudication = None
    sensitivity_source = None
    label = stage
    if human_sensitivity and terminal_periods:
        raise ValueError('Select only one sensitivity analysis')
    if terminal_periods:
        import terminal_period_adjudication as periods  # noqa: PLC0415
        adjudication = json.loads((
            Path(__file__).parent / 'adjudications'
            / 'unquoted-terminal-periods.json'
        ).read_text())
        if (adjudication['reviewer'] != 'user'
                or adjudication['dataset_hashes']
                != manifest['dataset_hashes']):
            raise ValueError('Adjudication belongs to another corpus')
        reviewed = []
        for row in rows:
            reference = manifest['references'][row['case']]['states']
            if row['backend'] == 'live':
                reference = json.loads((directory / 'live-references'
                                        / (row['case'] + '.json'))
                                       .read_text())['states']
            reviewed.append(periods.regrade(
                row, cases[row['case']], reference,
            ))
        rows = reviewed
        sensitivity_source = hashlib.sha256(
            Path(periods.__file__).read_bytes()).hexdigest()
        label += '-terminal-period-sensitivity'
    if human_sensitivity:
        if stage != 'main':
            raise ValueError('The m09 adjudication applies only to main')
        path = directory / 'analysis' / 'm09-adjudication.json'
        if not path.exists():
            path = (Path(__file__).parent / 'adjudications'
                    / 'm09-terminal-period.json')
        adjudication = json.loads(path.read_text())
        if adjudication['accepted_texts'] != [
            'Verified against the original', 'Verified against the original.',
        ] or adjudication['reviewer'] != 'user':
            raise ValueError('Unsupported human adjudication')
        if adjudication['main_corpus_sha256'] != (
            manifest['dataset_hashes']['main']
        ):
            raise ValueError('Adjudication belongs to another corpus')
        reference = manifest['references']['m09']['states']
        rows = [m09_sensitivity(row, reference) for row in rows]
        label += '-human-sensitivity'
    report = {
        'stage': stage, 'manifest_sha256': (
            directory / 'manifest.sha256').read_text().strip(),
        'analysis_source_sha256': hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        'scheduled': len(manifest['schedules'][stage]),
        'reserved_attempts': len(attempts), 'missing_results': missing,
        'overall': rate_summary(rows), 'groups': {}, 'paired_effects': {},
        'treatment_by_model': {},
        'primary_grading': manifest.get('grading', {
            'primary': 'frozen exact native-state comparison',
        }),
        'human_adjudication': adjudication,
        'sensitivity_source_sha256': sensitivity_source,
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
    report['by_backend'] = {
        backend: rate_summary([r for r in rows if r['backend'] == backend])
        for backend in ('fixture', 'live')
    }
    native = [r for r in rows if r['backend'] == 'live']
    report['native_confirmations'] = {}
    for model in ['equal_model_summary', *manifest['models']]:
        models = (manifest['models'] if model == 'equal_model_summary'
                  else [model])
        subset = [r for r in native if r['model'] in models]
        report['native_confirmations'][model] = {
            'rates_by_arm': {
                arm: rate_summary([r for r in subset if r['variant'] == arm])
                for arm in VARIANTS
            },
            'primary_D-A': {
                metric: paired_effect(subset, cases, metric, CONTRASTS['D-A'],
                                      models, draws=draws)
                for metric in METRICS
            },
        }
    packet, key = audit_packet(rows, cases)
    output = directory / 'analysis'
    output.mkdir(exist_ok=True, mode=0o700)
    for name, value in [(label + '.json', report),
                        (label + '-blinded-audit.json', packet),
                        (label + '-audit-key.json', key)]:
        (output / name).write_text(json.dumps(value, indent=2,
                                            ensure_ascii=False))
    return report


def main():
    """Write analysis alongside private campaign artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['pilot', 'main'], required=True)
    parser.add_argument('--m09-human-sensitivity', action='store_true')
    parser.add_argument('--terminal-period-human-sensitivity',
                        action='store_true')
    args = parser.parse_args()
    report = analyze(args.output, args.stage,
                     human_sensitivity=args.m09_human_sensitivity,
                     terminal_periods=args.terminal_period_human_sensitivity)
    print(json.dumps({key: report[key] for key in (
        'stage', 'scheduled', 'reserved_attempts', 'missing_results',
        'overall',
    )}, indent=2))


if __name__ == '__main__':
    main()
