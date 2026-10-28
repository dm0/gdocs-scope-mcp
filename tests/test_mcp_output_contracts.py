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

from .native_comment_fixtures import comment_thread, wire_native_comments

EXPECTED_SHORT_PREVIEW_LIMIT = 80
EXPECTED_TEXT_PREVIEW_LIMIT = 200
EXPECTED_RECEIPT_ITEM_LIMIT = 100
EXPECTED_LIST_PAGE_SIZE = 100


@pytest.mark.usefixtures('contract_api', 'table_document')
@pytest.mark.parametrize(
    ('name', 'arguments'),
    [
        ('docs_search_replace', {
            'find': r'(?<=tail)\W+', 'replace': 'X',
            'regex': True, 'heading_id': 'owner',
        }),
        ('docs_batch_replace', {
            'replacements': [{
                'find': 'Before table\nAfter table', 'replace': 'X',
            }],
        }),
        ('docs_add_comment', {
            'comment': 'Comment', 'anchor_text': 'Before table\nAfter table',
        }),
    ],
)
def test_table_structural_boundaries_fail_through_mcp(
    mock_docs, name, arguments,
):
    """Report protected-cell and cross-table matches before any write."""
    tool, result = call_tool(
        name, {'doc_id': 'example', **arguments}, raise_on_error=False,
    )
    assert result.is_error is True
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert result.structured_content['suggested_action']
    validate(result.structured_content, tool.outputSchema)
    mock_docs.batchUpdate.assert_not_called()


@pytest.fixture
def contract_api(monkeypatch, mock_docs, simple_document):
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
    wire_native_comments(mock_docs, simple_document)
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
def test_empty_anchor_cannot_delete_document_with_empty_final_paragraph(
    simple_document, mock_docs, with_nonfinal,
):
    """Reject match-all deletion even when a protected paragraph is empty."""
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
    tool, result = call_tool(
        'docs_delete_paragraph', {'doc_id': 'example', 'anchor': ''},
        raise_on_error=False,
    )
    assert result.is_error
    validate(result.structured_content, tool.outputSchema)
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


TOOL_CASES = [
    ('server_info', {}, {'package_version': version('gdocs-scope-mcp')}),
    ('docs_tabs_list', {'doc_id': 'example'}, {'default_tab_id': None}),
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
            'replacements': [
                {'find': 'Introduction', 'replace': 'Changed'},
            ],
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
            'post_id': 'head-id',
            'anchor_id': 'anchor-comment-id',
            'comment_content': 'Comment body',
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
                    'anchored': False,
                    'anchor_id': 'anchor-comment-id', 'tab_id': None,
                    'ranges': [], 'head_post_id': 'head-id',
                    'reply_count': 1, 'replies': [],
                    'quoted_text': 'Target phrase',
                    'resolved': False,
                    'deleted': False,
                    'created': '2026-10-23T09:00:00Z',
                }
            ],
        },
    ),
    (
        'docs_suggestions_read',
        {'doc_id': 'example'},
        {'document_id': 'example', 'suggestions': [], 'count': 0,
         'total': 0, 'has_more': False, 'page_kind': 'suggestions'},
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
    assert set(data) == {'ok', 'code', 'description', 'suggested_action',
                         'committed_batches'}
    assert data['committed_batches'] == 0
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
            {'replacements': [{'find': 'absent', 'replace': 'new'}]},
            'TEXT_NOT_FOUND',
        ),
        (
            'docs_batch_replace',
            {
                'replacements': [
                    {'find': 'Introduction', 'replace': 'new',
                     'occurrence': 100},
                ],
            },
            'OCCURRENCE_NOT_FOUND',
        ),
        (
            'docs_batch_replace',
            {'replacements': '{invalid'},
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
        (503, 'WRITE_OUTCOME_UNKNOWN'),
    ],
)
def test_google_api_errors_have_safe_recovery_fields(
    contract_api, status, code
):
    """Preserve API status without exposing response bodies to the client."""
    request = contract_api.documents.return_value.batchUpdate.return_value
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
    if status < 500:  # noqa: PLR2004
        assert str(status) in data['description']
    assert data['suggested_action']
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

    monkeypatch.setattr(docs_edit, '_get_service', lambda *_args: expired())
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

    # Entity/table outputs are schema-validated in their dedicated tests.
    assert asyncio.run(names()) == {name for name, _, _ in TOOL_CASES} | {
        'docs_reopen_comment', 'docs_edit_comment',
        'docs_delete_comment_reply',
        'docs_get_entity', 'docs_create_dropdown_definition',
        'docs_select_dropdown',
        'docs_tables_list', 'docs_table_read',
        'docs_table_snapshot', 'docs_table_patch', 'docs_table_format',
        'docs_table_structure',
    }


