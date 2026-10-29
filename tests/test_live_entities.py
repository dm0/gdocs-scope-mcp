"""Verify native smart-chip conversion through isolated STDIO MCP."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from gdocs_scope_mcp.entities import ENTITY_KINDS
from gdocs_scope_mcp.google_api import clients


@pytest.mark.parametrize('kind', ['person', 'dateElement', 'richLink'])
@pytest.mark.parametrize('tool', ['docs_append', 'docs_insert_before',
                                 'docs_insert_after'])
def test_live_entity_round_trip(live_test_doc, isolated_mcp, kind, tool):
    """Read and copy a native entity without flattening its display label."""
    marker = 'CHIP_' + uuid.uuid4().hex
    log = Path(f'/tmp/gdocs-scope-mcp-entities-{tool}-{kind}.log')
    report = {}
    attributes = {
        'person': f'data-mcp-email="{marker.lower()}@example.com"',
        'dateElement': 'data-mcp-timestamp="2026-10-26T12:00:00Z"',
        'richLink': f'data-mcp-uri="https://docs.google.com/document/d/'
        f'{live_test_doc}/edit"',
    }[kind]

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            if tool != 'docs_append':
                await client.call_tool('docs_append', {
                    'doc_id': live_test_doc, 'text': marker + ' anchor',
                })
            arguments = {
                'doc_id': live_test_doc,
                'text': f'{marker} before😀 <span data-mcp-entity="{kind}" '
                f'{attributes}>placeholder</span> **{marker} after**',
            }
            if tool != 'docs_append':
                arguments['anchor'] = marker + ' anchor'
            result = await client.call_tool(tool, arguments,
                                            raise_on_error=False)
            report['result'] = result.structured_content
            assert not result.is_error, report
            read = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            markdown = '\n'.join(section['markdown'] for section in
                                 read.structured_content['sections'])
            soup = BeautifulSoup(markdown, 'html.parser')
            native = clients.get_service('docs', 'v1').documents().get(
                documentId=live_test_doc,
            ).execute()
            paragraphs = [item['paragraph'] for item in native['body'][
                'content'] if 'paragraph' in item]
            paragraph = next(p for p in paragraphs if marker + ' before'
                             in ''.join(e.get('textRun', {}).get('content', '')
                                        for e in p['elements']))
            native_chip = next(e[kind] for e in paragraph['elements']
                               if kind in e)
            chip = soup.find(attrs={
                'data-mcp-id': native_chip[ENTITY_KINDS[kind][0]],
            })
            report['html'] = str(chip)
            entity_id = chip['data-mcp-id']
            details = await client.call_tool('docs_get_entity', {
                'doc_id': live_test_doc, 'entity_id': entity_id,
            })
            report['entity'] = details.structured_content
            assert details.structured_content['kind'] == kind
            assert details.structured_content['end_index'] - (
                details.structured_content['start_index']
            ) == 1
            report['native_paragraph'] = paragraph
            assert any(e.get('textRun', {}).get('textStyle', {}).get('bold')
                       for e in paragraph['elements'] if marker + ' after'
                       in e.get('textRun', {}).get('content', ''))
            copied = await client.call_tool('docs_append', {
                'doc_id': live_test_doc, 'text': str(chip),
            }, raise_on_error=False)
            report['copy_result'] = copied.structured_content
            assert not copied.is_error, report
            reread = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            markup = '\n'.join(s['markdown'] for s in
                               reread.structured_content['sections'])
            copies = BeautifulSoup(markup, 'html.parser').find_all(
                attrs={'data-mcp-entity': kind},
            )
            assert copies[-1]['data-mcp-id'] != entity_id
            assert copies[-1].get_text() == chip.get_text()
            if kind == 'person' and tool == 'docs_append':
                for label in ['before😀', 'after']:
                    edited = await client.call_tool('docs_search_replace', {
                        'doc_id': live_test_doc, 'find': marker + ' ' + label,
                        'replace': marker + ' updated ' + label,
                    })
                    assert edited.structured_content['applied'] == 1
                preserved = await client.call_tool('docs_get_entity', {
                    'doc_id': live_test_doc, 'entity_id': entity_id,
                })
                assert preserved.structured_content['metadata'] == (
                    details.structured_content['metadata']
                )
                unchanged = await client.call_tool('docs_search_replace', {
                    'doc_id': live_test_doc,
                    'find': marker.lower() + '@example.com',
                    'replace': 'ordinary text', 'occurrence': 0,
                })
                assert unchanged.structured_content['applied'] == 0
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))


def test_live_dropdown_selection(live_test_doc, isolated_mcp):
    """Copy a dropdown and change one instance without changing its sibling."""
    log = Path('/tmp/gdocs-scope-mcp-entities-dropdown.log')
    report = {}
    marker = 'DROPDOWN_' + uuid.uuid4().hex

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            arguments = {
                'doc_id': live_test_doc, 'title': marker,
                'options': [{'display_value': 'Ready',
                             'background_color': '#00ff00'},
                            {'display_value': 'Review'}],
            }
            created = await client.call_tool('docs_create_dropdown_definition',
                                             arguments, raise_on_error=False)
            report['definition_result'] = created.structured_content
            assert not created.is_error, report
            definition = created.structured_content['dropdown_definition']
            definition_id = definition['dropdownDefinitionId']
            first, second = definition['dropdownDefinitionProperties'][
                'options']
            html = (f'<span data-mcp-entity="dropdown" '
                    f'data-mcp-definition-id="{definition_id}" '
                    f'data-mcp-option-id="{first["optionId"]}">Ready</span>')
            inserted = await client.call_tool('docs_append', {
                'doc_id': live_test_doc, 'text': marker + ' ' + html + html,
            }, raise_on_error=False)
            report['insertion_result'] = inserted.structured_content
            assert not inserted.is_error, report
            read = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            markdown = '\n'.join(s['markdown'] for s in
                                 read.structured_content['sections'])
            chips = BeautifulSoup(markdown, 'html.parser').find_all(attrs={
                'data-mcp-definition-id': definition_id,
            })
            assert len(chips) == 2  # noqa: PLR2004
            assert chips[0]['data-mcp-id'] != chips[1]['data-mcp-id']
            selected = await client.call_tool('docs_select_dropdown', {
                'doc_id': live_test_doc, 'entity_id': chips[0]['data-mcp-id'],
                'option_id': second['optionId'],
                'expected_option_id': first['optionId'],
            }, raise_on_error=False)
            report['selection_result'] = selected.structured_content
            assert not selected.is_error, report
            details = []
            for chip in chips:
                result = await client.call_tool('docs_get_entity', {
                    'doc_id': live_test_doc, 'entity_id': chip['data-mcp-id'],
                })
                details.append(result.structured_content)
            assert details[0]['metadata']['dropdownProperties'][
                'selectedOptionId'] == second['optionId']
            assert details[1]['metadata']['dropdownProperties'][
                'selectedOptionId'] == first['optionId']
            report['entities'] = details
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))


def test_live_chip_blocks_and_heading(live_test_doc, isolated_mcp):
    """Keep native chips in headings, list continuations and table cells."""
    log = Path('/tmp/gdocs-scope-mcp-entities-blocks.log')
    marker = 'BLOCK_CHIP_' + uuid.uuid4().hex
    expected_count = 4
    email = marker.lower() + '@example.com'
    chip = (f'<span data-mcp-entity="person" data-mcp-email="{email}">'
            'Person</span>')
    report = {}

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            inserted = await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'### {marker} {chip}\n\n- Parent {chip}\n\n'
                f'  Continued {chip}\n\n| Header |\n| --- |\n| {chip} |',
            }, raise_on_error=False)
            report['result'] = inserted.structured_content
            assert not inserted.is_error, report
            assert inserted.structured_content['inserted_entity_count'] == (
                expected_count
            )
            tree = await client.call_tool('docs_get_tree', {
                'doc_id': live_test_doc,
            })
            heading = next(s for s in tree.structured_content['sections']
                           if marker in s['title'])
            assert email in heading['title']
            read = await client.call_tool('docs_read', {
                'doc_id': live_test_doc, 'heading_ids': [heading['id']],
            })
            markup = read.structured_content['sections'][0]['markdown']
            chips = BeautifulSoup(markup, 'html.parser').find_all(attrs={
                'data-mcp-email': email,
            })
            assert len(chips) == expected_count
            assert len({c['data-mcp-id'] for c in chips}) == expected_count
            assert '<table data-mcp-table-ref=' in markup
            report['markdown'] = markup
            for instance in chips:
                entity = await client.call_tool('docs_get_entity', {
                    'doc_id': live_test_doc,
                    'entity_id': instance['data-mcp-id'],
                })
                assert entity.structured_content['metadata'][
                    'personProperties']['email'] == email
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
