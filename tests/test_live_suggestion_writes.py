"""Verify public proposal tools through isolated MCP servers."""

# Imported pytest fixtures intentionally retain their names.
# ruff: noqa: F811

import asyncio
import uuid

import pytest

from .test_live_suggestions import cleanup_suggestion_tab, text
from .test_live_table_identity import table_probe  # noqa: F401


@pytest.mark.parametrize('revision_mode', ['required', 'target'])
def test_live_public_suggestions(live_test_doc, table_probe, revision_mode):
    """Exercise text, formatting, independent proposals and decisions."""

    async def run():
        async with table_probe('suggestion-writes-' + revision_mode,
                               revision_mode=revision_mode) as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {
                        'title': 'mcp-sw-' + uuid.uuid4().hex,
                    },
                }}], before)
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                arguments = {'doc_id': live_test_doc, 'tab_id': tab_id}
                await probe.call(0, 'docs_append', {
                    **arguments, 'text': '### Scope\n\nAlpha target\n\n'
                    'Beta target\n\n### Other\n\nOutside target',
                })
                tree = await probe.call(1, 'docs_get_tree', arguments)
                heading_id = next(s['id'] for s in tree['sections']
                                  if s['title'].strip() == 'Scope')

                async def propose(operation, **kwargs):
                    result = await probe.call(0, 'docs_suggest', {
                        **arguments, 'operation': operation, **kwargs,
                    })
                    assert result['comment_update_state'] == 'ALL_SAVED'
                    ids = sorted(set(result['changes']['created'])
                                 | set(result['changes']['updated']))
                    assert ids
                    return result, ids

                async def decide(action, ids):
                    result = await probe.call(1, 'docs_suggestions_manage', {
                        'doc_id': live_test_doc,
                        'action': action, 'suggestion_ids': ids,
                    })
                    assert result['comment_update_state'] == 'ALL_SAVED'
                    assert all(r['outcome'] == 'applied'
                               for r in result['results'])
                    return result

                async def read_native():
                    return await probe.call(1, 'probe_tabs_document')

                _, replacement = await propose({
                    'operation': 'replace', 'find': 'Alpha target',
                    'text': 'Proposed 🦷',
                }, heading_id=heading_id)
                clean = await probe.call(1, 'docs_read', arguments)
                markdown = ''.join(s['markdown'] for s in clean['sections'])
                assert 'Alpha target' in markdown
                assert 'Proposed 🦷' not in markdown
                _, formatting = await propose({
                    'operation': 'format_text', 'find': 'Beta target',
                    'style': {'bold': True},
                })
                probe.report['independent_paragraph_proposals'] = True
                await decide('reject', replacement)
                await decide('accept', formatting)
                repeated = await probe.call(1, 'docs_suggestions_manage', {
                    'doc_id': live_test_doc, 'action': 'accept',
                    'suggestion_ids': formatting,
                })
                assert all(r['outcome'] == 'already_decided'
                           for r in repeated['results'])

                _, insertion = await propose({
                    'operation': 'insert_before', 'anchor': 'Alpha target',
                    'text': '**Rich proposal**',
                })
                assert 'Rich proposal' in text(await read_native(), tab_id)
                await decide('delete', insertion)
                assert 'Rich proposal' not in text(await read_native(), tab_id)

                _, after = await propose({
                    'operation': 'insert_after', 'anchor': 'Alpha target',
                    'text': 'Inserted after', 'rich': False,
                })
                await decide('accept', after)
                _, deletion = await propose({
                    'operation': 'delete_paragraph',
                    'anchor': 'Inserted after',
                })
                await decide('accept', deletion)
                assert 'Inserted after' not in text(
                    await read_native(), tab_id,
                )

                _, appended = await propose({
                    'operation': 'append',
                    'text': 'Scoped append', 'rich': False,
                }, heading_id=heading_id)
                await decide('accept', appended)
                body = text(await read_native(), tab_id)
                assert body.index('Scoped append') < body.index('Other')

                code, code_ids = await propose({
                    'operation': 'append', 'text': '```python\nx = 1\n```',
                })
                assert code['warnings']
                await decide('reject', code_ids)
                probe.report['public_workflow_passed'] = True
            finally:
                if tab_id:
                    await cleanup_suggestion_tab(probe, tab_id, before['tabs'])

    asyncio.run(run())
