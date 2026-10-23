"""Verify every MCP output contract against mocked Google API boundaries."""

import asyncio
import json
import logging
from importlib.metadata import version
from unittest.mock import MagicMock

import pytest
from fastmcp import Client

from google_docs_mcp import docs_edit, server
from google_docs_mcp.tool_logging import LOGGER_NAME


@pytest.fixture
def contract_api(monkeypatch, mock_docs):
    """Provide Docs and Drive responses without using real credentials."""
    api = MagicMock()
    api.documents.return_value = mock_docs
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'createNamedRange': {'namedRangeId': 'range-id'}}],
    }
    mock_docs.create.return_value.execute.return_value = {
        'documentId': 'created-doc',
    }
    api.files.return_value.list.return_value.execute.return_value = {
        'files': [
            {
                'id': 'example',
                'name': 'Example',
                'modifiedTime': '2026-10-23T09:00:00Z',
                'webViewLink': 'https://docs.google.com/document/d/example/edit',
            }
        ],
    }
    api.comments.return_value.create.return_value.execute.return_value = {
        'id': 'comment-id',
    }
    api.comments.return_value.list.return_value.execute.return_value = {
        'comments': [
            {
                'id': 'comment-id',
                'content': 'Comment body',
                'author': {'displayName': 'Author'},
                'anchor': json.dumps({'a': [{'t': 'r', 'v': 'range-id'}]}),
                'quotedFileContent': {'value': 'Target phrase'},
                'resolved': False,
                'deleted': False,
                'createdTime': '2026-10-23T09:00:00Z',
            }
        ],
    }
    api.replies.return_value.create.return_value.execute.return_value = {
        'id': 'reply-id',
        'content': 'Reply body',
    }
    monkeypatch.setattr(server, 'build', lambda *_args, **_kwargs: api)
    monkeypatch.setattr(docs_edit, 'build', lambda *_args, **_kwargs: api)
    monkeypatch.setattr(docs_edit, '_load_creds', object)
    return api


def call_tool(name, arguments, *, raise_on_error=True):
    """Call through MCP serialization and client-side schema validation."""

    async def call():
        async with Client(server.mcp) as client:
            catalog = {tool.name: tool for tool in await client.list_tools()}
            result = await client.call_tool(
                name,
                arguments,
                raise_on_error=raise_on_error,
            )
            return catalog[name], result

    return asyncio.run(call())


