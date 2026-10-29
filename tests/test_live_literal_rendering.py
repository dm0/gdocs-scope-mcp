"""Check literal read/copy fidelity through isolated STDIO MCP servers."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio
from html import escape

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


def paragraph_signatures(content):
    """Compare actual characters and supported styles without native IDs."""
    signatures = []
    for item in content:
        if 'table' in item:
            signatures.append(('table', [
                [paragraph_signatures(cell['content'])
                 for cell in row['tableCells']]
                for row in item['table']['tableRows']
            ]))
        elif 'paragraph' in item and paragraph_text(item).strip():
            paragraph = item['paragraph']
            characters = []
            for element in paragraph['elements']:
                run = element.get('textRun', {})
                style = run.get('textStyle', {})
                characters.extend((char, bool(style.get('bold')),
                                   bool(style.get('italic')),
                                   style.get('link', {}).get('url'))
                                  for char in run.get('content', '')
                                  if char != '\n')
            signatures.append((paragraph.get('paragraphStyle', {}).get(
                'namedStyleType', 'NORMAL_TEXT'), characters))
    return signatures


def test_live_literal_read_copy(live_test_doc, table_probe):
    """Copy source text/styles exactly and keep raw-text editing usable."""
    heading = 'Literal # heading 🦷'
    body = ('Use <b>literal</b> &amp; **stars** [linked] '
            'https://example.com / \\path\u000b1. plain, not a list')
    cell = '<i>literal cell</i> &amp; **plain** [x] 🦷'

    async def run():
        async with table_probe('literal-rendering') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tabs = []

            async def native():
                """Get a revision-coherent all-tabs snapshot over MCP."""
                return await probe.call(0, 'probe_tabs_document')

            try:
                for name in ('literal-source', 'literal-copy'):
                    result = await probe.batch([{'addDocumentTab': {
                        'tabProperties': {'title': name},
                    }}], await native())
                    tabs.append(result['response']['replies'][0][
                        'addDocumentTab']['tabProperties']['tabId'])
                source, target = tabs
                text = heading + '\n' + body + '\n'
                body_start = 1 + len((heading + '\n').encode('utf-16-le')) // 2
                requests = [{'insertText': {
                    'location': {'index': 1, 'tabId': source}, 'text': text,
                }}, {'updateParagraphStyle': {
                    'range': {'startIndex': 1, 'endIndex': body_start,
                              'tabId': source},
                    'paragraphStyle': {'namedStyleType': 'HEADING_1'},
                    'fields': 'namedStyleType',
                }}]
                for label, style in [
                    ('**stars**', {'bold': True}),
                    ('[linked]', {'italic': True, 'link': {
                        'url': 'https://example.com/?a=1&b=2',
                    }}),
                ]:
                    start = body_start + len(body[:body.index(label)].encode(
                        'utf-16-le')) // 2
                    requests.append({'updateTextStyle': {
                        'range': {'startIndex': start,
                                  'endIndex': start + len(label),
                                  'tabId': source},
                        'textStyle': style, 'fields': ','.join(style),
                    }})
                await probe.batch(requests, await native())
                await probe.call(0, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': source,
                    'text': '<table><tr><td><b>' + escape(cell)
                            + '</b></td></tr></table>',
                })
                read = await probe.call(0, 'docs_read', {
                    'doc_id': live_test_doc, 'tab_id': source,
                })
                markup = ''.join(s['markdown'] for s in read['sections'])
                await probe.call(1, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': target, 'text': markup,
                })
                document = await native()
                contents = {
                    tab['tabProperties']['tabId']: tab['documentTab'][
                        'body']['content'] for tab in document['tabs']
                }
                assert paragraph_signatures(contents[source]) == (
                    paragraph_signatures(contents[target])
                )
                await probe.call(1, 'docs_search_replace', {
                    'doc_id': live_test_doc, 'tab_id': target,
                    'find': '<b>literal</b>', 'replace': 'kept literal',
                })
                document = await native()
                target_content = next(t['documentTab']['body']['content']
                    for t in document['tabs']
                    if t['tabProperties']['tabId'] == target)
                assert body.replace('<b>literal</b>', 'kept literal') in (
                    ''.join(paragraph_text(p) for p in target_content)
                )
                probe.report['checks_passed'] = True
            finally:
                for tab in reversed(tabs):
                    await probe.batch([{'deleteTab': {'tabId': tab}}],
                                      await native())
                after = await native()
                assert_tabs_unchanged(before['tabs'], after['tabs'])
                probe.report['cleanup_passed'] = True

    asyncio.run(run())
