"""Verify access validation, bounded snapshots and write invalidation."""

# ruff: noqa: D103, PLR2004

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from gdocs_scope_mcp import document_cache
from gdocs_scope_mcp.document_cache import CachedService, SnapshotCache
from gdocs_scope_mcp.settings import Settings


@pytest.fixture
def setup_cache(monkeypatch, simple_document):
    """Provide deterministic native requests with observable full downloads."""
    clock = [0.0]
    store = SnapshotCache(clock=lambda: clock[0])
    monkeypatch.setattr(document_cache, 'cache', store)
    settings = Settings()
    monkeypatch.setattr(document_cache, 'get_settings', lambda: settings)
    state = SimpleNamespace(
        document=simple_document,
        calls=[],
        error=None,
        write_error=None,
        clock=clock,
        store=store,
        settings=settings,
    )

    class Documents:
        """Emulate the discovery request's mutable URI and delayed execute."""

        def get(self, **kwargs):
            request = SimpleNamespace(
                uri='https://docs.test/?' + urlencode(kwargs)
            )

            def execute():
                state.calls.append(kwargs)
                if state.error:
                    raise state.error
                if 'fields' in kwargs:
                    return {'revisionId': state.document.get('revisionId')}
                return deepcopy(state.document)

            request.execute = execute
            return request

        def batchUpdate(self, **_kwargs):  # noqa: N802
            def execute():
                if state.write_error:
                    raise state.write_error
                return {'writeControl': {'requiredRevisionId': 'next'}}

            return SimpleNamespace(execute=execute, uri='https://docs.test/')

    service = CachedService(SimpleNamespace(documents=Documents), 'account')
    state.service = service
    state.read = lambda **kwargs: (
        service.documents()
        .get(
            documentId=kwargs.pop('documentId', 'example'),
            includeTabsContent=True,
            **kwargs,
        )
        .execute()
    )
    return state


def full_reads(state):
    """Count actual full-response requests separately from revision checks."""
    return sum('fields' not in call for call in state.calls)


def test_hit_validates_access_and_isolates_mutations(setup_cache):
    state = setup_cache
    first = state.read()
    first['body']['content'].clear()
    second = state.read()
    assert second['body']['content']
    second['body']['content'].clear()
    assert state.read()['body']['content']
    assert full_reads(state) == 1
    assert [call.get('fields') for call in state.calls] == [
        None,
        'revisionId',
        'revisionId',
    ]


def test_changed_revision_uses_revision_from_full_fetch(setup_cache):
    state = setup_cache
    state.read()
    state.document['revisionId'] = 'changed'
    assert state.read()['revisionId'] == 'changed'
    assert state.read()['revisionId'] == 'changed'
    assert full_reads(state) == 2


@pytest.mark.parametrize('missing', [None, ''])
def test_missing_revision_never_cached(setup_cache, missing):
    state = setup_cache
    state.document['revisionId'] = missing
    state.read()
    state.read()
    assert full_reads(state) == 2
    assert not state.store.entries


def test_lost_revision_evicts_previous_snapshot(setup_cache):
    state = setup_cache
    state.read()
    del state.document['revisionId']
    state.read()
    assert not state.store.entries


@pytest.mark.parametrize(
    'error', [PermissionError('revoked'), OSError('timeout')]
)
def test_check_error_never_serves_stale_or_keeps_entry(setup_cache, error):
    state = setup_cache
    state.read()
    state.error = error
    with pytest.raises(type(error)):
        state.read()
    assert not state.store.entries
    state.error = None
    state.read()
    assert full_reads(state) == 2


def test_expiration_and_no_sliding_lifetime(setup_cache):
    state = setup_cache
    state.read()
    state.clock[0] = state.settings.document_cache_ttl_seconds - 1
    state.read()
    assert full_reads(state) == 1
    state.clock[0] += 1
    state.read()
    assert full_reads(state) == 2
    assert state.calls[-1].get('fields') is None


def test_options_document_and_account_isolation(setup_cache):
    state = setup_cache
    state.read(suggestionsViewMode='SUGGESTIONS_INLINE')
    state.read(suggestionsViewMode='PREVIEW_WITHOUT_SUGGESTIONS')
    state.read(documentId='other')
    other = CachedService(state.service.service, 'another-account')
    other.documents().get(
        documentId='example', includeTabsContent=True
    ).execute()
    assert full_reads(state) == 4
    assert len(state.store.entries) == 4