TOOL_CASES = [
    ('server_info', {}, {'package_version': version('google-docs-mcp')}),
    ('docs_get_tree', {'doc_id': 'example'}, {'document_id': 'example'}),
    ('docs_read', {'doc_id': 'example'}, {'partial': False}),
    (
        'docs_search_replace',
        {
            'doc_id': 'example',
            'find': 'Target phrase',
            'replace': 'Changed',
        },
        {'ok': True, 'replaced': 'Target phrase'},
    ),
    (
        'docs_insert_after',
        {
            'doc_id': 'example',
            'anchor': 'Introduction',
            'text': '**New**',
        },
        {'ok': True, 'insert_position': 'after', 'inserted_text': '\nNew'},
    ),
    (
        'docs_insert_before',
        {
            'doc_id': 'example',
            'anchor': 'Introduction',
            'text': '**New**',
        },
        {'ok': True, 'insert_position': 'before', 'inserted_text': 'New\n'},
    ),
    (
        'docs_delete_paragraph',
        {
            'doc_id': 'example',
            'anchor': 'Target phrase',
        },
        {'ok': True, 'deleted_count': 3},
    ),
    (
        'docs_append',
        {
            'doc_id': 'example',
            'text': '**New**',
        },
        {'ok': True, 'appended': '\nNew'},
    ),
    (
        'docs_batch_replace',
        {
            'doc_id': 'example',
            'replacements_json': json.dumps(
                [
                    {'find': 'Introduction', 'replace': 'Changed'},
                ]
            ),
        },
        {
            'ok': True,
            'applied': 1,
            'changes': [
                {
                    'replaced': 'Introduction',
                    'with': 'Changed',
                    'at_index': 1,
                }
            ],
        },
    ),
    (
        'docs_add_comment',
        {
            'doc_id': 'example',
            'anchor_text': 'Target phrase',
            'comment': 'Comment body',
        },
        {
            'ok': True,
            'comment_id': 'comment-id',
            'named_range_id': 'range-id',
            'bookmark_id': None,
            'bookmark_url': None,
            'apps_script_id': None,
            'comment_content': (
                'Comment body\n\nAnchored text: “Target phrase”'
            ),
        },
    ),
    (
        'docs_reply_to_comment',
        {
            'doc_id': 'example',
            'comment_id': 'comment-id',
            'reply': 'Reply body',
        },
        {'ok': True, 'reply_id': 'reply-id', 'content': 'Reply body'},
    ),
    (
        'docs_resolve_comment',
        {
            'doc_id': 'example',
            'comment_id': 'comment-id',
        },
        {'ok': True, 'comment_id': 'comment-id', 'resolved': True},
    ),
    (
        'docs_delete_comment',
        {
            'doc_id': 'example',
            'comment_id': 'comment-id',
        },
        {'ok': True, 'comment_id': 'comment-id'},
    ),
    (
        'docs_read_comments',
        {'doc_id': 'example'},
        {
            'count': 1,
            'comments': [
                {
                    'id': 'comment-id',
                    'content': 'Comment body',
                    'author': 'Author',
                    'anchored': True,
                    'named_range_id': 'range-id',
                    'quoted_text': 'Target phrase',
                    'resolved': False,
                    'deleted': False,
                    'created': '2026-10-23T09:00:00Z',
                }
            ],
        },
    ),
    (
        'docs_list',
        {},
        {
            'count': 1,
            'documents': [
                {
                    'id': 'example',
                    'name': 'Example',
                    'modifiedTime': '2026-10-23T09:00:00Z',
                    'webViewLink': 'https://docs.google.com/document/d/example/edit',
                }
            ],
        },
    ),
    (
        'docs_create',
        {'title': 'Created', 'initial_text': 'Initial text'},
        {
            'id': 'created-doc',
            'title': 'Created',
            'webViewLink': 'https://docs.google.com/document/d/created-doc/edit',
        },
    ),
]


@pytest.mark.usefixtures('contract_api')
@pytest.mark.parametrize(('name', 'arguments', 'expected'), TOOL_CASES)
def test_all_tools_return_direct_typed_objects(name, arguments, expected):
    """Schemas expose fields and both result channels carry direct objects."""
    tool, response = call_tool(name, arguments)

    assert tool.outputSchema['type'] == 'object'
    assert not tool.outputSchema.get('x-fastmcp-wrap-result', False)
    assert response.is_error is False
    data = response.structured_content
    assert isinstance(data, dict)
    assert 'result' not in data
    assert json.loads(response.content[0].text) == data
    for key, value in expected.items():
        assert data[key] == value


@pytest.mark.parametrize(
    'name',
    [
        'docs_search_replace',
        'docs_insert_before',
        'docs_insert_after',
    ],
)
def test_edit_failures_are_direct_objects_and_log_failure(
    contract_api,
    mock_docs,
    caplog,
    name,
):
    """Typed error branches remain unwrapped and middleware sees ok=False."""
    arguments = {'doc_id': 'example', 'heading_id': 'missing'}
    if name == 'docs_search_replace':
        arguments.update(find='Target phrase', replace='Changed')
    else:
        arguments.update(anchor='Target phrase', text='New')

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        tool, response = call_tool(name, arguments)

    assert response.is_error is False
    data = response.structured_content
    assert set(data) == {'ok', 'description', 'suggested_action'}
    assert data['ok'] is False
    assert 'missing' in data['description']
    assert json.loads(response.content[0].text) == data
    branches = [
        tool.outputSchema['$defs'][branch['$ref'].split('/')[-1]]
        if '$ref' in branch
        else branch
        for branch in tool.outputSchema['anyOf']
    ]
    assert {branch['properties']['ok']['const'] for branch in branches} == {
        True,
        False,
    }
    assert any(
        record.name == LOGGER_NAME
        and record.levelno == logging.ERROR
        and f'tool={name} status=failure' in record.getMessage()
        for record in caplog.records
    )
    mock_docs.batchUpdate.assert_not_called()
    contract_api.comments.return_value.create.assert_not_called()


