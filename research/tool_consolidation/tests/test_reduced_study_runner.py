"""Verify study pairing, cap arithmetic and grading without model inference."""

import asyncio
import json
import sys
from collections import Counter
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client

from gdocs_scope_mcp.tools import documents

from .helpers import study_server
from .test_codex_study_runtime import runtime
from .test_study_corpus import execution, load_research, scenarios


@pytest.fixture
def runner(monkeypatch):
    """Load research dependencies explicitly without changing sys.path."""
    for name, module in [('codex_study_runtime', runtime),
                         ('study_execution', execution),
                         ('study_scenarios', scenarios),
                         ('terminal_period_adjudication',
                          load_research('terminal_period_adjudication'))]:
        monkeypatch.setitem(sys.modules, name, module)
    preflight = load_research('tool_consolidation_preflight')
    monkeypatch.setitem(sys.modules, 'tool_consolidation_preflight', preflight)
    return load_research('run_reduced_study')


def test_session_cap_and_predeclared_native_subset(runner):
    """Count paired trials and keep native confirmations within the cap."""
    pilot = runner.schedule('pilot')
    main = runner.schedule('main')
    assert len(pilot) == 120  # noqa: PLR2004
    assert len(main) == 960  # noqa: PLR2004
    assert len(pilot) + len(main) == runner.CAP
    assert len({job['id'] for job in pilot + main}) == runner.CAP
    live = [job for job in main if job['backend'] == 'live']
    assert len(live) == 60  # noqa: PLR2004
    assert Counter(job['case'] for job in live) == dict.fromkeys(
        runner.LIVE_CASES, 12,
    )
    assert all(job['repeat'] == 1 and job['level'] == 'end_to_end'
               for job in live)
    assert runner.schedule('pilot') == pilot


@pytest.mark.parametrize('variant', ['baseline', 'both'])
@pytest.mark.parametrize('case_id,optional_period', [
    ('p1', False), ('p1', True), ('p3', False), ('p3', True), ('p4', False),
])
def test_actual_fixture_grading_with_a_scripted_model(
    runner, monkeypatch, tmp_path, variant, *, case_id, optional_period,
):
    """Execute production MCP writes while replacing only model inference."""
    case = next(c for c in scenarios.PILOT if c['id'] == case_id)
    job = next(job for job in runner.schedule('pilot')
               if job['case'] == case_id and job['variant'] == variant
               and job['level'] == 'end_to_end')

    class ScriptedClient:
        """Return a fixed, independently specified valid tool trajectory."""

        def __init__(self):
            self.events = []
            self.process_reaped = False
            self.turns = 0

        async def start(self, **kwargs):
            return {'model': kwargs['model'], 'reasoningEffort': 'medium',
                    'thread': {'id': 'scripted-test-no-inference'}}

        async def turn(self, _thread, _prompt, execute, **_kwargs):
            self.turns += 1
            calls = []
            if self.turns == 1:
                call = {'tool': 'docs_get_tree',
                        'arguments': {'doc_id': 'study_fixture'}}
                await execute(call)
                calls.append(call)
            if case['clarification'] and self.turns == 1:
                decision = 'clarify'
            else:
                for original in case['oracle']:
                    call = execution.translated(original, variant)
                    if optional_period and original['tool'] in {
                        'docs_append', 'docs_insert_before',
                    }:
                        call['arguments']['text'] += '.'
                    await execute(call)
                    calls.append(call)
                decision = 'action'
            return {'calls': calls, 'messages': [json.dumps({
                'decision': decision, 'message': 'Synthetic test response',
            })], 'duration_seconds': 0}

    @asynccontextmanager
    async def fake_client(*_args, **_kwargs):
        client = ScriptedClient()
        try:
            yield client
        finally:
            client.process_reaped = True

    monkeypatch.setattr(runner, 'isolated_client', fake_client)

    async def run():
        reference = await execution.reference_states(
            case, 'baseline', tmp_path / 'reference',
        )
        server = study_server(variant)
        documents.register_discovery(server)
        documents.register_reading(server)
        async with Client(server) as client:
            tools = [tool.model_dump(mode='json')
                     for tool in await client.list_tools()]
        manifest = {
            'catalogs': {variant: {'catalog': {'instructions': '',
                                               'tools': tools},
                                    'identity': reference['identity']}},
            'references': {case_id: reference},
        }
        return await runner.run_job(job, case, manifest, tmp_path)
    result = asyncio.run(run())
    assert result['status'] == 'completed', result.get('error')
    assert result['first_action_correct']
    assert result['final_success']
    assert result['recovery_free']
    assert not result['unintended_changes']
    if optional_period:
        assert result['final_state_has_optional_period_difference']
    assert result['process_reaped']


