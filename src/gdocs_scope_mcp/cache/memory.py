"""Validate immutable snapshots and bound process-local storage."""


import json
import logging
import time
from collections import OrderedDict
from threading import RLock

from gdocs_scope_mcp.cache.types import Entry

log = logging.getLogger(__name__)


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
