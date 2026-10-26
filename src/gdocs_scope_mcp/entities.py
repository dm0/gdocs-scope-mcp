"""Native smart-chip metadata, readable HTML and strict MCP inputs."""

from copy import deepcopy
from datetime import datetime
from html import escape
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

ENTITY_KINDS = {
    'person': ('personId', 'personProperties'),
    'richLink': ('richLinkId', 'richLinkProperties'),
    'dateElement': ('dateId', 'dateElementProperties'),
    'dropdown': ('dropdownId', 'dropdownProperties'),
}


class PersonProperties(BaseModel, populate_by_name=True, extra='allow'):
    """Retain the linked person's email and optional displayed name."""

    email: str
    name: str | None = None


class RichLinkProperties(BaseModel, populate_by_name=True, extra='allow'):
    """Retain a native resource chip, distinct from a text hyperlink."""

    uri: str
    title: str
    mime_type: str | None = Field(default=None, alias='mimeType')


class DateProperties(BaseModel, populate_by_name=True, extra='allow'):
    """Preserve the timestamp and native display/locale configuration."""

    timestamp: str
    display_text: str | None = Field(default=None, alias='displayText')
    date_format: str | None = Field(default=None, alias='dateFormat')
    time_format: str | None = Field(default=None, alias='timeFormat')
    time_zone_id: str | None = Field(default=None, alias='timeZoneId')
    locale: str | None = None


class DropdownProperties(BaseModel, populate_by_name=True, extra='allow'):
    """Separate the instance selection from its shared definition."""

    dropdown_definition_id: str = Field(alias='dropdownDefinitionId')
    selected_option_id: str | None = Field(
        default=None, alias='selectedOptionId',
    )
    display_value: str | None = Field(default=None, alias='displayValue')


class EntityInfo(BaseModel):
    """Expose identity, original UTF-16 range and unmodified API metadata."""

    kind: Literal['person', 'richLink', 'dateElement', 'dropdown']
    entity_id: str
    tab_id: str | None = None
    start_index: int
    end_index: int
    metadata: dict
    dropdown_definition: dict | None = None


class EntityDetails(EntityInfo):
    """Scope one native entity to the document revision that was read."""

    document_id: str
    revision_id: str


class EntityEditResponse(BaseModel):
    """Report one guarded write without promising automatic safe replay."""

    ok: Literal[True] = True
    document_id: str
    tab_id: str | None = None
    operation: str
    revision_id: str | None = None
    entity_id: str | None = None
    selected_option_id: str | None = None
    dropdown_definition: dict | None = None


class EntityInput(BaseModel):
    """Disallow unknown fields and coercion in agent-facing inputs."""

    model_config = ConfigDict(strict=True, extra='forbid')


