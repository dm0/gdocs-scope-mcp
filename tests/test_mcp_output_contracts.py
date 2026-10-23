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

EXPECTED_SHORT_PREVIEW_LIMIT = 80
EXPECTED_TEXT_PREVIEW_LIMIT = 200
EXPECTED_RECEIPT_ITEM_LIMIT = 100


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


@pytest.fixture
def receipt_document(simple_document):
    """Build valid paragraph ranges for receipt boundary cases."""
    def populate(lines):
        content = []
        index = 1
        for line in lines:
            text = line + '\n'
            end = index + len(text)
            content.append({
                'startIndex': index,
                'endIndex': end,
                'paragraph': {
                    'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                    'elements': [{
                        'startIndex': index, 'endIndex': end,
                        'textRun': {'content': text, 'textStyle': {}},
                    }],
                },
            })
            index = end
        simple_document['body']['content'] = content

    return populate


@pytest.mark.parametrize('only_paragraph', [False, True])
@pytest.mark.usefixtures('contract_api')
def test_delete_final_paragraph_through_mcp(
    simple_document, mock_docs, only_paragraph,
):
    """Validate receipts and atomic edits against Body boundaries."""
    if only_paragraph:
        simple_document['body']['content'] = (
            simple_document['body']['content'][:1]
        )
    original = '\n' + ''.join(
        element['paragraph']['elements'][0]['textRun']['content']
        for element in simple_document['body']['content']
    )
    remaining = original

    def apply_batch():
        nonlocal remaining
        requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
        starts = []
        for request in requests:
            span = request['deleteContentRange']['range']
            start, end = span['startIndex'], span['endIndex']
            assert 1 <= start < end < len(remaining)
            starts.append(start)
            remaining = remaining[:start] + remaining[end:]
        assert starts == sorted(starts, reverse=True)
        return {}

    mock_docs.batchUpdate.return_value.execute.side_effect = apply_batch
    anchor = 'Introduction' if only_paragraph else 'target PHRASE'
    tool, result = call_tool(
        'docs_delete_paragraph', {'doc_id': 'example', 'anchor': anchor},
    )

    assert not result.is_error
    validate(result.structured_content, tool.outputSchema)
    count = 1 if only_paragraph else 3
    assert result.structured_content['deleted_count'] == count
    assert len(result.structured_content['deleted']) == count
    assert remaining == (
        '\n\n'
        if only_paragraph else '\nIntroduction\nParent\nNested\nOther\n\n'
    )
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('with_nonfinal', [False, True])
@pytest.mark.usefixtures('contract_api')
def test_delete_skips_empty_final_paragraph(
    simple_document, mock_docs, with_nonfinal,
):
    """Never send an empty range or count the protected empty paragraph."""
    content = simple_document['body']['content'][:1] if with_nonfinal else []
    start = content[-1]['endIndex'] if content else 1
    content.append({
        'startIndex': start,
        'endIndex': start + 1,
        'paragraph': {'elements': [{
            'startIndex': start,
            'endIndex': start + 1,
            'textRun': {'content': '\n'},
        }]},
    })
    simple_document['body']['content'] = content
    # Empty-anchor validation is separate (#17); exercise current match-all
    # semantics to cover a matching empty final paragraph.
    tool, result = call_tool(
        'docs_delete_paragraph', {'doc_id': 'example', 'anchor': ''},
    )
    assert not result.is_error
    validate(result.structured_content, tool.outputSchema)
    assert result.structured_content['deleted_count'] == int(with_nonfinal)
    assert result.structured_content['deleted'] == (
        ['Introduction'] if with_nonfinal else []
    )
    if with_nonfinal:
        requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
        assert requests == [{'deleteContentRange': {'range': {
            'startIndex': 1, 'endIndex': start,
        }}}]
        mock_docs.batchUpdate.assert_called_once()
    else:
        mock_docs.batchUpdate.assert_not_called()


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
                    'replaced_char_count': 12,
                    'replacement_char_count': 7,
                    'preview_truncated': False,
                    'replacement_preview_truncated': False,
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
    if name in {
        'docs_search_replace', 'docs_insert_before', 'docs_insert_after',
        'docs_delete_paragraph', 'docs_append', 'docs_batch_replace',
        'docs_add_comment', 'docs_reply_to_comment', 'docs_resolve_comment',
        'docs_delete_comment',
    }:
        assert data['document_id'] == arguments['doc_id']
        assert data['heading_id'] == arguments.get('heading_id')
        assert data['scope'] in {'document', 'document_end', 'comment'}


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
    'options',
    [
        {'heading_id': 'parent'},
        {'regex': True},
        {'heading_id': 'parent', 'regex': True},
    ],
    ids=['scoped', 'regex', 'scoped-regex'],
)
@pytest.mark.usefixtures('contract_api')
def test_unsupported_replace_all_returns_structured_mcp_error(
    mock_docs, monkeypatch, options,
):
    """Reject unsupported modes before credentials or Google API access."""
    get_service = MagicMock(
        side_effect=AssertionError('Unexpected API access'),
    )
    monkeypatch.setattr(docs_edit, '_get_service', get_service)

    tool, response = call_tool(
        'docs_search_replace',
        {
            'doc_id': 'example', 'find': 'Target phrase', 'replace': 'Changed',
            'occurrence': 0, **options,
        },
        raise_on_error=False,
    )

    assert response.is_error
    data = response.structured_content
    assert data['ok'] is False
    assert data['code'] == 'INVALID_ARGUMENT'
    assert data['description']
    assert data['suggested_action']
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)
    get_service.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()
    mock_docs.get.assert_not_called()


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
        'document_id': 'example',
        'scope': 'comment',
        'heading_id': None,
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
    assert 'JSON object' in text
    for field in ('document_id', 'title', 'revision_id'):
        assert field in text
    assert 'flat sections' in text
    assert 'sections' in text
    assert 'ancestor_ids' in text


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
    assert 'default 1 = first' in text
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


