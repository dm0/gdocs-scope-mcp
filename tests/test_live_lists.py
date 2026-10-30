"""Opt-in multi-paragraph list verification through isolated STDIO MCP."""

import asyncio
import json
import re
import uuid
from html import unescape
from pathlib import Path

import pytest

from gdocs_scope_mcp.google_api import clients


@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('ordered', [False, True])
def test_native_continuation_lists(live_test_doc, isolated_mcp, tool, ordered):
    """Verify list identity, marker removal, indentation and inline styles."""
    marker = 'LIST_' + uuid.uuid4().hex
    mode = 'ordered' if ordered else 'unordered'
    log = Path(f'/tmp/gdocs-scope-mcp-{tool}-lists-{mode}.log')
    report = {}
    documents = clients.get_service('docs', 'v1').documents()

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'{marker} left\n\n{marker} anchor\n\n{marker} right',
            })
            bullet, indent = ('1.', '   ') if ordered else ('-', '  ')
            text = (
                f'{marker} before\n\n'
                f'{bullet} **{marker} first😀**\n\n'
                f'{indent}{marker} continuation '
                '[link](https://example.com).\n\n'
                f'{indent}{bullet} *{marker} child*\n\n'
                f'{indent}{marker} after child\n\n'
                f'{bullet} {marker} second\n\n'
                f'{bullet} {marker} third\n\n{marker} after'
            )
            arguments = {'doc_id': live_test_doc, 'text': text}
            if tool != 'docs_append':
                arguments['anchor'] = marker + ' anchor'
            result = await client.call_tool(tool, arguments)
            report['result'] = result.structured_content
            native = documents.get(documentId=live_test_doc).execute()
            rows = {}
            for item in native['body']['content']:
                paragraph = item.get('paragraph', {})
                value = ''.join(e.get('textRun', {}).get('content', '')
                                for e in paragraph.get('elements', []))
                if value.startswith(marker):
                    rows[value.rstrip('\n').removeprefix(marker + ' ')] = (
                        paragraph
                    )
            report['paragraphs'] = rows
            report['lists'] = native.get('lists', {})
            assert list(rows) == (
                ['left', 'before', 'first😀', 'continuation link.', 'child',
                 'after child', 'second', 'third', 'after', 'anchor', 'right']
                if tool == 'docs_insert_before' else
                ['left', 'anchor', 'before', 'first😀', 'continuation link.',
                 'child', 'after child', 'second', 'third', 'after', 'right']
                if tool == 'docs_insert_after' else
                ['left', 'anchor', 'right', 'before', 'first😀',
                 'continuation link.', 'child', 'after child', 'second',
                 'third', 'after']
            )
            identity = rows['first😀']['bullet']['listId']
            for label in ('first😀', 'second', 'third', 'child'):
                assert rows[label]['bullet']['listId'] == identity
                assert rows[label]['bullet'].get('nestingLevel', 0) == (
                    1 if label == 'child' else 0
                )
            for label in ('continuation link.', 'after child'):
                paragraph = rows[label]
                assert 'bullet' not in paragraph
                style = paragraph['paragraphStyle']
                assert style['indentStart'] == style['indentFirstLine']
                assert style['indentStart']['magnitude'] == 36  # noqa: PLR2004
            for label in ('left', 'anchor', 'right', 'before', 'after'):
                assert 'bullet' not in rows[label]
            assert rows['first😀']['elements'][0]['textRun'][
                'textStyle']['bold']
            assert rows['child']['elements'][0]['textRun'][
                'textStyle']['italic']
            assert any(e.get('textRun', {}).get('textStyle', {}).get('link',
                       {}).get('url') == 'https://example.com'
                       for e in rows['continuation link.']['elements'])
            read = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            markdown = '\n'.join(s['markdown'] for s in
                                 read.structured_content['sections'])
            assert marker + ' after child' in unescape(markdown)
            if ordered:
                exported = clients.get_service('drive', 'v3').files(
                ).export_media(fileId=live_test_doc,
                               mimeType='text/plain').execute().decode('utf-8')
                for number, label in enumerate(('first😀', 'second', 'third'),
                                               start=1):
                    assert re.search(
                        rf'(?m)^\s*{number}\.\s+{marker} {label}\r?$',
                        exported,
                    )
                report['rendered_numbers'] = [1, 2, 3]
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
