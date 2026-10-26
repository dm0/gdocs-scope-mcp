"""Map Pygments tokens to native text styles without rewriting source text."""

from pygments.lexers import get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.token import Token
from pygments.util import ClassNotFound

from .models import (
    GoogleDocumentColor,
    GoogleDocumentOptionalColor,
    GoogleDocumentRgbColor,
    GoogleDocumentTextStyle,
    GoogleDocumentWeightedFontFamily,
)
from .settings import get_settings


def native_color(value: str) -> GoogleDocumentOptionalColor:
    """Convert a six-digit RGB color into the Google Docs color wrapper."""
    value = value.removeprefix('#')
    return GoogleDocumentOptionalColor(color=GoogleDocumentColor(
        rgb_color=GoogleDocumentRgbColor(
            red=int(value[:2], 16) / 255,
            green=int(value[2:4], 16) / 255,
            blue=int(value[4:], 16) / 255,
        ),
    ))


def code_spans(
    content: str, language: str | None,
) -> list[tuple[str, GoogleDocumentTextStyle]]:
    """Highlight a declared language, coalescing adjacent equal styles."""
    settings = get_settings()
    base = GoogleDocumentTextStyle(
        weighted_font_family=GoogleDocumentWeightedFontFamily(
            font_family=settings.code_font_family,
        ),
    )
    if not language or not settings.code_block_highlighting:
        return [(content, base)] if content else []
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return [(content, base)] if content else []
    theme = get_style_by_name(settings.code_block_style)
    default_color = theme.style_for_token(Token)['color'] or '000000'
    spans = []
    # Avoid get_tokens(): its preprocessing may normalize newlines or strip
    # whitespace. Keep the exact text already produced by Markdown/HTML.
    for _, token, value in lexer.get_tokens_unprocessed(content):
        if not value:
            continue
        attributes = theme.style_for_token(token)
        style = base.model_copy(update={
            'foreground_color': native_color(
                attributes['color'] or default_color,
            ),
            'background_color': native_color(
                attributes['bgcolor'] or theme.background_color,
            ),
            'bold': attributes['bold'], 'italic': attributes['italic'],
            'underline': attributes['underline'],
        })
        if spans and spans[-1][1] == style:
            spans[-1] = (spans[-1][0] + value, style)
        else:
            spans.append((value, style))
    # Some specialised lexers transform tokens even without preprocessing.
    # Preserve source text rather than applying styles to mismatched offsets.
    if ''.join(value for value, _ in spans) != content:
        return [(content, base)] if content else []
    return spans
