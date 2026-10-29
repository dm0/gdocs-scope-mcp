"""Validate snapshots independently of memory or disk storage."""

import json
import logging
import time

from gdocs_scope_mcp.cache.types import Entry

log = logging.getLogger(__name__)


class ValidatedSnapshots:
    """Share revision, expiry and invalidation rules across backends."""

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock

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
