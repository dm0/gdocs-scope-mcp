"""Exercise heading-ID boundary insertion without text matching."""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client

from gdocs_scope_mcp.documents import editing, targeting
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.server import mcp

from .test_revision_guards import api_error


@pytest.mark.parametrize('heading,offset', [
    ('parent', 1), ('nested', 3), ('other', 5),
])
@pytest.mark.parametrize('position', ['before_subtree', 'after_subtree'])
@pytest.mark.parametrize('rich', [False, True])
def test_heading_boundaries(simple_document, mock_docs, apply_insertions,
                            heading, offset, position, rich):
    """Place separate paragraphs around complete native subtrees."""
    body = simple_document['body']['content']
    end = position == 'after_subtree' and heading == 'other'
    index = (body[offset]['startIndex'] if position == 'before_subtree'
             else body[-1]['endIndex'] - 1 if end
             else body[5]['startIndex'])
    result = editing.insert_at_heading('example', heading, 'New', position,
                                      rich=rich)
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, _ = apply_insertions(simple_document, requests)
    original = '\n' + ''.join(p['paragraph']['elements'][0]['textRun'][
        'content'] for p in body)
    inserted = '\nNew' if end else 'New\n'
    assert text == original[:index] + inserted + original[index:]
    assert result.inserted_text == inserted
    assert result.at_index == index
    assert result.heading_id == heading
    assert result.insert_position == position
    assert result.scope == 'heading_subtree'
    assert any(r.get('updateParagraphStyle', {}).get('paragraphStyle', {}).get(
        'namedStyleType') == 'NORMAL_TEXT' for r in requests)


def test_empty_adjacent_and_repeated_titles(simple_document, mock_docs):
    """IDs distinguish identical titles, including headings without body text."""
    body = simple_document['body']['content']
    for p in (body[1], body[3], body[5]):
        p['paragraph']['elements'][0]['textRun']['content'] = 'Same\n'
    # Retaining native positions tests that display lengths never drive writes.
    body.pop(4)
    body.pop(2)
    result = editing.insert_at_heading('example', 'nested', 'X',
                                      'after_subtree')
    assert result.at_index == body[3]['startIndex']


def test_table_is_inside_subtree(simple_document):
    """A table or a heading inside its cells is not a body boundary."""
    body = simple_document['body']['content']
    body.insert(5, {'startIndex': body[4]['endIndex'], 'endIndex': 999,
                    'table': {'tableRows': [{'tableCells': [{'content': [{
                        'paragraph': {'paragraphStyle': {
                            'headingId': 'cell', 'namedStyleType': 'HEADING_1',
                        }},
                    }]}]}]}})
    assert targeting.heading_insertion_point(simple_document, 'parent',
                                             'after_subtree') == (
        body[6]['startIndex'], False,
    )
    with pytest.raises(ToolFailureError):
        targeting.heading_insertion_point(simple_document, 'cell',
                                          'before_subtree')


@pytest.mark.parametrize('mode', ['required', 'target'])
@pytest.mark.parametrize('position', ['before_subtree', 'after_subtree'])
def test_revision_race_never_retargets(monkeypatch, mock_docs, mode, position):
    """Both sides enforce required revisions without retry in either mode."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_WRITE_REVISION_MODE', mode)
    from gdocs_scope_mcp.settings import get_settings
    get_settings.cache_clear()
    try:
        mock_docs.batchUpdate.return_value.execute.side_effect = api_error(
            'The provided revision ID does not match the current revision ID '
            'of the document.',
        )
        with pytest.raises(ToolFailureError) as caught:
            editing.insert_at_heading('example', 'parent', 'X', position)
        assert caught.value.failure.code == 'EDIT_CONFLICT'
        mock_docs.batchUpdate.assert_called_once()
        assert mock_docs.batchUpdate.call_args.kwargs['body'][
            'writeControl'] == {'requiredRevisionId': 'revision'}
    finally:
        get_settings.cache_clear()


def call(**arguments):
    """Exercise public schema validation and error conversion."""
    async def run():
        async with Client(mcp) as client:
            return await client.call_tool('docs_insert_at_heading', arguments,
                                          raise_on_error=False)
    return asyncio.run(run())


def test_catalog_contract():
    """Advertise a typed, anchor-free, non-idempotent insertion tool."""
    async def run():
        async with Client(mcp) as client:
            tool = next(t for t in await client.list_tools()
                        if t.name == 'docs_insert_at_heading')
            assert set(tool.inputSchema['required']) == {
                'doc_id', 'heading_id', 'text', 'position',
            }
            assert 'anchor' not in tool.inputSchema['properties']
            assert tool.inputSchema['properties']['position']['enum'] == [
                'before_subtree', 'after_subtree',
            ]
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.idempotentHint is False
            assert tool.outputSchema
    asyncio.run(run())


@pytest.mark.parametrize('extra,code', [
    ({'heading_id': 'missing'}, 'HEADING_NOT_FOUND'),
    ({'heading_id': ''}, 'INVALID_ARGUMENT'),
    ({'position': 'after'}, 'INVALID_ARGUMENT'),
    ({'expected_revision_id': 'old'}, 'EDIT_CONFLICT'),
    ({'tab_id': 'missing'}, 'RESOURCE_NOT_FOUND'),
])
def test_mcp_failures_do_not_write(mock_docs, extra, code):
    """Bad targets, modes and stale preconditions cannot mutate a document."""
    result = call(**{'doc_id': 'example', 'heading_id': 'parent', 'text': 'X',
                     'position': 'after_subtree', **extra})
    assert result.is_error
    assert result.structured_content['code'] == code
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('tab_id', [None, 'first', 'second'])
def test_mcp_scopes_and_receipts(simple_document, mock_docs, tab_id):
    """Duplicate heading IDs in different tabs remain tab-local."""
    document = {k: simple_document[k] for k in (
        'documentId', 'title', 'revisionId')}
    document['tabs'] = [{
        'tabProperties': {'tabId': name, 'title': name},
        'documentTab': {'body': deepcopy(simple_document['body'])},
    } for name in ('first', 'second')]
    mock_docs.get.return_value.execute.side_effect = lambda: deepcopy(document)
    result = call(doc_id='example', heading_id='parent', text='**New**',
                  position='after_subtree', tab_id=tab_id)
    assert not result.is_error
    data = result.structured_content
    assert data['tab_id'] == (tab_id or 'first')
    assert data['heading_id'] == 'parent'
    assert data['inserted_text'] == 'New\n'
    assert data['inserted_char_count'] == 4
    assert data['preview_truncated'] is False
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[0]['insertText']['location']['tabId'] == (tab_id or 'first')
