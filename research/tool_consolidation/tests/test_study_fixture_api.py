"""Verify actual MCP application operations against the study API fixture."""

import asyncio
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from googleapiclient.errors import HttpError

from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.tool_logging import ToolCallLoggingMiddleware
from gdocs_scope_mcp.tools import comments, documents, formatting

SPEC = importlib.util.spec_from_file_location(
    'study_fixture_api', Path(__file__).parents[1]
    / 'study_fixture_api.py',
)
fixture_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_api)


@pytest.fixture
def fixture_specification():
    """Include a heading, non-BMP character, protected tab and comment."""
    return {
        'document_id': 'study_fixture',
        'tabs': [
            {'id': 't.main', 'title': 'Main', 'paragraphs': [
                {'text': 'Protected main'},
            ]},
            {'id': 't.review', 'title': 'Review', 'paragraphs': [
                {'text': 'Review', 'heading_id': 'h.review',
                 'level': 'HEADING_1'},
                {'text': 'Anchor 😀'}, {'text': 'Tail'},
            ]},
        ],
        'comments': [{'id': 'c.review', 'text': 'Please check',
                      'resolved': False}],
    }


def test_utf16_atomicity_and_revision(fixture_specification):
    """Reject split surrogates and stale/unsupported batches atomically."""
    api = fixture_api.FixtureAPI(fixture_specification)
    before = api.snapshot()
    for requests in [
        [{'insertText': {'location': {'tabId': 't.review', 'index': 16},
                         'text': 'bad'}}],
        [{'insertText': {'location': {'index': 1}, 'text': 'not committed'}},
         {'unsupported': {}}],
    ]:
        with pytest.raises(HttpError):
            api.apply({'requests': requests,
                       'writeControl': {'requiredRevisionId': 'r0'}})
        assert api.snapshot() == before
    with pytest.raises(HttpError):
        api.apply({'requests': [],
                   'writeControl': {'requiredRevisionId': 'stale'}})


def test_duplicate_tab_titles_are_rejected(fixture_specification):
    """Match the title uniqueness enforced by actual native tab creation."""
    fixture_specification['tabs'][1]['title'] = (
        fixture_specification['tabs'][0]['title'])
    with pytest.raises(ValueError, match='unique tab titles'):
        fixture_api.FixtureAPI(fixture_specification)


def test_whole_paragraph_style_includes_newline(fixture_specification):
    """Match native formatting without expanding a partial-text selection."""
    api = fixture_api.FixtureAPI(fixture_specification)
    for end, expected in [(10, False), (15, True)]:
        api.apply({'requests': [{'updateTextStyle': {
            'range': {'tabId': 't.main', 'startIndex': 1, 'endIndex': end},
            'textStyle': {'bold': True}, 'fields': 'bold',
        }}]})
        actual = bool(api.tabs[0]['chars'][-1]['textStyle'].get('bold'))
        assert actual == expected


@pytest.mark.parametrize('variant', ['baseline', 'both'])
def test_production_reads_writes_and_comment_status(
    fixture_specification, monkeypatch, variant,
):
    """Use real parsing, targeting, compilation and receipt validation."""
    api = fixture_api.FixtureAPI(fixture_specification)
    monkeypatch.setattr(clients, 'get_service', lambda *_a, **_k: api)
    server = FastMCP('fixture', middleware=[ToolCallLoggingMiddleware()])
    documents.register_discovery(server)
    documents.register_reading(server)
    documents.register_editing(server, consolidated=variant == 'both')
    comments.register(server, consolidated=variant == 'both')
    formatting.register(server)
    protected = deepcopy(api.snapshot()['tabs'][0])

    async def run():
        async with Client(server) as client:
            args = {'doc_id': 'study_fixture', 'tab_id': 't.review'}
            outline = (await client.call_tool('docs_get_tree', args)
                       ).structured_content
            assert outline['sections'][0]['id'] == 'h.review'
            name = 'docs_append' if variant == 'baseline' else 'docs_insert'
            extra = {} if variant == 'baseline' else {
                'target': {'position': 'append'},
            }
            receipt = (await client.call_tool(name, {
                **args, 'text': '**Bold**', **extra,
            })).structured_content
            assert receipt['ok']
            read = (await client.call_tool('docs_read', args)
                    ).structured_content
            assert 'Bold' in str(read)
            native = (api.snapshot()['tabs'][1]['documentTab']['body']
                      ['content'])
            assert any(e['textRun']['textStyle'].get('bold')
                       for p in native for e in p['paragraph']['elements']
                       if 'Bold' in e['textRun']['content'])
            name = ('docs_insert_before' if variant == 'baseline'
                    else 'docs_insert')
            target = {'anchor': 'Anchor 😀', 'heading_id': 'h.review'}
            extra = target if variant == 'baseline' else {
                'target': {'position': 'before', **target},
            }
            await client.call_tool(name, {**args, 'text': 'Before', **extra})
            await client.call_tool('docs_search_replace', {
                **args, 'find': 'Tail', 'replace': 'Changed',
            })
            await client.call_tool('docs_format_text', {
                **args, 'anchor_text': 'Anchor 😀', 'foreground_color': 'blue',
            })
            for action in ('resolve', 'reopen'):
                name = (f'docs_{action}_comment' if variant == 'baseline'
                        else 'docs_comment_status')
                extra = {} if variant == 'baseline' else {'action': action}
                await client.call_tool(name, {
                    'doc_id': 'study_fixture', 'comment_id': 'c.review',
                    **extra,
                })
                read = (await client.call_tool('docs_read_comments', {
                    'doc_id': 'study_fixture', 'comment_id': 'c.review',
                })).structured_content
                assert read['comments'][0]['resolved'] == (action == 'resolve')
    asyncio.run(run())
    assert api.snapshot()['tabs'][0] == protected
