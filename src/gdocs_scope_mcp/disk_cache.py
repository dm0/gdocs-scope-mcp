"""Persist revision-validated snapshots with bounded SQLite storage."""

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from functools import lru_cache

from filelock import FileLock
from platformdirs import user_cache_path

from .document_cache import Entry, SnapshotCache
from .settings import get_settings

log = logging.getLogger(__name__)
PAGE_SIZE = 4096


class DiskSnapshotCache(SnapshotCache):
    """Share snapshots and document locks between local MCP processes."""

    def __init__(self, directory, max_bytes, *, clock=time.time):
        super().__init__(clock=clock)
        self.directory = directory
        self.max_bytes = max_bytes
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / 'snapshots-v1.sqlite3'
        self.database_lock = FileLock(
            str(directory / 'database.lock'), timeout=30, mode=0o600
        )
        self.stripes = tuple(
            FileLock(
                str(directory / f'document-{index}.lock'),
                timeout=60,
                mode=0o600,
            )
            for index in range(64)
        )
        with self.database_lock:
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute('PRAGMA page_size=4096')
                connection.execute('PRAGMA auto_vacuum=FULL')
                connection.execute('PRAGMA journal_mode=DELETE')
                connection.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                    owner TEXT NOT NULL, document TEXT NOT NULL,
                    options TEXT NOT NULL, payload BLOB NOT NULL,
                    revision TEXT NOT NULL, created REAL NOT NULL,
                    used REAL NOT NULL,
                    PRIMARY KEY (owner, document, options)
                )""")
                connection.commit()
                if self.path.stat().st_size > max_bytes:
                    # A reduced limit may discard cache data, never documents.
                    connection.execute('DELETE FROM snapshots')
                    connection.commit()
                    connection.execute('VACUUM')
                self._limit(connection)

    def _limit(self, connection):
        """Enforce the main database file limit, including SQLite pages."""
        pages = self.max_bytes // PAGE_SIZE
        connection.execute(f'PRAGMA max_page_count={pages}')
        current = connection.execute('PRAGMA page_count').fetchone()[0]
        if current > pages:
            raise sqlite3.DatabaseError('Cache database exceeds size limit')

    @contextmanager
    def _connection(self):
        """Hold only short storage transactions under the database lock."""
        with self.database_lock, closing(sqlite3.connect(self.path)) as conn:
            self._limit(conn)
            with conn:
                yield conn

    def document_lock(self, owner, doc_id):
        """Use deterministic stripes; Python hash values differ by process."""
        digest = hashlib.sha256(json.dumps([owner, doc_id]).encode()).digest()
        return self.stripes[
            int.from_bytes(digest[:4], 'big') % len(self.stripes)
        ]

    @staticmethod
    def _key(key):
        return (*key[:2], json.dumps(key[2], sort_keys=True))

    def _entry(self, key, settings):
        try:
            with self._connection() as conn:
                now = self.clock()
                conn.execute(
                    'DELETE FROM snapshots WHERE created <= ? OR created > ?',
                    (now - settings.document_cache_ttl_seconds, now),
                )
                row = conn.execute(
                    'SELECT payload, revision, created FROM snapshots '
                    'WHERE owner=? AND document=? AND options=?',
                    self._key(key),
                ).fetchone()
            return Entry(*row) if row else None
        except (sqlite3.Error, OSError):
            log.warning(
                'snapshot_cache=disk_read_failed; fetching Google data'
            )
            return None

    def _touch(self, key):
        try:
            with self._connection() as conn:
                conn.execute(
                    'UPDATE snapshots SET used=? WHERE owner=? '
                    'AND document=? AND options=?',
                    (self.clock(), *self._key(key)),
                )
        except (sqlite3.Error, OSError):
            log.warning('snapshot_cache=disk_touch_failed')

    def invalidate(self, owner, doc_id):
        """Evict variants without masking successful or uncertain writes."""
        try:
            with self._connection() as conn:
                conn.execute(
                    'DELETE FROM snapshots WHERE owner=? AND document=?',
                    (owner, doc_id),
                )
        except (sqlite3.Error, OSError):
            log.warning('snapshot_cache=disk_invalidation_failed')

    def _save(self, key, entry, settings):
        # Reserve metadata pages; max_page_count remains the hard backstop.
        budget = min(settings.document_cache_max_bytes, self.max_bytes - 65536)
        if len(entry.payload) > budget:
            return
        try:
            with self._connection() as conn:
                conn.execute(
                    'DELETE FROM snapshots WHERE owner=? '
                    'AND document=? AND options=?',
                    self._key(key),
                )
                count, size = conn.execute(
                    'SELECT count(*), coalesce(sum(length(payload)), 0) '
                    'FROM snapshots',
                ).fetchone()
                while count and (
                    count >= settings.document_cache_max_entries
                    or size + len(entry.payload) > budget
                ):
                    row = conn.execute(
                        'SELECT rowid, length(payload) '
                        'FROM snapshots ORDER BY used, rowid '
                        'LIMIT 1'
                    ).fetchone()
                    conn.execute(
                        'DELETE FROM snapshots WHERE rowid=?', (row[0],)
                    )
                    count -= 1
                    size -= row[1]
                conn.execute(
                    'INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)',
                    (
                        *self._key(key),
                        entry.payload,
                        entry.revision,
                        entry.created,
                        self.clock(),
                    ),
                )
        except (sqlite3.Error, OSError):
            log.warning('snapshot_cache=disk_save_failed; snapshot not stored')


@lru_cache(maxsize=4)
def _open_cache(directory, max_bytes):
    """Share lock instances within one process and storage across processes."""
    return DiskSnapshotCache(directory, max_bytes)


def disk_cache():
    """Resolve a platform-native cache directory or explicit override."""
    settings = get_settings()
    directory = settings.document_cache_directory
    if directory is None:
        directory = user_cache_path('gdocs-scope-mcp')
    return _open_cache(
        directory.expanduser(), settings.document_cache_database_max_bytes
    )
