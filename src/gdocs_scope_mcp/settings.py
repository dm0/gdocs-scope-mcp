"""Load code formatting defaults from JSON and environment overrides."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints, field_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound


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
    """Configure code font and inline color; environment overrides JSON."""

    model_config = SettingsConfigDict(
        env_prefix='GOOGLE_DOCS_MCP_', extra='forbid', frozen=True,
    )

    code_font_family: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1),
    ] = 'Roboto Mono'
    inline_code_color: Annotated[
        str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$'),
    ] = '#188038'
    code_block_highlighting: bool = True
    code_block_style: str = 'default'

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
