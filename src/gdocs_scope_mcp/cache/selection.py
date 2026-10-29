"""Select snapshot storage without eagerly opening the disk backend."""

from ..settings import get_settings
from .memory import SnapshotCache

cache = SnapshotCache()


def selected_cache():
    """Select a backend without initializing disk storage when disabled."""
    if get_settings().document_cache_storage == 'memory':
        return cache
    from .disk import disk_cache  # noqa: PLC0415

    return disk_cache()
