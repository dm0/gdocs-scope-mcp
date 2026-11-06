"""Check pairing, missing-data handling and treatment blinding."""

import hashlib
import json
from copy import deepcopy

import pytest

from .test_study_corpus import load_research

analysis = load_research('analyze_reduced_study')


def row(case, model, repeat, arm, success):
    """Build an outcome with an explicit paired-block identity."""
    return {'case': case, 'model': model, 'repeat': repeat,
            'variant': arm, 'status': 'completed',
            'first_action_correct': success}


def test_pairing_excludes_incomplete_blocks_and_weights_models_equally():
    """Extra repeats and a missing arm cannot distort paired contrasts."""
    rows = [row('c1', model, repeat, arm, arm == 'both')
            for model, repeats in [('small', 2), ('large', 1)]
            for repeat in range(repeats) for arm in analysis.VARIANTS]
    rows += [row('c2', 'small', 0, 'baseline', True)]
    rows += [row('c3', 'small', 0, arm, arm == 'baseline')
             for arm in analysis.VARIANTS]
    cases = {'c1': {'family': 'f1'}, 'c2': {'family': 'f2'},
             'c3': {'family': 'f3'}}
    result = analysis.paired_effect(
        rows, cases,
        'first_action_correct', analysis.CONTRASTS['D-A'],
        ['small', 'large'], draws=50,
    )
    assert result['estimate'] == 1
    assert result['families'] == 1
    assert result['complete_four_arm_blocks'] == 3  # noqa: PLR2004
    assert result['available_complete_four_arm_blocks'] == 4  # noqa: PLR2004
    assert result['ci95'] == [1, 1]
    assert result['degenerate_interval']
    interaction = analysis.paired_effect(
        rows, cases,
        'first_action_correct', analysis.CONTRASTS['D-A'],
        ['small', 'large'], draws=50, weights={'small': 1, 'large': -1},
    )
    assert interaction['estimate'] == 0


def test_infrastructure_is_not_a_model_failure():
    """Count model failures while reporting infrastructure separately."""
    report = analysis.rate_summary([
        {'id': 'ok', 'status': 'completed', 'final_success': True},
        {'id': 'budget', 'status': 'agent_failure'},
        {'id': 'auth', 'status': 'infrastructure_failure'},
    ])
    assert report['graded'] == 2  # noqa: PLR2004
    assert report['rates']['final_success'] == 0.5  # noqa: PLR2004


def test_missing_trials_do_not_reweight_the_equal_model_summary():
    """Retain equal model weight when completed-trial counts differ."""
    rows = [{'model': 'small', 'status': 'completed', 'final_success': True}
            for _ in range(10)]
    rows.append({'model': 'large', 'status': 'completed',
                 'final_success': False})
    report = analysis.rate_summary(rows, equal_models=['small', 'large'])
    assert report['rates']['final_success'] == 0.5  # noqa: PLR2004


def test_semantic_calls_hide_treatment_names():
    """Present the same operation to a reviewer for both interfaces."""
    assert analysis.neutral_call({
        'tool': 'docs_insert_before',
        'arguments': {'doc_id': 'd', 'anchor': 'a', 'text': 'x'},
    }) == analysis.neutral_call({
        'tool': 'docs_insert',
        'arguments': {'doc_id': 'd', 'text': 'x',
                      'target': {'position': 'before', 'anchor': 'a'}},
    })
    assert analysis.neutral_text('Used docs_insert_before safely') == (
        'Used insert_text safely')


def test_audit_projection_keeps_literal_text_and_style_boundaries():
    """Compact display must not hide formatting or comment action posts."""
    state = {'tabs': [{'id': 't', 'title': 'Main', 'paragraphs': [
        {'style': {}, 'characters': [['*', {}], ['*', {}],
                                     ['X', {'bold': True}], ['\n', {}]]},
    ]}], 'comments': [{'replies': [{'action': 'RESOLVE'}]}]}
    compact = analysis.compact_state(state)
    assert compact['comments'] == state['comments']
    assert compact['tabs'][0]['paragraphs'][0]['runs'] == [
        {'text': '**', 'style': {}},
        {'text': 'X', 'style': {'bold': True}},
        {'text': '\n', 'style': {}},
    ]


@pytest.mark.parametrize('level', ['decision', 'end_to_end'])
@pytest.mark.parametrize('defect', [None, 'protected', 'status', 'extra_post'])
def test_human_punctuation_adjudication_preserves_every_other_invariant(
    level, defect,
):
    """Allow the reviewed period without erasing damage or raw evidence."""
    initial = {'tabs': ['Protected'], 'comments': [{
        'id': 'c.citation', 'resolved': False, 'replies': [],
    }]}
    expected = deepcopy(initial)
    expected['comments'][0].update(resolved=True, replies=[{
        'action': 'RESOLVE', 'text': 'Verified against the original',
    }])
    actual = deepcopy(expected)
    actual['comments'][0]['replies'][0]['text'] += '.'
    if defect == 'protected':
        actual['tabs'] = ['Changed']
    elif defect == 'status':
        actual['comments'][0]['resolved'] = False
    elif defect == 'extra_post':
        actual['comments'][0]['replies'].append({
            'action': None, 'text': 'Unexpected reply',
        })
    row = {'case': 'm09', 'level': level, 'status': 'completed',
           'schema_errors': 0, 'unnecessary_clarification': False,
           'first_action_correct': False, 'final_state': actual,
           'trace': [{'tool': 'docs_comment_status', 'schema_valid': True,
                      'post_state': actual, 'result': {'ok': True}}]}
    before = deepcopy(row)
    reviewed = analysis.m09_sensitivity(row, [initial, expected])
    assert reviewed['final_success'] == (defect is None)
    assert reviewed['first_action_correct'] == (defect is None)
    assert reviewed['unintended_changes'] == (defect is not None)
    assert row == before


def test_analysis_checks_manifest_and_does_not_reapply_restart_sensitivity(
    tmp_path,
):
    """Reject changed provenance and a misleading post-hoc restart label."""
    manifest = {'version': analysis.RESTART_MANIFEST_VERSION}
    text = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    (tmp_path / 'manifest.json').write_text(text)
    (tmp_path / 'manifest.sha256').write_text('wrong')
    with pytest.raises(ValueError, match='manifest changed'):
        analysis.analyze(tmp_path, 'pilot')
    (tmp_path / 'manifest.sha256').write_text(
        hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(ValueError, match='already uses the period rule'):
        analysis.analyze(tmp_path, 'pilot', human_sensitivity=True)
