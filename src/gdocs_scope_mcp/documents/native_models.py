"""Models owned by documents.native_models."""

from abc import abstractmethod
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    Discriminator,
    Field,
    field_validator,
    model_validator,
)

from gdocs_scope_mcp.documents import rendering
from gdocs_scope_mcp.documents.styles import (
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentGlyphType,
    GoogleDocumentNamedStyleType,
)
from gdocs_scope_mcp.entities import (
    DateProperties,
    DropdownProperties,
    PersonProperties,
    RichLinkProperties,
)
from gdocs_scope_mcp.text_indices import utf16_length


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
    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.inline_object_to_markdown(self, doc)

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.inline_object_to_text(self, doc)


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
    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.structural_element_to_markdown(self, doc)

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.structural_element_to_text(self, doc)

    def __len__(self) -> int:
        return 0


class GoogleDocumentLink(BaseModel, populate_by_name=True):
    """Represent an external URL attached to text."""

    url: str | None = None  # The only supported link type - external


class GoogleDocumentWeightedFontFamily(BaseModel, populate_by_name=True):
    """Store the native font family and optional font weight."""

    font_family: Annotated[str, Field(alias='fontFamily')]
    weight: int | None = None


class GoogleDocumentRgbColor(BaseModel):
    """Store RGB channels in the native zero-to-one range."""

    red: float = 0
    green: float = 0
    blue: float = 0


class GoogleDocumentColor(BaseModel, populate_by_name=True):
    """Wrap the native RGB color representation."""

    rgb_color: Annotated[GoogleDocumentRgbColor, Field(alias='rgbColor')]


class GoogleDocumentOptionalColor(BaseModel):
    """Represent a native color or an unset/transparent color."""

    color: GoogleDocumentColor | None = None


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
    weighted_font_family: Annotated[
        GoogleDocumentWeightedFontFamily | None,
        Field(alias='weightedFontFamily'),
    ] = None
    foreground_color: Annotated[
        GoogleDocumentOptionalColor | None, Field(alias='foregroundColor'),
    ] = None
    background_color: Annotated[
        GoogleDocumentOptionalColor | None, Field(alias='backgroundColor'),
    ] = None

    @property
    def format_string(self) -> str:
        """Build a format template with HTML wrappers for active styles."""
        return rendering.text_style_format_string(self)


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
    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.text_run_to_markdown(self, doc)

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.text_run_to_text(self, doc)

    def __len__(self) -> int:
        """Return this run's length in Google Docs UTF-16 index units."""
        return utf16_length(self.content)


class GoogleDocumentHorizontalRule(GoogleDocumentStructuralElement):
    """Represent a horizontal rule within a paragraph."""

    type: Literal['horizontalRule'] = 'horizontalRule'
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]

    # Keep the shared rendering interface, including doc= callers.
    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.horizontal_rule_to_markdown(self, doc)

    # Keep the shared rendering interface, including doc= callers.
    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.horizontal_rule_to_text(self, doc)


class GoogleDocumentInlineObjectElement(GoogleDocumentStructuralElement):
    """Reference an embedded object from paragraph content."""

    type: Literal['inlineObjectElement'] = 'inlineObjectElement'
    inline_object_id: Annotated[str, Field(alias='inlineObjectId')]
    text_style: Annotated[GoogleDocumentTextStyle, Field(alias='textStyle')]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.inline_object_element_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.inline_object_element_to_text(self, doc)


class GoogleDocumentShading(BaseModel, populate_by_name=True):
    """Represent a paragraph's full-width background fill."""

    background_color: Annotated[
        GoogleDocumentOptionalColor | None, Field(alias='backgroundColor'),
    ] = None


class GoogleDocumentSmartChip(GoogleDocumentStructuralElement, extra='allow'):
    """Keep native entities separate from editable source text runs."""

    type: Literal['person', 'richLink', 'dateElement', 'dropdown']
    person_id: str | None = Field(default=None, alias='personId')
    rich_link_id: str | None = Field(default=None, alias='richLinkId')
    date_id: str | None = Field(default=None, alias='dateId')
    dropdown_id: str | None = Field(default=None, alias='dropdownId')
    person_properties: PersonProperties | None = Field(
        default=None, alias='personProperties',
    )
    rich_link_properties: RichLinkProperties | None = Field(
        default=None, alias='richLinkProperties',
    )
    date_element_properties: DateProperties | None = Field(
        default=None, alias='dateElementProperties',
    )
    dropdown_properties: DropdownProperties | None = Field(
        default=None, alias='dropdownProperties',
    )

    @property
    def identity(self) -> str:
        """Return the native ID appropriate to this entity's kind."""
        return (self.person_id or self.rich_link_id or self.date_id
                or self.dropdown_id or '')

    @property
    def properties(self) -> dict:
        """Retain typed properties and forward-compatible API additions."""
        properties = (self.person_properties or self.rich_link_properties
                      or self.date_element_properties
                      or self.dropdown_properties)
        return properties.model_dump(by_alias=True, exclude_none=True)

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Keep display text, kind and identity in an escaped inline span."""
        return rendering.smart_chip_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Expose the native label for display, never for source mapping."""
        return rendering.smart_chip_to_text(self, doc)

    def __len__(self) -> int:
        """Use API source width rather than the display label length."""
        return self.end_index - self.start_index


