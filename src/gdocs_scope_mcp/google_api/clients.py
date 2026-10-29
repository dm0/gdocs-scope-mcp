"""Construct clients with explicit cached and uncached Docs behavior."""

from googleapiclient.discovery import build

from ..cache.service import wrap_service
from . import credentials


def get_service(api: str = 'docs', version: str = 'v1', *, cached=True):
    """Build a Google API service, optionally wrapping Docs reads."""
    creds = credentials.load_credentials()
    service = build(api, version, credentials=creds)
    return (wrap_service(service, creds)
            if api == 'docs' and cached else service)
