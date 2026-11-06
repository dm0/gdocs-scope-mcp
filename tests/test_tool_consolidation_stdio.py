"""Capture real static catalogs and validate opt-in adapters over STDIO."""

import asyncio
import hashlib
import json
import os

import pytest

from .native_snapshot_assertions import assert_tabs_unchanged

VARIANTS = ['baseline', 'insertion', 'status', 'both']


@pytest.mark.parametrize('access_mode', ['full_drive', 'selected_files'])
def test_stdio_study_catalogs(isolated_mcp, tmp_path, access_mode):
    """Expose all four variants in fresh processes, without Google access."""
    async def run():
        catalogs = {}
        for variant in VARIANTS:
            env = {**os.environ,
                   'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant,
                   'GDOCS_SCOPE_MCP_ACCESS_MODE': access_mode}
            async with isolated_mcp(
                tmp_path / f'{variant}.stderr', environment=env,
            ) as (client, info):
                tools = [t.model_dump(mode='json', exclude_none=True)
                         for t in await client.list_tools()]
                assert tools == [t.model_dump(mode='json', exclude_none=True)
                                 for t in await client.list_tools()]
                catalog = {
                    'instructions': client.initialize_result.instructions,
                    'tools': tools,
                }
                encoded = json.dumps(catalog, sort_keys=True).encode()
                (tmp_path / f'{variant}.json').write_text(json.dumps({
                    'server': info, 'catalog': catalog,
                    'catalog_sha256': hashlib.sha256(encoded).hexdigest(),
                    'serialized_bytes': len(encoded),
                }, indent=2))
                catalogs[variant] = {t['name']: t for t in tools}
        base = catalogs['baseline']
        for variant, catalog in catalogs.items():
            removed = set()
            added = set()
            if variant in {'insertion', 'both'}:
                removed.update({'docs_append', 'docs_insert_before',
                                'docs_insert_after'})
                added.add('docs_insert')
            if variant in {'status', 'both'}:
                removed.update({'docs_resolve_comment', 'docs_reopen_comment'})
                added.add('docs_comment_status')
            assert set(catalog) == set(base) - removed | added
            for name in set(base) - removed:
                assert catalog[name] == base[name]
    asyncio.run(run())


@pytest.mark.live
@pytest.mark.parametrize('variant', VARIANTS)
def test_live_consolidation_lifecycle(
    isolated_mcp, live_test_doc, tmp_path, variant,
):
    """Check native edits/status, strict revisions and tab cleanup."""
    async def run():
        env = {**os.environ, 'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant}
        control_env = {
            **env, 'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': 'baseline',
        }
        report = {'variant': variant, 'trace': []}
        async with isolated_mcp(
            tmp_path / 'control.stderr', probe=True, environment=control_env,
        ) as (control, _info), isolated_mcp(
            tmp_path / 'server.stderr', environment=env,
        ) as (client, info):
            report['server'] = info

            async def native():
                return (await control.call_tool('probe_tabs_document', {})
                        ).structured_content

            async def batch(requests):
                result = await control.call_tool('probe_batch', {
                    'requests': requests,
                    'write_control': {'requiredRevisionId':
                                      (await native())['revisionId']},
                })
                assert result.structured_content['accepted']
                return result.structured_content['response']

            async def call(name, args):
                result = await client.call_tool(name, args)
                report['trace'].append({'tool': name, 'result':
                                        result.structured_content})
                return result.structured_content

            before = await native()
            tab_id = None
            comment_id = None
            try:
                created = await batch([{'addDocumentTab': {
                    'tabProperties': {'title': 'Study 1 adapter check'},
                }}])
                tab_id = created['replies'][0]['addDocumentTab'][
                    'tabProperties']['tabId']
                args = {'doc_id': live_test_doc, 'tab_id': tab_id}

                async def insert(position, text, **options):
                    target = {'position': position}
                    if position != 'append':
                        target['anchor'] = 'Distinct anchor 😀'
                    if variant in {'insertion', 'both'}:
                        return await call('docs_insert', {
                            **args, 'text': text, 'target': target, **options,
                        })
                    return await call(
                        'docs_append' if position == 'append'
                        else f'docs_insert_{position}',
                        {**args, 'text': text, **options,
                         **{k: v for k, v in target.items()
                            if k != 'position'}},
                    )

                await insert('append', 'Distinct anchor 😀', rich=False)
                revision = (await native())['revisionId']
                await insert('before', '**Bold before**')
                await insert('after', '**Literal after**', rich=False)
                await insert('append', '| Header |\n| --- |\n| Cell🦷 |')
                state = await native()
                selected = next(t for t in state['tabs']
                                if t['tabProperties']['tabId'] == tab_id)
                paragraphs = selected['documentTab']['body']['content']
                elements = [
                    e for p in paragraphs
                    for e in p.get('paragraph', {}).get('elements', [])
                ]
                text = ''.join(e.get('textRun', {}).get('content', '')
                               for e in elements)
                assert ('Bold before\nDistinct anchor 😀\n**Literal after**'
                        in text)
                assert any('table' in p for p in paragraphs)
                assert any(e.get('textRun', {}).get('textStyle', {})
                           .get('bold') for e in elements)
                with pytest.raises(Exception, match='EDIT_CONFLICT'):
                    await insert('append', 'STALE MUST NOT APPEAR',
                                 expected_revision_id=revision)
                created_comment = await call('docs_add_comment', {
                    **args, 'anchor_text': 'Distinct anchor 😀',
                    'comment': 'Synthetic Study 1 check',
                })
                comment_id = created_comment['comment_id']
                for action in ('resolve', 'reopen'):
                    thread_args = {'doc_id': live_test_doc,
                                   'comment_id': comment_id,
                                   'reply': 'Synthetic status check'}
                    name = f'docs_{action}_comment'
                    if variant in {'status', 'both'}:
                        name = 'docs_comment_status'
                        thread_args['action'] = action
                    receipt = await call(name, thread_args)
                    assert receipt['comment_update_state'] == 'ALL_SAVED'
                    read = await call('docs_read_comments', {
                        'doc_id': live_test_doc, 'comment_id': comment_id,
                    })
                    assert (read['comments'][0]['resolved']
                            == (action == 'resolve'))
                report['checks_passed'] = True
            finally:
                if comment_id:
                    await call('docs_delete_comment', {
                        'doc_id': live_test_doc, 'comment_id': comment_id,
                    })
                if tab_id:
                    await batch([{'deleteTab': {'tabId': tab_id}}])
                assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
                report['cleanup_passed'] = True
                (tmp_path / 'report.json').write_text(
                    json.dumps(report, indent=2),
                )
        report['processes_reaped'] = True
        (tmp_path / 'report.json').write_text(json.dumps(report, indent=2))
    asyncio.run(run())
