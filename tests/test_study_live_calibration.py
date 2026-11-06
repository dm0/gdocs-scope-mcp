"""Compare frozen fixture trajectories with the real authorized document."""

import asyncio
import os
import sys

import pytest

from .test_study_corpus import execution, load_research, scenarios


@pytest.mark.live
@pytest.mark.parametrize('case_id', ['m01', 'm08', 'm11', 'm15', 'm20'])
def test_native_fixture_calibration(case_id, tmp_path, monkeypatch):
    """Use the research context's own lock/reset rather than double-locking."""
    monkeypatch.setitem(sys.modules, 'study_execution', execution)
    live = load_research('study_live')
    if os.environ.get('GDOCS_SCOPE_MCP_LIVE_TEST_DOC') != live.AUTHORIZED_DOC:
        pytest.skip('Opt in with the authorized development-document ID.')
    case = next(c for c in scenarios.MAIN if c['id'] == case_id)

    async def run():
        native = await live.native_reference(case, tmp_path / 'live')
        async with execution.fixture_backend(
            case, 'baseline', tmp_path / 'fixture',
        ) as (backend, _info):
            semantic = [await backend.state(semantic=True)]
            for call in case['oracle']:
                receipt = await backend.call(call)
                assert receipt.get('ok') is not False
                semantic.append(await backend.state(semantic=True))
        assert native['semantic'] == semantic
    asyncio.run(run())
