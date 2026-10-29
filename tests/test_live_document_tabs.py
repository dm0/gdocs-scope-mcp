"""Exercise tab-scoped public tools through isolated real STDIO servers."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio
import uuid

from bs4 import BeautifulSoup

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import table_probe  # noqa: F401


def markdown(read):
    """Combine only the selected tab's returned sections."""
    return '\n'.join(section['markdown'] for section in read['sections'])


def test_live_document_tabs(live_test_doc, table_probe):
    """Create temporary root/child tabs; verify isolation and exact cleanup."""

    async def run():
        async with table_probe('document-tabs') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            original_tabs = before['tabs']
            original_read = await probe.call(
                0,
                'docs_read',
                {
                    'doc_id': live_test_doc,
                },
            )
            parent = None
            comment_id = None
            try:
                created = await probe.batch(
                    [
                        {
                            'addDocumentTab': {
                                'tabProperties': {
                                    'title': 'mcp-tabs-' + uuid.uuid4().hex
                                },
                            }
                        }
                    ],
                    before,
                )
                parent = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                current = await probe.call(0, 'probe_tabs_document')
                created = await probe.batch(
                    [
                        {
                            'addDocumentTab': {
                                'tabProperties': {
                                    'title': 'mcp-nested',
                                    'parentTabId': parent,
                                },
                            }
                        }
                    ],
                    current,
                )
                child = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                listing = await probe.call(
                    0,
                    'docs_tabs_list',
                    {
                        'doc_id': live_test_doc,
                    },
                )
                listed = next(
                    t for t in listing['tabs'] if t['tab_id'] == child
                )
                assert listed['parent_tab_id'] == parent
                assert listed['depth'] == 1
                text = (
                    '### Identical heading\n\nIdentical target\n\n'
                    '```python\nprint(42)\n```\n\n'
                    '| same | same |\n| --- | --- |\n| one | two |'
                )
                for tab_id in (parent, child):
                    await probe.call(
                        0,
                        'docs_append',
                        {
                            'doc_id': live_test_doc,
                            'tab_id': tab_id,
                            'text': text,
                        },
                    )
                child_read = await probe.call(
                    0,
                    'docs_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                    },
                )
                assert child_read['tab_id'] == child
                assert child_read['tab_count'] == len(listing['tabs'])
                assert child_read['partial'] is False
                assert '```python\nprint(42)' in markdown(child_read)
                outline = await probe.call(
                    0,
                    'docs_get_tree',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                    },
                )
                assert outline['tabs'] == listing['tabs']
                assert outline['tab_id'] == child
                heading = next(
                    s['id']
                    for s in outline['sections']
                    if s['title'].strip() == 'Identical heading'
                )
                await probe.call(
                    0,
                    'docs_search_replace',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'find': 'Identical target',
                        'replace': 'child replacement',
                        'heading_id': heading,
                    },
                )
                await probe.call(
                    0,
                    'docs_search_replace',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'find': 'child replacement',
                        'replace': 'child final',
                        'occurrence': 0,
                    },
                )
                parent_read = await probe.call(
                    1,
                    'docs_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': parent,
                    },
                )
                assert 'Identical target' in markdown(parent_read)
                assert 'child final' not in markdown(parent_read)
                tables = await probe.call(
                    0,
                    'docs_tables_list',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                    },
                )
                reference = tables['tables'][0]['table_ref']
                assert tables['tab_id'] == child
                snapshot = await probe.call(
                    0,
                    'docs_table_snapshot',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'table_ref': reference,
                        'cells': ['A2'],
                    },
                )
                assert snapshot['tab_id'] == child
                patched = await probe.call(
                    0,
                    'docs_table_patch',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'table_ref': reference,
                        'base_token': snapshot['base_token'],
                        'changes': [
                            {'address': 'A2', 'markdown': '**child cell**'}
                        ],
                    },
                )
                assert patched['tab_id'] == child
                result = await probe.call(
                    0,
                    'docs_table_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'table_ref': reference,
                    },
                )
                assert 'child cell' in str(result['rows'])
                assert result['tab_id'] == child
                wrong = await probe.clients[0].call_tool(
                    'docs_table_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': parent,
                        'table_ref': reference,
                    },
                    raise_on_error=False,
                )
                assert wrong.is_error
                assert wrong.structured_content['code'] == 'TAB_MISMATCH'
                assert repr(child) in wrong.structured_content[
                    'suggested_action']
                formatting = await probe.call(0, 'docs_table_snapshot', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'table_ref': reference, 'cells': ['A1'],
                    'fields': ['cell.background_color'],
                })
                formatted = await probe.call(0, 'docs_table_format', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'table_ref': reference,
                    'base_token': formatting['base_token'],
                    'changes': {'cells': [{'address': 'A1',
                                           'background_color': '#FFEEDD'}]},
                })
                assert formatted['tab_id'] == child
                merging = await probe.call(0, 'docs_table_snapshot', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'table_ref': reference, 'cells': ['A1', 'B1'],
                    'fields': ['merge'],
                })
                merged = await probe.call(0, 'docs_table_structure', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'table_ref': reference,
                    'base_token': merging['base_token'],
                    'operation': {'type': 'merge_cells',
                                  'start_cell': 'A1', 'end_cell': 'B1'},
                })
                assert merged['table_ref']
                assert merged['tab_id'] == child
                assert not merged['reference_refresh_required']
                await probe.call(0, 'docs_table_read', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'table_ref': merged['table_ref'],
                })
                email = 'mcp-tabs-' + uuid.uuid4().hex + '@example.com'
                await probe.call(
                    0,
                    'docs_append',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'text': '<span data-mcp-entity="person" '
                        f'data-mcp-email="{email}">Person</span>',
                    },
                )
                read = await probe.call(
                    0,
                    'docs_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                    },
                )
                chip = BeautifulSoup(markdown(read), 'html.parser').find(
                    attrs={'data-mcp-email': email},
                )
                assert chip is not None
                entity = await probe.call(
                    0,
                    'docs_get_entity',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': child,
                        'entity_id': chip['data-mcp-id'],
                    },
                )
                assert entity['tab_id'] == child
                created_comment = await probe.call(0, 'docs_add_comment', {
                    'doc_id': live_test_doc, 'tab_id': child,
                    'anchor_text': 'child final',
                    'comment': 'Nested tab review',
                })
                comment_id = created_comment['comment_id']
                native_comments = await probe.call(0, 'docs_read_comments', {
                    'doc_id': live_test_doc, 'comment_id': comment_id,
                })
                native_thread = native_comments['comments'][0]
                assert native_thread['tab_id'] == child
                assert native_thread['anchored'] and native_thread['ranges']
                nested_reply = await probe.call(0, 'docs_reply_to_comment', {
                    'doc_id': live_test_doc, 'comment_id': comment_id,
                    'reply': 'Nested thread reply',
                })
                assert nested_reply['tab_id'] == child
                await probe.call(0, 'docs_delete_comment', {
                    'doc_id': live_test_doc, 'comment_id': comment_id,
                })
                comment_id = None
                default = await probe.call(
                    1,
                    'docs_read',
                    {
                        'doc_id': live_test_doc,
                    },
                )
                assert default['tab_id'] == original_read['tab_id']
                # Compare selectors on the current snapshot: Markdown image
                # URLs from the initial read may already have rotated. Native
                # preservation is checked separately in the cleanup below.
                explicit = await probe.call(1, 'docs_read', {
                    'doc_id': live_test_doc,
                    'tab_id': original_read['tab_id'],
                })
                assert default['revision_id'] == explicit['revision_id']
                assert default['sections'] == explicit['sections']
                probe.report['checks_passed'] = True
            finally:
                if comment_id:
                    await probe.call(0, 'docs_delete_comment', {
                        'doc_id': live_test_doc, 'comment_id': comment_id,
                    })
                if parent:
                    current = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': parent}}], current
                    )
                after = await probe.call(0, 'probe_tabs_document')
                assert_tabs_unchanged(original_tabs, after['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
