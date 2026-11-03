"""Compare rich insertions from hostile source styles with a clean baseline."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio

import pytest

from gdocs_scope_mcp.documents.snapshots import normalized

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401

ORIGINAL = {'Root', 'Anchor', 'Tail'}
MARKUP = ('# Title🦷\n\n## Subtitle\n\n'
          + '\n\n'.join('#' * (level + 2) + f' Heading {level}'
                         for level in range(1, 7))
          + '\n\nPlain text\n\n'
          'A **bold** *italic* <u>under</u> ~~strike~~ '
          '[link](https://example.com) `inline` x<sup>2</sup>\n\n'
          '<p style="text-align: center;">Centered</p>\n\n'
          '```python\nreturn 1\n```\n\nLast plain')


def presentation(paragraphs):
    """Compare text and all styles, excluding generated heading identities."""
    result = normalized(paragraphs)
    for item in result:
        item['paragraph']['paragraphStyle'].pop('headingId', None)
    return result


def document_tab(document, tab_id):
    """Select a temporary scenario's native tab."""
    return next(t['documentTab'] for t in document['tabs']
                if t['tabProperties']['tabId'] == tab_id)


@pytest.mark.live
@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
def test_live_insertion_ignores_source_styles(
    live_test_doc, table_probe, tool,
):
    """Preserve explicit formatting while discarding every source override."""
    async def run():
        async with table_probe('insertion-styles-' + tool) as probe:
            before = await probe.call(0, 'probe_tabs_document')

            async def native():
                """Read all tabs through the isolated MCP server."""
                return await probe.call(0, 'probe_tabs_document')

            golden = None
            for source_kind in ('clean', 'styled', 'heading', 'code',
                                'bullets', 'numbered',
                                'nested-bullets', 'nested-numbered'):
                tab_id = None

                def selected(document):
                    """Select the temporary scenario's native content."""
                    return next(t['documentTab'] for t in document['tabs']
                                # Calls finish within this loop iteration.
                                if t['tabProperties']['tabId'] == tab_id)  # noqa: B023

                try:
                    result = await probe.batch([{'addDocumentTab': {
                        'tabProperties': {'title': 'styles-' + source_kind},
                    }}], await native())
                    tab_id = result['response']['replies'][0][
                        'addDocumentTab']['tabProperties']['tabId']
                    nested = '\t\t' if source_kind.startswith('nested') else ''
                    await probe.batch([{'insertText': {
                        'location': {'index': 1, 'tabId': tab_id},
                        'text': f'Root\n{nested}Anchor\n{nested}Tail',
                    }}], await native())
                    document = await native()
                    content = selected(document)['body']['content']
                    if source_kind.endswith(('bullets', 'numbered')):
                        await probe.batch([{'createParagraphBullets': {
                            'range': {'startIndex': 1,
                                      'endIndex': content[-1]['endIndex'] - 1,
                                      'tabId': tab_id},
                            'bulletPreset': ('NUMBERED_DECIMAL_ALPHA_ROMAN'
                                             if 'numbered' in source_kind else
                                             'BULLET_DISC_CIRCLE_SQUARE'),
                        }}], document)
                        document = await native()
                        content = selected(document)['body']['content']
                    source = next(p for p in content
                                  if paragraph_text(p).strip() == (
                                      'Tail' if tool == 'docs_append'
                                      else 'Anchor'))
                    if source_kind != 'clean':
                        span = {'startIndex': source['startIndex'],
                                'endIndex': source['endIndex'] - 1,
                                'tabId': tab_id}
                        red = {'color': {'rgbColor': {'red': 1}}}
                        yellow = {'color': {'rgbColor': {
                            'red': 1, 'green': 1,
                        }}}
                        await probe.batch([{'updateParagraphStyle': {
                            'range': span,
                            'paragraphStyle': {
                                'namedStyleType': (
                                    'HEADING_2' if source_kind == 'heading'
                                    else 'NORMAL_TEXT'),
                                'alignment': 'END', 'lineSpacing': 250,
                                'direction': 'RIGHT_TO_LEFT',
                                'spaceAbove': {'magnitude': 1, 'unit': 'PT'},
                                'spaceBelow': {'magnitude': 100, 'unit': 'PT'},
                                'indentStart': {'magnitude': 90, 'unit': 'PT'},
                                'indentEnd': {'magnitude': 20, 'unit': 'PT'},
                                'indentFirstLine': {
                                    'magnitude': 70, 'unit': 'PT',
                                },
                                'shading': {'backgroundColor': yellow},
                                'borderBottom': {
                                    'color': red, 'dashStyle': 'SOLID',
                                    'width': {'magnitude': 1, 'unit': 'PT'},
                                    'padding': {'magnitude': 1, 'unit': 'PT'},
                                },
                            }, 'fields': '*',
                        }}, {'updateTextStyle': {
                            'range': span, 'fields': '*',
                            'textStyle': {
                                'bold': True, 'italic': True,
                                'underline': True, 'strikethrough': True,
                                'baselineOffset': 'SUPERSCRIPT',
                                'fontSize': {'magnitude': 18, 'unit': 'PT'},
                                'weightedFontFamily': {
                                    'fontFamily': 'Courier New',
                                },
                                'foregroundColor': red,
                                'backgroundColor': yellow,
                                'link': {'url': 'https://example.org/source'},
                            },
                        }}], document)
                    seeded = selected(await native())
                    arguments = {'doc_id': live_test_doc, 'tab_id': tab_id,
                                 'text': MARKUP}
                    if tool != 'docs_append':
                        arguments['anchor'] = 'Anchor'
                    await probe.call(0, tool, arguments)
                    updated = selected(await native())
                    existing, inserted = [], []
                    for item in updated['body']['content']:
                        target = (existing if 'paragraph' not in item
                                  or paragraph_text(item).strip() in ORIGINAL
                                  else inserted)
                        target.append(item)
                    assert normalized(existing) == normalized(
                        seeded['body']['content'])
                    assert updated.get('lists', {}) == seeded.get('lists', {})
                    assert updated['namedStyles'] == seeded['namedStyles']
                    assert all('bullet' not in p['paragraph']
                               for p in inserted)
                    observed = presentation(inserted)
                    if golden is None:
                        golden = observed
                        assert len(inserted) >= 13  # noqa: PLR2004
                        plain = next(p for p in inserted
                                     if paragraph_text(p).strip()
                                     == 'Last plain')
                        assert all(not e.get('textRun', {}).get('textStyle')
                                   for e in plain['paragraph']['elements'])
                    else:
                        assert observed == golden, source_kind
                    probe.report[source_kind] = {'baseline_matches': True,
                                                 'neighbours_preserved': True}
                finally:
                    if tab_id is not None:
                        await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                          await native())
            assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
            probe.report.update(checks_passed=True, cleanup_passed=True)

    asyncio.run(run())


