"""Exercise per-test fixture ordering and cleanup without Google access."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gdocs_scope_mcp.google_api import clients

from .live_document_state import DOC_MIME, LiveDocuments

pytest_plugins = ['pytester']


@pytest.mark.parametrize('keep', [False, True])
@pytest.mark.parametrize('outcome', [
    'success', 'test_failure', 'setup_failure', 'teardown_failure',
    'creation_failure', 'interruption', 'missing', 'invalid',
])
def test_pytest_document_lifecycle(pytester, monkeypatch, outcome, keep):
    """Verify separate IDs and cleanup across all pytest phases."""
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', 'folder')
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_KEEP_ON_FAILURE', str(int(keep)))
    if outcome == 'missing':
        monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER')
    if outcome == 'invalid':
        monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', 'https://bad')
    pytester.makeini('[pytest]\nmarkers = live: live Google tests')
    pytester.makeconftest("""
from pathlib import Path
import uuid
import pytest
import tests.conftest as fixtures
from tests.conftest import (
    live_document_guard, live_test_folder, live_document_factory,
    live_test_doc, pytest_sessionfinish,
    pytest_runtest_makereport, pytest_runtest_teardown, pytest_runtest_call,
)

def event(text):
    with Path('events').open('a') as stream:
        stream.write(text + '\\n')

class Documents:
    def __init__(self, folder, root, connect, *, keep_on_failure):
        self.keep = keep_on_failure
        self.identity = uuid.uuid4().hex
    def save(self):
        pass
    def create(self):
        event('create:' + self.identity)
        if OUTCOME == 'creation_failure':
            raise RuntimeError('Injected creation failure')
        return {'id': self.identity}
    def finish(self, *, failed):
        prefix = 'retain:' if failed and self.keep else 'trash:'
        event(prefix + self.identity)

fixtures.LiveDocuments = Documents

@pytest.fixture
def isolated_mcp():
    pass

@pytest.fixture
def dependent(live_test_doc):
    if OUTCOME == 'setup_failure':
        raise RuntimeError('Injected setup failure')
    yield
    event('dependent-teardown')
    if OUTCOME == 'teardown_failure':
        raise RuntimeError('Injected teardown failure')
""".replace('OUTCOME', repr(outcome)))
    pytester.makepyfile("""
import pytest

@pytest.mark.live
@pytest.mark.parametrize('number', [1, 2])
def test_document(number, dependent, live_test_doc):
    from conftest import event
    event('test:' + live_test_doc)
    if OUTCOME == 'interruption':
        raise KeyboardInterrupt
    assert OUTCOME != 'test_failure'
""".replace('OUTCOME', repr(outcome)))
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1]))
    result = pytester.runpytest_subprocess('-q')
    path = pytester.path / 'events'
    events = path.read_text().splitlines() if path.exists() else []
    if outcome == 'missing':
        result.assert_outcomes(skipped=2)
        assert not events
        return
    if outcome == 'invalid':
        result.assert_outcomes(errors=2)
        assert not events
        return
    if outcome == 'interruption':
        assert result.ret == pytest.ExitCode.INTERRUPTED
    elif outcome in {'creation_failure', 'setup_failure'}:
        result.assert_outcomes(errors=2)
    elif outcome == 'teardown_failure':
        result.assert_outcomes(passed=2, errors=2)
    elif outcome == 'test_failure':
        result.assert_outcomes(failed=2)
    else:
        result.assert_outcomes(passed=2)
    created = [e.split(':')[1] for e in events if e.startswith('create:')]
    assert len(created) == (1 if outcome == 'interruption' else 2)
    assert len(set(created)) == len(created)
    retain = keep and outcome != 'success'
    prefix = 'retain:' if retain else 'trash:'
    assert [e for e in events if e.startswith(prefix)] == [
        prefix + identity for identity in created
    ]


@pytest.fixture
def document_backend(monkeypatch, tmp_path):
    """Model confirmed creation and independent Drive cleanup failures."""
    drive = MagicMock()
    created = {'id': 'new-id', 'title': ''}
    client = MagicMock()
    client.partial = False

    async def call(_tool, arguments, **_kwargs):
        created['title'] = arguments['title']
        return SimpleNamespace(
            is_error=client.partial,
            structured_content=({'created_document': dict(created)}
                                if client.partial else dict(created)),
        )

    client.call_tool = AsyncMock(side_effect=call)

    @asynccontextmanager
    async def connect(_log):
        yield client, {'pid': 123}

    def get(**arguments):
        if arguments['fileId'] == 'folder':
            return {'mimeType': 'application/vnd.google-apps.folder',
                    'capabilities': {'canAddChildren': True}}
        if arguments['fields'] == 'parents':
            return {'parents': ['root']}
        if arguments['fields'] == 'trashed':
            return {'trashed': True}
        return {'id': created['id'], 'name': created['title'],
                'mimeType': DOC_MIME}

    drive.get.side_effect = lambda **kwargs: SimpleNamespace(
        execute=lambda: get(**kwargs),
    )
    drive.update.return_value.execute.side_effect = lambda: {
        'id': created['id'], 'name': created['title'],
        'mimeType': DOC_MIME, 'parents': ['folder'],
    }
    service = MagicMock()
    service.files.return_value = drive
    monkeypatch.setattr(clients, 'get_service', lambda *_a, **_k: service)
    return LiveDocuments('folder', tmp_path, connect), drive, client


@pytest.mark.parametrize('failure', ['none', 'partial', 'move'])
def test_confirmed_creation_cleanup(document_backend, failure):
    """Trash known IDs even when creation initialization or placement fails."""
    documents, drive, client = document_backend
    if failure == 'partial':
        client.partial = True
    if failure == 'move':
        drive.update.return_value.execute.side_effect = RuntimeError('move')
    if failure == 'none':
        documents.create(via_mcp=True)
        move = drive.update.call_args.kwargs
        assert move['addParents'] == 'folder'
        assert move['removeParents'] == 'root'
    else:
        with pytest.raises((AssertionError, RuntimeError)):
            documents.create(via_mcp=True)
    drive.update.return_value.execute.side_effect = None
    documents.finish(failed=failure != 'none')
    assert documents.documents[0]['status'] == 'trashed'
    assert drive.update.call_args.kwargs['body'] == {'trashed': True}


def test_cleanup_identity_mismatch_never_trashes(document_backend):
    """Reject a mismatched document rather than deleting an unrelated file."""
    documents, drive, _client = document_backend
    documents.create(via_mcp=True)
    drive.update.reset_mock()
    drive.get.side_effect = None
    drive.get.return_value.execute.return_value = {'id': 'unrelated'}
    with pytest.raises(AssertionError):
        documents.finish(failed=False)
    drive.update.assert_not_called()
    assert documents.documents[0]['status'] == 'cleanup_failed'


def test_create_directly_in_folder(document_backend):
    """Use one Drive creation request with the parent folder already set."""
    documents, drive, client = document_backend

    def create(**arguments):
        body = arguments['body']
        return SimpleNamespace(execute=lambda: {
            'id': 'direct-id', 'name': body['name'],
            'mimeType': body['mimeType'], 'parents': body['parents'],
        })

    drive.create.side_effect = create
    created = documents.create()
    assert created['id'] == 'direct-id'
    assert drive.create.call_args.kwargs['body']['parents'] == ['folder']
    drive.update.assert_not_called()
    client.call_tool.assert_not_called()
