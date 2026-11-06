"""Validate the frozen reduced corpus and all four reference trajectories."""

import asyncio
import importlib.util
from collections import Counter
from pathlib import Path

import pytest


def load_research(name):
    """Load a research module without changing the interpreter search path."""
    path = Path(__file__).parents[1] / 'research' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scenarios = load_research('study_scenarios')
execution = load_research('study_execution')


def test_reduced_corpus_composition():
    """Freeze the agreed counts, strata, language mix and disjoint families."""
    pilot = scenarios.corpus('pilot')
    main = scenarios.corpus('main')
    assert len(pilot) == 5  # noqa: PLR2004
    assert len(main) == 20  # noqa: PLR2004
    assert Counter(c['stratum'] for c in pilot) == dict.fromkeys(
        ('insertion', 'status', 'multi_step', 'ambiguity', 'control'), 1,
    )
    assert Counter(c['stratum'] for c in main) == {
        'insertion': 6, 'status': 4, 'multi_step': 4,
        'ambiguity': 3, 'control': 3,
    }
    assert Counter(c['language'] for c in main) == {'ru': 10, 'en': 10}
    assert not ({c['family'] for c in pilot} & {c['family'] for c in main})
    assert len({c['id'] for c in pilot + main}) == len(pilot + main)
    pilot[0]['request'] = 'Changed copy'
    assert scenarios.corpus('pilot')[0]['request'] != 'Changed copy'


@pytest.mark.parametrize('case', scenarios.PILOT + scenarios.MAIN,
                         ids=lambda case: case['id'])
def test_reference_state_parity_in_all_catalogs(case, tmp_path):
    """Run production MCP operations over fresh fixtures for every arm."""
    async def run():
        references = await asyncio.gather(*[
            execution.reference_states(case, variant, tmp_path / variant)
            for variant in ('baseline', 'insertion', 'status', 'both')
        ])
        assert all(reference['states'] == references[0]['states']
                   for reference in references)
        return references[0]['states']
    states = asyncio.run(run())
    assert len(states) == len(case['oracle']) + 1
    if not case['oracle']:
        assert states[0] == states[-1]


def test_projection_keeps_protected_styles_and_comment_actions():
    """Unintended style changes and extra action posts cannot compare equal."""
    fixture_api = load_research('study_fixture_api')
    api = fixture_api.FixtureAPI(scenarios.PILOT[1]['fixture'])
    before = execution.canonical(api.snapshot())
    api.tabs[0]['chars'][0]['textStyle']['bold'] = True
    assert execution.canonical(api.snapshot()) != before
    api.tabs[0]['chars'][0]['textStyle'].clear()
    api.comments[0]['replies'].append({'commentAction': 'RESOLVE'})
    assert execution.canonical(api.snapshot()) != before
