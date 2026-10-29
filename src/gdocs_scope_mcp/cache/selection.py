"""Select snapshot storage without eagerly opening the disk backend."""

from gdocs_scope_mcp.cache.memory import SnapshotCache
from gdocs_scope_mcp.settings import get_settings

cache = SnapshotCache()


def selected_cache():
    """Select a backend without initializing disk storage when disabled."""
    if get_settings().document_cache_storage == 'memory':
        return cache
    from gdocs_scope_mcp.cache.disk import disk_cache  # noqa: PLC0415

    return disk_cache()
