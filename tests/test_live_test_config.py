"""Verify live-test opt-in and target selection without accessing Google."""

import pytest

from gdocs_scope_mcp import docs_edit


@pytest.fixture(autouse=True)
def no_google_access(monkeypatch):
    """Reject any attempt to construct a Google client in config checks."""
    def forbidden(*_args, **_kwargs):
        pytest.fail('Configuration checks must not access Google.')

    monkeypatch.setattr(docs_edit, '_get_service', forbidden)


@pytest.mark.parametrize('legacy_flag', [None, '1'])
def test_missing_document_skips_live_tests(monkeypatch, request, legacy_flag):
    """The old flag cannot enable tests or choose a fallback document."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', raising=False)
    if legacy_flag is not None:
        monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES', legacy_flag)
    else:
        monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES', raising=False)
    with pytest.raises(pytest.skip.Exception, match='LIVE_TEST_DOC'):
        request.getfixturevalue('live_test_doc')


@pytest.mark.parametrize('doc_id', [
    'test-document_42', 'another_document-123',
])
def test_explicit_document_is_used(monkeypatch, request, doc_id):
    """Use the configured target verbatim without a separate enable flag."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', doc_id)
    monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_DRIVE_IMAGES', raising=False)
    assert request.getfixturevalue('live_test_doc') == doc_id


@pytest.mark.parametrize('doc_id', [
    '', ' ', ' test-document', 'test-document\n',
    'https://docs.google.com/document/d/test-document/edit',
])
def test_invalid_document_fails_before_google_access(
    monkeypatch, request, doc_id,
):
    """Catch an empty target, URL or stray whitespace before live writes."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', doc_id)
    with pytest.raises(pytest.fail.Exception,
                       match='must contain a Google Doc ID'):
        request.getfixturevalue('live_test_doc')
