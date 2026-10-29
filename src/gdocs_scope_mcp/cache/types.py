"""Immutable storage entries shared by snapshot backends."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    """Keep serialized snapshots private and bound their lifetime."""

    payload: bytes
    revision: str
    created: float
