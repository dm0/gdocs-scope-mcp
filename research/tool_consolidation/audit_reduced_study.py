"""Audit frozen outcomes without inference or changing primary grades."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from copy import deepcopy
from html import unescape
from pathlib import Path

from analyze_reduced_study import (
    METRICS,
    VARIANTS,
    paired_effect,
    rate_summary,
)
from run_reduced_study import (
    digest,
    final_decision,
    prior_checkpoint,
    source_hashes,
)

MANIFEST = 'e6c15741378738c86ddf71fa3840ea6529d15e5f3b278ef550f1ba82d2e80b82'


def execution_sources_match(manifest):
    """Verify archived execution bytes without restoring live identifiers."""
    if manifest['sources'] == source_hashes():
        return True
    commit = manifest['commit']
    root = Path(__file__).resolve().parents[2]
    for name, expected in manifest['sources'].items():
        path = (Path(__file__).parent / name).resolve().relative_to(root)
        result = subprocess.run(
            ['git', 'show', f'{commit}:{path.as_posix()}'], cwd=root,
            capture_output=True, check=True,
        )
        if hashlib.sha256(result.stdout).hexdigest() != expected:
            return False
    return True


def messages(row):
    """Return completed messages without interpreting prose as actions."""
    return '\n'.join(m for t in row.get('turns', [])
                     for m in t.get('messages', []))


def reference_question(row):
    """Identify an observed Reference anchor followed by a safety question."""
    anchored = any(
        thread.get('quoted_text') == 'Protected reference'
        and thread.get('anchored')
        for call in row.get('trace', [])
        if call['tool'] == 'docs_read_comments'
        for thread in call['result'].get('comments', [])
    )
    return (row['case'] == 'm11' and anchored
            and row.get('clarifications', 0) > 0
            and 'Reference' in messages(row))


def failure_category(row):  # noqa: PLR0911 - distinct audited outcomes
    """Assign evidence categories established in the trace audit."""
    if row['status'] == 'infrastructure_failure':
        return 'infrastructure'
    if row['status'] == 'agent_failure':
        return 'agent_budget'
    if row.get('final_success'):
        return 'success'
    if (row['level'] == 'decision' and not row['trace']
            and '"decision":"action"' in messages(row)):
        return 'verbal_action_without_tool_call'
    if row['case'] == 'm18' and '&#58;' in messages(row):
        return 'escaped_verbatim_answer'
    if reference_question(row):
        return 'ambiguous_reference_protection'
    if row['case'] == 'm11':
        return 'resolved_thread_not_discovered'
    if row['case'] == 'm18' and not row['trace']:
        return 'unsupported_access_or_capability_claim'
    if any(call['result'].get('code') == 'PERMISSION_DENIED'
           for call in row['trace']):
        return 'wrong_document_id'
    return 'unclassified'


def fixture_heading_error(call):
    """Select only the audited scoped-read failure, retaining write errors."""
    return (call['tool'] == 'docs_read'
            and call['result'].get('code') == 'TARGET_CHANGED'
            and call.get('schema_valid')
            and not call.get('state_changed'))


def recovery_diagnostic(row):
    """Remove fixture read errors from a separate recovery diagnostic."""
    row = deepcopy(row)
    if row['backend'] == 'fixture' and row['case'] in {'m05', 'm16'}:
        removed = sum(fixture_heading_error(call) for call in row['trace'])
        row['semantic_errors'] -= removed
        if row['semantic_errors'] < 0:
            raise ValueError('Read-error count exceeds semantic errors')
        row['recovery_free'] = bool(
            row.get('final_success') and not row['schema_errors']
            and not row['semantic_errors']
            and not row.get('unnecessary_clarification')
        )
    return row


def rendered_answer_diagnostic(row):
    """Evaluate conditional visible-text equivalence with strict read scope."""
    row = deepcopy(row)
    if row['case'] != 'm18' or row['status'] != 'completed':
        return row
    final = final_decision(row['turns'][-1]['messages'])
    safe = all(
        call['tool'] in {'docs_get_tree', 'docs_read'}
        and not call.get('state_changed')
        and (call['tool'] != 'docs_read'
             or call['arguments'].get('heading_ids') == ['h.delivery'])
        for call in row['trace']
    )
    if (safe and final.get('decision') == 'noop'
            and unescape(final.get('message', '')) == 'Batch: WH-7294-Z'):
        row['final_success'] = True
        if row['level'] == 'decision':
            row['first_action_correct'] = True
        row['recovery_free'] = bool(
            not row['schema_errors'] and not row['semantic_errors']
            and not row.get('unnecessary_clarification')
        )
    return row


def summary(rows, cases, models):
    """Keep model-specific rates and paired intervals for every sensitivity."""
    report = {}
    for level in ('decision', 'end_to_end'):
        for label in ['equal_model_summary', *models]:
            selected_models = (models if label == 'equal_model_summary'
                               else [label])
            subset = [r for r in rows if r['level'] == level
                      and r['model'] in selected_models]
            report[f'{level}/{label}'] = {
                'rates': {
                    arm: rate_summary(
                        [r for r in subset if r['variant'] == arm],
                        equal_models=(models if label == 'equal_model_summary'
                                      else None),
                    ) for arm in VARIANTS
                },
                'D-A': {metric: paired_effect(
                    subset, cases, metric, {'both': 1, 'baseline': -1},
                    selected_models,
                ) for metric in METRICS},
            }
    return report


def audit(directory):
    """Verify lineage and write private, explicitly post-hoc audit evidence."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    approval_path = (Path(__file__).parent / 'adjudications'
                     / 'rendered-verbatim-answer.json')
    approval = json.loads(approval_path.read_text())
    if (digest(manifest) != MANIFEST
            or (directory / 'manifest.sha256').read_text().strip() != MANIFEST
            or not execution_sources_match(manifest)
            or prior_checkpoint(Path(manifest['prior_run']['directory']))
            != manifest['prior_run']
            or any(digest(v) != manifest['dataset_hashes'][k]
                   for k, v in manifest['datasets'].items())):
        raise ValueError('Frozen experiment lineage changed')
    if (approval['manifest_sha256'] != MANIFEST
            or approval['main_corpus_sha256']
            != manifest['dataset_hashes']['main']):
        raise ValueError('Answer adjudication belongs to another experiment')
    ledger = json.loads((directory / 'ledger.json').read_text())['attempts']
    scheduled = {x['id'] for s in manifest['schedules'].values() for x in s}
    if len(ledger) != len(scheduled) or {x['id'] for x in ledger} != scheduled:
        raise ValueError('Incomplete or duplicate attempt ledger')
    hashes, rows = {}, []
    for attempt in ledger:
        path = directory / 'runs' / attempt['id'] / 'result.json'
        raw = path.read_bytes()
        row = json.loads(raw)
        if (row['id'] != attempt['id'] or row['status'] != attempt['status']
                or row['manifest_sha256'] != MANIFEST):
            raise ValueError('Result does not match frozen attempt')
        hashes[str(path.relative_to(directory))] = (
            hashlib.sha256(raw).hexdigest())
        if row['stage'] == 'main':
            rows.append(row)
    cases = {c['id']: c for c in manifest['datasets']['main']}
    categories = {r['id']: failure_category(r) for r in rows}
    report = {
        'manifest_sha256': MANIFEST,
        'reviewer': 'Retrospective assistant; not independent human review',
        'primary_grades_changed': False, 'new_model_sessions': 0,
        'rendered_answer_adjudication': approval,
        'input_hashes': hashes,
        'categories': categories,
        'category_counts': dict(Counter(categories.values())),
        'semantic_error_responses': dict(Counter(
            '/'.join([r['case'], c['tool'], c['result'].get('code', '')])
            for r in rows for c in r['trace']
            if c['result'].get('ok') is False
        )),
        'sensitivities': {
            'exclude_m11_entire_family': summary(
                [r for r in rows if r['case'] != 'm11'], cases,
                manifest['models'],
            ),
            'fixture_read_error_recovery_diagnostic': summary(
                [recovery_diagnostic(r) for r in rows], cases,
                manifest['models'],
            ),
            'user_adjudicated_rendered_answer': summary(
                [rendered_answer_diagnostic(r) for r in rows], cases,
                manifest['models'],
            ),
            'user_adjudicated_rendered_answer_excluding_m11': summary(
                [rendered_answer_diagnostic(r) for r in rows
                 if r['case'] != 'm11'], cases, manifest['models'],
            ),
        },
    }
    output = directory / 'analysis' / 'retrospective-audit.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main():
    """Audit an existing completed restart without starting model actors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.output)
    print(json.dumps({k: report[k] for k in (
        'manifest_sha256', 'primary_grades_changed', 'new_model_sessions',
        'category_counts', 'semantic_error_responses',
    )}, indent=2))


if __name__ == '__main__':
    main()