def test_prior_campaign_budget_is_counted_and_bound_to_its_ledger(
    runner, tmp_path,
):
    """Interrupted reservations still consume budget and cannot disappear."""
    manifest = {'version': 'original'}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'manifest.sha256').write_text(runner.digest(manifest))
    ledger = {'attempts': [{'status': 'reserved'}] * runner.PRIOR_ATTEMPTS}
    path = tmp_path / 'ledger.json'
    path.write_text(json.dumps(ledger))
    checkpoint = runner.prior_checkpoint(tmp_path)
    assert checkpoint['attempts'] + runner.CAP == runner.TOTAL_CAP
    ledger['attempts'][0] = {'status': 'completed'}
    path.write_text(json.dumps(ledger))
    assert runner.prior_checkpoint(tmp_path) != checkpoint
    ledger['attempts'].pop()
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match='241 prior attempts'):
        runner.prior_checkpoint(tmp_path)


def test_requested_stop_drains_reserved_jobs_without_starting_more(
    runner, monkeypatch, tmp_path,
):
    """Keep interruption cleanup out of active actors and preserve the cap."""
    prior = {'directory': '/unused', 'attempts': runner.PRIOR_ATTEMPTS}
    case = {'id': 'case'}
    jobs = [{'id': f'job-{i}', 'case': 'case', 'stage': 'pilot'}
            for i in range(5)]
    manifest = {'sources': {}, 'prior_run': prior,
                'datasets': {'pilot': [case]},
                'dataset_hashes': {'pilot': runner.digest([case])},
                'schedules': {'pilot': jobs}}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'manifest.sha256').write_text(runner.digest(manifest))
    (tmp_path / 'ledger.json').write_text(json.dumps({
        'attempts': [], 'cap': runner.CAP, 'total_cap': runner.TOTAL_CAP,
        'prior_attempts': runner.PRIOR_ATTEMPTS,
    }))
    monkeypatch.setattr(runner, 'source_hashes', dict)
    monkeypatch.setattr(runner, 'prior_checkpoint', lambda _path: prior)
    handlers, started = {}, []

    async def run():
        ready = asyncio.Event()
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, 'add_signal_handler',
                            lambda sig, callback, *args: handlers.update(
                                {sig: (callback, args)}))
        monkeypatch.setattr(loop, 'remove_signal_handler', handlers.pop)

        async def actor(job, *_args):
            ledger = json.loads((tmp_path / 'ledger.json').read_text())
            assert job['id'] in {a['id'] for a in ledger['attempts']}
            started.append(job['id'])
            if len(started) == 3:  # noqa: PLR2004
                callback, args = handlers[runner.signal.SIGINT]
                callback(*args)
                ready.set()
            await ready.wait()
            return {'id': job['id'], 'status': 'completed'}
        monkeypatch.setattr(runner, 'run_job', actor)
        await runner.run_stage(tmp_path, 'pilot', concurrency=3)
    asyncio.run(run())
    ledger = json.loads((tmp_path / 'ledger.json').read_text())
    assert len(ledger['attempts']) == 3  # noqa: PLR2004
    assert all(a['status'] == 'completed' for a in ledger['attempts'])
    summary = json.loads((tmp_path / 'pilot-run-status.json').read_text())
    assert summary['stop_reasons'] == ['SIGINT']
    assert not summary['stopped_on_infrastructure_failure']


def test_read_only_state_comparison_does_not_hide_changes(runner):
    """Keep diagnostic formatting separate from actual protected content."""
    assert runner.final_decision(['not JSON']) == {}
    assert runner.final_decision(['{"decision":"noop"}']) == {
        'decision': 'noop',
    }
    assert runner.usage([
        {'method': 'thread/tokenUsage/updated',
         'params': {'tokenUsage': {'total': {'inputTokens': 10}}}},
        {'method': 'thread/tokenUsage/updated',
         'params': {'tokenUsage': {'total': {'inputTokens': 20}}}},
    ]) == {'inputTokens': 20}


@pytest.mark.usefixtures('runner')
def test_native_seed_ignores_the_preamble_outline_entry():
    """A normal-text preamble is not a native heading to count or alias."""
    live = load_research('study_live')
    section = {'id': 'h.real', 'title': 'Real heading', 'level': 'h1'}
    assert live.body_headings({'sections': [
        {'id': '', 'title': '', 'level': 'n'}, section,
    ]}) == [section]