class PersonInput(EntityInput):
    """Insert by email; Google resolves the native display name."""

    kind: Literal['person']
    email: Annotated[str, Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')]


class DropdownInput(EntityInput):
    """Reference a tab-local definition and optional initial selection."""

    kind: Literal['dropdown']
    definition_id: Annotated[str, Field(min_length=1)]
    selected_option_id: Annotated[str | None, Field(min_length=1)] = None


class RichLinkInput(EntityInput):
    """Insert a native resource chip from an HTTPS resource URI."""

    kind: Literal['richLink']
    uri: Annotated[str, Field(pattern=r'^https://[^\s]+$')]


class DateInput(EntityInput):
    """Insert a UTC timestamp using the native ISO date display."""

    kind: Literal['dateElement']
    timestamp: Annotated[str, Field(
        pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$',
    )]
    date_format: Literal[
        'DATE_FORMAT_MONTH_DAY_ABBREVIATED', 'DATE_FORMAT_MONTH_DAY_FULL',
        'DATE_FORMAT_MONTH_DAY_YEAR_ABBREVIATED', 'DATE_FORMAT_ISO8601',
    ] = 'DATE_FORMAT_ISO8601'
    time_format: Literal[
        'TIME_FORMAT_DISABLED', 'TIME_FORMAT_HOUR_MINUTE',
        'TIME_FORMAT_HOUR_MINUTE_TIMEZONE',
    ] = 'TIME_FORMAT_DISABLED'
    time_zone_id: str | None = None
    locale: str | None = None

    @field_validator('timestamp')
    @classmethod
    def valid_date(cls, value):
        """Reject impossible calendar values before any Google API calls."""
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value


EntityInsertion = Annotated[
    PersonInput | DropdownInput | RichLinkInput | DateInput,
    Field(discriminator='kind'),
]


class DropdownOptionInput(EntityInput):
    """Define one option, with optional native foreground/background colors."""

    display_value: Annotated[str, Field(min_length=1, max_length=200)]
    foreground_color: Annotated[
        str | None, Field(pattern=r'^#[0-9A-Fa-f]{6}$'),
    ] = None
    background_color: Annotated[
        str | None, Field(pattern=r'^#[0-9A-Fa-f]{6}$'),
    ] = None


DropdownOptions = Annotated[
    list[DropdownOptionInput], Field(min_length=2, max_length=50, strict=True),
]


def chip_label(kind: str, properties: dict) -> str:
    """Return a useful display value without inventing an editable text run."""
    if kind == 'person':
        return properties.get('name') or properties.get('email') or '[person]'
    if kind == 'richLink':
        return properties.get('title') or properties.get('uri') or '[resource]'
    if kind == 'dateElement':
        return properties.get('displayText') or properties.get('timestamp',
                                                             '[date]')
    return properties.get('displayValue') or '[dropdown]'


def chip_html(kind: str, identity: str, properties: dict) -> str:
    """Render a self-identifying chip in Markdown's inline HTML subset."""
    attributes = {'data-mcp-entity': kind, 'data-mcp-id': identity}
    if kind == 'person':
        attributes['data-mcp-email'] = properties.get('email', '')
    elif kind == 'richLink':
        attributes['data-mcp-uri'] = properties.get('uri', '')
    elif kind == 'dateElement':
        attributes['data-mcp-timestamp'] = properties.get('timestamp', '')
        for key, value in [('date-format', 'dateFormat'),
                           ('time-format', 'timeFormat'),
                           ('time-zone', 'timeZoneId'), ('locale', 'locale')]:
            if properties.get(value):
                attributes['data-mcp-' + key] = properties[value]
    elif kind == 'dropdown':
        attributes['data-mcp-definition-id'] = properties.get(
            'dropdownDefinitionId', '',
        )
        attributes['data-mcp-option-id'] = properties.get(
            'selectedOptionId', '',
        )
    attrs = ' '.join(f'{key}="{escape(value, quote=True)}"'
                     for key, value in attributes.items())
    return f'<span {attrs}>{escape(chip_label(kind, properties))}</span>'


def chip_input(attributes: dict) -> EntityInsertion:
    """Interpret reader HTML as a new native instance, never reuse its ID."""
    kind = attributes['data-mcp-entity']
    arguments = {'kind': kind}
    fields = {
        'person': {'email': 'data-mcp-email'},
        'richLink': {'uri': 'data-mcp-uri'},
        'dateElement': {'timestamp': 'data-mcp-timestamp',
                        'date_format': 'data-mcp-date-format',
                        'time_format': 'data-mcp-time-format',
                        'time_zone_id': 'data-mcp-time-zone',
                        'locale': 'data-mcp-locale'},
        'dropdown': {'definition_id': 'data-mcp-definition-id',
                     'selected_option_id': 'data-mcp-option-id'},
    }
    for field, attribute in fields.get(kind, {}).items():
        if attribute in attributes:
            arguments[field] = attributes[attribute]
    return TypeAdapter(EntityInsertion).validate_python(arguments)


def insertion_request(entity: EntityInsertion) -> tuple[str, dict]:
    """Build the API payload independently of its final insertion location."""
    if isinstance(entity, PersonInput):
        return 'insertPerson', {'personProperties': {'email': entity.email}}
    if isinstance(entity, RichLinkInput):
        return 'insertRichLink', {'richLinkProperties': {'uri': entity.uri}}
    if isinstance(entity, DateInput):
        properties = {'timestamp': entity.timestamp,
                      'dateFormat': entity.date_format,
                      'timeFormat': entity.time_format}
        if entity.time_zone_id is not None:
            properties['timeZoneId'] = entity.time_zone_id
        if entity.locale is not None:
            properties['locale'] = entity.locale
        return 'insertDate', {'dateElementProperties': properties}
    payload = {'dropdownDefinitionId': entity.definition_id}
    if entity.selected_option_id is not None:
        payload['selectedOptionId'] = entity.selected_option_id
    return 'insertDropdown', payload


def collect_entities(document: dict, tab_id: str | None = None):
    """Walk body/table paragraphs without modifying original API payloads."""
    result = []
    definitions = document.get('dropdownDefinitions', {})

    def visit(content):
        """Keep paragraph element boundaries even inside nested tables."""
        for item in content:
            for element in item.get('paragraph', {}).get('elements', []):
                for kind, (identity, _) in ENTITY_KINDS.items():
                    if kind not in element:
                        continue
                    payload = element[kind]
                    definition_id = payload.get('dropdownProperties', {}).get(
                        'dropdownDefinitionId',
                    )
                    result.append(EntityInfo(
                        kind=kind, entity_id=payload[identity], tab_id=tab_id,
                        start_index=element['startIndex'],
                        end_index=element['endIndex'],
                        metadata=deepcopy(payload),
                        dropdown_definition=deepcopy(definitions.get(
                            definition_id,
                        )),
                    ))
            for row in item.get('table', {}).get('tableRows', []):
                for cell in row['tableCells']:
                    visit(cell['content'])

    visit(document.get('body', {}).get('content', []))
    return result