def test_catalog_contract_covers_every_registered_tool():
    """A newly added tool must be included in the output contract checks."""

    async def names():
        async with Client(server.mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    assert asyncio.run(names()) == {name for name, _, _ in TOOL_CASES}


@pytest.mark.parametrize('name', ['docs_create', 'docs_delete_comment'])
def test_api_errors_remain_mcp_errors(contract_api, name):
    """API exceptions do not become typed success receipts."""
    if name == 'docs_create':
        request = contract_api.documents.return_value.create.return_value
        arguments = {'title': 'Created'}
    else:
        request = contract_api.comments.return_value.delete.return_value
        arguments = {'doc_id': 'example', 'comment_id': 'comment-id'}
    request.execute.side_effect = RuntimeError('Simulated Google API failure')

    _, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error is True
    assert response.structured_content is None


def test_comment_bookmark_fields_are_preserved(contract_api, monkeypatch):
    """Optional bookmark navigation survives conversion to a typed response."""
    monkeypatch.setattr(
        docs_edit,
        '_create_bookmark_via_apps_script',
        lambda *_args, **_kwargs: {
            'bookmark_id': 'bookmark-id',
            'script_id': 'script-id',
        },
    )
    _, response = call_tool(
        'docs_add_comment',
        {
            'doc_id': 'example',
            'anchor_text': 'Target phrase',
            'comment': 'Comment body',
            'bookmark_jump': True,
        },
    )

    data = response.structured_content
    assert data['bookmark_id'] == 'bookmark-id'
    assert data['apps_script_id'] == 'script-id'
    assert '#bookmark=bookmark-id' in data['bookmark_url']
    assert data['bookmark_url'] in data['comment_content']
    contract_api.comments.return_value.create.assert_called_once()


@pytest.mark.parametrize('name', ['docs_list', 'docs_read_comments'])
def test_empty_lists_keep_named_typed_collections(contract_api, name):
    """An empty collection remains an object with count and a named list."""
    if name == 'docs_list':
        files = contract_api.files.return_value
        files.list.return_value.execute.return_value = {}
        arguments, collection = {}, 'documents'
    else:
        comments = contract_api.comments.return_value
        comments.list.return_value.execute.return_value = {}
        arguments, collection = {'doc_id': 'example'}, 'comments'

    _, response = call_tool(name, arguments)

    assert response.structured_content == {'count': 0, collection: []}


def test_document_list_allows_missing_optional_drive_fields(contract_api):
    """Absent optional Drive metadata remains explicitly nullable."""
    files = contract_api.files.return_value
    files.list.return_value.execute.return_value = {
        'files': [{'id': 'example', 'name': 'Example'}],
    }

    _, response = call_tool('docs_list', {})

    assert response.structured_content['documents'] == [
        {
            'id': 'example',
            'name': 'Example',
            'modifiedTime': None,
            'webViewLink': None,
        }
    ]


@pytest.mark.parametrize('include_resolved', [False, True])
def test_comment_filtering_and_defaults_survive_typed_output(
    contract_api,
    include_resolved,
):
    """Comment counts reflect filtering and missing metadata keeps defaults."""
    comments = contract_api.comments.return_value
    comments.list.return_value.execute.return_value = {
        'comments': [{'id': 'resolved-id', 'resolved': True}],
    }

    _, response = call_tool(
        'docs_read_comments',
        {
            'doc_id': 'example',
            'include_resolved': include_resolved,
        },
    )

    data = response.structured_content
    assert data['count'] == int(include_resolved)
    if include_resolved:
        assert data['comments'] == [
            {
                'id': 'resolved-id',
                'content': '',
                'author': '?',
                'anchored': False,
                'named_range_id': None,
                'quoted_text': '',
                'resolved': True,
                'deleted': False,
                'created': '',
            }
        ]
    else:
        assert data['comments'] == []
