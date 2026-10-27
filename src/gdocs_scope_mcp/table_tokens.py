"""Portable positional references and selected-state tokens without keys."""

import base64
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import EditFailedResponse
from .tool_errors import ToolFailureError

CellAddress = Annotated[
    str, Field(strict=True, pattern=r'^[A-Z]{1,5}[1-9][0-9]{0,5}$'),
]
SnapshotField = Literal[
    'content', 'text_style', 'paragraph_style', 'cell_style', 'structure',
    'cell.background_color', 'cell.vertical_alignment',
    'cell.padding_top', 'cell.padding_bottom',
    'cell.padding_left', 'cell.padding_right',
    'cell.border_top', 'cell.border_bottom', 'cell.border_left',
    'cell.border_right', 'paragraph.alignment', 'column.width',
    'row.min_height', 'table.header_rows',
]
SnapshotFields = Annotated[
    list[SnapshotField], Field(min_length=1, max_length=19),
]
SnapshotToken = Annotated[
    str, Field(strict=True, min_length=1, max_length=262144),
]


def fail(code, description):
    """Require a fresh read instead of silently selecting another position."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action='Refresh table discovery and reread affected cells. '
        'Use returned refs and A1 addresses without changing token data. '
        'Structural changes require a new reference; content/property '
        'conflicts require reviewing affected cells before a new snapshot.',
    ))


def digest(value):
    """Hash canonical state, excluding nothing implicitly."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'),
    ).encode()).hexdigest()


class Token(BaseModel):
    """Describe a checked position, not persistent native object identity."""

    model_config = ConfigDict(strict=True, extra='forbid')
    version: Literal[2] = 2
    kind: Literal['table', 'cell', 'base']
    document: str
    tab: str | None
    section: list[str]
    ordinal: Annotated[int, Field(ge=0)]
    nested: list[list[Annotated[int, Field(ge=0)]]] = Field(
        default_factory=list,
    )
    structure: str
    inventory: str
    address: CellAddress | None = None
    expires: int = 0
    fields: list[SnapshotField] = Field(default_factory=list)
    cells: dict[CellAddress, dict[SnapshotField, str]] = Field(
        default_factory=dict,
    )


def encode(token):
    """Encode self-contained state with a SHA-256 corruption checksum."""
    payload = token.model_dump(exclude_defaults=True)
    data = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    encoded = base64.urlsafe_b64encode(data).decode().rstrip('=')
    return 'gdt2.' + encoded + '.' + hashlib.sha256(data).hexdigest()


def _unpack(value, kind, doc_id):
    """Check transport bytes before constructing positional expectations."""
    bound = 262144 if kind == 'base' else 8192
    if len(value) > bound:
        raise ValueError('Oversized token')
    prefix, payload, checksum = value.split('.')
    if prefix != 'gdt2':
        raise ValueError('Unsupported token version')
    data = base64.b64decode(payload + '=' * (-len(payload) % 4),
                            altchars=b'-_', validate=True)
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError('Invalid checksum')
    token = Token.model_validate_json(data)
    if any(len(step) != 3 for step in token.nested):  # noqa: PLR2004
        raise ValueError('Invalid nested path')
    if token.kind != kind or token.document != doc_id:
        raise ValueError('Different document/tool')
    return token


def decode(value, kind, doc_id):
    """Validate format/checksum/scope; tokens grant no Google permissions."""
    try:
        token = _unpack(value, kind, doc_id)
    except (ValueError, TypeError, ValidationError):
        fail('INVALID_ARGUMENT', 'Invalid reference or snapshot token for '
             'this document/tool.')
    return token


def address(row, column):
    """Format zero-based logical coordinates using spreadsheet notation."""
    label = ''
    column += 1
    while column:
        column, remainder = divmod(column - 1, 26)
        label = chr(65 + remainder) + label
    return f'{label}{row + 1}'


def coordinates(value):
    """Decode a validated A1 address into zero-based row and column."""
    split = next(i for i, char in enumerate(value) if char.isdecimal())
    column = 0
    for char in value[:split]:
        column = column * 26 + ord(char) - 64
    return int(value[split:]) - 1, column - 1
