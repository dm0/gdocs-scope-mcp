"""Check the A/D schedule, exact gate and protected task instances."""

import asyncio
import json
import sys
from collections import Counter
from copy import deepcopy

import pytest

from .test_reduced_study_runner import runner  # noqa: F401
from .test_study_corpus import (
    adjudication,
    execution,
    load_research,
    scenarios,
)


@pytest.fixture
def modules(monkeypatch, runner):  # noqa: F811 - imported pytest fixture
    """Load stage code using explicit existing research dependencies."""
    for name, module in [
        ('study_scenarios', scenarios), ('study_execution', execution),
        ('run_reduced_study', runner),
        ('analyze_reduced_study', load_research('analyze_reduced_study')),
    ]:
        monkeypatch.setitem(sys.modules, name, module)
    cases = load_research('noninferiority_scenarios')
    monkeypatch.setitem(sys.modules, 'noninferiority_scenarios', cases)
    monkeypatch.setitem(sys.modules, 'study_live', load_research('study_live'))
    return (cases, load_research('run_noninferiority'),
            load_research('analyze_noninferiority'))


def test_corpus_and_matched_schedule(modules):
    """Use 250 distinct instances and exactly 500 attempts per model."""
    generator, controller, _analysis = modules
    cases = generator.corpus()
    assert len(cases) == 250  # noqa: PLR2004
    assert len({c['request'] for c in cases}) == len(cases)
    assert cases == generator.corpus()
    assert set(Counter(c['family'] for c in cases).values()) == {10}
    jobs = controller.schedule(cases)
    assert len(jobs) == controller.CAP == 1500  # noqa: PLR2004
    assert len({j['id'] for j in jobs}) == len(jobs)
    assert Counter(j['variant'] for j in jobs) == {
        'baseline': 750, 'both': 750,
    }
    assert Counter(j['backend'] for j in jobs) == {
        'live': 150, 'fixture': 1350,
    }
    first = Counter((jobs[i]['model'], jobs[i]['variant'])
                    for i in range(0, len(jobs), 2))
    assert set(first.values()) == {125}
    for left, right in zip(jobs[::2], jobs[1::2], strict=True):
        for field in ('case', 'model', 'backend'):
            assert left[field] == right[field]
    m11 = [c for c in cases if c['template'] == 'm11']
    assert all('explicitly allowed' in c['request'] for c in m11)
    for case in cases:
        if case['answer_contains']:
            assert case['answer_contains'] in json.dumps(case['fixture'])
            assert case['answer_heading_id']


def test_bold_request_gold_and_regrade(modules, tmp_path):
    """Every bold request renders bold; literal stars remain a wrong result."""
    generator, _controller, _analysis = modules

    async def check():
        for case in generator.corpus():
            if case['template'] != 'm04':
                continue
            assert case['oracle'][0]['arguments']['rich'] is True
            reference = await execution.reference_states(
                case, 'baseline', tmp_path / case['id'],
            )
            states = reference['states']
            target = case['oracle'][0]['arguments']['tab_id']
            paragraph = next(t for t in states[-1]['tabs']
                             if t['id'] == target)['paragraphs'][-1]
            assert '**' not in adjudication.paragraph_text(paragraph)
            assert all(style.get('bold') for char, style in
                       paragraph['characters'] if char != '\n')
            row = {'status': 'completed', 'level': 'end_to_end',
                   'trace': [], 'final_state': states[-1],
                   'schema_errors': 0, 'unnecessary_clarification': False}
            assert adjudication.regrade(row, case, states)['final_success']
            wrong = deepcopy(case)
            wrong['oracle'][0]['arguments']['rich'] = False
            literal = await execution.reference_states(
                wrong, 'baseline', tmp_path / (case['id'] + '-literal'),
            )
            row['final_state'] = literal['states'][-1]
            assert not adjudication.regrade(row, case, states)['final_success']

    asyncio.run(check())


