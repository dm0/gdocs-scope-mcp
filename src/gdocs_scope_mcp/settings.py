"""Load editing and formatting settings from JSON and environment."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

FontName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1),
]
HexColor = Annotated[str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$')]


def config_path() -> Path:
    """Find the default config or require an explicitly chosen file."""
    explicit = os.environ.get('GOOGLE_DOCS_MCP_CONFIG')
    if explicit is not None:
        if not explicit.strip():
            raise ValueError('GOOGLE_DOCS_MCP_CONFIG must name a JSON file')
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ValueError(
                f'GOOGLE_DOCS_MCP_CONFIG file does not exist: {path}'
            )
        return path
    root = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'gdocs-scope-mcp' / 'config.json'


class Settings(BaseSettings):
    """Configure editing and formatting; environment overrides JSON."""

    model_config = SettingsConfigDict(
        env_prefix='GOOGLE_DOCS_MCP_', extra='forbid', frozen=True,
    )
    write_revision_mode: Literal['required', 'target'] = 'required'

    code_font_family: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1),
    ] = 'Roboto Mono'
    inline_code_color: Annotated[
        str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$'),
    ] = '#188038'
    code_block_highlighting: bool = True
    code_block_style: str = 'default'
    code_block_line_spacing: Annotated[
        float, Field(gt=0, allow_inf_nan=False),
    ] = 1.0
    code_block_theme_background: bool = False
    code_block_named_ranges: bool = True
    read_inline_code: bool = True
    read_inline_code_fonts: list[FontName] | None = None
    read_inline_code_colors: list[HexColor] | None = None
    read_inline_code_match: Literal['font', 'color', 'both'] = 'both'
    read_code_block_heuristic: bool = True
    read_native_code_blocks: bool = True
    read_code_block_fonts: list[FontName] | None = None
    read_code_block_line_spacing: Annotated[
        float, Field(gt=0, allow_inf_nan=False),
    ] = 1.0
    read_code_block_require_background: bool = False
    read_code_block_min_lines: Annotated[int, Field(ge=1)] = 2

    @field_validator('code_block_style')
    @classmethod
    def validate_style(cls, value: str) -> str:
        """Reject unknown Pygments themes before serving tool calls."""
        try:
            get_style_by_name(value)
        except ClassNotFound as exc:
            raise ValueError(f'Unknown Pygments style: {value}') from exc
        return value

    @field_validator('inline_code_color')
    @classmethod
    def normalize_color(cls, value: str) -> str:
        """Use one canonical representation for RGB hex colors."""
        return value.upper()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use explicit values, environment, JSON, then field defaults."""
        return (
            init_settings, env_settings,
            JsonConfigSettingsSource(
                settings_cls, json_file=config_path(),
                json_file_encoding='utf-8',
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings once for this server process."""
    return Settings()


_code_settings: ContextVar[Settings | None] = ContextVar(
    'code_formatting_settings', default=None,
)


def get_code_settings() -> Settings:
    """Use request-local code formatting or the cached server defaults."""
    override = _code_settings.get()
    return override if override is not None else get_settings()


@contextmanager
def code_formatting(
    *, style: str | None = None, theme_background: bool | None = None,
) -> Iterator[None]:
    """Scope formatting overrides to one call, including on failure."""
    settings = get_code_settings()
    updates = {}
    if style is not None:
        updates['code_block_style'] = Settings.validate_style(style)
    if theme_background is not None:
        updates['code_block_theme_background'] = theme_background
    token = _code_settings.set(settings.model_copy(update=updates))
    try:
        yield
    finally:
        _code_settings.reset(token)
