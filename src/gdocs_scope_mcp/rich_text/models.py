"""Internal rich_text.models responsibilities."""


from typing import Literal

from pydantic import BaseModel, field_validator

from gdocs_scope_mcp.documents.native_models import (
    GoogleDocumentParagraph,
    GoogleDocumentTextRun,
)


class InsertionCodeRun(GoogleDocumentTextRun):
    """Preserve literal block whitespace, including trailing blank lines."""

    @field_validator('content', mode='before')
    @classmethod
    def remove_trailing_newline(cls, value: str) -> str:
        """Keep code newlines; the converter removes one block terminator."""
        return value


class InsertionImage(BaseModel):
    """Describe an image to insert, without inventing a native object ID."""

    type: Literal['image'] = 'image'
    start_index: int
    end_index: int
    uri: str
    object_size: dict

    def __len__(self) -> int:
        """Reserve one UTF-16 index for the native inline object."""
        return 1

    def to_markdown(self, _doc) -> str:
        """Keep the paragraph rendering interface for converter diagnostics."""
        return f'![](<{self.uri}>)'

    def to_text(self, _doc) -> str:
        """Represent the object slot without inventing visible image text."""
        return '\ufffc'


class InsertionChip(BaseModel):
    """Reserve a native entity slot separately from its displayed label."""

    type: Literal['chip'] = 'chip'
    start_index: int
    end_index: int
    request_kind: str
    payload: dict

    def __len__(self) -> int:
        """Reserve one UTF-16 unit for the native smart element."""
        return 1

    def to_markdown(self, _doc) -> str:
        """Keep insertion previews independent of Google-resolved labels."""
        return '\ufffc'

    def to_text(self, _doc) -> str:
        """Represent the native slot without guessing its displayed text."""
        return '\ufffc'


class InsertionParagraph(GoogleDocumentParagraph):
    """Keep insertion-only list metadata separate from API list identities."""

    elements: list[GoogleDocumentTextRun | InsertionImage | InsertionChip]
    bullet_preset: str | None = None
    nesting_level: int = 0
    list_key: int | None = None
    item_key: int | None = None
    continuation: bool = False
    loose_list: bool = False
    code_block: bool = False
    code_language: str | None = None


from dataclasses import dataclass


@dataclass
class TableCell:
    """Keep validated cell requests relative to its first paragraph."""

    requests: list[dict]
    text: str


@dataclass
class InsertionTable:
    """Retain a rectangular table separately from ordinary paragraphs."""

    start_index: int
    cells: list[list[TableCell]]

    def __len__(self) -> int:
        """Leave structural size to the native API instead of guessing it."""
        return 0