@pytest.mark.live
def test_live_heading_after_explicit_nested_list(live_test_doc, table_probe):
    """End a newly inserted list before a heading and ordinary paragraph."""
    async def run():
        async with table_probe('heading-after-explicit-list') as probe:
            before = await probe.call(0, 'probe_tabs_document')

            async def native():
                """Read current native content through MCP."""
                return await probe.call(0, 'probe_tabs_document')

            for tool in ('docs_append', 'docs_insert_before',
                         'docs_insert_after'):
                tab_id = None
                try:
                    result = await probe.batch([{'addDocumentTab': {
                        'tabProperties': {'title': 'explicit-list-' + tool},
                    }}], await native())
                    tab_id = result['response']['replies'][0][
                        'addDocumentTab']['tabProperties']['tabId']
                    await probe.call(0, 'docs_append', {
                        'doc_id': live_test_doc, 'tab_id': tab_id,
                        'text': '1. Existing parent\n   1. Existing child',
                    })
                    seeded = document_tab(await native(), tab_id)
                    arguments = {
                        'doc_id': live_test_doc, 'tab_id': tab_id,
                        'text': ('1. Requested parent\n'
                                 '   1. Requested child\n\n'
                                 '###### Heading after list\n\n'
                                 'Plain after list'),
                    }
                    if tool != 'docs_append':
                        arguments['anchor'] = 'Existing child'
                    await probe.call(0, tool, arguments)
                    updated = document_tab(await native(), tab_id)
                    original = []
                    rows = {}
                    for item in updated['body']['content']:
                        label = paragraph_text(item).strip()
                        if not label or label.startswith('Existing'):
                            original.append(item)
                        else:
                            rows[label] = item['paragraph']
                    assert normalized(original) == normalized(
                        seeded['body']['content'])
                    for label, depth in [('Requested parent', 0),
                                         ('Requested child', 1)]:
                        bullet = rows[label]['bullet']
                        assert bullet.get('nestingLevel', 0) == depth
                        assert bullet['listId'] not in seeded.get('lists', {})
                    assert (rows['Requested parent']['bullet']['listId']
                            == rows['Requested child']['bullet']['listId'])
                    for label, kind in [('Heading after list', 'HEADING_4'),
                                        ('Plain after list', 'NORMAL_TEXT')]:
                        paragraph = rows[label]
                        assert 'bullet' not in paragraph
                        style = paragraph['paragraphStyle']
                        assert style['namedStyleType'] == kind
                        assert set(style) <= {
                            'namedStyleType', 'direction', 'headingId',
                        }
                    probe.report[tool] = {'checks_passed': True}
                finally:
                    if tab_id is not None:
                        await probe.batch([{'deleteTab': {'tabId': tab_id}}],
                                          await native())
            assert_tabs_unchanged(before['tabs'], (await native())['tabs'])
            probe.report.update(checks_passed=True, cleanup_passed=True)

    asyncio.run(run())
