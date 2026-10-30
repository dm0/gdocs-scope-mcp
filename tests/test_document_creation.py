"""Preserve confirmed creation across rejected and ambiguous initial writes."""

# Imported fixture names intentionally match pytest arguments.
# ruff: noqa: F811
import json
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response
from jsonschema import validate

from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import clients, files

from .test_mcp_output_contracts import call_tool, contract_api  # noqa: F401

IDENTITY = {
    'id': 'created-doc', 'title': 'Created title',
    'webViewLink': 'https://docs.google.com/document/d/created-doc/edit',
}
PRIVATE_TEXT = 'PRIVATE_INITIAL_CONTENT'
PRIVATE_ERROR = 'PRIVATE_ERROR_BODY_TOKEN'
FAILURE_CASES = [
    (400, 'rejected'), (401, 'rejected'), (403, 'rejected'),
    (404, 'rejected'), (409, 'rejected'), (412, 'rejected'),
    (429, 'rejected'), (408, 'unknown'), (500, 'unknown'),
    (502, 'unknown'), (503, 'unknown'), ('timeout', 'unknown'),
    ('internal', 'unknown'), ('refresh', 'unknown'),
]


def failure(kind):
    """Include sensitive diagnostics that must not reach MCP output."""
    if isinstance(kind, int):
        return HttpError(
            Response({'status': kind}),
            json.dumps({'error': {'message': PRIVATE_ERROR}}).encode(),
        )
    error_type = {
        'timeout': TimeoutError, 'internal': RuntimeError,
        'refresh': RefreshError,
    }[kind]
    return error_type(PRIVATE_ERROR)


@pytest.fixture
def creation_api(monkeypatch):
    """Replace only the client seam and retain request-count assertions."""
    api = MagicMock()
    api.documents.return_value.create.return_value.execute.return_value = {
        'documentId': IDENTITY['id'],
    }
    monkeypatch.setattr(clients, 'get_service', MagicMock(return_value=api))
    return api.documents.return_value


@pytest.mark.parametrize(('kind', 'outcome'), FAILURE_CASES)
def test_backend_retains_created_document(creation_api, kind, outcome):
    """Never replay creation or an unconfirmed initial write."""
    error = failure(kind)
    creation_api.batchUpdate.return_value.execute.side_effect = error

    with pytest.raises(ToolFailureError) as caught:
        files.create_document(IDENTITY['title'], PRIVATE_TEXT)

    result = caught.value.failure.model_dump()
    assert result['created_document'] == IDENTITY
    assert result['initial_content'] == outcome
    assert result['code'] == (
        'WRITE_OUTCOME_UNKNOWN' if outcome == 'unknown' else 'PARTIAL_WRITE'
    )
    assert result['committed_batches'] == 0
    assert caught.value.__cause__ is error
    creation_api.create.assert_called_once_with(
        body={'title': IDENTITY['title']},
    )
    creation_api.create.return_value.execute.assert_called_once_with()
    creation_api.batchUpdate.return_value.execute.assert_called_once_with()
    assert PRIVATE_TEXT not in json.dumps(result)
    assert PRIVATE_ERROR not in json.dumps(result)


def test_request_construction_failure_is_not_attempted(creation_api):
    """A local error before execute still retains the created identity."""
    creation_api.batchUpdate.side_effect = RuntimeError(PRIVATE_ERROR)
    with pytest.raises(ToolFailureError) as caught:
        files.create_document(IDENTITY['title'], PRIVATE_TEXT)
    result = caught.value.failure
    assert result.initial_content == 'not_attempted'
    assert result.code == 'PARTIAL_WRITE'
    assert result.created_document.model_dump() == IDENTITY
    creation_api.batchUpdate.return_value.execute.assert_not_called()


