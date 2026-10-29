"""Verify persistent snapshots, process coordination and database limits."""

# Explicit byte budgets and fixture counts are part of these contracts.
# ruff: noqa: D103, PLR2004
import multiprocessing
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from gdocs_scope_mcp.cache.disk import DiskSnapshotCache
from gdocs_scope_mcp.settings import Settings

MIB = 1024 * 1024
KEY = ('owner', 'document', ())


def process_read(directory, count, gate):
    """Read concurrently in independent interpreters with one download."""
    cache = DiskSnapshotCache(Path(directory), MIB)

    def fetch():
        with count.get_lock():
            count.value += 1
        time.sleep(0.05)
        return {'revisionId': 'revision', 'body': {'content': []}}

    gate.wait(timeout=10)
    return cache.read(
        *KEY,
        fetch=fetch,
        check=lambda: {'revisionId': 'revision'},
        settings=Settings(),
    )


@pytest.fixture
def disk(tmp_path):
    return DiskSnapshotCache(tmp_path / 'cache', MIB)


def read(cache, document=None, *, settings=None, key=KEY):
    """Populate or validate a native snapshot through the shared algorithm."""
    document = document or {'revisionId': 'revision', 'content': 'initial'}
    return cache.read(
        *key,
        fetch=lambda: document,
        check=lambda: document,
        settings=settings or Settings(),
    )


def test_snapshot_survives_new_backend_instance(disk):
    read(disk)
    second = DiskSnapshotCache(disk.directory, MIB)
    fetched = []
    result = second.read(
        *KEY,
        fetch=lambda: fetched.append(True),
        check=lambda: {'revisionId': 'revision'},
        settings=Settings(),
    )
    assert result['content'] == 'initial'
    assert not fetched
    assert disk.path.stat().st_mode & 0o777 == 0o600


def test_shared_invalidation_covers_all_options(disk):
    read(disk)
    read(disk, key=('owner', 'document', (('suggestions', 'preview'),)))
    other = DiskSnapshotCache(disk.directory, MIB)
    with other.document_lock(*KEY[:2]):
        other.invalidate(*KEY[:2])
    assert disk._entry(KEY, Settings()) is None
    assert (
        disk._entry(
            ('owner', 'document', (('suggestions', 'preview'),)), Settings()
        )
        is None
    )


def test_revision_failure_removes_persistent_data(disk):
    read(disk)

    def fail():
        raise PermissionError('Access removed')

    with pytest.raises(PermissionError):
        disk.read(*KEY, fetch=dict, check=fail, settings=Settings())
    assert (
        DiskSnapshotCache(disk.directory, MIB)._entry(KEY, Settings()) is None
    )


def test_wall_clock_expiration_and_clock_rollback(disk):
    now = time.time()
    disk.clock = lambda: now
    read(disk)
    disk.clock = lambda: now + 301
    assert disk._entry(KEY, Settings()) is None
    read(disk)
    disk.clock = lambda: now
    assert disk._entry(KEY, Settings()) is None


def test_database_file_is_bounded_under_repeated_eviction(disk):
    settings = Settings(document_cache_max_bytes=8 * MIB)
    for number in range(12):
        document = {'revisionId': 'revision', 'content': 'x' * (200 * 1024)}
        assert (
            read(
                disk,
                document,
                settings=settings,
                key=('owner', str(number), ()),
            )
            == document
        )
        assert disk.path.stat().st_size <= MIB
    with sqlite3.connect(disk.path) as conn:
        count = conn.execute('SELECT count(*) FROM snapshots').fetchone()[0]
        assert 1 <= count <= 4
        assert conn.execute('PRAGMA auto_vacuum').fetchone()[0] == 1


def test_oversized_snapshot_returns_without_growing_database(disk):
    document = {'revisionId': 'revision', 'content': 'x' * (2 * MIB)}
    assert read(disk, document) == document
    assert disk._entry(KEY, Settings()) is None
    assert disk.path.stat().st_size <= MIB


def test_reduced_database_limit_reclaims_file(tmp_path):
    larger = DiskSnapshotCache(tmp_path / 'cache', 4 * MIB)
    read(larger, {'revisionId': 'revision', 'content': 'x' * (2 * MIB)})
    assert larger.path.stat().st_size > MIB
    smaller = DiskSnapshotCache(larger.directory, MIB)
    assert smaller.path.stat().st_size <= MIB
    assert smaller._entry(KEY, Settings()) is None


def test_full_database_cannot_exceed_configured_pages(disk):
    with (
        pytest.raises(sqlite3.OperationalError, match='full'),
        disk._connection() as conn,
    ):
        conn.execute(
            'INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)',
            (
                'owner',
                'document',
                '[]',
                b'x' * (2 * MIB),
                'rev',
                0,
                0,
            ),
        )
    assert disk.path.stat().st_size <= MIB


def test_processes_share_one_full_download(tmp_path, monkeypatch):
    # Spawned interpreters must resolve this importlib-mode pytest module.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    context = multiprocessing.get_context('spawn')
    # Manager proxies are pickleable in spawn workers.
    with context.Manager() as manager:
        gate = manager.Barrier(3)
        count = manager.Value('i', 0)
        # Manager values use a separate explicit lock.
        lock = manager.Lock()
        with ProcessPoolExecutor(max_workers=3, mp_context=context) as pool:
            results = list(
                pool.map(
                    _process_read,
                    [str(tmp_path)] * 3,
                    [count] * 3,
                    [gate] * 3,
                    [lock] * 3,
                )
            )
        assert count.value == 1
        assert len(results) == 3


def _process_read(directory, count, gate, lock):
    """Adapt manager values to the reusable concurrent read probe."""

    class Count:
        def get_lock(self):
            return lock

        @property
        def value(self):
            return count.value

        @value.setter
        def value(self, value):
            count.value = value

    return process_read(directory, Count(), gate)
