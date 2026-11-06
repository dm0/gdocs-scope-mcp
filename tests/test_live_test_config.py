"""Verify live-test opt-in without accessing Google."""

import pytest

from gdocs_scope_mcp.google_api import clients


@pytest.fixture(autouse=True)
def no_google_access(monkeypatch):
    """Reject any Google access from configuration checks."""
    def forbidden(*_args, **_kwargs):
        pytest.fail('Configuration checks must not access Google.')

    monkeypatch.setattr(clients, 'get_service', forbidden)


def test_missing_folder_skips_even_with_old_target(monkeypatch, request):
    """A permanent document and legacy flags cannot enable live writes."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', raising=False)
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', 'old-document')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_CREATE', '1')
    with pytest.raises(pytest.skip.Exception, match='LIVE_TEST_FOLDER'):
        request.getfixturevalue('live_test_doc')


def test_explicit_folder_is_used(monkeypatch, request):
    """Accept a raw folder ID without accessing Google."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', 'folder_42-a')
    assert request.getfixturevalue('live_test_folder') == 'folder_42-a'


@pytest.mark.parametrize('folder', ['', ' ', ' folder', 'folder\n',
                                    'https://drive.google.com/drive/folders/id'])
def test_invalid_folder_fails_before_google(monkeypatch, request, folder):
    """Reject URLs and whitespace before document creation."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', folder)
    with pytest.raises(pytest.fail.Exception, match='Google folder ID'):
        request.getfixturevalue('live_test_doc')


def test_invalid_retention_flag_fails_before_google(monkeypatch, request):
    """Prevent typos from silently discarding failure evidence."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', 'folder')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_KEEP_ON_FAILURE', 'yes')
    with pytest.raises(pytest.fail.Exception, match='must be 0 or 1'):
        request.getfixturevalue('live_test_doc')
