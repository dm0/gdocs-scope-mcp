"""Verify effective read selections and their serialized MCP contract."""

import asyncio

import pytest
from fastmcp import Client
from jsonschema import validate

from gdocs_scope_mcp import server
from gdocs_scope_mcp.documents import reading


@pytest.mark.parametrize(
    ('requested', 'selected', 'unknown'),
    [
        ([], [], []),
        (['nested', 'parent', 'nested'], ['parent'], []),
        (['other', 'nested', 'other'], ['nested', 'other'], []),
        (['missing-b', 'nested', 'missing-a', 'missing-b'],
         ['nested'], ['missing-b', 'missing-a']),
        (['', 'parent'], ['parent'], ['']),
    ],
)
def test_effective_selection(mock_docs, requested, selected, unknown):
    """Resolve once, order by source, and distinguish empty from full reads."""
    result = reading.read('example', requested)

    assert result.selected_headings == selected
    assert [item.heading_id for item in result.sections] == selected
    assert result.unknown_heading_ids == unknown
    assert result.partial is True
    assert result.document_id == 'example'
    assert result.title == 'Example'
    assert result.revision_id == 'revision'
    mock_docs.batchUpdate.assert_not_called()


def test_whole_read_identifies_preamble(mock_docs):
    """Keep pre-heading content distinct from selectable headings."""
    result = reading.read('example')

    assert [item.heading_id for item in result.sections] == [
        None, 'parent', 'other',
    ]
    assert 'Introduction' in result.sections[0].markdown
    assert 'Parent' not in result.sections[0].markdown
    assert result.unknown_heading_ids == []
    assert result.selected_headings is None
    assert result.partial is False
    assert 'subset_md' not in result.model_dump(mode='json')
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('empty', [False, True])
def test_document_without_headings(mock_docs, simple_document, empty):
    """Full reads still work with only a preamble or no body content."""
    simple_document['body']['content'] = (
        [] if empty else simple_document['body']['content'][:1]
    )
    result = reading.read('example')

    assert result.partial is False
    assert [item.heading_id for item in result.sections] == (
        [] if empty else [None]
    )
    failure = reading.read('example', ['parent', 'parent'])
    assert failure.code == 'HEADING_NOT_FOUND'
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize(
    ('requested', 'selected', 'unknown', 'is_error'),
    [
        (None, None, [], False),
        ([], [], [], False),
        (['nested', 'parent', 'missing'], ['parent'], ['missing'], False),
        (['missing', 'missing'], None, None, True),
    ],
)
def test_mcp_read_selection_contract(
    mock_docs, requested, selected, unknown, is_error,
):
    """Expose identified chunks and mark all-unknown selections as errors."""
    async def call():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            tool = next(item for item in tools if item.name == 'docs_read')
            result = await client.call_tool(
                'docs_read', {'doc_id': 'example', 'heading_ids': requested},
                raise_on_error=False,
            )
            return tool, result

    tool, result = asyncio.run(call())
    data = result.structured_content
    validate(data, tool.outputSchema)
    assert result.is_error is is_error
    if is_error:
        assert data['ok'] is False
        assert data['code'] == 'HEADING_NOT_FOUND'
        assert 'docs_get_tree' in data['suggested_action']
    else:
        assert data['selected_headings'] == selected
        assert data['unknown_heading_ids'] == unknown
        assert 'subset_md' not in data
        assert data['revision_id'] == 'revision'
        if selected is not None:
            returned = [item['heading_id'] for item in data['sections']]
            assert returned == selected
        if selected == ['parent']:
            assert data['sections'][0]['markdown'].count(
                'Target phrase again',
            ) == 1
    mock_docs.batchUpdate.assert_not_called()
