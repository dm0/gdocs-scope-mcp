"""Keep search text inside one Drive literal without changing list options."""

# Imported fixture names intentionally match pytest arguments.
# ruff: noqa: F811
from unittest.mock import MagicMock

import pytest

from gdocs_scope_mcp.google_api import clients, files

from .test_mcp_output_contracts import call_tool, contract_api  # noqa: F401

BASE_QUERY = (
    'mimeType="application/vnd.google-apps.document" and trashed=false'
)
SEARCH_CASES = [
    ('', ''),
    ('board deck', " and fullText contains 'board deck'"),
    ('"exact phrase"', " and fullText contains '\"exact phrase\"'"),
    ("quinn's paper", " and fullText contains 'quinn\\'s paper'"),
    ('paper\\essay\\', " and fullText contains 'paper\\\\essay\\\\'"),
    ("quinn\\'s", " and fullText contains 'quinn\\\\\\'s'"),
    ('café 🦷', " and fullText contains 'café 🦷'"),
    ('   ', " and fullText contains '   '"),
    ("' or trashed=true or name contains '",
     " and fullText contains '\\' or trashed=true or name contains \\''"),
    ('" or mimeType != "application/vnd.google-apps.document',
     " and fullText contains '\" or mimeType != "
     "\"application/vnd.google-apps.document'"),
]


@pytest.mark.parametrize(('query', 'clause'), SEARCH_CASES)
def test_backend_search_literal(query, clause, monkeypatch):
    """Verify the wire expression and unchanged retrieval options."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_USE_DRIVE', 'false')
    monkeypatch.delenv('GDOCS_SCOPE_MCP_DRIVE_ID', raising=False)
    api = MagicMock()
    api.files.return_value.list.return_value.execute.return_value = {
        'files': [], 'nextPageToken': 'next',
    }
    service = MagicMock(return_value=api)
    monkeypatch.setattr(clients, 'get_service', service)

    result = files.list_documents(query, limit=150, page_token='previous')

    service.assert_called_once_with('drive', 'v3', cached=False)
    api.files.return_value.list.assert_called_once_with(
        q=BASE_QUERY + clause, pageSize=100,
        fields='nextPageToken,files(id, name, modifiedTime, webViewLink)',
        orderBy='modifiedTime desc', pageToken='previous',
    )
    assert result.count == 0
    assert result.next_page_token == 'next'


@pytest.mark.parametrize(('query', 'clause'), SEARCH_CASES)
def test_mcp_search_literal(contract_api, query, clause, monkeypatch):
    """Keep MCP input in one search value, including expression-like text."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_USE_DRIVE', 'false')
    monkeypatch.delenv('GDOCS_SCOPE_MCP_DRIVE_ID', raising=False)

    _, result = call_tool('docs_list', {'query': query, 'limit': 1})

    assert not result.is_error
    request = contract_api.files.return_value.list.call_args.kwargs
    assert request['q'] == BASE_QUERY + clause
    assert request['pageSize'] == 1
