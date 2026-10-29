"""Inspect native entities and guard definition/instance mutations."""

# Resolve the existing authentication/service boundary without import cycles.
# ruff: noqa: PLC0415

import uuid

from .document_tabs import select
from .entities import EntityDetails, EntityEditResponse, collect_entities
from .errors import ToolFailureError
from .models import EditFailedResponse
from .revision_guards import revision_changed, uses_target_revision
from .table_insertion import TableInsertionPlan

INSERT_ENTITY_KINDS = {'insertPerson', 'insertRichLink', 'insertDate',
                       'insertDropdown'}


def _fail(description: str, code: str = 'INVALID_ARGUMENT') -> None:
    """Return actionable failures without silently replacing native chips."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action='Read the document and call docs_get_entity to '
        'refresh native IDs, tab, definition and option IDs before retrying.',
    ))


def _tab_document(service, doc_id: str, tab_id: str | None = None):
    """Select one tab explicitly; never retarget a missing requested tab."""
    document = service.documents().get(
        documentId=doc_id, includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    ).execute()

    selected = select(document, tab_id)
    return document, selected, selected['_mcp_tab_id']


def _service():
    """Reuse the project's configured OAuth service provider."""
    from . import docs_edit
    return docs_edit._get_service('docs', 'v1')


def get_entity(doc_id: str, entity_id: str, tab_id: str | None = None):
    """Return original metadata and the shared dropdown definition, if any."""
    document, tab, actual_tab = _tab_document(_service(), doc_id, tab_id)
    entity = next((item for item in collect_entities(tab, actual_tab)
                   if item.entity_id == entity_id), None)
    if entity is None:
        _fail('Native entity was not found in this tab.', 'RESOURCE_NOT_FOUND')
    return EntityDetails(**entity.model_dump(), document_id=doc_id,
                         revision_id=document['revisionId'])


def _option(definitions, definition_id, option_id):
    """Validate a shared definition and an optional selected option."""
    definition = definitions.get(definition_id)
    if definition is None:
        _fail('Dropdown definition does not exist in the destination tab. '
              'Cross-document definitions are not copied automatically.')
    options = definition['dropdownDefinitionProperties']['options']
    if option_id is not None and not any(o['optionId'] == option_id
                                         for o in options):
        _fail('Selected option does not belong to the dropdown definition.')


def validate_insertions(service, doc_id, requests, required_revision=None, *,
                        tab_id=None):
    """Validate all entity dependencies before image uploads or any writes."""
    planned = (list(requests.iter_requests())
               if isinstance(requests, TableInsertionPlan) else requests)
    entities = [r for r in planned if INSERT_ENTITY_KINDS.intersection(r)]
    if not entities:
        return
    document, tab, _ = _tab_document(service, doc_id, tab_id)
    if (required_revision and document['revisionId'] != required_revision
            and not uses_target_revision()):
        revision_changed()
        _fail('Document changed while planning the smart-chip insertion. '
              'No insertion was submitted.', 'GOOGLE_API_ERROR')
    for request in entities:
        if 'insertDropdown' in request:
            payload = request['insertDropdown']
            _option(tab.get('dropdownDefinitions', {}),
                    payload['dropdownDefinitionId'],
                    payload.get('selectedOptionId'))


def create_dropdown_definition(doc_id, title, options, tab_id=None):
    """Create a reusable definition without changing existing instances."""
    service = _service()
    document, _, actual_tab = _tab_document(service, doc_id, tab_id)
    converted = []
    for option in options:
        native = {'optionId': 'dropdownItem.' + uuid.uuid4().hex[:12],
                  'displayValue': option.display_value}
        style = {}
        for field, value in [('foregroundColor', option.foreground_color),
                             ('backgroundColor', option.background_color)]:
            if value:
                color = value.removeprefix('#')
                style[field] = {'color': {'rgbColor': {
                    channel: int(color[index:index + 2], 16) / 255
                    for channel, index in [('red', 0), ('green', 2),
                                           ('blue', 4)]
                }}}
        if style:
            native['textStyle'] = style
        converted.append(native)
    definition = {
        'dropdownDefinitionId': 'kix.' + uuid.uuid4().hex[:12],
        'dropdownDefinitionProperties': {'title': title, 'options': converted},
    }
    payload = {'dropdownDefinition': definition}
    if actual_tab is not None:
        payload['tabId'] = actual_tab
    response = service.documents().batchUpdate(documentId=doc_id, body={
        'requests': [{'createDropdownDefinition': payload}],
        'writeControl': {'requiredRevisionId': document['revisionId']},
    }).execute()
    return EntityEditResponse(
        document_id=doc_id, tab_id=actual_tab,
        operation='create_dropdown_definition',
        revision_id=response.get('writeControl', {}).get('requiredRevisionId'),
        dropdown_definition=response.get('replies', [{}])[0].get(
            'createDropdownDefinition', {},
        ).get('dropdownDefinition', definition),
    )


def select_dropdown(doc_id, entity_id, option_id, tab_id=None,
                    expected_option_id=None):
    """Change one instance only; never mutate its shared definition."""
    service = _service()
    document, tab, actual_tab = _tab_document(service, doc_id, tab_id)
    entity = next((item for item in collect_entities(tab, actual_tab)
                   if item.entity_id == entity_id), None)
    if entity is None or entity.kind != 'dropdown':
        _fail('Dropdown instance was not found.', 'RESOURCE_NOT_FOUND')
    properties = entity.metadata['dropdownProperties']
    if (expected_option_id is not None
            and properties.get('selectedOptionId') != expected_option_id):
        _fail('Dropdown selection changed since it was read.')
    _option(tab.get('dropdownDefinitions', {}),
            properties['dropdownDefinitionId'], option_id)
    payload = {'dropdownId': entity_id,
               'dropdownProperties': {'selectedOptionId': option_id},
               'fields': 'selectedOptionId'}
    if actual_tab is not None:
        payload['tabId'] = actual_tab
    response = service.documents().batchUpdate(documentId=doc_id, body={
        'requests': [{'updateDropdownProperties': payload}],
        'writeControl': {'requiredRevisionId': document['revisionId']},
    }).execute()
    return EntityEditResponse(
        document_id=doc_id, tab_id=actual_tab, operation='select_dropdown',
        revision_id=response.get('writeControl', {}).get('requiredRevisionId'),
        entity_id=entity_id, selected_option_id=option_id,
    )
