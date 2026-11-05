"""Exercise heading-ID boundary insertion without text matching."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client

from gdocs_scope_mcp.documents import editing, targeting
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.rich_text.insertion import rich_insertion_requests
from gdocs_scope_mcp.server import mcp

from .test_revision_guards import api_error, race_docs, reindex  # noqa: F401


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


@pytest.mark.parametrize('position', ['before_subtree', 'after_subtree'])
def test_heading_only_at_tab_edges(simple_document, mock_docs, position):
    """The first and final heading can be the tab's only paragraph."""
    body = simple_document['body']['content']
    simple_document['body']['content'] = [body[1]]
    body[1]['paragraph']['elements'][0]['textRun']['content'] = 'Heading😀\n'
    reindex(simple_document)
    result = editing.insert_at_heading('example', 'parent', 'Text🦷', position,
                                      rich=False)
    assert result.at_index == (1 if position == 'before_subtree' else 10)
    assert result.inserted_char_count == len('Text🦷\n')
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    span = requests[-1]['updateParagraphStyle']['range']
    assert span['endIndex'] - span['startIndex'] == (
        7 if position == 'before_subtree' else 6)


@pytest.mark.parametrize('mode', ['required', 'target'])
@pytest.mark.parametrize('position', ['before_subtree', 'after_subtree'])
def test_revision_race_recomputes_current_subtree(
    monkeypatch, race_docs, mode, position,
):
    """Both sides replan the same heading ID even when its subtree changes."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_WRITE_REVISION_MODE', mode)
    from gdocs_scope_mcp.settings import get_settings
    get_settings.cache_clear()
    try:
        def change(document):
            body = document['body']['content']
            body[1]['paragraph']['elements'][0]['textRun']['content'] = (
                'Renamed heading😀\n')
            body[1]['paragraph']['paragraphStyle']['namedStyleType'] = (
                'HEADING_3')
            body[2]['paragraph']['elements'][0]['textRun']['content'] += (
                'Changed body\n')
        race_docs['change'] = change
        result = editing.insert_at_heading('example', 'parent', 'X', position)
        assert result.ok
        body = race_docs['document']['body']['content']
        expected = body[1 if position == 'before_subtree' else 3]['startIndex']
        assert result.at_index == expected
        assert len(race_docs['writes']) == 2
        assert race_docs['writes'][-1]['writeControl'] == {
            'requiredRevisionId': race_docs['document']['revisionId'],
        }
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize('rich', [False, True])
@pytest.mark.parametrize('to_end', [False, True])
def test_retry_changes_boundary_breaks(race_docs, rich, to_end):
    """Rebuild separators when a subtree becomes last or gains a successor."""
    heading = 'parent' if to_end else 'other'
    def change(document):
        body = document['body']['content']
        if to_end:
            del body[5:]
        else:
            sibling = deepcopy(body[5])
            sibling['paragraph']['paragraphStyle']['headingId'] = 'new'
            body.append(sibling)
    race_docs['change'] = change
    result = editing.insert_at_heading('example', heading, 'X',
                                      'after_subtree', rich=rich)
    body = race_docs['document']['body']['content']
    expected = body[-1]['endIndex'] - 1 if to_end else body[-1]['startIndex']
    assert result.at_index == expected
    assert result.inserted_text == ('\nX' if to_end else 'X\n')
    batch = race_docs['writes'][-1]['requests']
    assert batch[0]['insertText'] == {
        'location': {'index': expected},
        'text': '\nX' if to_end else 'X\n',
    }
    normal = next(r['updateParagraphStyle'] for r in batch
                  if 'updateParagraphStyle' in r)
    assert normal['range']['startIndex'] == expected + int(to_end)


@pytest.mark.parametrize('scenario', ['deleted', 'exhausted', 'unknown',
                                      'explicit'])
def test_heading_retry_limits(race_docs, scenario):
    """Never recreate deleted headings or replay uncertain/completed writes."""
    kwargs = {}
    expected = 'EDIT_CONFLICT'
    if scenario == 'deleted':
        race_docs['change'] = lambda doc: doc['body']['content'].pop(1)
        expected = 'TARGET_DELETED'
    elif scenario == 'exhausted':
        race_docs['always'] = True
        expected = 'REVISION_RETRY_EXHAUSTED'
    elif scenario == 'unknown':
        race_docs['documents'].batchUpdate.return_value.execute.side_effect = (
            TimeoutError('unknown write outcome'))
        expected = 'WRITE_OUTCOME_UNKNOWN'
    elif scenario == 'explicit':
        kwargs['expected_revision_id'] = 'revision'
    with pytest.raises(ToolFailureError) as caught:
        editing.insert_at_heading('example', 'parent', 'X', 'after_subtree',
                                  **kwargs)
    assert caught.value.failure.code == expected
    assert race_docs['documents'].batchUpdate.call_count == (
        3 if scenario == 'exhausted' else 1)


def test_table_recompile_keeps_staged_sources():
    """Changing boundary breaks retains body and cell image source mappings."""
    source = 'https://example.com/source.png'
    staged = 'https://example.com/staged.png'
    text = f'![body]({source})\n\n| Cell |\n| --- |\n| ![cell]({source}) |'
    with rich_insertion_requests(text, 20, newline_before=False,
                                 drive_factory=None) as prepared:
        prepared.requests.replace_image_uri(source, staged)
        for newline_before in (True, False):
            prepared.requests = prepared.recompile(newline_before)
            assert prepared.requests.newline_before == newline_before
            images = [r['insertInlineImage']['uri']
                      for r in prepared.requests.iter_requests()
                      if 'insertInlineImage' in r]
            assert images == [staged, staged]


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