@pytest.mark.parametrize('name', ['docs_create', 'docs_delete_comment'])
def test_api_errors_remain_mcp_errors(contract_api, name):
    """API exceptions do not become typed success receipts."""
    if name == 'docs_create':
        request = contract_api.documents.return_value.create.return_value
        arguments = {'title': 'Created'}
    else:
        request = contract_api.documents.return_value.batchUpdate.return_value
        arguments = {'doc_id': 'example', 'comment_id': 'comment-id'}
    request.execute.side_effect = RuntimeError('Simulated Google API failure')

    _, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error is True
    assert response.structured_content['code'] == 'INTERNAL_ERROR'


def test_obsolete_comment_options_are_removed(contract_api):
    """Native anchoring does not accept a legacy bookmark workaround."""
    _, response = call_tool('docs_add_comment', {
        'doc_id': 'example', 'anchor_text': 'Target phrase',
        'comment': 'Comment body', 'bookmark_jump': True,
    }, raise_on_error=False)
    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    contract_api.comments.return_value.create.assert_not_called()


@pytest.mark.parametrize('name', ['docs_list'])
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

    assert response.structured_content == {
        'count': 0, collection: [], 'next_page_token': None, 'has_more': False,
    }


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
@pytest.mark.usefixtures('contract_api')
def test_comment_filtering_and_defaults_survive_typed_output(
    simple_document, include_resolved,
):
    """Native status filtering preserves missing-post metadata defaults."""
    simple_document['comments'] = [
        {'commentId': 'resolved-id', 'status': 'RESOLVED'},
    ]
    _, response = call_tool('docs_read_comments', {
        'doc_id': 'example', 'include_resolved': include_resolved,
    })
    data = response.structured_content
    assert data['count'] == int(include_resolved)
    if include_resolved:
        item = data['comments'][0]
        assert item['id'] == 'resolved-id' and item['resolved']
        assert item['head_post_id'] is None and item['ranges'] == []
        assert not item['anchored'] and item['author'] == '?'
    else:
        assert data['comments'] == []


@pytest.mark.parametrize('reply', ['', 'Closing reply'])
def test_resolve_uses_reply_action_in_one_request(contract_api, reply):
    """Resolve through one native action post, including optional content."""
    _, response = call_tool('docs_resolve_comment', {
        'doc_id': 'example', 'comment_id': 'comment-id', 'reply': reply,
    })
    expected_post = {'commentAction': 'RESOLVE'}
    if reply:
        expected_post['content'] = reply
    docs = contract_api.documents.return_value
    docs.batchUpdate.assert_called_once()
    body = docs.batchUpdate.call_args.kwargs['body']
    assert body['requests'] == [{'addCommentReply': {
        'commentId': 'comment-id', 'post': expected_post,
    }}]
    assert response.is_error is False
    assert response.structured_content['resolved'] is True
    assert response.structured_content['comment_update_state'] == 'ALL_SAVED'
    assert response.structured_content['reply_id'] == 'reply-id'
    assert json.loads(response.content[0].text) == response.structured_content
    contract_api.comments.assert_not_called()
    contract_api.replies.assert_not_called()


def test_resolve_failure_does_not_return_success(contract_api):
    """A failed resolve action stays an MCP error without a success receipt."""
    request = contract_api.documents.return_value.batchUpdate.return_value
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