class GoogleDocumentParagraphStyle(BaseModel, populate_by_name=True):
    """Store a paragraph heading ID, named style, and alignment."""

    heading_id: Annotated[str | None, Field(alias='headingId')] = None
    line_spacing: Annotated[float | None, Field(alias='lineSpacing')] = None
    shading: GoogleDocumentShading | None = None
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
    kinds = {'textRun', 'horizontalRule', 'inlineObjectElement',
             'person', 'richLink', 'dateElement', 'dropdown'}
    present_kinds = kinds.intersection(data.keys())
    if present_kinds:
        kind = next(iter(present_kinds))
        inner_payload = data[kind]
    else:
        kind = 'base'
        inner_payload = {}
    return {'type': kind, **{k: v for k, v in data.items() if k != kind},
            **inner_payload}


GoogleDocumentParagraphElement = Annotated[
    Annotated[
        GoogleDocumentTextRun
        | GoogleDocumentHorizontalRule
        | GoogleDocumentInlineObjectElement
        | GoogleDocumentSmartChip
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
        return rendering.paragraph_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.paragraph_to_text(self, doc)

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

    row_span: Annotated[int, Field(alias='rowSpan')] = 1
    column_span: Annotated[int, Field(alias='columnSpan')] = 1


class GoogleDocumentTableCell(GoogleDocumentStructuralElement):
    """Represent structural content within a table cell."""

    content: list[GoogleDocumentContent]
    table_cell_style: Annotated[
        GoogleDocumentTableCellStyle,
        Field(alias='tableCellStyle',
              default_factory=GoogleDocumentTableCellStyle),
    ]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.table_cell_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.table_cell_to_text(self, doc)


class GoogleDocumentTableRow(GoogleDocumentStructuralElement):
    """Represent the cells in one table row."""

    table_cells: Annotated[
        list[GoogleDocumentTableCell], Field(alias='tableCells')
    ]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.table_row_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.table_row_to_text(self, doc)


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
        return rendering.table_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.table_to_text(self, doc)


class GoogleDocumentBody(GoogleDocumentRepresentableBase):
    """Represent the ordered structural elements of a document body."""

    content: list[GoogleDocumentContent]

    def to_markdown(self, doc: 'GoogleDocument') -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.body_to_markdown(self, doc)

    def to_text(self, doc: 'GoogleDocument') -> str:
        """Render this element as plain text using document metadata."""
        return rendering.body_to_text(self, doc)


class GoogleDocument(BaseModel, populate_by_name=True):
    """Validate a Google Docs API response and render its body."""

    title: str
    body: GoogleDocumentBody
    lists: dict[str, GoogleDocumentList] = Field(default_factory=dict)
    inline_objects: Annotated[
        dict[str, GoogleDocumentInlineObject],
        Field(alias='inlineObjects', default_factory=dict),
    ]
    revision_id: Annotated[str | None, Field(alias='revisionId')] = None
    document_id: Annotated[str, Field(alias='documentId')]
    presentation: rendering.PresentationState = Field(
        default_factory=rendering.PresentationState, exclude=True,
    )

    @property
    def code_markdown(self):
        """Expose recovered block markup through the rendering context."""
        return self.presentation.code_markdown

    @property
    def plain_native_code(self):
        """Expose code boundaries that require plain native presentation."""
        return self.presentation.plain_native_code

    @property
    def table_refs(self):
        """Expose checked table references supplied by the reader."""
        return self.presentation.table_refs

    @model_validator(mode='before')
    @classmethod
    def recover_code_blocks(cls, data):
        """Preserve raw code newlines before text-run display normalization."""
        return rendering.prepare_document(data)

    def to_markdown(self) -> str:
        """Render this element as Markdown using document metadata."""
        return rendering.to_markdown(self)

    def to_text(self) -> str:
        """Render this element as plain text using document metadata."""
        return rendering.to_text(self)
