"""Verify study pairing, cap arithmetic and grading without model inference."""

import asyncio
import json
import sys
from collections import Counter
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client

from gdocs_scope_mcp.tools import documents

from .test_codex_study_runtime import runtime
from .test_study_corpus import execution, load_research, scenarios
from .test_tool_consolidation import study_server


@pytest.fixture
def runner(monkeypatch):
    """Load research dependencies explicitly without changing sys.path."""
    for name, module in [('codex_study_runtime', runtime),
                         ('study_execution', execution),
                         ('study_scenarios', scenarios)]:
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
@pytest.mark.parametrize('case_id', ['p1', 'p3', 'p4'])
def test_actual_fixture_grading_with_a_scripted_model(
    runner, monkeypatch, tmp_path, variant, case_id,
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
    assert result['process_reaped']


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