def test_typed_batch_input_schema_exposes_replacement_fields():
    """Expose item fields for constructing validated replacement objects."""
    async def schema():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            return next(
                tool.inputSchema for tool in tools
                if tool.name == 'docs_batch_replace'
            )

    input_schema = asyncio.run(schema())
    assert 'replacements_json' not in input_schema['properties']
    assert 'replacements' in input_schema['required']
    item_array = input_schema['properties']['replacements']
    assert item_array['type'] == 'array'
    assert item_array['minItems'] == 1
    item = item_array['items']
    assert item['type'] == 'object'
    assert item['additionalProperties'] is False
    assert {'find', 'replace'} <= set(item['required'])
    assert item['properties']['find']['minLength'] == 1
    assert item['properties']['occurrence']['minimum'] == 0
    assert item['properties']['occurrence']['default'] == 1
    assert item['properties']['regex']['default'] is False


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
        ('docs_batch_replace', {'replacements': [{'replace': 'New'}]}),
    ],
)
def test_invalid_tool_constraints_fail_before_api_access(
    contract_api, mock_docs, monkeypatch, name, arguments,
):
    """Reject invalid ranges, empty anchors, and incomplete replacements."""
    credentials = MagicMock()
    monkeypatch.setattr(docs_edit, '_load_creds', credentials)
    if name != 'docs_list':
        arguments = {'doc_id': 'example', **arguments}
    _, response = call_tool(name, arguments, raise_on_error=False)

    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    assert response.structured_content['suggested_action']
    credentials.assert_not_called()
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()
    contract_api.files.return_value.list.assert_not_called()
    contract_api.comments.return_value.create.assert_not_called()


@pytest.mark.parametrize('invalid', [
    {}, {'find': 'Introduction'},
    {'find': '', 'replace': 'X'},
    {'find': 123, 'replace': 'X'},
    {'find': 'Introduction', 'replace': None},
    {'find': 'Introduction', 'replace': 123},
    {'find': 'Introduction', 'replace': 'X', 'occurrence': -1},
    {'find': 'Introduction', 'replace': 'X', 'occurrence': True},
    {'find': 'Introduction', 'replace': 'X', 'occurrence': 1.0},
    {'find': 'Introduction', 'replace': 'X', 'occurrence': '1'},
    {'find': 'Introduction', 'replace': 'X', 'regex': 'false'},
    {'find': 'Introduction', 'replace': 'X', 'regex': 0},
    {'find': 'Introduction', 'replace': 'X', 'unknown': 'value'},
    {'find': '[', 'replace': 'X', 'regex': True},
    None, 'not an object',
])
@pytest.mark.usefixtures('contract_api')
def test_entire_batch_is_validated_before_credentials(
    mock_docs, monkeypatch, invalid,
):
    """An invalid later item prevents reads and writes for earlier items."""
    credentials = MagicMock()
    monkeypatch.setattr(docs_edit, '_load_creds', credentials)
    tool, response = call_tool('docs_batch_replace', {
        'doc_id': 'example',
        'replacements': [
            {'find': 'Introduction', 'replace': 'Changed'}, invalid,
        ],
    }, raise_on_error=False)
    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    assert response.structured_content['suggested_action']
    validate(response.structured_content, tool.outputSchema)
    credentials.assert_not_called()
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('arguments', [
    {}, {'replacements': []}, {'replacements': None},
    {'replacements': '[{"find":"Introduction","replace":"X"}]'},
    {'replacements': {'find': 'Introduction', 'replace': 'X'}},
    {'replacements_json': '[{"find":"Introduction","replace":"X"}]'},
])
@pytest.mark.usefixtures('contract_api')
def test_batch_requires_nonempty_object_array(
    mock_docs, arguments,
):
    """Reject removed inputs and empty batches without document access."""
    _, response = call_tool('docs_batch_replace', {
        'doc_id': 'example', **arguments,
    }, raise_on_error=False)
    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize(('name', 'arguments'), [
    ('docs_search_replace', {'find': '', 'replace': 'X'}),
    ('docs_search_replace', {'find': 'Introduction', 'replace': 'X',
                             'occurrence': '1'}),
    ('docs_search_replace', {'find': 'Introduction', 'replace': 'X',
                             'occurrence': False}),
    ('docs_insert_after', {'anchor': '', 'text': 'X'}),
    ('docs_add_comment', {'anchor_text': '', 'comment': 'X'}),
    ('docs_add_comment', {'anchor_text': 'Introduction', 'comment': 'X',
                          'occurrence': -1}),
    ('docs_list', {'limit': '20'}),
    ('docs_list', {'limit': True}),
    ('docs_list', {'limit': 1.5}),
])
@pytest.mark.usefixtures('contract_api')
def test_input_types_and_empty_searches_fail_before_credentials(
    mock_docs, monkeypatch, name, arguments,
):
    """Protect both insertion sides and distinguish integers from booleans."""
    credentials = MagicMock()
    monkeypatch.setattr(docs_edit, '_load_creds', credentials)
    _, response = call_tool(name, {
        **({'doc_id': 'example'} if name != 'docs_list' else {}),
        **arguments,
    }, raise_on_error=False)
    assert response.is_error
    assert response.structured_content['code'] == 'INVALID_ARGUMENT'
    credentials.assert_not_called()
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('regex', [False, True])
@pytest.mark.usefixtures('contract_api')
def test_typed_batch_allows_deletion_and_replace_all(
    mock_docs, regex,
):
    """Empty replacement text deletes every selected literal or regex match."""
    _, response = call_tool('docs_batch_replace', {
        'doc_id': 'example',
        'replacements': [{
            'find': 'Target phrase', 'replace': '',
            'occurrence': 0, 'regex': regex,
        }],
    })
    assert response.is_error is False
    expected_matches = 3
    assert response.structured_content['applied'] == expected_matches
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert len(requests) == expected_matches
    assert all('deleteContentRange' in request for request in requests)
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize(
    ('limit', 'page_size'), [(1, 1), (100, 100), (101, 100)],
)
def test_positive_listing_limit_preserves_upper_cap(
    contract_api, limit, page_size,
):
    """Accept positive integers while retaining the existing page-size cap."""
    _, response = call_tool('docs_list', {'limit': limit})
    assert response.is_error is False
    request = contract_api.files.return_value.list.call_args.kwargs
    assert request['pageSize'] == page_size


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


