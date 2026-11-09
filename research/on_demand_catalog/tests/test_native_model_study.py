"""Check reservation balance and execution isolation before paid trials."""

import asyncio
import importlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def study(monkeypatch):
    """Load only research modules from their own directory."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    return importlib.import_module('native_model_study')


def test_schedule_balances_models_and_alternates_order(study):
    """Each model/arm has ten reservations with no duplicate identity."""
    jobs = study.schedule()
    assert len(jobs) == study.CAP == len({j['id'] for j in jobs})
    assert set(Counter((j['model'], j['arm']) for j in jobs).values()) == {10}
    for repeat in range(10):
        group = [j for j in jobs if j['repeat'] == repeat]
        assert group[0]['arm'] == ('eager' if repeat % 2 == 0 else 'deferred')
        assert {j['model'] for j in group[:3]} == set(study.MODELS)


def test_guard_blocks_forbidden_application_dispatch(study, tmp_path):
    """A visible document tool can never reach its underlying operation."""
    del study
    server = importlib.import_module('native_palette_server')
    guard = server.PaletteGuard(tmp_path)
    calls = []

    async def dispatch(context):
        calls.append(context.message.name)
        return 'safe'

    def context(name):
        return SimpleNamespace(message=SimpleNamespace(name=name))

    with pytest.raises(ValueError, match='Only bounded'):
        asyncio.run(guard.on_call_tool(context('docs_read'), dispatch))
    assert not calls
    assert asyncio.run(guard.on_call_tool(
        context('docs_get_color_palette'), dispatch)) == 'safe'
    assert calls == ['docs_get_color_palette']
    guard.count = 6
    with pytest.raises(ValueError, match='Only bounded'):
        asyncio.run(guard.on_call_tool(context('server_info'), dispatch))
    assert len(calls) == 1
