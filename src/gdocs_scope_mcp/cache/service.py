"""Wrap authenticated discovery clients with snapshot-aware requests."""

import hashlib
import json
import logging
import time
from urllib.parse import parse_qsl, urlsplit

from gdocs_scope_mcp.cache.selection import selected_cache
from gdocs_scope_mcp.settings import get_settings

log = logging.getLogger(__name__)


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
