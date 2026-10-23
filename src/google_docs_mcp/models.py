"""Model Google Docs API data, heading scopes, and typed edit responses."""

import re
from abc import abstractmethod
from collections.abc import Generator, Sequence
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    Discriminator,
    Field,
    PlainSerializer,
    field_validator,
)
from typing_extensions import Self

HEADING_LEVELS = {
    'TITLE': 'Title',
    'SUBTITLE': 'Subtitle',
    'HEADING_1': 'H1',
    'HEADING_2': 'H2',
    'HEADING_3': 'H3',
    'HEADING_4': 'H4',
    'HEADING_5': 'H5',
    'HEADING_6': 'H6',
}
HEADING_ORDER = dict(zip(HEADING_LEVELS.keys(), range(len(HEADING_LEVELS))))
HEADING_ORDER_COMPACT = dict(
    zip(HEADING_LEVELS.values(), range(len(HEADING_LEVELS)))
)


class GoogleDocumentGlyphType(Enum):
    """Enumerate the numbering styles of Google Docs list items."""

    GLYPH_TYPE_UNSPECIFIED = 'GLYPH_TYPE_UNSPECIFIED'
    NONE = 'NONE'
    DECIMAL = 'DECIMAL'
    ZERO_DECIMAL = 'ZERO_DECIMAL'
    UPPER_ALPHA = 'UPPER_ALPHA'
    ALPHA = 'ALPHA'
    UPPER_ROMAN = 'UPPER_ROMAN'
    ROMAN = 'ROMAN'


class GoogleDocumentBaselineOffset(Enum):
    # The text's baseline offset is inherited from the parent.
    """Enumerate normal, superscript, and subscript baselines."""

    BASELINE_OFFSET_UNSPECIFIED = 'BASELINE_OFFSET_UNSPECIFIED'
    # The text is not vertically offset.
    NONE = 'NONE'
    # The text is vertically offset upwards (superscript).
    SUPERSCRIPT = 'SUPERSCRIPT'
    # The text is vertically offset downwards (subscript).
    SUBSCRIPT = 'SUBSCRIPT'


class GoogleDocumentNamedStyleType(Enum):
    """Enumerate Google Docs title and paragraph styles."""

    TITLE = 'TITLE'
    SUBTITLE = 'SUBTITLE'
    HEADING_1 = 'HEADING_1'
    HEADING_2 = 'HEADING_2'
    HEADING_3 = 'HEADING_3'
    HEADING_4 = 'HEADING_4'
    HEADING_5 = 'HEADING_5'
    HEADING_6 = 'HEADING_6'
    NORMAL_TEXT = 'NORMAL_TEXT'
    NAMED_STYLE_TYPE_UNSPECIFIED = 'NAMED_STYLE_TYPE_UNSPECIFIED'

    @property
    def compact(self) -> str:
        """Return the compact outline label for this named style."""
        return HEADING_LEVELS.get(self.value, '(no heading)')

    @property
    def level(self) -> int:
        """Return the ordering index used for title and heading styles."""
        return HEADING_ORDER.get(self.value, len(HEADING_ORDER))

    @classmethod
    def from_level(cls, level: int) -> 'GoogleDocumentNamedStyleType':
        """Map a Markdown heading level to a Google Docs named style."""
        if level > len(HEADING_LEVELS):
            return GoogleDocumentNamedStyleType.NORMAL_TEXT
        return list(GoogleDocumentNamedStyleType)[level - 1]


class GoogleDocumentAlignment(Enum):
    """Enumerate paragraph alignment values from the Docs API."""

    ALIGNMENT_UNSPECIFIED = 'ALIGNMENT_UNSPECIFIED'
    START = 'START'
    CENTER = 'CENTER'
    END = 'END'
    JUSTIFIED = 'JUSTIFIED'


class DocumentOutlineItem(BaseModel):
    """A document section (heading)"""

    title: Annotated[str, Field(description='Heading title')]
    id: Annotated[str, Field(description='Heading id')]
    level: Annotated[str, Field(description='Heading level')]
    ancestor_ids: Annotated[
        list[str], Field(description='Parent headings')
    ] = []

    @property
    def level_index(self) -> int:
        """Return the relative nesting order of this outline item."""
        return HEADING_ORDER_COMPACT.get(self.level, len(HEADING_LEVELS))


