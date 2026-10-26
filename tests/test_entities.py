"""Exercise native identity, display HTML and editing around smart chips."""

# Independent UTF-16 offsets and native payloads are deliberate expectations.
# ruff: noqa: PLR2004

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastmcp import Client
from jsonschema import validate

from gdocs_scope_mcp import docs_edit, server
from gdocs_scope_mcp.md2requests import (
    inserted_text_from_requests,
    markdown_to_requests,
)


def call(name, **arguments):
    """Check serialized tool results through the actual MCP boundary."""
    async def run():
        async with Client(server.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            result = await client.call_tool(name, arguments,
                                            raise_on_error=False)
            validate(result.structured_content, tools[name].outputSchema)
            return result
    return asyncio.run(run())


@pytest.fixture(params=['person', 'richLink', 'dateElement', 'dropdown'])
def entity_document(request, simple_document):
    """Use API-shaped metadata with one native slot after an emoji."""
    kind = request.param
    identity, properties_key, properties = {
        'person': ('personId', 'personProperties',
                   {'email': 'reader@example.com', 'name': 'Alice & Bob'}),
        'richLink': ('richLinkId', 'richLinkProperties',
                     {'uri': 'https://docs.google.com/document/d/example/edit',
                      'title': 'Report <draft>',
                      'mimeType': 'application/vnd.google-apps.document'}),
        'dateElement': ('dateId', 'dateElementProperties',
                        {'timestamp': '2026-10-26T12:00:00Z',
                         'displayText': '2026-10-26',
                         'dateFormat': 'DATE_FORMAT_ISO8601'}),
        'dropdown': ('dropdownId', 'dropdownProperties',
                     {'dropdownDefinitionId': 'kix.definition',
                      'selectedOptionId': 'dropdownItem.first',
                      'displayValue': 'Approved'}),
    }[kind]
    document = deepcopy(simple_document)
    # Both the chip and its trailing text have independent API source ranges.
    first = document['body']['content'][0]
    first['endIndex'] = 16
    first['paragraph']['elements'] = [
        {'startIndex': 1, 'endIndex': 9,
         'textRun': {'content': 'Before😀', 'textStyle': {}}},
        {'startIndex': 9, 'endIndex': 10,
         kind: {identity: 'kix.entity', properties_key: properties,
                'textStyle': {}, 'suggestedInsertionIds': ['suggestion']}},
        {'startIndex': 10, 'endIndex': 16,
         'textRun': {'content': 'After\n', 'textStyle': {}}},
    ]
    # Keep all following headings; shift them independently of backend helpers.
    for item in document['body']['content'][1:]:
        item['startIndex'] += 2
        item['endIndex'] += 2
        for element in item['paragraph']['elements']:
            element['startIndex'] += 2
            element['endIndex'] += 2
    definition = {
        'dropdownDefinitionId': 'kix.definition',
        'dropdownDefinitionProperties': {
            'title': 'Status',
            'options': [
                {'optionId': 'dropdownItem.first', 'displayValue': 'Approved'},
                {'optionId': 'dropdownItem.second', 'displayValue': 'Review'},
            ],
        },
    }
    document['dropdownDefinitions'] = {'kix.definition': definition}
    return document, kind, properties


def configure(mock_docs, document):
    """Return fresh payloads because table validators flatten source data."""
    mock_docs.get.return_value.execute.side_effect = lambda: deepcopy(document)


def test_entity_read_and_inspection(mock_docs, entity_document):
    """Display escaped labels inline and retain full metadata on demand."""
    document, kind, properties = entity_document
    configure(mock_docs, document)
    read = call('docs_read', doc_id='example')
    assert not read.is_error
    soup = BeautifulSoup(read.structured_content['sections'][0]['markdown'],
                         'html.parser')
    chip = soup.find(attrs={'data-mcp-entity': kind})
    assert chip['data-mcp-id'] == 'kix.entity'
    assert chip.get_text() in {'Alice & Bob', 'Report <draft>',
                               '2026-10-26', 'Approved'}
    assert 'Before😀' in soup.get_text() and 'After' in soup.get_text()
    details = call('docs_get_entity', doc_id='example', entity_id='kix.entity')
    data = details.structured_content
    assert not details.is_error
    assert data['start_index'] == 9 and data['end_index'] == 10
    assert data['kind'] == kind
    assert data['metadata']['suggestedInsertionIds'] == ['suggestion']
    assert properties in data['metadata'].values()
    assert bool(data['dropdown_definition']) is (kind == 'dropdown')
    scoped = call('docs_read', doc_id='example', heading_ids=['parent'])
    assert 'data-mcp-entity' not in str(scoped.structured_content)
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('operation', ['docs_search_replace',
                                      'docs_batch_replace'])
def test_edits_around_chips_keep_native_offsets(
    mock_docs, entity_document, operation,
):
    """Never count a chip's displayed label as editable UTF-16 source text."""
    document, _, _ = entity_document
    configure(mock_docs, document)
    arguments = ({'find': 'After', 'replace': 'Next'}
                 if operation == 'docs_search_replace' else
                 {'replacements': [{'find': 'After', 'replace': 'Next'}]})
    result = call(operation, doc_id='example', **arguments)
    assert not result.is_error
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[0]['insertText']['location']['index'] == 10
    mock_docs.batchUpdate.reset_mock()
    arguments = ({'find': 'Before😀After', 'replace': 'Lost chip'}
                 if operation == 'docs_search_replace' else
                 {'replacements': [{'find': 'Before😀After',
                                    'replace': 'Lost chip'}]})
    result = call(operation, doc_id='example', **arguments)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('newline_before', [False, True])
def test_converter_recreates_native_entities(
    mock_docs, entity_document, newline_before,
):
    """Copy semantics preserve properties, but never reuse the instance ID."""
    document, kind, _ = entity_document
    configure(mock_docs, document)
    read = docs_edit.read('example')
    chip = BeautifulSoup(read.sections[0].markdown, 'html.parser').find(
        attrs={'data-mcp-entity': kind},
    )
    requests = markdown_to_requests(
        f'Left😀 {chip} **Right**', start=1, newline_before=newline_before,
    )
    native = next(r for r in requests if any(key in r for key in (
        'insertPerson', 'insertRichLink', 'insertDate', 'insertDropdown',
    )))
    assert 'kix.entity' not in str(native)
    payload = next(iter(native.values()))
    assert payload['location']['index'] == 8 + int(newline_before)
    text = inserted_text_from_requests(requests)
    assert text == ('\nLeft😀 \ufffc Right' if newline_before else
                    'Left😀 \ufffc Right\n')
    style = next(r['updateTextStyle'] for r in requests
                 if 'updateTextStyle' in r)
    assert style['range'] == {'startIndex': 10 + int(newline_before),
                              'endIndex': 15 + int(newline_before)}


@pytest.mark.parametrize('markup', [
    '<span data-mcp-entity="person">Alice</span>',
    '<span data-mcp-entity="unknown">Unknown</span>',
    '<span data-mcp-entity="person" data-mcp-email="invalid">Alice</span>',
    '<span data-mcp-entity="dateElement" '
    'data-mcp-timestamp="2026-02-30T00:00:00Z">Date</span>',
    '<span data-mcp-entity="person" data-mcp-email="a@b.org">'
    '<span data-mcp-entity="person" data-mcp-email="b@c.org">B</span></span>',
])
def test_invalid_chip_html_fails_before_writes(mock_docs, markup):
    """Labels and malformed metadata cannot silently become ordinary text."""
    result = call('docs_append', doc_id='example', text=markup)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.batchUpdate.assert_not_called()


def test_missing_entity_and_definition_fail_safely(mock_docs):
    """A stale ID or foreign dropdown template must not fall back to text."""
    result = call('docs_get_entity', doc_id='example', entity_id='missing')
    assert result.is_error
    assert result.structured_content['code'] == 'RESOURCE_NOT_FOUND'
    result = call('docs_append', doc_id='example', text=(
        '<span data-mcp-entity="dropdown" '
        'data-mcp-definition-id="foreign">Status</span>'
    ))
    assert result.is_error
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('tool', ['docs_append', 'docs_insert_before',
                                 'docs_insert_after'])
@pytest.mark.parametrize('rich', [False, True])
def test_chip_insertion_receipts(mock_docs, tool, rich):
    """Share native conversion and literal behavior across insertion tools."""
    html = '<span data-mcp-entity="person" data-mcp-email="a@b.org">A</span>'
    arguments = {'doc_id': 'example', 'text': html, 'rich': rich}
    if tool != 'docs_append':
        arguments['anchor'] = 'Introduction'
    result = call(tool, **arguments)
    assert not result.is_error
    assert result.structured_content['inserted_entity_count'] == int(rich)
    assert result.structured_content['inserted_image_count'] == 0
    expected = '\ufffc' if rich else html
    expected = (expected + '\n' if tool == 'docs_insert_before' else
                '\n' + expected)
    assert result.structured_content.get('appended', result.structured_content[
        'inserted_text'] if tool != 'docs_append' else '') == expected
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert ('writeControl' in body) is rich
    if rich:
        assert body['writeControl'] == {'requiredRevisionId': 'revision'}


def test_definition_creation_has_typed_receipt(mock_docs):
    """Return usable IDs and native colors without changing instances."""
    result = call('docs_create_dropdown_definition', doc_id='example',
                  title='Status', options=[
                      {'display_value': 'Ready',
                       'background_color': '#00ff00'},
                      {'display_value': 'Review'},
                  ])
    assert not result.is_error
    data = result.structured_content
    assert 'result' not in data
    definition = data['dropdown_definition']
    assert definition['dropdownDefinitionId'].startswith('kix.')
    options = definition['dropdownDefinitionProperties']['options']
    assert options[0]['optionId'] != options[1]['optionId']
    assert options[0]['textStyle']['backgroundColor'] == {'color': {
        'rgbColor': {'red': 0, 'green': 1, 'blue': 0},
    }}
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert list(body['requests'][0]) == ['createDropdownDefinition']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}


