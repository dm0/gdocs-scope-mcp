"""Verify every MCP output contract against mocked Google API boundaries."""

import asyncio
import json
import logging
from importlib.metadata import version
from unittest.mock import MagicMock

import pytest
from fastmcp import Client
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response
from jsonschema import validate

from gdocs_scope_mcp import docs_edit, server
from gdocs_scope_mcp.tool_logging import LOGGER_NAME


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
    ('server_info', {}, {'package_version': version('gdocs-scope-mcp')}),
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
    validate(data, tool.outputSchema)
    error_schema = next(
        branch
        for branch in tool.outputSchema['anyOf']
        if branch['title'] == 'EditFailedResponse'
    )
    assert {'code', 'description', 'suggested_action'} <= set(
        error_schema['required']
    )
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
    """Typed error branches are unwrapped and marked as MCP failures."""
    arguments = {'doc_id': 'example', 'heading_id': 'missing'}
    if name == 'docs_search_replace':
        arguments.update(find='Target phrase', replace='Changed')
    else:
        arguments.update(anchor='Target phrase', text='New')

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        tool, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error is True
    data = response.structured_content
    assert set(data) == {'ok', 'code', 'description', 'suggested_action'}
    assert data['ok'] is False
    assert data['code'] == 'HEADING_NOT_FOUND'
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


@pytest.mark.parametrize(
    ('name', 'arguments', 'code'),
    [
        (
            'docs_insert_before',
            {'anchor': 'absent', 'text': 'New'},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_insert_after',
            {'anchor': 'absent', 'text': 'New'},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_search_replace',
            {'find': 'absent', 'replace': 'New'},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_search_replace',
            {'find': 'Target phrase', 'replace': 'New', 'occurrence': 100},
            'OCCURRENCE_NOT_FOUND',
        ),
        ('docs_delete_paragraph', {'anchor': 'absent'}, 'TEXT_NOT_FOUND'),
        (
            'docs_add_comment',
            {'anchor_text': 'absent', 'comment': 'New'},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_add_comment',
            {
                'anchor_text': 'Target phrase',
                'comment': 'New',
                'occurrence': 100,
            },
            'OCCURRENCE_NOT_FOUND',
        ),
        (
            'docs_batch_replace',
            {'replacements_json': '[{"find":"absent","replace":"new"}]'},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_batch_replace',
            {
                'replacements_json': (
                    '[{"find":"Introduction","replace":"new",'
                    '"occurrence":100}]'
                )
            },
            'OCCURRENCE_NOT_FOUND',
        ),
        (
            'docs_batch_replace',
            {'replacements_json': '{invalid'},
            'INVALID_ARGUMENT',
        ),
        (
            'docs_append',
            {'rich': 'not-a-bool', 'text': 'New'},
            'INVALID_ARGUMENT',
        ),
        ('docs_append', {}, 'INVALID_ARGUMENT'),
    ],
)
def test_expected_failures_have_codes_and_do_not_write(
    contract_api,
    mock_docs,
    *,
    name,
    arguments,
    code,
    caplog,
):
    """Expected failures have recovery fields and perform no API writes."""
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        tool, response = call_tool(
            name,
            {'doc_id': 'example', **arguments},
            raise_on_error=False,
        )

    assert response.is_error
    data = response.structured_content
    assert data['ok'] is False
    assert data['code'] == code
    assert data['suggested_action']
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)
    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert f'code={code}' in records[0].getMessage()
    assert records[0].exc_info is None
    mock_docs.batchUpdate.assert_not_called()
    contract_api.comments.return_value.create.assert_not_called()


@pytest.mark.parametrize(
    ('status', 'code'),
    [
        (400, 'INVALID_ARGUMENT'),
        (401, 'AUTHENTICATION_REQUIRED'),
        (403, 'PERMISSION_DENIED'),
        (404, 'RESOURCE_NOT_FOUND'),
        (429, 'RATE_LIMITED'),
        (503, 'GOOGLE_API_ERROR'),
    ],
)
def test_google_api_errors_have_safe_recovery_fields(
    contract_api, status, code
):
    """Preserve API status without exposing response bodies to the client."""
    request = contract_api.replies.return_value.create.return_value
    request.execute.side_effect = HttpError(
        Response({'status': status}),
        b'{"error":{"message":"private-api-body"}}',
    )
    tool, response = call_tool(
        'docs_resolve_comment',
        {'doc_id': 'example', 'comment_id': 'comment-id'},
        raise_on_error=False,
    )

    assert response.is_error
    data = response.structured_content
    assert data['code'] == code
    assert str(status) in data['description']
    assert 'before retrying a write' in data['suggested_action']
    assert 'private-api-body' not in json.dumps(data)
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)
    request.execute.assert_called_once()