@pytest.mark.parametrize('kind', [403, 503, 'timeout'])
def test_backend_creation_failure_has_no_identity(creation_api, kind):
    """An initial create failure cannot claim a confirmed document ID."""
    error = failure(kind)
    creation_api.create.return_value.execute.side_effect = error
    with pytest.raises(type(error)) as caught:
        files.create_document(IDENTITY['title'], PRIVATE_TEXT)
    assert caught.value is error
    creation_api.batchUpdate.assert_not_called()
    creation_api.create.return_value.execute.assert_called_once_with()


@pytest.mark.parametrize('text', ['', PRIVATE_TEXT])
def test_backend_creation_success_is_unchanged(creation_api, text):
    """Keep the successful object and literal initial insertion request."""
    result = files.create_document(IDENTITY['title'], text)
    assert result.model_dump() == IDENTITY
    if text:
        creation_api.batchUpdate.assert_called_once_with(
            documentId=IDENTITY['id'],
            body={'requests': [{'insertText': {
                'location': {'index': 1}, 'text': text,
            }}]},
        )
    else:
        creation_api.batchUpdate.assert_not_called()


@pytest.mark.parametrize(('kind', 'outcome'), FAILURE_CASES)
def test_mcp_partial_creation_error(contract_api, kind, outcome):
    """Expose identity and recovery guidance in both MCP error channels."""
    docs = contract_api.documents.return_value
    docs.batchUpdate.return_value.execute.side_effect = failure(kind)
    tool, result = call_tool('docs_create', {
        'title': IDENTITY['title'], 'initial_text': PRIVATE_TEXT,
    }, raise_on_error=False)
    assert result.is_error
    data = result.structured_content
    assert data['created_document'] == IDENTITY
    assert data['initial_content'] == outcome
    assert data['code'] == (
        'WRITE_OUTCOME_UNKNOWN' if outcome == 'unknown' else 'PARTIAL_WRITE'
    )
    assert data['committed_batches'] == 0
    assert 'Do not repeat docs_create' in data['suggested_action']
    assert json.loads(result.content[0].text) == data
    validate(data, tool.outputSchema)
    assert PRIVATE_TEXT not in result.content[0].text
    assert PRIVATE_ERROR not in result.content[0].text
    docs.create.return_value.execute.assert_called_once_with()
    docs.batchUpdate.return_value.execute.assert_called_once_with()


@pytest.mark.parametrize('kind', [403, 503, 'timeout'])
def test_mcp_creation_failure_stays_generic(contract_api, kind):
    """Do not invent identity when the create response was not received."""
    docs = contract_api.documents.return_value
    docs.create.return_value.execute.side_effect = failure(kind)
    tool, result = call_tool('docs_create', {
        'title': IDENTITY['title'], 'initial_text': PRIVATE_TEXT,
    }, raise_on_error=False)
    assert result.is_error
    assert 'created_document' not in result.structured_content
    validate(result.structured_content, tool.outputSchema)
    docs.batchUpdate.assert_not_called()


def test_mcp_request_construction_failure(contract_api):
    """Preserve the not-attempted outcome through FastMCP wrapping."""
    docs = contract_api.documents.return_value
    docs.batchUpdate.side_effect = RuntimeError(PRIVATE_ERROR)
    tool, result = call_tool('docs_create', {
        'title': IDENTITY['title'], 'initial_text': PRIVATE_TEXT,
    }, raise_on_error=False)
    assert result.is_error
    assert result.structured_content['initial_content'] == 'not_attempted'
    assert result.structured_content['created_document'] == IDENTITY
    validate(result.structured_content, tool.outputSchema)


@pytest.mark.parametrize('text', ['', PRIVATE_TEXT])
def test_mcp_creation_success_is_unchanged(contract_api, text):
    """Keep the ordinary success contract without new partial fields."""
    tool, result = call_tool('docs_create', {
        'title': IDENTITY['title'], 'initial_text': text,
    })
    assert not result.is_error
    assert result.structured_content == IDENTITY
    validate(result.structured_content, tool.outputSchema)
    if not text:
        contract_api.documents.return_value.batchUpdate.assert_not_called()