@pytest.mark.parametrize('options', [[], [{'display_value': 'Single'}],
                                   [{'display_value': 'A', 'extra': True},
                                    {'display_value': 'B'}]])
def test_bad_definition_inputs_fail_before_google(mock_docs, options):
    """Reject missing options and unknown fields through argument schemas."""
    result = call('docs_create_dropdown_definition', doc_id='example',
                  title='Status', options=options)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


def test_instance_selection_preserves_definition(mock_docs, entity_document):
    """An instance update contains no shared-definition mutation request."""
    document, kind, _ = entity_document
    configure(mock_docs, document)
    result = call('docs_select_dropdown', doc_id='example',
                  entity_id='kix.entity', option_id='dropdownItem.second',
                  expected_option_id='dropdownItem.first')
    if kind != 'dropdown':
        assert result.is_error
        mock_docs.batchUpdate.assert_not_called()
        return
    assert not result.is_error
    assert result.structured_content['selected_option_id'] == (
        'dropdownItem.second'
    )
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['requests'] == [{'updateDropdownProperties': {
        'dropdownId': 'kix.entity',
        'dropdownProperties': {'selectedOptionId': 'dropdownItem.second'},
        'fields': 'selectedOptionId',
    }}]
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    mock_docs.batchUpdate.reset_mock()
    conflict = call('docs_select_dropdown', doc_id='example',
                    entity_id='kix.entity', option_id='dropdownItem.second',
                    expected_option_id='different')
    assert conflict.is_error
    mock_docs.batchUpdate.assert_not_called()


