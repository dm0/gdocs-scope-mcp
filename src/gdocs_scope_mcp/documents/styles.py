"""Models owned by documents.styles."""

from enum import Enum

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
