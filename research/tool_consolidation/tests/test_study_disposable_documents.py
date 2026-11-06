"""Check independent research-document ownership without Google access."""

import asyncio
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from .test_study_corpus import execution, load_research, scenarios


@pytest.fixture
def native(monkeypatch):
    """Load the integration with explicit research dependencies."""
    monkeypatch.setitem(sys.modules, 'study_execution', execution)
    return load_research('study_live')


@pytest.mark.parametrize('failed', [False, True])
def test_parallel_document_ownership_and_failure_cleanup(
    native, monkeypatch, tmp_path, failed,
):
    """Three creations must overlap and cleanup must use only owned IDs."""
    barrier = threading.Barrier(3, timeout=10)
    records = []

    class Documents:
        """Record independent factory ownership and verified disposal."""

        def __init__(self, folder, output, _connect, **_kwargs):
            assert folder == native.AUTHORIZED_FOLDER
            self.identifier = output.name
            self.documents = []

        def create(self):
            barrier.wait()
            self.documents.append({'id': self.identifier, 'status': 'placed'})
            return {'id': self.identifier}

        def finish(self, *, failed):
            records.append((self.identifier, failed))
            self.documents[0]['status'] = 'trashed'

    class Transport:
        """Retain each child environment for scope assertions."""

        def __init__(self, **kwargs):
            self.env = kwargs['env']

    class Client:
        """Model only STDIO lifecycle and process identity discovery."""

        def __init__(self, transport):
            self.transport = transport

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def call_tool(self, name, _args):
            assert name == 'server_info'
            return SimpleNamespace(structured_content={
                'pid': -123, 'package_path': str(
                    native.ROOT / 'src/gdocs_scope_mcp'),
            })

    async def seed(backend, _fixture):
        assert backend.document_id == (
            backend.client.transport.env['GDOCS_SCOPE_MCP_LIVE_TEST_DOC'])
        await asyncio.sleep(0)

    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER',
                       native.AUTHORIZED_FOLDER)
    monkeypatch.setattr(native.DOCUMENTS, 'LiveDocuments', Documents)
    monkeypatch.setattr(native, 'StdioTransport', Transport)
    monkeypatch.setattr(native, 'Client', Client)
    monkeypatch.setattr(native.LiveBackend, 'seed', seed)

    async def job(index):
        path = tmp_path / str(index)
        try:
            async with native.live_backend(
                scenarios.PILOT[0], 'baseline', path, reference_mode=True,
            ) as (backend, _identity):
                assert backend.document_id == str(index)
                if failed:
                    raise RuntimeError('Injected actor failure')  # noqa: TRY301
        except RuntimeError as error:
            assert failed and str(error) == 'Injected actor failure'
        report = json.loads((path / 'live-cleanup.json').read_text())
        assert report['documents'] == [{'id': str(index), 'status': 'trashed'}]
        assert report['processes_reaped']

    async def run():
        await asyncio.gather(*(job(i) for i in range(3)))
    asyncio.run(run())
    assert sorted(records) == [(str(i), failed) for i in range(3)]


def test_no_permanent_document_fallback(native, monkeypatch, tmp_path):
    """A legacy Doc ID alone must never permit creation or live execution."""
    monkeypatch.delenv('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER', raising=False)
    monkeypatch.setenv('GDOCS_SCOPE_MCP_LIVE_TEST_DOC', 'legacy-doc')

    async def run():
        with pytest.raises(ValueError, match='authorized test folder'):
            async with native.live_backend(
                scenarios.PILOT[0], 'baseline', tmp_path,
                reference_mode=True,
            ):
                pytest.fail('A permanent document was reused')
    asyncio.run(run())