@pytest.mark.usefixtures('contract_api')
def test_backend_model_validation_is_internal_error(mock_docs):
    """Malformed Google data must not be blamed on the caller's arguments."""
    mock_docs.get.return_value.execute.side_effect = lambda: {
        'documentId': 'example',
    }
    _, response = call_tool(
        'docs_get_tree',
        {'doc_id': 'example'},
        raise_on_error=False,
    )

    assert response.is_error
    assert response.structured_content['code'] == 'INTERNAL_ERROR'


@pytest.mark.usefixtures('contract_api')
def test_empty_document_append_has_structured_failure(mock_docs):
    """An unusable document body fails before sending an insertion."""
    mock_docs.get.return_value.execute.side_effect = lambda: {'body': {}}
    _, response = call_tool(
        'docs_append',
        {'doc_id': 'example', 'text': 'New'},
        raise_on_error=False,
    )

    assert response.is_error
    assert response.structured_content['code'] == 'EMPTY_DOCUMENT'
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('contract_api')
def test_expired_credentials_have_authentication_guidance(monkeypatch):
    """Credential refresh errors tell the agent how to authenticate again."""

    def expired():
        raise RefreshError('private-token-details')

    monkeypatch.setattr(docs_edit, '_load_creds', expired)
    _, response = call_tool(
        'docs_resolve_comment',
        {'doc_id': 'example', 'comment_id': 'comment-id'},
        raise_on_error=False,
    )

    assert response.is_error
    data = response.structured_content
    assert data['code'] == 'AUTHENTICATION_REQUIRED'
    assert 'gdocs-scope-mcp-auth' in data['suggested_action']
    assert 'private-token-details' not in json.dumps(data)


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
    assert response.structured_content['code'] == 'INTERNAL_ERROR'


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


@pytest.mark.parametrize('reply', ['', 'Closing reply'])
def test_resolve_uses_reply_action_in_one_request(contract_api, reply):
    """Resolve through replies.create, with optional content on that action."""
    contract_api.comments.return_value.update.side_effect = AssertionError(
        'comments.update cannot resolve a comment',
    )

    _, response = call_tool(
        'docs_resolve_comment',
        {
            'doc_id': 'example',
            'comment_id': 'comment-id',
            'reply': reply,
        },
    )

    expected_body = {'action': 'resolve'}
    if reply:
        expected_body['content'] = reply
    contract_api.replies.return_value.create.assert_called_once_with(
        fileId='example',
        commentId='comment-id',
        body=expected_body,
        fields='id',
    )
    contract_api.replies.return_value.create.return_value.execute.assert_called_once()
    contract_api.comments.return_value.update.assert_not_called()
    assert response.is_error is False
    assert response.structured_content == {
        'ok': True,
        'comment_id': 'comment-id',
        'resolved': True,
    }
    assert json.loads(response.content[0].text) == response.structured_content


def test_resolve_failure_does_not_return_success(contract_api):
    """A failed resolve action stays an MCP error without a success receipt."""
    request = contract_api.replies.return_value.create.return_value
    request.execute.side_effect = RuntimeError('Simulated resolve failure')

    _, response = call_tool(
        'docs_resolve_comment',
        {
            'doc_id': 'example',
            'comment_id': 'comment-id',
        },
        raise_on_error=False,
    )

    assert response.is_error is True
    assert response.structured_content['code'] == 'INTERNAL_ERROR'
    contract_api.comments.return_value.update.assert_not_called()


@pytest.mark.xfail(
    strict=True,
    reason='Batch replacements are exposed as an opaque JSON string.',
)
def test_typed_batch_input_schema_exposes_replacement_fields():
    """Expose item fields for constructing validated replacement objects."""
    async def schema():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            return next(
                tool.inputSchema for tool in tools
                if tool.name == 'docs_batch_replace'
            )

    item_array = asyncio.run(schema())['properties']['replacements']
    assert item_array['type'] == 'array'
    item = item_array['items']
    assert item['type'] == 'object'
    assert {'find', 'replace'} <= set(item['required'])
    assert item['properties']['occurrence']['minimum'] == 0


@pytest.mark.xfail(
    strict=True,
    reason='The batch tool does not accept a typed replacements array.',
)
def test_typed_batch_input_accepts_structured_replacements(
    contract_api, mock_docs,
):
    """Pass replacement objects directly, without nested JSON serialization."""
    _, response = call_tool(
        'docs_batch_replace',
        {'doc_id': 'example', 'replacements': [
            {'find': 'Introduction', 'replace': 'Changed'},
        ]},
        raise_on_error=False,
    )

    assert response.is_error is False
    assert response.structured_content['applied'] == 1
    mock_docs.batchUpdate.assert_called_once()
    contract_api.files.return_value.list.assert_not_called()


