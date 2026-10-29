"""Internal rich_text.parsing responsibilities."""

from functools import lru_cache
from html import escape

import mistune

from gdocs_scope_mcp.rich_text.cells import convert_table
from gdocs_scope_mcp.rich_text.paragraphs import (
    parse_html,
)


class DocsHTMLRenderer(mistune.HTMLRenderer):
    """Keep Markdown soft wraps from becoming Google Docs paragraph breaks."""

    def softbreak(self) -> str:
        """Render a soft-wrapped source line as a space, as HTML would."""
        return ' '

    def image(self, text: str, url: str, title: str | None = None) -> str:
        """Preserve file sources for the opt-in upload stage to validate."""
        if url.lower().startswith('file:'):
            # Retain Mistune's alt/title escaping while allowing only this
            # image source through. Links and other protocols stay unchanged.
            placeholder = 'https://gdocs-scope-mcp.invalid/local'
            rendered = super().image(text, placeholder, title)
            return rendered.replace(
                f'src="{placeholder}"', f'src="{escape(url, quote=True)}"', 1,
            )
        return super().image(text, url, title)


@lru_cache
def _md_instance() -> mistune.Markdown:
    md = mistune.create_markdown(
        renderer=DocsHTMLRenderer(escape=False),
        plugins=['strikethrough', 'table', 'url', 'superscript', 'subscript']
    )

    def parse_ext_h(_block, m, state):
        heading = m.group('atx')
        contents = m.group('contents')
        state.append_token(
            {
                'type': 'heading',
                'text': contents,
                'attrs': {'level': len(heading)},
            }
        )
        return m.end() + 1

    md.block.register(
        'extended_headings',
        r'^ {0,3}(?P<atx>#{7,10})\s+(?P<contents>.+)$',
        parse_ext_h,
    )

    return md


def markdown_to_html(markdown: str) -> str:
    """Render the supported Markdown syntax as HTML."""
    html = _md_instance()(markdown)
    assert isinstance(html, str), f'Expected a string, got {type(html)}'
    return html


def html_to_gpars(html, start=0):
    """Parse supported body HTML using explicit structural table dispatch."""
    return parse_html(html, start, table_converter=convert_table)