@pytest.mark.parametrize('name', ['docs_list'])
@pytest.mark.parametrize('has_more', [False, True])
@pytest.mark.parametrize('empty', [False, True])
def test_listing_reports_page_continuation(
    contract_api, name, has_more, empty,
):
    """Distinguish a terminal page from a page with further results."""
    if name == 'docs_list':
        request = contract_api.files.return_value.list.return_value
        arguments = {}
    else:
        request = contract_api.comments.return_value.list.return_value
        arguments = {'doc_id': 'example'}
    if empty:
        request.execute.return_value = {}
    if has_more:
        request.execute.return_value['nextPageToken'] = 'next-page'

    _, response = call_tool(name, arguments)

    data = response.structured_content
    assert data['has_more'] is has_more
    assert data['next_page_token'] == ('next-page' if has_more else None)
    assert data['count'] == (0 if empty else 1)


@pytest.mark.parametrize('name', ['docs_list'])
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


@pytest.mark.usefixtures('contract_api')
def test_native_comment_filtering_precedes_output_pagination(
    simple_document,
):
    """Client-side native pagination filters resolved threads before paging."""
    simple_document['comments'] = [
        comment_thread('resolved', resolved=True), comment_thread('visible'),
    ]
    _, response = call_tool('docs_read_comments', {
        'doc_id': 'example', 'limit': 1,
    })
    data = response.structured_content
    assert [t['id'] for t in data['comments']] == ['visible']
    assert data['count'] == 1
    assert not data['has_more']


@pytest.mark.parametrize(
    ('name', 'include_resolved', 'shared_drive'),
    [('docs_list', False, False), ('docs_list', False, True)],
)
def test_two_page_listing_preserves_request_options(
    contract_api, monkeypatch, *, name, include_resolved, shared_drive,
):
    """Reach page two with the same filters and shared-drive options."""
    monkeypatch.setenv('GOOGLE_DOCS_USE_DRIVE', 'false')
    monkeypatch.delenv('GOOGLE_DOCS_DRIVE_ID', raising=False)
    if shared_drive:
        monkeypatch.setenv('GOOGLE_DOCS_DRIVE_ID', 'shared-drive')
    if name == 'docs_list':
        resource = contract_api.files.return_value
        arguments = {'query': 'Example', 'limit': 150}
        collection, key = 'documents', 'files'
        first = {'id': 'first', 'name': 'First'}
        second = {'id': 'second', 'name': 'Second'}
    else:
        resource = contract_api.comments.return_value
        arguments = {
            'doc_id': 'example', 'include_resolved': include_resolved,
        }
        collection = key = 'comments'
        first = {'id': 'first', 'resolved': True}
        second = {'id': 'second', 'content': 'Visible comment'}

    def page(**kwargs):
        token = kwargs['pageToken']
        assert token in {None, 'next-page'}
        response = (
            {key: [first], 'nextPageToken': 'next-page'}
            if token is None else {key: [second]}
        )
        return MagicMock(execute=MagicMock(return_value=response))

    resource.list.side_effect = page
    tool, first_result = call_tool(name, arguments)
    first_data = first_result.structured_content
    _, second_result = call_tool(name, {
        **arguments, 'page_token': first_data['next_page_token'],
    })
    second_data = second_result.structured_content
    for result in [first_result, second_result]:
        assert result.is_error is False
        validate(result.structured_content, tool.outputSchema)
    assert first_data['has_more'] is True
    assert second_data['has_more'] is False
    assert second_data['next_page_token'] is None
    assert [item['id'] for item in second_data[collection]] == ['second']
    expected_first = (
        [] if name == 'docs_read_comments' and not include_resolved
        else ['first']
    )
    assert [item['id'] for item in first_data[collection]] == expected_first
    assert first_data['count'] == len(expected_first)
    assert second_data['count'] == 1
    first_request, second_request = (
        dict(call.kwargs) for call in resource.list.call_args_list
    )
    assert first_request.pop('pageToken') is None
    assert second_request.pop('pageToken') == 'next-page'
    assert first_request == second_request
    assert first_request['pageSize'] == EXPECTED_LIST_PAGE_SIZE
    assert 'nextPageToken' in first_request['fields']
    if name == 'docs_list':
        assert 'fullText contains "Example"' in first_request['q']
        assert first_request['orderBy'] == 'modifiedTime desc'
        if shared_drive:
            assert first_request['driveId'] == 'shared-drive'
            assert first_request['corpora'] == 'drive'
            assert first_request['supportsAllDrives'] is True
            assert first_request['includeItemsFromAllDrives'] is True
    else:
        assert first_request['fileId'] == 'example'