@pytest.mark.parametrize(
    ('name', 'read_only'),
    [
        ('docs_get_tree', True), ('docs_read', True),
        ('docs_list', True), ('docs_read_comments', True),
        ('docs_search_replace', False), ('docs_insert_before', False),
        ('docs_insert_after', False), ('docs_delete_paragraph', False),
        ('docs_append', False), ('docs_batch_replace', False),
        ('docs_add_comment', False), ('docs_reply_to_comment', False),
        ('docs_resolve_comment', False), ('docs_delete_comment', False),
        ('docs_create', False),
    ],
)
def test_google_tools_declare_action_hints(name, read_only):
    """Distinguish reads from mutations and identify the external service."""
    async def annotations():
        async with Client(server.mcp) as client:
            return next(
                tool.annotations for tool in await client.list_tools()
                if tool.name == name
            )

    hints = asyncio.run(annotations())
    assert hints is not None
    assert hints.readOnlyHint is read_only
    assert hints.openWorldHint is True
    assert hints.destructiveHint is (name in {
        'docs_search_replace', 'docs_batch_replace',
        'docs_delete_paragraph', 'docs_delete_comment',
    })
    assert hints.idempotentHint is (
        read_only or name in {'docs_delete_paragraph', 'docs_delete_comment'}
    )


@pytest.mark.parametrize('name', ['docs_insert_before', 'docs_insert_after'])
def test_insertion_receipts_identify_scope_and_preview_truncation(
    contract_api, mock_docs, name,
):
    """Make the edited document/scope and an incomplete preview explicit."""
    text = 'X' * 240
    _, response = call_tool(name, {
        'doc_id': 'example', 'heading_id': 'nested',
        'anchor': 'Target phrase', 'text': text, 'rich': False,
    })

    data = response.structured_content
    assert data['document_id'] == 'example'
    assert data['heading_id'] == 'nested'
    assert data['scope'] == 'heading_subtree'
    assert data['preview_truncated'] is True
    assert data['inserted_char_count'] == len(text) + 1
    assert len(data['inserted_text']) < data['inserted_char_count']
    mock_docs.batchUpdate.assert_called_once()
    contract_api.comments.return_value.create.assert_not_called()


@pytest.mark.parametrize('name', ['docs_insert_before', 'docs_insert_after'])
@pytest.mark.parametrize('rich', [False, True])
@pytest.mark.parametrize('length', [0, 199, 200, 240])
@pytest.mark.usefixtures('contract_api')
def test_insertion_preview_counts_actual_unicode_requests(
    mock_docs, name, rich, length,
):
    """Count API text including added breaks, independent of UTF-16 width."""
    tool, response = call_tool(name, {
        'doc_id': 'example', 'anchor': 'Target phrase',
        'text': '😀' * length, 'rich': rich,
    })
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    inserted = ''.join(
        request['insertText']['text']
        for request in requests
        if 'insertText' in request
    )
    data = response.structured_content
    assert data['inserted_text'] == inserted[:200]
    assert data['inserted_char_count'] == len(inserted)
    assert data['preview_truncated'] is (
        len(inserted) > EXPECTED_TEXT_PREVIEW_LIMIT
    )
    assert data['anchor_char_count'] == len(data['anchor'])
    assert data['anchor_preview_truncated'] is False
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('name', ['docs_insert_before', 'docs_insert_after'])
@pytest.mark.usefixtures('contract_api')
def test_long_anchor_has_explicit_preview_metadata(receipt_document, name):
    """Do not silently shorten the anchor used to identify an insertion."""
    anchor = 'Z' * 81
    receipt_document([anchor])
    tool, response = call_tool(name, {
        'doc_id': 'example', 'anchor': anchor,
        'text': 'Inserted', 'rich': False,
    })
    data = response.structured_content
    assert data['anchor'] == anchor[:80]
    assert data['anchor_char_count'] == len(anchor + '\n\n')
    assert data['anchor_preview_truncated'] is True
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('length', [80, 81])
@pytest.mark.usefixtures('contract_api')
def test_replacement_preview_and_match_completeness(
    simple_document, length,
):
    """Keep full counts and explicitly distinguish early-stop matches."""
    original = '😀' * length
    paragraph = simple_document['body']['content'][0]['paragraph']
    paragraph['elements'][0]['textRun']['content'] = original + '\n'
    tool, response = call_tool('docs_search_replace', {
        'doc_id': 'example', 'find': original, 'replace': '',
    })
    data = response.structured_content
    assert data['replaced'] == original[:80]
    assert data['replaced_char_count'] == length
    assert data['preview_truncated'] is (length > EXPECTED_SHORT_PREVIEW_LIMIT)
    assert data['applied'] == 1
    assert data['occurrences_found_complete'] is False
    assert data['occurrences_changed'] is None
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('occurrence', [1, 2])
@pytest.mark.usefixtures('contract_api')
def test_replacement_scope_and_count_metadata(occurrence):
    """Expose scoped counts without changing the existing search strategy."""
    _, response = call_tool('docs_search_replace', {
        'doc_id': 'example', 'find': 'Target phrase', 'replace': 'New',
        'heading_id': 'parent', 'occurrence': occurrence,
    })
    data = response.structured_content
    assert data['document_id'] == 'example'
    assert data['scope'] == 'heading_subtree'
    assert data['heading_id'] == 'parent'
    assert data['applied'] == 1
    assert data['occurrences_found_complete'] is (occurrence != 1)


