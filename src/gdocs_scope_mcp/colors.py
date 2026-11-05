"""Resolve the Google Docs editor palette without CSS-name ambiguity."""

import re
from typing import Annotated

from pydantic import AfterValidator, Field

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError

# Verified against the English Google Docs highlight picker on 2026-11-03:
# aria-label on each grid cell and its swatch's background-color (80 cells).
_GRAY_NAMES = ('black', 'dark gray 4', 'dark gray 3', 'dark gray 2',
               'dark gray 1', 'gray', 'light gray 1', 'light gray 2',
               'light gray 3', 'white')
_HUES = ('red berry', 'red', 'orange', 'yellow', 'green', 'cyan',
         'cornflower blue', 'blue', 'purple', 'magenta')
_ROWS = (
    '000000 434343 666666 999999 B7B7B7 CCCCCC D9D9D9 EFEFEF F3F3F3 FFFFFF',
    '980000 FF0000 FF9900 FFFF00 00FF00 00FFFF 4A86E8 0000FF 9900FF FF00FF',
    'E6B8AF F4CCCC FCE5CD FFF2CC D9EAD3 D0E0E3 C9DAF8 CFE2F3 D9D2E9 EAD1DC',
    'DD7E6B EA9999 F9CB9C FFE599 B6D7A8 A2C4C9 A4C2F4 9FC5E8 B4A7D6 D5A6BD',
    'CC4125 E06666 F6B26B FFD966 93C47D 76A5AF 6D9EEB 6FA8DC 8E7CC3 C27BA0',
    'A61C00 CC0000 E69138 F1C232 6AA84F 45818E 3C78D8 3D85C6 674EA7 A64D79',
    '85200C 990000 B45F06 BF9000 38761D 134F5C 1155CC 0B5394 351C75 741B47',
    '5B0F00 660000 783F04 7F6000 274E13 0C343D 1C4587 073763 20124D 4C1130',
)
_NAMES = (_GRAY_NAMES, _HUES, *(
    tuple(f'{tone} {hue} {level}' for hue in _HUES)
    for tone, level in [('light', 3), ('light', 2), ('light', 1),
                        ('dark', 1), ('dark', 2), ('dark', 3)]
))
GOOGLE_COLORS = {name: '#' + value
                 for names, row in zip(_NAMES, _ROWS)
                 for name, value in zip(names, row.split())}
COLOR_NAMES = {value: name for name, value in GOOGLE_COLORS.items()}


def resolve_color(value: str) -> str:
    """Normalize a Google palette name or six-digit hex to RGB hex."""
    normalized = ' '.join(value.lower().split())
    if normalized in GOOGLE_COLORS:
        return GOOGLE_COLORS[normalized]
    if re.fullmatch(r'#[0-9a-f]{6}', normalized):
        return normalized.upper()
    raise ValueError('Use a Google Docs palette name or #RRGGBB.')


def validate_setting(value: str) -> str:
    """Keep reset distinct from concrete colors in the public schema."""
    if value == 'reset':
        return value
    resolve_color(value)
    return value


ColorSetting = Annotated[str, Field(strict=True, description=(
    'Google Docs English palette name (e.g. yellow, light orange 2), '
    '#RRGGBB, or reset to remove direct formatting. Names are not CSS names. '
    'Google green=#00FF00, orange=#FF9900. Names ignore case/extra spaces.'
)), AfterValidator(validate_setting)]


def native_color(value: str) -> dict:
    """Convert a validated name/hex into the native optional-color wrapper."""
    color = resolve_color(value)[1:]
    return {'color': {'rgbColor': {
        channel: int(color[index:index + 2], 16) / 255
        for channel, index in [('red', 0), ('green', 2), ('blue', 4)]
    }}}


def color_label(optional) -> str | None:
    """Render an opaque native color as its exact palette name or hex."""
    if optional is None or optional.color is None:
        return None
    rgb = optional.color.rgb_color
    if rgb is None:
        return None
    value = '#' + ''.join(f'{round(channel * 255):02X}'
                          for channel in (rgb.red, rgb.green, rgb.blue))
    return COLOR_NAMES.get(value, value)


def invalid_color(description: str) -> None:
    """Report malformed rich color markup before any external mutations."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use Google palette names or #RRGGBB in '
        'data-mcp-color/data-mcp-background-color; CSS color values must '
        'be #RRGGBB. Use reset only in formatting tools.',
    ))


def html_colors(element) -> dict[str, str]:
    """Parse the bounded HTML color contract, rejecting conflicting inputs."""
    result = {}
    for key in ('color', 'background-color'):
        value = element.get('data-mcp-' + key)
        if value is not None:
            try:
                result[key] = resolve_color(str(value))
            except ValueError:
                invalid_color(f'Invalid data-mcp-{key} value.')
    for declaration in str(element.get('style', '')).split(';'):
        key, separator, value = declaration.partition(':')
        key, value = key.strip().lower(), value.strip()
        if key not in {'color', 'background-color'}:
            continue
        if not separator or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            invalid_color('CSS colors require #RRGGBB; use data-mcp '
                          'attributes for Google palette names.')
        color = value.upper()
        if key in result and result[key] != color:
            invalid_color('Conflicting CSS and data-mcp color values.')
        result[key] = color
    return result
