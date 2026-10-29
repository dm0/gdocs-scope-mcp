"""Render native elements without changing their schema responsibilities."""

# Rendering functions share one uniform element/document calling convention.
# ruff: noqa: ARG001

from html import escape

from pydantic import BaseModel, Field

from gdocs_scope_mcp.code_reading import (
    NATIVE_CODE_BOUNDARY,
    block_markdown,
    inline_markdown,
)
from gdocs_scope_mcp.documents.styles import (
    HEADING_LEVELS,
    GoogleDocumentAlignment,
    GoogleDocumentBaselineOffset,
    GoogleDocumentGlyphType,
)
from gdocs_scope_mcp.entities import (
    chip_html,
    chip_label,
)


class PresentationState(BaseModel):
    """Keep recovered code and table references outside native API fields."""

    code_markdown: dict[int, str] = Field(default_factory=dict)
    plain_native_code: set[int] = Field(default_factory=set)
    table_refs: dict[int, str] = Field(default_factory=dict)


# Character references survive both Markdown and raw HTML table parsing.
# Escape per character so even independently styled runs cannot form syntax.
_LITERAL_PUNCTUATION = str.maketrans({
    char: f'&#{ord(char)};' for char in '\\`*_[]#!|~^-+=.():'
})


def literal_text(text: str) -> str:
    """Encode native text once without exposing it as Markdown/HTML syntax."""
    text = escape(text, quote=False).translate(_LITERAL_PUNCTUATION)
    return text.replace('\t', '&#9;').replace('\u000b', '<br>')


def boundary_whitespace(text: str) -> str:
    """Keep run-edge spaces from becoming Markdown indentation/hard breaks."""
    return literal_text(text).replace(' ', '&#32;')


def prepare_document(data):
    """Recover raw code before native text-run normalization removes breaks."""
    if isinstance(data, dict) and 'body' in data:
        plain_native = set()
        markdown = block_markdown(data, plain_native=plain_native)
        return {**data, 'presentation': PresentationState(
            code_markdown=markdown, plain_native_code=plain_native,
            table_refs=data.get('table_refs', {}),
        )}
    return data


def inline_object_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    embedded_obj = self.inline_object_properties.embedded_object
    img_props = embedded_obj.image_properties
    if img_props is None:
        return ''
    return (f'<img src="{escape(img_props.content_uri or "", quote=True)}" '
            f'alt="{escape(embedded_obj.title or "", quote=True)}">')


def inline_object_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    embedded_obj = self.inline_object_properties.embedded_object
    return embedded_obj.title or ''


def structural_element_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    return ''


def structural_element_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return ''


def text_style_format_string(self) -> str:
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
        'link': ('<a href="' + escape(
            self.link.url or '' if self.link else '', quote=True,
        ).replace('{', '{{').replace('}', '}}') + '">', '</a>'),
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


def text_run_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    content = self.content
    if not content:
        return content
    text = content
    orig_len = len(text)
    text = text.lstrip()
    start = orig_len - len(text)
    text = text.rstrip()
    end = len(text) + start
    return (
        f'{boundary_whitespace(content[:start])}'
        f'{self.text_style.format_string.format(text=literal_text(text))}'
        f'{boundary_whitespace(content[end:])}'
    )


def text_run_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return self.content.replace('\u000b', '\n')


def horizontal_rule_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    return '\n---\n'


def horizontal_rule_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return '\n---\n'


def inline_object_element_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    return doc.inline_objects[self.inline_object_id].to_markdown(doc)


def inline_object_element_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return doc.inline_objects[self.inline_object_id].to_text(doc)


def smart_chip_to_markdown(self, doc) -> str:
    """Keep display text, kind and identity in an escaped inline span."""
    return chip_html(self.type, self.identity, self.properties)


def smart_chip_to_text(self, doc) -> str:
    """Expose the native label for display, never for source mapping."""
    return chip_label(self.type, self.properties)


def paragraph_to_markdown(self, doc) -> str:  # noqa: PLR0911
    """Render this element as Markdown using document metadata."""
    style = self.paragraph_style
    if doc is not None and self.start_index in doc.code_markdown:
        return doc.code_markdown[self.start_index]
    if doc is not None and self.start_index in doc.plain_native_code:
        text = ''.join(el.to_markdown(doc) for el in self.elements
                       if not (el.type == 'textRun'
                               and el.content == NATIVE_CODE_BOUNDARY))
    else:
        text = inline_markdown(self.elements, doc)
    if style.heading_id or style.named_style_type.level < len(
        HEADING_LEVELS
    ):
        prefix = '#' * (style.named_style_type.level + 1)
        anchor = (
            f'<a id="{escape(style.heading_id, quote=True)}"></a>'
            if style.heading_id is not None
            else ''
        )
        return f'{prefix} {anchor}{text}\n\n'
    if self.bullet:
        list_props = doc.lists.get(self.bullet.list_id)
        if list_props is None:
            raise ValueError(
                'Paragraph references missing list definition: '
                f'{self.bullet.list_id!r}',
            )
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


def paragraph_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    text = ''.join([el.to_text(doc) for el in self.elements])
    return f'{text}\n\n'


def table_cell_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    content = ''.join([el.to_markdown(doc) for el in self.content])
    style = self.table_cell_style
    row_span = f' rowspan="{style.row_span}"' if style.row_span > 1 else ''
    col_span = (
        f' colspan="{style.column_span}"' if style.column_span > 1 else ''
    )
    return f'<td{row_span}{col_span}>{content.rstrip()}</td>'


def table_cell_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return ''.join([el.to_text(doc) for el in self.content])


def table_row_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    cells = ''.join([cell.to_markdown(doc) for cell in self.table_cells])
    return f'<tr>{cells}</tr>'


def table_row_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    cells = ' | '.join([cell.to_text(doc) for cell in self.table_cells])
    return f'| {cells} |'


def table_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    rows = ''.join([row.to_markdown(doc) for row in self.table_rows])
    ref = doc.table_refs.get(self.start_index)
    attribute = (
        f' data-mcp-table-ref="{escape(ref, quote=True)}"' if ref else ''
    )
    return f'<table{attribute}>{rows}</table>'


def table_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return '\n'.join([row.to_text(doc) for row in self.table_rows])


def body_to_markdown(self, doc) -> str:
    """Render this element as Markdown using document metadata."""
    return ''.join([el.to_markdown(doc) for el in self.content])


def body_to_text(self, doc) -> str:
    """Render this element as plain text using document metadata."""
    return ''.join([el.to_text(doc) for el in self.content])


def to_markdown(self) -> str:
    """Render this element as Markdown using document metadata."""
    return self.body.to_markdown(self)


def to_text(self) -> str:
    """Render this element as plain text using document metadata."""
    return self.body.to_text(self)
