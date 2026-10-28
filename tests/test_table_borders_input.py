"""Verify strict border inputs and forwarding through real MCP tools."""

import asyncio

import pytest
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.table_insertion import TableInsertionPlan


def call(tool, extra):
    """Call a rich insertion through the public MCP schema."""
    args = {'doc_id': 'example',
            'text': '| A | B |\n| --- | --- |\n| C | D |', **extra}
    if tool != 'docs_append':
        args['anchor'] = 'Introduction'

    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(tool, args, raise_on_error=False)

    return asyncio.run(run())


@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize(('extra', 'expected'), [
    ({}, True), ({'table_borders': True}, True),
    ({'table_borders': False}, False),
    ({'table_borders': False, 'upload_local_images': True}, False),
])
@pytest.mark.usefixtures('mock_docs')
def test_border_input_reaches_table_executor(tool, extra, expected,
                                            monkeypatch):
    """Forward default/explicit values through both image-planning paths."""
    calls = []

    def execute(_self, _service, _doc_id, _revision, *,
                table_borders, tab_id=None, size_images=None):
        assert tab_id is None
        assert callable(size_images)
        calls.append(table_borders)

    monkeypatch.setattr(TableInsertionPlan, 'execute', execute)
    result = call(tool, extra)
    assert not result.is_error
    assert calls == [expected]


@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('invalid', [None, 'false', 0, 1, [], {}])
def test_invalid_border_values_fail_before_google(tool, invalid, mock_docs):
    """Require a Boolean and reject null/string/numeric coercion."""
    result = call(tool, {'table_borders': invalid})
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


def test_border_schema_is_optional_and_defaults_to_true():
    """Expose a clear Boolean switch to agents on all three tools."""
    async def run():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            for tool in tools:
                if tool.name in {
                    'docs_append', 'docs_insert_before', 'docs_insert_after',
                }:
                    schema = tool.inputSchema
                    assert 'table_borders' not in schema.get('required', [])
                    field = schema['properties']['table_borders']
                    assert field['type'] == 'boolean'
                    assert field['default'] is True

    asyncio.run(run())
