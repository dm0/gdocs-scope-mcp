"""Verify Study 1 capability parity at the MCP boundary."""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client, FastMCP
from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp.settings import Settings
from gdocs_scope_mcp.tool_logging import ToolCallLoggingMiddleware
from gdocs_scope_mcp.tools import comments, documents


def study_server(variant):
    """Create an independent, fully static study catalog."""
    server = FastMCP('study', middleware=[ToolCallLoggingMiddleware()])
    documents.register_editing(
        server, consolidated=variant in {'insertion', 'both'},
    )
    comments.register(server, consolidated=variant in {'status', 'both'})
    return server


@pytest.mark.parametrize('variant', [
    'baseline', 'insertion', 'status', 'both',
])
def test_static_catalog_and_unchanged_contracts(variant):
    """Only the declared interfaces change, including approval annotations."""
    async def capture(server):
        async with Client(server) as client:
            first = {t.name: t.model_dump() for t in await client.list_tools()}
            assert first == {t.name: t.model_dump()
                             for t in await client.list_tools()}
            return first

    baseline = asyncio.run(capture(study_server('baseline')))
    actual = asyncio.run(capture(study_server(variant)))
    removed = set()
    additions = {}
    if variant in {'insertion', 'both'}:
        removed.update({
            'docs_append', 'docs_insert_before', 'docs_insert_after',
        })
        additions['docs_insert'] = 'docs_append'
    if variant in {'status', 'both'}:
        removed.update({'docs_resolve_comment', 'docs_reopen_comment'})
        additions['docs_comment_status'] = 'docs_resolve_comment'
    assert set(actual) == (set(baseline) - removed) | set(additions)
    for name in set(baseline) - removed:
        assert actual[name] == baseline[name]
    for name, original in additions.items():
        assert actual[name]['annotations'] == baseline[original]['annotations']


@pytest.mark.parametrize('position', ['append', 'before', 'after'])
@pytest.mark.parametrize('rich', [False, True])
def test_native_insertion_requests_and_receipts_match(
    position, rich, mock_docs,
):
    """Compare real orchestration, native batches and exact MCP receipts."""
    async def run(variant):
        mock_docs.batchUpdate.reset_mock()
        args = {
            'doc_id': 'example', 'text': '**Added** 😀', 'rich': rich,
            'code_block_style': 'monokai',
            'code_block_theme_background': False,
            'table_borders': False, 'expected_revision_id': 'revision',
        }
        target = {'position': position}
        if position != 'append':
            target.update(anchor='Target phrase again', heading_id='nested')
        if variant == 'baseline':
            name = ('docs_append' if position == 'append'
                    else f'docs_insert_{position}')
            args.update({k: v for k, v in target.items() if k != 'position'})
        else:
            name = 'docs_insert'
            args['target'] = target
        async with Client(study_server(variant)) as client:
            result = await client.call_tool(name, args)
        assert not result.is_error
        requests = [deepcopy(call.kwargs)
                    for call in mock_docs.batchUpdate.call_args_list]
        return result.structured_content, requests

    assert asyncio.run(run('baseline')) == asyncio.run(run('both'))


@pytest.mark.parametrize('target', [
    {'position': 'before'}, {'position': 'after', 'anchor': ''},
    {'position': 'append', 'anchor': 'ignored?'},
    {'position': 'append', 'heading_id': 'nested'},
    {'position': 'before', 'anchor': 'x', 'occurrence': 2},
    {'position': 'after_subtree', 'heading_id': 'nested'},
])
def test_invalid_targets_fail_before_google(target, mock_docs):
    """Reject contradictory selectors before side effects."""
    async def run():
        async with Client(study_server('both')) as client:
            result = await client.call_tool('docs_insert', {
                'doc_id': 'example', 'text': 'added', 'target': target,
            }, raise_on_error=False)
            assert result.is_error
    asyncio.run(run())
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('position', ['before', 'after'])
@pytest.mark.parametrize('anchor', ['missing anchor', 'Target phrase'])
def test_insertion_failure_parity(position, anchor, mock_docs):
    """Retain missing-anchor errors and existing repeated-anchor matching."""
    async def run(variant):
        args = {'doc_id': 'example', 'text': 'added'}
        if variant == 'baseline':
            name = f'docs_insert_{position}'
            args['anchor'] = anchor
        else:
            name = 'docs_insert'
            args['target'] = {'position': position, 'anchor': anchor}
        async with Client(study_server(variant)) as client:
            result = await client.call_tool(name, args, raise_on_error=False)
        assert result.is_error == (anchor == 'missing anchor')
        return result.is_error, result.structured_content, result.content
    assert asyncio.run(run('baseline')) == asyncio.run(run('both'))
    if anchor == 'missing anchor':
        mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('action', ['resolve', 'reopen'])
@pytest.mark.parametrize('reply', ['', 'Review complete 😀'])
def test_comment_status_delegation(action, reply, monkeypatch):
    """Preserve action posts, optional text, revisions and response models."""
    calls = []

    def mutate(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            'ok': True, 'document_id': 'example', 'comment_id': 'thread',
            'reply_id': 'post', 'resolved': action == 'resolve',
            'comment_update_state': 'ALL_SAVED',
        }

    monkeypatch.setattr(comments.comments, 'mutate', mutate)

    async def run(variant):
        args = {'doc_id': 'example', 'comment_id': 'thread', 'reply': reply,
                'expected_revision_id': 'revision'}
        name = f'docs_{action}_comment'
        if variant != 'baseline':
            name = 'docs_comment_status'
            args['action'] = action
        async with Client(study_server(variant)) as client:
            return (await client.call_tool(name, args)).structured_content

    assert asyncio.run(run('baseline')) == asyncio.run(run('both'))
    assert calls[0] == calls[1]


def test_variant_configuration_rejects_typos(monkeypatch):
    """Invalid variants must not silently switch interfaces."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT', raising=False)
    assert Settings().tool_interface_variant == 'both'
    with pytest.raises(ValueError):
        Settings(tool_interface_variant='dynamic')


def test_google_input_failure_keeps_insertion_recovery_guidance(mock_docs):
    """Preserve Google image/input recovery guidance for docs_insert."""
    mock_docs.batchUpdate.return_value.execute.side_effect = HttpError(
        Response({'status': '400'}), b'{"error":{"message":"bad input"}}',
    )

    async def run(name, extra):
        async with Client(study_server('baseline' if name == 'docs_append'
                                      else 'both')) as client:
            result = await client.call_tool(name, {
                'doc_id': 'example', 'text': 'added', **extra,
            }, raise_on_error=False)
            assert result.is_error
            return result.structured_content

    assert asyncio.run(run('docs_append', {})) == asyncio.run(run(
        'docs_insert', {'target': {'position': 'append'}},
    ))
