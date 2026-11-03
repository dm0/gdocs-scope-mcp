"""Verify the editor palette and lossless ordinary-text color conversion."""

from copy import deepcopy

import pytest

from gdocs_scope_mcp.colors import GOOGLE_COLORS, native_color, resolve_color
from gdocs_scope_mcp.documents.native_models import (
    GoogleDocument,
    GoogleDocumentTextStyle,
)
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests
from gdocs_scope_mcp.rich_text.models import InsertionTable
from gdocs_scope_mcp.rich_text.parsing import html_to_gpars
from gdocs_scope_mcp.tables.patch import compile_cell

from .test_literal_rendering import native_document


def test_google_palette():
    """Keep editor names distinct from CSS and preserve verified yellow levels."""
    assert len(GOOGLE_COLORS) == len(set(GOOGLE_COLORS.values())) == 80
    assert resolve_color(' Light  Orange 2 ') == '#F9CB9C'
    assert resolve_color('green') == '#00FF00'
    assert resolve_color('light yellow 1') == '#FFD966'
    assert resolve_color('light yellow 2') == '#FFE599'


@pytest.mark.parametrize('paragraph_style', [
    {}, {'alignment': 'CENTER'},
    {'namedStyleType': 'HEADING_2', 'headingId': 'heading'},
])
def test_colors_read_write_roundtrip(paragraph_style):
    """Retain text, range colors and paragraph fill through reader markup."""
    paragraph_style = {**paragraph_style, 'shading': {
        'backgroundColor': native_color('light orange 2')}}
    style = {'foregroundColor': native_color('green'),
             'backgroundColor': native_color('#123456'), 'bold': True}
    source = native_document([(' x😀 & <b> ', style)],
                             paragraph_style=paragraph_style)
    markdown = GoogleDocument.model_validate(deepcopy(source)).to_markdown()
    assert 'data-mcp-color="green"' in markdown
    assert 'data-mcp-background-color="#123456"' in markdown
    assert 'data-mcp-background-color="light orange 2"' in markdown
    requests = markdown_to_requests(markdown, newline_before=False)
    assert ''.join(r['insertText']['text'] for r in requests
                   if 'insertText' in r) == ' x😀 & <b> \n'
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if r.get('updateTextStyle', {}).get('textStyle')]
    assert [GoogleDocumentTextStyle.model_validate(s) for s in styles] == [
        GoogleDocumentTextStyle.model_validate(style)]
    assert any(r.get('updateParagraphStyle', {}).get('paragraphStyle', {})
               .get('shading') == paragraph_style['shading'] for r in requests)


def test_nearest_color_wins_and_paragraph_fill_is_not_highlight():
    """Honor nearest explicit colors without copying paragraph fill to text."""
    requests = markdown_to_requests(
        '<p data-mcp-background-color="yellow" data-mcp-color="red">'
        '<span data-mcp-color="blue"><b>A</b></span>B</p>')
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if r.get('updateTextStyle', {}).get('textStyle')]
    assert [GoogleDocumentTextStyle.model_validate(s) for s in styles] == [
        GoogleDocumentTextStyle(bold=True, foreground_color=native_color('blue')),
        GoogleDocumentTextStyle(foreground_color=native_color('red'))]


@pytest.mark.parametrize('markup', [
    '<span data-mcp-color="lime">bad</span>',
    '<span style="color:green">bad</span>',
    '<span data-mcp-color="reset">bad</span>',
    '<span style="color:#GG0000">bad</span>',
    '<span data-mcp-color="red" style="color:#0000FF">bad</span>',
    '<p data-mcp-background-color="invalid"></p>',
])
def test_invalid_rich_colors_fail_before_compilation(markup):
    """Reject malformed and conflicting declarations before making requests."""
    with pytest.raises(ToolFailureError) as caught:
        markdown_to_requests(markup)
    assert caught.value.failure.code == 'INVALID_ARGUMENT'


def test_colored_cell_paragraph_and_patch():
    """Support cell paragraph fill and inline-only color patches separately."""
    markup = ('<table><tr><td><p data-mcp-background-color="yellow">'
              '<span data-mcp-color="red">Cell</span></p></td></tr></table>')
    table = next(p for p in html_to_gpars(markup) if isinstance(p, InsertionTable))
    assert table.cells[0][0].text == 'Cell'
    assert any(r.get('updateParagraphStyle', {}).get('paragraphStyle', {}).get(
        'shading') for r in table.cells[0][0].requests)
    patch = compile_cell('<span data-mcp-color="green" '
                         'data-mcp-background-color="yellow">Cell</span>')
    assert patch.text == 'Cell'
    assert not any('updateParagraphStyle' in r for r in patch.requests)
    style = next(r['updateTextStyle']['textStyle'] for r in patch.requests
                 if r.get('updateTextStyle', {}).get('textStyle'))
    assert GoogleDocumentTextStyle.model_validate(style) == GoogleDocumentTextStyle(
        foreground_color=native_color('green'), background_color=native_color('yellow'))
