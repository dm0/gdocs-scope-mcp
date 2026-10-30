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
    list_markup: dict[int, tuple[str, str]] = Field(default_factory=dict)
    html_lists: set[int] = Field(default_factory=set)
    lists_prepared: bool = False


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


def _list_tag(paragraph, doc) -> str:
    """Resolve marker kind from the paragraph's actual native nesting level."""
    bullet = paragraph.bullet
    properties = doc.lists.get(bullet.list_id)
    if properties is None:
        raise ValueError('Paragraph references missing list definition: '
                         f'{bullet.list_id!r}')
    level = properties.list_properties.nesting_levels[bullet.nesting_level]
    return ('ul' if level.glyph_symbol or level.glyph_type
            == GoogleDocumentGlyphType.GLYPH_TYPE_UNSPECIFIED else 'ol')


def _prepare_lists(doc) -> None:
    """Cache balanced list fragments without changing native source models."""
    if doc.presentation.lists_prepared:
        return
    markup = {}
    html_lists = set()

    def eligible(item):
        """Keep headings and structural content outside ordinary list runs."""
        return (item.type == 'paragraph' and item.bullet is not None
                and not item.paragraph_style.heading_id
                and item.paragraph_style.named_style_type.level
                >= len(HEADING_LEVELS))

    def blank(item):
        """Recognize whitespace barriers that Markdown would ignore."""
        return (item.type == 'paragraph' and not item.bullet
                and not item.paragraph_style.heading_id
                and item.paragraph_style.named_style_type.level
                >= len(HEADING_LEVELS)
                and item.paragraph_style.alignment not in {
                    GoogleDocumentAlignment.CENTER,
                    GoogleDocumentAlignment.JUSTIFIED,
                    GoogleDocumentAlignment.END,
                }
                and all(e.type == 'textRun' and not e.content.strip()
                        for e in item.elements))

    def markdown_safe(run, content):
        """Require complete ancestors and unambiguous list-group boundaries."""
        frames = []
        for _, item in run:
            depth = item.bullet.nesting_level
            frame = (item.bullet.list_id, _list_tag(item, doc))
            if depth > len(frames):
                return False
            if depth < len(frames):
                if (frames[depth][0] != frame[0]
                        and frames[depth][1] == frame[1]):
                    return False
                frames[depth:] = [frame]
            else:
                frames.append(frame)
        # Blank native paragraphs do not reliably separate Markdown lists.
        # Keep both neighboring groups explicit when their root kinds match.
        first, last = run[0][0], run[-1][0]
        left, right = first - 1, last + 1
        while left >= 0 and blank(content[left]):
            left -= 1
        if left < first - 1 and left >= 0 and eligible(content[left]):
            while left > 0 and eligible(content[left - 1]):
                left -= 1
            if _list_tag(content[left], doc) == _list_tag(run[0][1], doc):
                return False
        while right < len(content) and blank(content[right]):
            right += 1
        return not (right > last + 1 and right < len(content)
                    and eligible(content[right])
                    and _list_tag(content[right], doc)
                    == _list_tag(run[0][1], doc))

    def container(content, *, html_context=False):
        """Keep list frames local to one body or physical table cell."""
        frames = []
        previous = None
        run = []

        def close():
            """Finish the current list before a structural/section boundary."""
            if frames:
                prefix, suffix = markup[previous]
                markup[previous] = (
                    prefix, suffix + ''.join('</li></' + tag + '>'
                                            for _, _, tag in reversed(frames))
                    + '\n\n',
                )
                frames.clear()
                if not html_context and markdown_safe(run, content):
                    for _, item in run:
                        marker = '1.' if _list_tag(item, doc) == 'ol' else '-'
                        markup[item.start_index] = (
                            '    ' * item.bullet.nesting_level + marker + ' ',
                            '\n',
                        )
                    prefix, _ = markup[previous]
                    markup[previous] = (prefix, '\n\n')
                    first_index, first_item = run[0]
                    if first_index:
                        before = content[first_index - 1]
                        separator = ''
                        if before.type != 'paragraph':
                            separator = '\n\n'
                        elif before.paragraph_style.alignment in {
                            GoogleDocumentAlignment.CENTER,
                            GoogleDocumentAlignment.JUSTIFIED,
                            GoogleDocumentAlignment.END,
                        }:
                            separator = '\n'
                        prefix, suffix = markup[first_item.start_index]
                        markup[first_item.start_index] = (
                            separator + prefix, suffix,
                        )
                else:
                    html_lists.update(item.start_index for _, item in run)
                run.clear()

        for index, item in enumerate(content):
            if eligible(item):
                run.append((index, item))
                depth = item.bullet.nesting_level
                tag = _list_tag(item, doc)
                frame = (depth, item.bullet.list_id, tag)
                prefix = ''
                while frames and frames[-1][0] > depth:
                    prefix += '</li></' + frames.pop()[2] + '>'
                if frames and frames[-1][0] == depth:
                    if frames[-1] == frame:
                        prefix += '</li><li>'
                        markup[item.start_index] = (prefix, '')
                        previous = item.start_index
                        continue
                    prefix += '</li></' + frames.pop()[2] + '>'
                prefix += '<' + tag + '><li>'
                frames.append(frame)
                markup[item.start_index] = (prefix, '')
                previous = item.start_index
            else:
                close()
                if item.type == 'table':
                    for row in item.table_rows:
                        for cell in row.table_cells:
                            container(cell.content, html_context=True)
        close()

    container(doc.body.content)
    doc.presentation.list_markup = markup
    doc.presentation.html_lists = html_lists
    doc.presentation.lists_prepared = True


def paragraph_to_markdown(self, doc) -> str:  # noqa: PLR0911
    """Render this element as Markdown using document metadata."""
    style = self.paragraph_style
    if doc is not None and self.start_index in doc.code_markdown:
        return doc.code_markdown[self.start_index]
    html_list = False
    if self.bullet:
        _prepare_lists(doc)
        html_list = (self.start_index in doc.presentation.html_lists
                     or self.start_index not in doc.presentation.list_markup)
    if doc is not None and self.start_index in doc.plain_native_code:
        text = ''.join(el.to_markdown(doc) for el in self.elements
                       if not (el.type == 'textRun'
                               and el.content == NATIVE_CODE_BOUNDARY))
    else:
        text = inline_markdown(self.elements, doc, html_code=html_list)
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
        tag = _list_tag(self, doc)
        prefix, suffix = doc.presentation.list_markup.get(
            self.start_index, (f'<{tag}><li>', f'</li></{tag}>\n\n'),
        )
        return prefix + text + suffix

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
