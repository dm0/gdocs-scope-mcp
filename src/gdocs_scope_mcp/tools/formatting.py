"""Expose the shared palette and anchored color-formatting operations."""

from pydantic import BaseModel

from gdocs_scope_mcp.colors import GOOGLE_COLORS, ColorSetting
from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.formatting import FormatResponse, format_colors
from gdocs_scope_mcp.documents.tabs import TabId
from gdocs_scope_mcp.tool_inputs import (
    ExpectedRevision,
    NonemptyText,
    PositiveInteger,
)
from gdocs_scope_mcp.tools.schema import tool_response_schema


class PaletteColor(BaseModel):
    """Describe a stable Google editor palette entry."""

    name: str
    hex: str


class PaletteResponse(BaseModel):
    """Return all eight palette rows in editor order."""

    rows: list[list[PaletteColor]]


def register(mcp):
    """Register explicit read-only discovery and guarded formatting tools."""
    @mcp.tool(annotations={'readOnlyHint': True, 'destructiveHint': False,
                           'idempotentHint': True, 'openWorldHint': False})
    def docs_get_color_palette() -> PaletteResponse:
        """
        List all 80 Google Docs English color names with #RRGGBB values.

        Fixed palette shared by documents; no Google access or doc_id needed.
        Rows follow the editor: grayscale, hues, light 3/2/1, dark 1/2/3.
        Use these names in formatting tools and data-mcp-color or
        data-mcp-background-color HTML attributes. These are Google names,
        not CSS names: green=#00FF00, orange=#FF9900, gray=#CCCCCC.
        Custom colors use #RRGGBB. Palette verified in the editor 2026-11-03.
        """
        entries = [PaletteColor(name=name, hex=value)
                   for name, value in GOOGLE_COLORS.items()]
        return PaletteResponse(rows=[entries[i:i + 10]
                                     for i in range(0, len(entries), 10)])

    annotations = {'readOnlyHint': False, 'destructiveHint': False,
                   'idempotentHint': True, 'openWorldHint': True}

    @mcp.tool(output_schema=tool_response_schema(FormatResponse),
              annotations=annotations)
    def docs_format_text(
        doc_id: str, anchor_text: NonemptyText, *,
        foreground_color: ColorSetting | None = None,
        background_color: ColorSetting | None = None,
        occurrence: PositiveInteger | None = None,
        heading_id: str | None = None, tab_id: TabId | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> FormatResponse | EditFailedResponse:
        """
        Set or clear colors on exactly the matched ordinary text fragment.

        Colors accept Google palette names, #RRGGBB or reset. Discover names
        with docs_get_color_palette. Omitted/null preserves a property;
        reset removes direct formatting and allows inheritance (foreground)
        or no direct highlighting (background). At least one is required.
        Other text styles, links, content and paragraph fills are preserved.
        Literal case-insensitive anchor must fit one paragraph and ordinary
        source runs; matches crossing chips/images/omitted structure fail.
        Omitted occurrence requires a unique match; positive occurrence picks
        the 1-based match in document order. heading_id scopes its subtree.
        Omitted tab_id selects the first tab, never the last-used tab.
        Required revision mode validates target content/styles before bounded
        retries. Target mode lets Google merge without local retries.
        expected_revision_id forces strict required without retries.
        Unknown write outcomes are never replayed; read before retrying.
        """
        return format_colors(
            doc_id, anchor_text, foreground_color=foreground_color,
            background_color=background_color, occurrence=occurrence,
            heading_id=heading_id, tab_id=tab_id,
            expected_revision_id=expected_revision_id,
        )

    @mcp.tool(output_schema=tool_response_schema(FormatResponse),
              annotations=annotations)
    def docs_format_paragraph(
        doc_id: str, anchor_text: NonemptyText, *,
        background_color: ColorSetting,
        occurrence: PositiveInteger | None = None,
        heading_id: str | None = None, tab_id: TabId | None = None,
        expected_revision_id: ExpectedRevision | None = None,
    ) -> FormatResponse | EditFailedResponse:
        """
        Set a whole paragraph's background fill, distinct from highlighting.

        background_color is a Google palette name, #RRGGBB or reset to remove
        direct fill. Discover names with docs_get_color_palette. Applies to
        the single paragraph containing the literal case-insensitive anchor,
        including headings, list paragraphs and table-cell paragraphs.
        Table-cell fill, text highlighting and all unrelated styles/content
        are preserved. Anchor must fit ordinary source text in one paragraph.
        Omitted occurrence requires a unique match; positive occurrence picks
        the 1-based text match in document order. heading_id scopes a subtree.
        Omitted tab_id selects the first tab. Required mode validates original
        target/styles before bounded retries; target delegates merging to
        Google without retries. expected_revision_id forces strict required.
        Unknown write outcomes are never replayed; read before retrying.
        """
        return format_colors(
            doc_id, anchor_text, paragraph=True,
            background_color=background_color, occurrence=occurrence,
            heading_id=heading_id, tab_id=tab_id,
            expected_revision_id=expected_revision_id,
        )