@pytest.mark.usefixtures('contract_api')
def test_native_replace_all_preserves_changed_count(mock_docs):
    """Native changed counts are not presented as complete search counts."""
    changed_count = 4
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'replaceAllText': {'occurrencesChanged': changed_count}}],
    }
    _, response = call_tool('docs_search_replace', {
        'doc_id': 'example', 'find': 'Target', 'replace': '', 'occurrence': 0,
    })
    data = response.structured_content
    assert data['occurrences_changed'] == data['applied'] == changed_count
    assert data['occurrences_found'] is None
    assert data['occurrences_found_complete'] is False
    mock_docs.get.assert_not_called()


@pytest.mark.parametrize('count', [100, 101])
@pytest.mark.usefixtures('contract_api')
def test_batch_preview_limits_do_not_limit_edits(
    mock_docs, receipt_document, count,
):
    """Bound receipts and preserve aliases while applying the entire batch."""
    replacement = '😀' * 201
    originals = ['Introduction' + 'X' * 70 + f'{index:03}'
                 for index in range(count)]
    receipt_document(originals)
    tool, response = call_tool('docs_batch_replace', {
        'doc_id': 'example',
        'replacements_json': json.dumps([
            {'find': original, 'replace': replacement}
            for original in originals
        ]),
    })
    data = response.structured_content
    assert data['applied'] == count
    assert len(data['changes']) == min(count, 100)
    assert data['changes_truncated'] is (count > EXPECTED_RECEIPT_ITEM_LIMIT)
    change = data['changes'][0]
    assert change['with'] == replacement[:200]
    assert change['replacement_char_count'] == len(replacement)
    assert change['replacement_preview_truncated'] is True
    assert change['replaced'] == originals[0][:80]
    assert change['replaced_char_count'] == len(originals[0])
    assert change['preview_truncated'] is True
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == count * 2
    assert requests[0]['insertText']['text'] == replacement
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('count', [100, 101])
@pytest.mark.usefixtures('contract_api')
def test_deleted_preview_limits_do_not_limit_edits(
    mock_docs, receipt_document, count,
):
    """Retain full paragraph lengths and deletion counts past preview caps."""
    text = 'X' * 81 + '\n'
    receipt_document([text.rstrip('\n')] * count)
    tool, response = call_tool('docs_delete_paragraph', {
        'doc_id': 'example', 'anchor': 'X',
    })
    data = response.structured_content
    shown = min(count, 100)
    assert data['deleted_count'] == count
    assert data['deleted'] == [text[:80]] * shown
    assert data['deleted_char_counts'] == [len(text.rstrip('\n'))] * shown
    assert data['deleted_preview_truncated'] == [True] * shown
    assert data['deleted_truncated'] is (count > EXPECTED_RECEIPT_ITEM_LIMIT)
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == count
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('name', [
    'docs_insert_before', 'docs_insert_after', 'docs_append',
])
def test_rich_insertion_catalog_explains_heading_mapping(name):
    """Keep the unusual Markdown mapping visible to tool callers."""
    async def description():
        async with Client(server.mcp) as client:
            return next(
                tool.description for tool in await client.list_tools()
                if tool.name == name
            )

    text = ' '.join(asyncio.run(description()).split())
    for mapping in ('# is TITLE', '## is SUBTITLE', '### is HEADING_1'):
        assert mapping in text