@pytest.mark.xfail(
    strict=True,
    reason='Tool constraints are not consistently validated before API calls.',
)
@pytest.mark.parametrize(
    ('name', 'arguments'),
    [
        ('docs_search_replace', {'find': 'Target phrase', 'replace': 'New',
                                 'occurrence': -1}),
        ('docs_insert_before', {'anchor': '', 'text': 'New'}),
        ('docs_delete_paragraph', {'anchor': ''}),
        ('docs_add_comment', {'anchor_text': 'Target phrase', 'comment': 'New',
                              'occurrence': 0}),
        ('docs_list', {'limit': 0}),
        ('docs_list', {'limit': -1}),
        ('docs_batch_replace', {'replacements_json': '[{"replace":"New"}]'}),
    ],
)
def test_invalid_tool_constraints_fail_before_api_access(
    contract_api, mock_docs, name, arguments,
):
    """Reject invalid ranges, empty anchors, and incomplete replacements."""
    if name != 'docs_list':
        arguments = {'doc_id': 'example', **arguments}
    _, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()
    contract_api.files.return_value.list.assert_not_called()
    contract_api.comments.return_value.create.assert_not_called()


@pytest.mark.xfail(
    strict=True,
    reason='Outline description still promises a JSON array.',
)
def test_outline_description_matches_object_and_flat_hierarchy():
    """Describe the object wrapper and hierarchy expressed by ancestors."""
    async def description():
        async with Client(server.mcp) as client:
            return next(
                tool.description for tool in await client.list_tools()
                if tool.name == 'docs_get_tree'
            )

    text = ' '.join(asyncio.run(description()).split())
    assert 'JSON array' not in text
    assert 'sections' in text
    assert 'ancestor_ids' in text


@pytest.mark.xfail(
    strict=True,
    reason='The public comment occurrence description is truncated.',
)
def test_comment_occurrence_description_is_complete_in_catalog():
    """Keep the first-occurrence explanation visible in the public schema."""
    async def description():
        async with Client(server.mcp) as client:
            tool = next(
                tool for tool in await client.list_tools()
                if tool.name == 'docs_add_comment'
            )
            return tool.inputSchema['properties']['occurrence']['description']

    text = ' '.join(asyncio.run(description()).split())
    assert 'first' in text.casefold()
    assert '2, 3' in text


@pytest.mark.xfail(
    strict=True,
    reason='Listing responses omit continuation and completeness metadata.',
)
@pytest.mark.parametrize('name', ['docs_list', 'docs_read_comments'])
@pytest.mark.parametrize('has_more', [False, True])
def test_listing_reports_page_continuation(contract_api, name, has_more):
    """Distinguish a terminal page from a page with further results."""
    if name == 'docs_list':
        request = contract_api.files.return_value.list.return_value
        arguments = {}
    else:
        request = contract_api.comments.return_value.list.return_value
        arguments = {'doc_id': 'example'}
    if has_more:
        request.execute.return_value['nextPageToken'] = 'next-page'

    _, response = call_tool(name, arguments)

    data = response.structured_content
    assert data['has_more'] is has_more
    assert data['next_page_token'] == ('next-page' if has_more else None)
    assert data['count'] == 1


@pytest.mark.xfail(
    strict=True,
    reason='Listing tools do not accept a continuation token.',
)
@pytest.mark.parametrize('name', ['docs_list', 'docs_read_comments'])
def test_listing_forwards_page_token_to_drive(contract_api, name):
    """Let an agent request the next page without repeating page one."""
    arguments = {'page_token': 'second-page'}
    if name == 'docs_list':
        resource = contract_api.files.return_value
    else:
        resource = contract_api.comments.return_value
        arguments['doc_id'] = 'example'

    _, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error is False
    resource.list.assert_called_once()
    assert resource.list.call_args.kwargs['pageToken'] == 'second-page'
    assert 'nextPageToken' in resource.list.call_args.kwargs['fields']


@pytest.mark.xfail(
    strict=True,
    reason='An empty filtered comment page hides continuation metadata.',
)
def test_filtered_comment_page_keeps_continuation(contract_api):
    """Zero visible comments on this page must not imply no later comments."""
    resource = contract_api.comments.return_value
    resource.list.return_value.execute.return_value = {
        'comments': [{'id': 'resolved', 'resolved': True}],
        'nextPageToken': 'more-comments',
    }

    _, response = call_tool('docs_read_comments', {'doc_id': 'example'})

    data = response.structured_content
    assert data['comments'] == []
    assert data['count'] == 0
    assert data['has_more'] is True
    assert data['next_page_token'] == 'more-comments'
