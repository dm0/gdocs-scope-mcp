"""Cache immutable native snapshots behind an authenticated Docs client."""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from urllib.parse import parse_qsl, urlsplit

from .settings import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Entry:
    """Keep serialized snapshots private and bound their lifetime."""

    payload: bytes
    revision: str
    created: float


class SnapshotCache:
    """Serialize same-document operations and bound process-local storage."""

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.entries = OrderedDict()
        self.size = 0
        self.lock = RLock()
        # Fixed stripes avoid an unbounded registry of document locks.
        self.stripes = tuple(RLock() for _ in range(64))

    def document_lock(self, owner, doc_id):
        """Share a lock across all read options for one account/document."""
        return self.stripes[hash((owner, doc_id)) % len(self.stripes)]

    def _remove(self, key):
        entry = self.entries.pop(key, None)
        if entry is not None:
            self.size -= len(entry.payload)

    def invalidate(self, owner, doc_id):
        """Discard every representation after attempted local writes."""
        with self.lock:
            for key in list(self.entries):
                if key[:2] == (owner, doc_id):
                    self._remove(key)

    def _entry(self, key, settings):
        """Expire old entries and retrieve one immutable snapshot."""
        with self.lock:
            now = self.clock()
            for stale, item in list(self.entries.items()):
                if (
                    not 0
                    <= now - item.created
                    < (settings.document_cache_ttl_seconds)
                ):
                    self._remove(stale)
            return self.entries.get(key)

    def _touch(self, key):
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)

    def _save(self, key, entry, settings):
        with self.lock:
            self._remove(key)
            if len(entry.payload) <= settings.document_cache_max_bytes:
                while self.entries and (
                    len(self.entries) >= settings.document_cache_max_entries
                    or self.size + len(entry.payload)
                    > settings.document_cache_max_bytes
                ):
                    self._remove(next(iter(self.entries)))
                self.entries[key] = entry
                self.size += len(entry.payload)

    def read(self, owner, doc_id, options, *, fetch, check, settings):
        """Validate access/revision on hits; never return stale on error."""
        key = (owner, doc_id, options)
        started = self.clock()
        with self.document_lock(owner, doc_id):
            entry = self._entry(key, settings)
            if entry is not None:
                try:
                    revision = check().get('revisionId')
                except Exception:
                    self.invalidate(owner, doc_id)
                    raise
                # A slow check must not extend the maximum entry lifetime.
                if (
                    revision == entry.revision
                    and self.clock() - entry.created
                    < settings.document_cache_ttl_seconds
                ):
                    self._touch(key)
                    self._report('hit', len(entry.payload), started)
                    return json.loads(entry.payload)
                self.invalidate(owner, doc_id)
            try:
                document = fetch()
            except Exception:
                self.invalidate(owner, doc_id)
                raise
            revision = document.get('revisionId')
            payload = json.dumps(document, ensure_ascii=False).encode('utf-8')
            if not isinstance(revision, str) or not revision:
                self.invalidate(owner, doc_id)
            if isinstance(revision, str) and revision:
                self._save(key, Entry(payload, revision, started), settings)
            self._report('miss', len(payload), started)
            return document

    def _report(self, outcome, size, started):
        """Expose bounded diagnostics without document IDs or contents."""
        log.info(
            'snapshot_cache=%s snapshot_bytes=%s duration_ms=%.1f',
            outcome,
            size,
            (self.clock() - started) * 1000,
        )


cache = SnapshotCache()


def selected_cache():
    """Select a backend without initializing disk storage when disabled."""
    if get_settings().document_cache_storage == 'memory':
        return cache
    from .disk_cache import disk_cache  # noqa: PLC0415

    return disk_cache()


def wrap_service(service, credentials):
    """Isolate grants without retaining or logging raw credential material."""
    if not get_settings().document_cache_enabled:
        return service
    grant = [
        credentials.client_id,
        credentials.refresh_token,
        sorted(credentials.scopes or []),
        getattr(credentials, 'quota_project_id', None),
    ]
    # Without a stable grant identity, safely bypass caching.
    if not credentials.refresh_token:
        return service
    owner = hashlib.sha256(json.dumps(grant).encode()).hexdigest()
    return CachedService(service, owner)


class CachedService:
    """Preserve the discovery service interface for non-document resources."""

    def __init__(self, service, owner):
        self.service = service
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.service, name)

    def documents(self):
        """Intercept document reads and every local document batch."""
        return CachedDocuments(self.service.documents(), self.owner)


def _execute_get(request, *args, **options):
    """Time native execute only, excluding cache and request construction."""
    query = dict(parse_qsl(urlsplit(request.uri).query))
    kind = ('revision' if query.get('fields') == 'revisionId' else
            'partial' if 'fields' in query else 'document')
    started = time.perf_counter()
    status = 'error'
    try:
        result = request.execute(*args, **options)
        status = 'success'
        return result
    finally:
        duration = (time.perf_counter() - started) * 1000
        log.info('document_get=%s status=%s duration_ms=%.1f',
                 kind, status, duration)


class CachedDocuments:
    """Leave unrelated discovery methods unchanged."""

    def __init__(self, documents, owner):
        self.documents = documents
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.documents, name)

    def get(self, **kwargs):
        """Defer option inspection until execution, including URI changes."""
        request = self.documents.get(**kwargs)

        def execute(*args, **options):
            query = dict(parse_qsl(urlsplit(request.uri).query))
            if (
                'fields' in query
                or 'fields' in kwargs
                or 'commentsViewMode' in query
                or not get_settings().document_cache_enabled
            ):
                return _execute_get(request, *args, **options)
            return selected_cache().read(
                self.owner,
                kwargs['documentId'],
                tuple(sorted(query.items())),
                fetch=lambda: _execute_get(request, *args, **options),
                check=lambda: _execute_get(self.documents.get(
                    documentId=kwargs['documentId'],
                    fields='revisionId',
                ), *args, **options),
                settings=get_settings(),
            )

        return DeferredRequest(request, execute)

    def batchUpdate(self, **kwargs):  # noqa: N802
        """Invalidate after every write, including unknown outcomes."""
        request = self.documents.batchUpdate(**kwargs)

        def execute(*args, **options):
            doc_id = kwargs['documentId']
            store = selected_cache()
            with store.document_lock(self.owner, doc_id):
                store.invalidate(self.owner, doc_id)
                try:
                    return request.execute(*args, **options)
                finally:
                    store.invalidate(self.owner, doc_id)

        return DeferredRequest(request, execute)


class DeferredRequest:
    """Forward request properties while controlling execution."""

    def __init__(self, request, execute):
        self.request = request
        self.execute = execute

    def __getattr__(self, name):
        return getattr(self.request, name)

    @property
    def uri(self):
        """Expose native request URI for newer API query parameters."""
        return self.request.uri

    @uri.setter
    def uri(self, value):
        self.request.uri = value
