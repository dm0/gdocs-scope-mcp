"""Check schema and intent grading for the infrastructure preflight."""

import asyncio
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from fastmcp import Client

from .helpers import study_server
from .test_codex_study_runtime import runtime


@pytest.fixture
def preflight(monkeypatch):
    """Load the research CLI without launching it or changing sys.path."""
    monkeypatch.setitem(sys.modules, 'codex_study_runtime', runtime)
    path = (Path(__file__).parents[1]
            / 'tool_consolidation_preflight.py')
    spec = importlib.util.spec_from_file_location('study_preflight', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['baseline', 'both'])
def action_catalog(request):
    """Use the actual adapter schemas rather than simplified test copies."""
    variant = request.param

    async def capture():
        async with Client(study_server(variant)) as client:
            return {'tools': [tool.model_dump(mode='json')
                              for tool in await client.list_tools()]}

    call = {'tool': 'docs_append' if variant == 'baseline' else 'docs_insert',
            'arguments': {'doc_id': 'study_fixture', 'text': '**Ready**',
                          'tab_id': 't.review', 'rich': False}}
    if variant == 'both':
        call['arguments']['target'] = {'position': 'append'}
    return call, asyncio.run(capture())


def test_correct_append_and_optional_revision(preflight, action_catalog):
    """Both interfaces accept the same valid literal/tab/revision decision."""
    call, catalog = action_catalog
    assert preflight.grade_decision([call], catalog)['correct']
    call['arguments']['expected_revision_id'] = 'r1'
    assert preflight.grade_decision([call], catalog)['correct']


@pytest.mark.parametrize('field,value', [
    ('rich', True), ('tab_id', 't.main'), ('doc_id', 'another-document'),
    ('expected_revision_id', 'old'), ('text', 'Ready'),
])
def test_schema_valid_semantic_errors_are_wrong(
    preflight, action_catalog, field, value,
):
    """A syntactically valid request alone does not establish understanding."""
    call, catalog = action_catalog
    call['arguments'][field] = value
    result = preflight.grade_decision([call], catalog)
    assert not result['correct']
    assert result['reason'] == 'Wrong arguments'


def test_no_action_multiple_actions_and_invalid_fields(
    preflight, action_catalog,
):
    """Reject omissions, extra calls and invalid arguments."""
    call, catalog = action_catalog
    assert not preflight.grade_decision([], catalog)['correct']
    assert not preflight.grade_decision([call, call], catalog)['correct']
    invalid = deepcopy(call)
    invalid['arguments']['unexpected'] = True
    assert not preflight.grade_decision([invalid], catalog)['correct']
    invalid = deepcopy(call)
    invalid['arguments'].pop('doc_id')
    assert not preflight.grade_decision([invalid], catalog)['correct']


def test_direct_tool_definitions_preserve_catalog_inputs(
    preflight, action_catalog,
):
    """Do not defer or rewrite the actual input schema and descriptions."""
    _call, catalog = action_catalog
    tools = preflight.model_tools(catalog)
    assert len(tools) == len(catalog['tools'])
    for original, actual in zip(catalog['tools'], tools, strict=True):
        assert actual == {
            'type': 'function', 'name': original['name'],
            'description': original['description'],
            'inputSchema': original['inputSchema'], 'deferLoading': False,
        }