class DocumentParagraph(BaseModel):
    """Retain a paragraph with source indices and rendered content."""

    start_index: int
    end_index: int
    text: str
    markdown: str


class SearchResult(BaseModel):
    """Locate matched text within its paragraph and heading section."""

    paragraph: DocumentParagraph
    section: 'DocumentSection'
    start_index: int
    end_index: int


class DocumentSection(DocumentOutlineItem):
    """An extended version that includes full parsed document details"""

    sections: list[Self] = []
    paragraphs: list[DocumentParagraph] = []
    parent: Annotated[Self | None, Field(exclude=True)] = None

    def descendants(self) -> Generator[Self, None, None]:
        """Yield nested sections in document order."""
        for child in self.sections:
            yield child
            yield from child.descendants()

    def subtree(self) -> Generator[Self, None, None]:
        """Yield this section followed by all nested sections."""
        yield self
        for child in self.sections:
            yield from child.subtree()

    def _find_text(
        self,
        search: str,
        case_sensitive: bool = True,
        first: bool = False,
        regex: bool = False,
    ) -> list[SearchResult]:
        if not case_sensitive:
            search = search.lower()
        results = []
        for par in self.paragraphs:
            text = par.text if case_sensitive else par.text.lower()
            pos = 0
            if regex:
                if first:
                    if match := re.search(search, text):
                        results.append(
                            SearchResult(
                                paragraph=par,
                                section=self,
                                start_index=match.start(),
                                end_index=match.end(),
                            )
                        )
                    return results
                results.extend(
                    [
                        SearchResult(
                            paragraph=par,
                            section=self,
                            start_index=match.start(),
                            end_index=match.end(),
                        )
                        for match in re.finditer(search, text)
                    ]
                )
            else:
                while 0 <= (pos := text.find(search, pos)) < len(text):
                    results.append(
                        SearchResult(
                            paragraph=par,
                            section=self,
                            start_index=pos,
                            end_index=pos + len(search),
                        )
                    )
                    pos += 1
                    if first:
                        return results
        for child in self.sections:
            found = child._find_text(search, case_sensitive, first, regex)
            results.extend(found)
            if first and len(found) > 0:
                return found
        return results

    def find_first(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> SearchResult | None:
        """Find the first matching text in this scope and its descendants."""
        results = self._find_text(
            search, case_sensitive, first=True, regex=regex
        )
        return results[0] if results else None

    def find_all(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> list[SearchResult]:
        """Find all matching text in this scope and its descendants."""
        return self._find_text(
            search, case_sensitive, first=False, regex=regex
        )

    @property
    def text(self):
        """Return the plain text of this section without nested sections."""
        return ''.join([par.text for par in self.paragraphs])

    @property
    def markdown(self):
        """Return the Markdown of this section without nested sections."""
        return ''.join([par.markdown for par in self.paragraphs])

    def subtree_markdown(self) -> str:
        """Render this section and its descendants as Markdown."""
        return ''.join(
            [
                self.markdown,
                *[child.subtree_markdown() for child in self.sections],
            ]
        )

    def subtree_text(self) -> str:
        """Render this section and its descendants as plain text."""
        return ''.join(
            [self.text, *[child.subtree_text() for child in self.sections]]
        )


class DocumentBase(BaseModel):
    """Store document identity and revision metadata."""

    title: Annotated[str, Field(description='Document title')]
    revision_id: Annotated[str, Field(description='Document revision id')]
    document_id: Annotated[str, Field(description='Document id')]


class DocumentOutline(DocumentBase):
    """Document outline"""

    sections: Sequence[DocumentOutlineItem] = []


class DocumentTree(DocumentBase):
    """Represent nested sections with a heading ID lookup."""

    sections: Sequence[DocumentSection] = []
    headings: Annotated[dict[str, DocumentSection], Field(exclude=True)]

    def descendants(self) -> Generator[DocumentSection, None, None]:
        """Yield nested sections in document order."""
        for child in self.sections:
            yield child
            yield from child.descendants()

    def _find_text(
        self,
        search: str,
        case_sensitive: bool = True,
        first: bool = False,
        regex: bool = False,
    ) -> list[SearchResult]:
        if not case_sensitive:
            search = search.lower()
        results = []
        for child in self.sections:
            found = child._find_text(
                search, case_sensitive, first, regex=regex
            )
            results.extend(found)
            if first and len(found) > 0:
                return found
        return results

    def find_first(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> SearchResult | None:
        """Find the first matching text in this scope and its descendants."""
        results = self._find_text(
            search, case_sensitive, first=True, regex=regex
        )
        return results[0] if results else None

    def find_all(
        self, search: str, case_sensitive: bool = True, regex: bool = False
    ) -> list[SearchResult]:
        """Find all matching text in this scope and its descendants."""
        return self._find_text(
            search, case_sensitive, first=False, regex=regex
        )

    def tree_markdown(self) -> str:
        """Render all document sections as Markdown."""
        return ''.join([child.subtree_markdown() for child in self.sections])

    def tree_text(self) -> str:
        """Render all document sections as plain text."""
        return ''.join([child.subtree_text() for child in self.sections])


class DocumentSubset(DocumentBase):
    """A subset of document contents"""

    subset_md: Annotated[
        Sequence[str],
        Field(
            description='An array of Markdown strings containing the '
            'requested document sections. Heading lines include '
            "hidden HTML anchor tags (e.g., <a id='...'></a>) "
            'matching their structural IDs.'
        ),
    ]
    selected_headings: Annotated[
        Sequence[str] | None,
        Field(
            description='List of sections in the response or None if the '
            'whole document is returned'
        ),
    ]
    partial: Annotated[
        bool,
        Field(
            description='If returned response includes only parts of the '
            'document'
        ),
    ] = False


class EditFailedResponse(BaseModel):
    """A failed document edit response"""

    ok: Literal[False] = False
    description: Annotated[str, Field(description='Failure description')]
    suggested_action: Annotated[
        str, Field(description='Suggested action to resolve the failure')
    ]


TruncatedStr80 = Annotated[
    str, PlainSerializer(lambda v: v[:80] if v else v, return_type=str)
]

TruncatedStr200 = Annotated[
    str, PlainSerializer(lambda v: v[:200] if v else v, return_type=str)
]


class InsertSucceedResponse(BaseModel):
    """Result of successful text insertion request"""

    ok: Literal[True] = True
    anchor: Annotated[
        TruncatedStr80,
        Field(
            description=(
                'A paragraph used as the anchor; the first 80 characters max'
            )
        ),
    ]
    insert_position: Annotated[
        Literal['before', 'after'],
        Field(description='Insert position relative to the anchor paragraph'),
    ]
    at_index: Annotated[
        int,
        Field(
            description='Plain document model index the text was inserted at'
        ),
    ]
    rich: bool
    inserted_text: Annotated[
        TruncatedStr200,
        Field(description='Inserted text; the first 200 characters max'),
    ]


class ReplaceSucceedResponse(BaseModel):
    """Result of successful text replacement request"""

    ok: Literal[True] = True
    replaced: Annotated[
        TruncatedStr80,
        Field(description='Replaced text; the first 80 characters max'),
    ]
    at_index: Annotated[
        int | None,
        Field(
            description='Plain document model index the text was replaced at'
        ),
    ] = None
    occurrences_found: Annotated[
        int | None,
        Field(description='Number of occurances of the search text found'),
    ] = None
    occurrences_changed: Annotated[
        int | None,
        Field(description='Number of occurances that were replaced'),
    ] = None


class GoogleDocumentRepresentableBase(BaseModel, populate_by_name=True):
    """Define Markdown and plain-text rendering for document elements."""

    @abstractmethod
    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        pass

    @abstractmethod
    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        pass


class GoogleDocumentImageProperties(BaseModel, populate_by_name=True):
    """Store source and content URLs for an embedded image."""

    content_uri: Annotated[str | None, Field(alias='contentUri')] = None
    source_uri: Annotated[str | None, Field(alias='sourceUri')] = None


class GoogleDocumentEmbeddedObject(BaseModel, populate_by_name=True):
    """Describe an embedded object and optional image properties."""

    title: str | None = None
    description: str | None = None
    image_properties: Annotated[
        GoogleDocumentImageProperties | None, Field(alias='imageProperties')
    ] = None


class GoogleDocumentInlineObjectProperties(BaseModel, populate_by_name=True):
    """Wrap the embedded object associated with an inline object."""

    embedded_object: Annotated[
        GoogleDocumentEmbeddedObject, Field(alias='embeddedObject')
    ]


class GoogleDocumentInlineObject(GoogleDocumentRepresentableBase):
    """Represent a named embedded object in the document."""

    object_id: Annotated[str, Field(alias='objectId')]
    inline_object_properties: Annotated[
        GoogleDocumentInlineObjectProperties,
        Field(alias='inlineObjectProperties'),
    ]

    # Keep the shared rendering interface, including doc= callers.
    def to_markdown(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as Markdown using document metadata."""
        embedded_obj = self.inline_object_properties.embedded_object
        img_props = embedded_obj.image_properties
        if img_props is None:
            return ''
        return f'![{embedded_obj.title or ""}]({img_props.content_uri})'

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as plain text using document metadata."""
        embedded_obj = self.inline_object_properties.embedded_object
        return embedded_obj.title or ''


class GoogleDocumentNestingLevel(BaseModel, populate_by_name=True):
    """Describe the glyph format at one list nesting level."""

    glyph_format: Annotated[str | None, Field(alias='glyphFormat')] = None
    glyph_symbol: Annotated[str | None, Field(alias='glyphSymbol')] = None
    glyph_type: Annotated[
        GoogleDocumentGlyphType, Field(alias='glyphType')
    ] = GoogleDocumentGlyphType.GLYPH_TYPE_UNSPECIFIED


class GoogleDocumentListProperties(BaseModel, populate_by_name=True):
    """Store glyph settings for each list nesting level."""

    nesting_levels: Annotated[
        list[GoogleDocumentNestingLevel], Field(alias='nestingLevels')
    ]


class GoogleDocumentList(BaseModel, populate_by_name=True):
    """Represent a list referenced by paragraph bullet metadata."""

    list_properties: Annotated[
        GoogleDocumentListProperties, Field(alias='listProperties')
    ]


class GoogleDocumentStructuralElement(GoogleDocumentRepresentableBase):
    """Store source indices for a structural document element."""

    type: Literal['base'] = 'base'
    start_index: Annotated[int, Field(alias='startIndex')] = 0
    end_index: Annotated[int, Field(alias='endIndex')] = 0

    # Keep the shared rendering interface, including doc= callers.
    def to_markdown(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as Markdown using document metadata."""
        return ''

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as plain text using document metadata."""
        return ''

    def __len__(self) -> int:
        return 0


class GoogleDocumentLink(BaseModel, populate_by_name=True):
    """Represent an external URL attached to text."""

    url: str | None = None  # The only supported link type - external


class GoogleDocumentTextStyle(BaseModel, populate_by_name=True):
    """Store inline formatting and build HTML style wrappers."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    small_caps: Annotated[bool, Field(alias='smallCaps')] = False
    baseline_offset: Annotated[
        GoogleDocumentBaselineOffset, Field(alias='baselineOffset')
    ] = GoogleDocumentBaselineOffset.BASELINE_OFFSET_UNSPECIFIED
    link: GoogleDocumentLink | None = None

    @property
    def format_string(self) -> str:
        """Build a format template with HTML wrappers for active styles."""
        markers = {
            'bold': ('<b>', '</b>'),
            'italic': ('<i>', '</i>'),
            'underline': ('<u>', '</u>'),
            'strikethrough': ('<s>', '</s>'),
            'small_caps': (
                '<span style="font-variant: small-caps;">',
                '</span>',
            ),
            'subscript': ('<sub>', '</sub>'),
            'superscript': ('<sup>', '</sup>'),
            'link': (f'<a href="{self.link and self.link.url}">', '</a>'),
        }

        collected = []
        for name in markers:
            if getattr(self, name, False):
                collected.append(name)
        if self.baseline_offset == GoogleDocumentBaselineOffset.SUBSCRIPT:
            collected.append('subscript')
        if self.baseline_offset == GoogleDocumentBaselineOffset.SUPERSCRIPT:
            collected.append('superscript')

        template = '{text}'
        for name in collected:
            template = f'{markers[name][0]}{template}{markers[name][1]}'
        return template


class GoogleDocumentTextRun(GoogleDocumentStructuralElement):
    """Represent a contiguous text run and its inline formatting."""

    type: Literal['textRun'] = 'textRun'
    content: str
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]

    @field_validator('content', mode='before')
    @classmethod
    def remove_trailing_newline(cls, value: str) -> str:
        """Strip paragraph terminators from the end of a text run."""
        return value.rstrip('\n')

    # Keep the shared rendering interface, including doc= callers.
    def to_markdown(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as Markdown using document metadata."""
        content = self.content.replace('\u000b', '  \n')
        if not content:
            return content
        text = content
        orig_len = len(text)
        text = text.lstrip()
        start = orig_len - len(text)
        text = text.rstrip()
        end = len(text) + start
        return (
            f'{content[:start]}'
            f'{self.text_style.format_string.format(text=text)}'
            f'{content[end:]}'
        )

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as plain text using document metadata."""
        return self.content.replace('\u000b', '\n')

    def __len__(self) -> int:
        return len(self.content)


class GoogleDocumentHorizontalRule(GoogleDocumentStructuralElement):
    """Represent a horizontal rule within a paragraph."""

    type: Literal['horizontalRule'] = 'horizontalRule'
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]

    # Keep the shared rendering interface, including doc= callers.
    def to_markdown(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as Markdown using document metadata."""
        return '\n---\n'

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:  # noqa: ARG002
        """Render this element as plain text using document metadata."""
        return '\n---\n'


class GoogleDocumentInlineObjectElement(GoogleDocumentStructuralElement):
    """Reference an embedded object from paragraph content."""

    type: Literal['inlineObjectElement'] = 'inlineObjectElement'
    inline_object_id: Annotated[str, Field(alias='inlineObjectId')]
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return doc.inline_objects[self.inline_object_id].to_markdown(doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return doc.inline_objects[self.inline_object_id].to_text(doc)


class GoogleDocumentParagraphStyle(BaseModel, populate_by_name=True):
    """Store a paragraph heading ID, named style, and alignment."""

    heading_id: Annotated[str | None, Field(alias='headingId')] = None
    named_style_type: Annotated[
        GoogleDocumentNamedStyleType, Field(alias='namedStyleType')
    ] = GoogleDocumentNamedStyleType.NAMED_STYLE_TYPE_UNSPECIFIED
    alignment: GoogleDocumentAlignment = (
        GoogleDocumentAlignment.ALIGNMENT_UNSPECIFIED
    )


class GoogleDocumentBullet(BaseModel, populate_by_name=True):
    """Link a paragraph to a list and its nesting level."""

    list_id: Annotated[str, Field(alias='listId')]
    nesting_level: Annotated[int, Field(alias='nestingLevel')] = 0
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]


def _unnest_paragraph_element(data: dict) -> dict:
    kinds = {'textRun', 'horizontalRule,inlineObjectElement'}
    present_kinds = kinds.intersection(data.keys())
    if present_kinds:
        kind = next(iter(present_kinds))
        inner_payload = data.pop(kind)
    else:
        kind = 'base'
        inner_payload = {}
    return {'type': kind, **data, **inner_payload}


GoogleDocumentParagraphElement = Annotated[
    Annotated[
        GoogleDocumentTextRun
        | GoogleDocumentHorizontalRule
        | GoogleDocumentInlineObjectElement
        | GoogleDocumentStructuralElement,
        Discriminator('type'),
    ],
    BeforeValidator(_unnest_paragraph_element),
]


class GoogleDocumentParagraph(GoogleDocumentStructuralElement):
    """Represent paragraph content, formatting, and optional bullets."""

    type: Literal['paragraph'] = 'paragraph'
    elements: list[GoogleDocumentParagraphElement]
    paragraph_style: Annotated[
        GoogleDocumentParagraphStyle, Field(alias='paragraphStyle')
    ]
    bullet: GoogleDocumentBullet | None = None

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        style = self.paragraph_style
        text = ''.join([el.to_markdown(doc) for el in self.elements])
        if style.heading_id or style.named_style_type.level < len(
            HEADING_LEVELS
        ):
            prefix = '#' * (style.named_style_type.level + 1)
            anchor = (
                f'<a id={style.heading_id}></a>'
                if style.heading_id is not None
                else ''
            )
            return f'{prefix} {anchor}{text}\n\n'
        if self.bullet:
            list_props = doc.lists[self.bullet.list_id]
            level = self.bullet.nesting_level
            level_props = list_props.list_properties.nesting_levels[level]
            if (
                level_props.glyph_type
                == GoogleDocumentGlyphType.GLYPH_TYPE_UNSPECIFIED
                or level_props.glyph_symbol
            ):
                text = f'{" " * level}- {text}'
            else:
                text = f'{" " * level}1. {text}'
            return f'{text}\n'

        match style.alignment:
            case GoogleDocumentAlignment.CENTER:
                return f'<p style="text-align: center;">{text}</p>\n'
            case GoogleDocumentAlignment.JUSTIFIED:
                return f'<p style="text-align: justify;">{text}</p>\n'
            case GoogleDocumentAlignment.END:
                return f'<p style="text-align: right;">{text}</p>\n'
            case _:
                pass

        return f'{text}\n\n'

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        text = ''.join([el.to_text(doc) for el in self.elements])
        return f'{text}\n\n'

    def __len__(self) -> int:
        return sum([len(el) for el in self.elements])


def _unnest_document_content(data: dict) -> dict:
    kinds = {'paragraph', 'table'}
    present_kinds = kinds.intersection(data.keys())
    if present_kinds:
        kind = next(iter(present_kinds))
        inner_payload = data.pop(kind)
    else:
        kind = 'base'
        inner_payload = {}
    return {'type': kind, **data, **inner_payload}


GoogleDocumentContent = Annotated[
    Annotated[
        Union[
            GoogleDocumentParagraph,
            'GoogleDocumentTable',
            GoogleDocumentStructuralElement,
        ],
        Discriminator('type'),
    ],
    BeforeValidator(_unnest_document_content),
]


class GoogleDocumentTableCellStyle(BaseModel, populate_by_name=True):
    """Store row and column spans for a table cell."""

    row_span: Annotated[int, Field(alias='rowSpan')]
    column_span: Annotated[int, Field(alias='columnSpan')]


class GoogleDocumentTableCell(GoogleDocumentStructuralElement):
    """Represent structural content within a table cell."""

    content: list[GoogleDocumentContent]
    table_cell_style: Annotated[
        GoogleDocumentTableCellStyle, Field(alias='tableCellStyle')
    ]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        content = ''.join([el.to_markdown(doc) for el in self.content])
        style = self.table_cell_style
        row_span = f' rowspan="{style.row_span}"' if style.row_span > 1 else ''
        col_span = (
            f' colspan="{style.column_span}"' if style.column_span > 1 else ''
        )
        return f'<td{row_span}{col_span}>{content.rstrip()}</td>'

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return ''.join([el.to_text(doc) for el in self.content])


class GoogleDocumentTableRow(GoogleDocumentStructuralElement):
    """Represent the cells in one table row."""

    table_cells: Annotated[
        list[GoogleDocumentTableCell], Field(alias='tableCells')
    ]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        cells = ''.join([cell.to_markdown(doc) for cell in self.table_cells])
        return f'<tr>{cells}</tr>'

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        cells = ' | '.join([cell.to_text(doc) for cell in self.table_cells])
        return f'| {cells} |'


class GoogleDocumentTable(GoogleDocumentStructuralElement):
    """Represent a table as a collection of rows."""

    type: Literal['table'] = 'table'
    rows: int
    columns: int
    table_rows: Annotated[
        list[GoogleDocumentTableRow], Field(alias='tableRows')
    ]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        rows = ''.join([row.to_markdown(doc) for row in self.table_rows])
        return f'<table>{rows}</table>'

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return '\n'.join([row.to_text(doc) for row in self.table_rows])


class GoogleDocumentBody(GoogleDocumentRepresentableBase):
    """Represent the ordered structural elements of a document body."""

    content: list[GoogleDocumentContent]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return ''.join([el.to_markdown(doc) for el in self.content])

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return ''.join([el.to_text(doc) for el in self.content])


class GoogleDocument(BaseModel, populate_by_name=True):
    """Validate a Google Docs API response and render its body."""

    title: str
    body: GoogleDocumentBody
    lists: dict[str, GoogleDocumentList]
    inline_objects: Annotated[
        dict[str, GoogleDocumentInlineObject],
        Field(alias='inlineObjects', default_factory=dict),
    ]
    revision_id: Annotated[str, Field(alias='revisionId')]
    document_id: Annotated[str, Field(alias='documentId')]

    def to_markdown(self) -> str:
        """Render this element as Markdown using document metadata."""
        return self.body.to_markdown(self)

    def to_text(self) -> str:
        """Render this element as plain text using document metadata."""
        return self.body.to_text(self)