def test_paragraph_deletion_protects_chips(mock_docs, entity_document):
    """Refuse destructive paragraph-level fallback that would remove a chip."""
    document, _, _ = entity_document
    configure(mock_docs, document)
    result = call('docs_delete_paragraph', doc_id='example', anchor='Before')
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.batchUpdate.assert_not_called()


def test_entity_inspection_is_tab_scoped(mock_docs, entity_document):
    """Resolve nested tabs explicitly rather than finding an unrelated ID."""
    document, kind, _ = entity_document
    native = {'title': 'Tabs', 'documentId': 'example', 'revisionId': 'rev',
              'tabs': [{'tabProperties': {'tabId': 'first'},
                        'documentTab': {'body': {'content': []}},
                        'childTabs': [{
                            'tabProperties': {'tabId': 'nested'},
                            'documentTab': document,
                        }]}]}
    configure(mock_docs, native)
    missing = call('docs_get_entity', doc_id='example', entity_id='kix.entity')
    assert missing.is_error
    found = call('docs_get_entity', doc_id='example', entity_id='kix.entity',
                 tab_id='nested')
    assert not found.is_error
    assert found.structured_content['tab_id'] == 'nested'
    assert found.structured_content['kind'] == kind
    absent = call('docs_get_entity', doc_id='example', entity_id='kix.entity',
                  tab_id='deleted')
    assert absent.is_error


def test_native_chips_in_list_and_table_cells():
    """Share inline conversion inside lists and structural table plans."""
    html = '<span data-mcp-entity="person" data-mcp-email="a@b.org">A</span>'
    requests = markdown_to_requests('- Parent\n\n  Continued ' + html)
    assert any('insertPerson' in r for r in requests)
    assert inserted_text_from_requests(requests) == (
        '\nParent\nContinued \ufffc'
    )
    plan = markdown_to_requests(
        '<table><tr><td>' + html + '</td></tr></table>',
    )
    assert any('insertPerson' in r for r in plan.iter_requests())
    assert plan.text() == '\n\ufffc\n'