def test_bounded_lru_and_payload_budget(setup_cache):
    state = setup_cache
    state.settings = state.settings.model_copy(
        update={'document_cache_max_entries': 2}
    )
    for doc_id in ['first', 'second', 'first', 'third']:
        state.store.read(
            'owner',
            doc_id,
            (),
            fetch=lambda: state.document,
            check=lambda: state.document,
            settings=state.settings,
        )
    assert {key[1] for key in state.store.entries} == {'first', 'third'}
    assert state.store.size == sum(
        len(e.payload) for e in state.store.entries.values()
    )
    tiny = state.settings.model_copy(update={'document_cache_max_bytes': 1})
    fresh = SnapshotCache()
    fresh.read(
        'owner',
        'large',
        (),
        fetch=lambda: state.document,
        check=dict,
        settings=tiny,
    )
    assert not fresh.entries
    assert fresh.size == 0


@pytest.mark.parametrize(
    'error', [None, OSError('unknown write outcome'), ValueError('rejected')]
)
def test_every_write_attempt_invalidates_all_read_options(setup_cache, error):
    state = setup_cache
    state.read(suggestionsViewMode='SUGGESTIONS_INLINE')
    state.read(suggestionsViewMode='PREVIEW_WITHOUT_SUGGESTIONS')
    state.write_error = error
    request = state.service.documents().batchUpdate(
        documentId='example', body={}
    )
    if error:
        with pytest.raises(type(error)):
            request.execute()
    else:
        request.execute()
    assert not state.store.entries


def test_mutated_comment_uri_and_field_masks_bypass_cache(setup_cache):
    state = setup_cache
    for _ in range(2):
        request = state.service.documents().get(documentId='example')
        request.uri += '&commentsViewMode=COMMENTS_VIEW_MODE_INCLUDED'
        request.execute()
    state.service.documents().get(
        documentId='example', fields='title'
    ).execute()
    assert not state.store.entries
    assert len(state.calls) == 3


def test_disabled_cache_bypasses_checks_and_storage(setup_cache, monkeypatch):
    state = setup_cache
    monkeypatch.setattr(
        document_cache,
        'get_settings',
        lambda: Settings(document_cache_enabled=False),
    )
    state.read()
    state.read()
    assert not state.store.entries
    assert full_reads(state) == 2


def test_concurrent_readers_download_once(setup_cache):
    state = setup_cache
    barrier = threading.Barrier(8)

    def read():
        barrier.wait(timeout=5)
        return state.read()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: read(), range(8)))
    assert len(results) == 8
    assert full_reads(state) == 1
    assert len(state.calls) == 8


def test_grants_are_stable_and_isolated(setup_cache):
    service = setup_cache.service.service
    creds = SimpleNamespace(
        client_id='client',
        refresh_token='secret',
        scopes=['docs'],
        quota_project_id=None,
    )
    first = document_cache.wrap_service(service, creds)
    assert first.owner == document_cache.wrap_service(service, creds).owner
    creds.refresh_token = 'another-secret'
    assert first.owner != document_cache.wrap_service(service, creds).owner
    assert 'secret' not in first.owner
    creds.refresh_token = None
    assert document_cache.wrap_service(service, creds) is service


@pytest.mark.parametrize('ttl', [0, 86400, 100000])
def test_ttl_below_revision_validity_window(ttl):
    with pytest.raises(ValueError):
        Settings(document_cache_ttl_seconds=ttl)


def test_change_between_revision_check_and_full_fetch(setup_cache):
    state = setup_cache
    state.read()
    state.document['revisionId'] = 'full-fetch-revision'
    calls = []

    def check():
        calls.append(True)
        return {'revisionId': 'intermediate-revision'}

    document = state.store.read(
        'account', 'example', (('documentId', 'example'),
                               ('includeTabsContent', 'True')),
        fetch=lambda: deepcopy(state.document), check=check,
        settings=state.settings,
    )
    assert calls
    assert document['revisionId'] == 'full-fetch-revision'
    assert state.read()['revisionId'] == 'full-fetch-revision'
    assert full_reads(state) == 1


def test_write_waits_for_read_and_cannot_leave_stale_entry(setup_cache):
    state = setup_cache
    started, release = threading.Event(), threading.Event()

    def slow_fetch():
        started.set()
        assert release.wait(timeout=5)
        return deepcopy(state.document)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(
            state.store.read, 'account', 'example', (), fetch=slow_fetch,
            check=dict, settings=state.settings,
        )
        assert started.wait(timeout=5)
        writing = pool.submit(
            state.service.documents().batchUpdate(
                documentId='example', body={},
            ).execute,
        )
        release.set()
        reading.result(timeout=5)
        writing.result(timeout=5)
    assert not state.store.entries


def test_byte_budget_evicts_multiple_entries(setup_cache):
    state = setup_cache
    state.read()
    size = state.store.size
    settings = state.settings.model_copy(update={
        'document_cache_max_bytes': size * 2,
    })
    for doc_id in ['second', 'third']:
        state.store.read(
            'account', doc_id, (), fetch=lambda: state.document,
            check=dict, settings=settings,
        )
    assert state.store.size <= size * 2
    assert {key[1] for key in state.store.entries} == {'second', 'third'}