@pytest.mark.parametrize('name', ['docs_list'])
def test_invalid_listing_token_has_restart_guidance(contract_api, name):
    """A rejected cursor remains a structured error with recovery guidance."""
    resource = (
        contract_api.files if name == 'docs_list' else contract_api.comments
    ).return_value
    resource.list.return_value.execute.side_effect = HttpError(
        Response({'status': '400'}), b'{"error":{"message":"private token"}}',
    )
    arguments = {'page_token': 'expired-token'}
    if name == 'docs_read_comments':
        arguments['doc_id'] = 'example'
    tool, result = call_tool(name, arguments, raise_on_error=False)
    data = result.structured_content
    assert result.is_error is True
    assert data['code'] == 'INVALID_ARGUMENT'
    assert 'omit page_token' in data['suggested_action']
    assert 'deduplicate' in data['suggested_action']
    assert 'private token' not in json.dumps(data)
    validate(data, tool.outputSchema)


@pytest.mark.parametrize(
    ('name', 'read_only'),
    [
        ('docs_get_tree', True), ('docs_read', True),
        ('docs_tabs_list', True),
        ('docs_tables_list', True), ('docs_table_read', True),
        ('docs_table_snapshot', True),
        ('docs_table_patch', False),
        ('docs_table_format', False),
        ('docs_table_structure', False),
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
        'docs_table_patch', 'docs_table_format', 'docs_table_structure',
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
    assert data['anchor_char_count'] == len(anchor + '\n')
    assert data['anchor_preview_truncated'] is True
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('length', [80, 81])
@pytest.mark.usefixtures('contract_api')
def test_replacement_preview_and_match_completeness(
    simple_document, length,
):
    """Keep complete counts even when the text preview is truncated."""
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
    assert data['occurrences_found_complete'] is True
    assert data['occurrences_found'] == 1
    assert data['occurrences_changed'] is None
    assert json.loads(response.content[0].text) == data
    validate(data, tool.outputSchema)


@pytest.mark.parametrize('occurrence', [1, 2])
@pytest.mark.parametrize('heading_id', [None, 'parent'])
@pytest.mark.usefixtures('contract_api')
def test_replacement_scope_and_count_metadata(occurrence, heading_id):
    """Expose total counts while changing only the selected occurrence."""
    _, response = call_tool('docs_search_replace', {
        'doc_id': 'example', 'find': 'Target phrase', 'replace': 'New',
        'heading_id': heading_id, 'occurrence': occurrence,
    })
    data = response.structured_content
    assert data['document_id'] == 'example'
    assert data['scope'] == (
        'document' if heading_id is None else 'heading_subtree'
    )
    assert data['heading_id'] == heading_id
    assert data['applied'] == 1
    assert data['occurrences_found_complete'] is True
    assert data['occurrences_found'] == (3 if heading_id is None else 2)


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
    mock_docs.get.assert_called_once()


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
        'replacements': [
            {'find': original, 'replace': replacement}
            for original in originals
        ],
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