def test_captured_mixed_chip_paragraph(mock_docs, simple_document):
    """Validate captured API payloads with adjacent chips of all four kinds."""
    captured = json.loads((Path(__file__).parent / 'fixtures' /
                           'smart_entities.json').read_text())
    document = deepcopy(simple_document)
    document['body']['content'] = [{
        'startIndex': 1, 'endIndex': 6,
        'paragraph': {'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                      'elements': captured['elements'] + [{
                          'startIndex': 5, 'endIndex': 6,
                          'textRun': {'content': '\n', 'textStyle': {}},
                      }]},
    }]
    document['dropdownDefinitions'] = captured['dropdownDefinitions']
    configure(mock_docs, document)
    result = call('docs_read', doc_id='example')
    assert not result.is_error
    html = result.structured_content['sections'][0]['markdown']
    chips = BeautifulSoup(html, 'html.parser').find_all('span')
    assert [chip['data-mcp-entity'] for chip in chips] == [
        'person', 'dateElement', 'richLink', 'dropdown',
    ]
    assert [chip.get_text() for chip in chips] == [
        'reader@example.com', '2026-10-26', 'Example document', 'Review',
    ]
    copied = call('docs_append', doc_id='example', text=html)
    assert not copied.is_error
    assert copied.structured_content['inserted_entity_count'] == 4


def test_entity_insertion_revision_race_prevents_writes(
    mock_docs, simple_document,
):
    """Do not apply an old insertion index after dependency preflight races."""
    original = deepcopy(simple_document)
    changed = deepcopy(original)
    changed['revisionId'] = 'later-revision'
    mock_docs.get.return_value.execute.side_effect = [original, changed]
    result = call('docs_append', doc_id='example', text=(
        '<span data-mcp-entity="person" data-mcp-email="a@b.org">A</span>'
    ))
    assert result.is_error
    assert result.structured_content['code'] == 'GOOGLE_API_ERROR'
    mock_docs.batchUpdate.assert_not_called()


def test_date_display_configuration_survives_conversion():
    """Keep native timezone, locale and date/time formats while copying."""
    html = ('<span data-mcp-entity="dateElement" '
            'data-mcp-timestamp="2026-10-26T12:00:00Z" '
            'data-mcp-time-zone="Europe/Paris" data-mcp-locale="fr" '
            'data-mcp-date-format="DATE_FORMAT_MONTH_DAY_FULL" '
            'data-mcp-time-format="TIME_FORMAT_HOUR_MINUTE">Date</span>')
    requests = markdown_to_requests(html)
    inserted = next(r['insertDate'] for r in requests if 'insertDate' in r)
    assert inserted['dateElementProperties'] == {
        'timestamp': '2026-10-26T12:00:00Z', 'timeZoneId': 'Europe/Paris',
        'locale': 'fr', 'dateFormat': 'DATE_FORMAT_MONTH_DAY_FULL',
        'timeFormat': 'TIME_FORMAT_HOUR_MINUTE',
    }


def test_entities_inside_table_cells_are_inspectable(
    mock_docs, entity_document,
):
    """Keep native identities and source ranges in recursive cell reads."""
    document, kind, _ = entity_document
    paragraph = document['body']['content'][0]
    document['body']['content'] = [{
        'startIndex': 0, 'endIndex': 20,
        'table': {'rows': 1, 'columns': 1, 'tableRows': [{
            'tableCells': [{'startIndex': 0, 'endIndex': 18,
                            'content': [paragraph],
                            'tableCellStyle': {'rowSpan': 1,
                                               'columnSpan': 1}}],
        }]},
    }]
    configure(mock_docs, document)
    read = call('docs_read', doc_id='example')
    assert not read.is_error
    assert '<table>' in read.structured_content['sections'][0]['markdown']
    found = call('docs_get_entity', doc_id='example', entity_id='kix.entity')
    assert not found.is_error
    assert found.structured_content['kind'] == kind
    assert found.structured_content['start_index'] == 9


def test_chip_heading_preserves_visible_title(mock_docs, entity_document):
    """Show chip labels in outline titles without making them editable runs."""
    document, kind, _ = entity_document
    document['body']['content'][0]['paragraph']['paragraphStyle'] = {
        'namedStyleType': 'HEADING_1', 'headingId': 'chip-heading',
    }
    configure(mock_docs, document)
    tree = call('docs_get_tree', doc_id='example')
    assert not tree.is_error
    heading = next(s for s in tree.structured_content['sections']
                   if s['id'] == 'chip-heading')
    assert heading['title'] != 'Before😀After\n'
    read = call('docs_read', doc_id='example', heading_ids=['chip-heading'])
    assert not read.is_error
    assert f'data-mcp-entity="{kind}"' in str(read.structured_content)
