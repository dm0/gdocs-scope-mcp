"""Internal tables.references responsibilities."""

import base64
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.tabs import require_matching_tab
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.tables.geometry import (
    _geometry,
    _tables,
)
from gdocs_scope_mcp.tables.refs import Layout
from gdocs_scope_mcp.tables.tokens import (
    Token,
    address,
    decode as decode_position,
    encode as encode_position,
)


def _fail(code, description, action=None):
    """Give callers a safe way to reacquire a reference instead of guessing."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action=action or (
            'Read the document or call docs_tables_list and use the returned '
            'reference/page token with unchanged arguments. References are '
            'tab-scoped; page tokens require the same revision. '
            'Structural changes require fresh table refs; do not edit tokens.'
        ),
    ))



def _digest(value):
    """Hash canonical native data or cursor options without a process cache."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
    ).encode()).hexdigest()



class _Token(BaseModel):
    """Validate internal token data; tokens confer no document permissions."""

    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1] = 1
    kind: Literal['table', 'cell', 'tables-page', 'cells-page']
    document: str
    revision: str
    scope: Literal['first_tab', 'selected_tab'] = 'first_tab'
    path: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    cell: list[Annotated[int, Field(ge=0)]] | None = None
    fingerprint: str = ''
    offset: Annotated[int, Field(ge=0)] = 0
    options: str = ''
    tab: str | None = None



def _encode(token):
    """Use versioned, portable opaque references with a corruption checksum."""
    if isinstance(token, Token):
        return encode_position(token)
    payload = token.model_dump(exclude_defaults=True)
    data = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    encoded = base64.urlsafe_b64encode(data).decode().rstrip('=')
    return 'gdt1.' + encoded + '.' + hashlib.sha256(data).hexdigest()[:16]



def _unpack(value):
    """Validate transport encoding separately from document/tool policy."""
    if len(value) > 8192:  # noqa: PLR2004
        raise ValueError('Oversized token')
    prefix, payload, checksum = value.split('.')
    if prefix != 'gdt1':
        raise ValueError('Unsupported token version')
    data = base64.b64decode(payload + '=' * (-len(payload) % 4),
                            altchars=b'-_', validate=True)
    if hashlib.sha256(data).hexdigest()[:16] != checksum:
        raise ValueError('Invalid token checksum')
    return _Token.model_validate_json(data)



def _decode(value, kind, doc_id):
    """Reject malformed, mismatched and wrong-kind tokens before API access."""
    if kind in {'table', 'cell'}:
        return decode_position(value, kind, doc_id)
    try:
        token = _unpack(value)
    except (ValueError, TypeError, ValidationError):
        _fail('INVALID_ARGUMENT', 'Invalid reference or continuation token '
              'for this document/tool.')
    if token.kind != kind or token.document != doc_id:
        _fail('INVALID_ARGUMENT', 'Reference has a different tool/document.')
    return token



def _check_revision(token, document):
    """Reject stale references without reusing an old structural path."""
    require_matching_tab(token.tab, document.get('_mcp_tab_id'))
    if token.revision != document['revisionId']:
        _fail('STALE_REFERENCE', 'The reference revision is not current.')



def _require_revision(document):
    """Do not issue misleading revision-bound references without metadata."""
    if not isinstance(document.get('revisionId'), str) or not document[
        'revisionId'
    ]:
        _fail('REVISION_UNAVAILABLE', 'Table references require a document '
              'revision, which this read did not return.',
              'Verify edit access: Google returns revision IDs only to '
              'editors. Refresh the document after access is corrected.')



def _table_token(document, entry, kind='table', *, layout=None, **updates):
    """Describe a checked position or an exact-revision page cursor."""
    if kind in {'table', 'cell'}:
        cell = updates.get('cell')
        cell_address = None
        if cell is not None:
            geometry, valid = _geometry(entry)
            value = next(x for x in geometry if x[:2] == tuple(cell))
            if not valid:
                _fail('INVALID_ARGUMENT', 'Cell geometry is not verified.')
            cell_address = address(value[0], value[2])
        return (layout or Layout(document)).reference(
            entry, kind=kind, address=cell_address,
        )
    return _Token(kind=kind, document=document['documentId'],
                  revision=document['revisionId'], path=entry.path,
                  tab=document.get('_mcp_tab_id'),
                  fingerprint=_digest(entry.item), **updates)



def reference_map(document):
    """Supply HTML table references without any document writes."""
    entries = _tables(document)
    if entries:
        _require_revision(document)
    layout = Layout(document)
    return {entry.item['startIndex']: _encode(layout.reference(entry))
            for entry in entries}