def test_exact_gate_does_not_accept_missing_or_harmful_pairs(modules):
    """No observed loss is required; missing evidence is not a free success."""
    _generator, _controller, analysis = modules
    cases = {str(i): {'family': str(i // 10)} for i in range(250)}
    rows = [{'id': f'{case}-{arm}', 'case': case, 'variant': arm,
             'status': 'completed', 'final_success': True,
             'trace': [], 'turns': []}
            for case in cases for arm in ('baseline', 'both')]
    assert analysis.zero_loss_upper(250) < .02  # noqa: PLR2004
    assert analysis.zero_loss_upper(200) > .02  # noqa: PLR2004
    assert analysis.model_summary(rows, cases)[
        'stage1_noninferiority_machine_gate']
    rows[-1]['final_success'] = False
    assert not analysis.model_summary(rows, cases)[
        'stage1_noninferiority_machine_gate']
    rows[-1]['final_success'] = True
    rows[-1]['status'] = 'infrastructure_failure'
    report = analysis.model_summary(rows, cases)
    assert report['complete_pairs'] == 249  # noqa: PLR2004
    assert not report['stage1_noninferiority_machine_gate']
    assert not report['adoption_authorized']
    rows[-1]['status'] = 'completed'
    rows[-1]['unintended_changes'] = True
    assert not analysis.model_summary(rows, cases)[
        'stage1_noninferiority_machine_gate']


def test_stage_resume_never_replaces_failed_reservations(
    modules, monkeypatch, tmp_path,
):
    """Reserve before dispatch, stop on infrastructure, skip every prior ID."""
    _generator, controller, _analysis = modules
    case = {'id': 'case'}
    jobs = [{'id': str(i), 'case': 'case', 'backend': 'fixture'}
            for i in range(5)]
    prior = [{'directory': '/unused'}]
    manifest = {'session_cap': controller.CAP, 'sources': {},
                'prior_runs': prior, 'datasets': {'stage1': [case]},
                'dataset_hashes': {'stage1': controller.digest([case])},
                'schedules': {'stage1': jobs}}
    controller.write_json(tmp_path / 'manifest.json', manifest)
    (tmp_path / 'manifest.sha256').write_text(controller.digest(manifest))
    controller.write_json(tmp_path / 'ledger.json', {
        'cap': controller.CAP, 'attempts': [],
    })
    monkeypatch.setattr(controller, 'sources', dict)
    monkeypatch.setattr(controller, 'lineage', lambda _previous: prior)
    started = []

    async def actor(job, *_args):
        ledger = json.loads((tmp_path / 'ledger.json').read_text())
        assert job['id'] in {a['id'] for a in ledger['attempts']}
        assert job['id'] not in started
        started.append(job['id'])
        return {'id': job['id'], 'status': ('infrastructure_failure'
                                          if len(started) == 1
                                          else 'completed')}

    monkeypatch.setattr(controller, 'run_job', actor)
    asyncio.run(controller.run(tmp_path, concurrency=1))
    assert started == ['0']
    asyncio.run(controller.run(tmp_path, concurrency=1))
    assert started == ['0', '1', '2', '3', '4']
    asyncio.run(controller.run(tmp_path, concurrency=1))
    assert len(started) == 5  # noqa: PLR2004
    ledger = json.loads((tmp_path / 'ledger.json').read_text())
    assert ledger['attempts'][0]['status'] == 'infrastructure_failure'
    ledger['attempts'] = [{'id': f'old-{i}'} for i in range(controller.CAP)]
    controller.write_json(tmp_path / 'ledger.json', ledger)
    with pytest.raises(ValueError, match='1500-attempt cap'):
        asyncio.run(controller.run(tmp_path, concurrency=1))


def test_exact_answer_grading_handles_native_aliases(runner):  # noqa: F811
    """Keep native IDs equivalent while rejecting extra text or broad reads."""
    case = {'answer_contains': 'Batch: WH-123-Z',
            'answer_heading_id': 'h.delivery'}
    final = {'message': 'Batch&#58; WH-123-Z'}
    trace = [{'tool': 'docs_read',
              'arguments': {'heading_ids': ['h.native']}}]
    aliases = {'headings': {'h.native': 'h.delivery'}}
    assert runner.rendered_answer_matches(case, final, trace, aliases)
    assert not runner.rendered_answer_matches(case, final, [], aliases)
    assert not runner.rendered_answer_matches(case, final, trace, {})
    final['message'] += ' extra'
    assert not runner.rendered_answer_matches(case, final, trace, aliases)
