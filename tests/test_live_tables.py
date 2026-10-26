"""Opt-in native table regression through an isolated worktree MCP process."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from gdocs_scope_mcp import docs_edit


@pytest.mark.parametrize('tool', [
    'docs_append', 'docs_insert_before', 'docs_insert_after',
])
@pytest.mark.parametrize('table_borders', [None, True, False])
def test_native_table_insertion(
    live_test_doc, isolated_mcp, tool, table_borders,
):
    """Check native cells, formatting and surrounding paragraphs via MCP."""
    marker = 'TABLE_' + uuid.uuid4().hex
    mode = 'default' if table_borders is None else str(table_borders).lower()
    log = Path(f'/tmp/gdocs-scope-mcp-{tool}-tables-{mode}.log')
    evidence = log.with_suffix('.json')
    report = {}
    docs = docs_edit._get_service('docs', 'v1').documents()

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            setup = await client.call_tool('docs_append', {
                'doc_id': live_test_doc,
                'text': f'{marker} left\n\n{marker} anchor\n\n{marker} right',
            })
            assert setup.structured_content['ok']
            text = (f'{marker} before\n\n'
                    '| Left | Center | Right |\n'
                    '| :--- | :---: | ---: |\n'
                    '| **bold😀**<br>*next* | '
                    '[link](https://example.com) | |\n'
                    '| plain | `code` | <br>~~gone~~<br/><br /> |\n\n'
                    f'{marker} after')
            arguments = {'doc_id': live_test_doc, 'text': text}
            if table_borders is not None:
                arguments['table_borders'] = table_borders
            if tool != 'docs_append':
                arguments['anchor'] = marker + ' anchor'
            original = docs.get(documentId=live_test_doc).execute()
            original_count = native_character_count(
                original['body']['content'],
            )
            result = await client.call_tool(tool, arguments,
                                            raise_on_error=False)
            report['result'] = result.structured_content
            assert not result.is_error, report
            native = docs.get(documentId=live_test_doc).execute()
            content = native['body']['content']
            assert result.structured_content['inserted_char_count'] == (
                native_character_count(content) - original_count
            )
            before = next(i for i, item in enumerate(content)
                          if marker + ' before' in paragraph_text(item))
            after = next(i for i, item in enumerate(content)
                         if marker + ' after' in paragraph_text(item))
            tables = [item['table'] for item in content[before:after]
                      if 'table' in item]
            assert len(tables) == 1
            rows = [list(row['tableCells'])
                    for row in tables[0]['tableRows']]
            values = [[cell_text(cell) for cell in row] for row in rows]
            assert values == [
                ['Left\n', 'Center\n', 'Right\n'],
                ['bold😀\u000bnext\n', 'link\n', '\n'],
                ['plain\n', 'code\n', '\u000bgone\u000b\u000b\n'],
            ]
            for row in rows:
                for cell, alignment in zip(row, ['START', 'CENTER', 'END'],
                                           strict=True):
                    assert len(cell['content']) == 1
                    for side in ('Top', 'Bottom', 'Left', 'Right'):
                        border = cell['tableCellStyle'].get('border' + side)
                        # Docs omits inherited standard borders (black 1 pt).
                        # Hidden borders must have an explicit zero width.
                        if border is None:
                            assert table_borders is not False
                            continue
                        width = border['width']
                        assert width.get('magnitude', 0) == (
                            0 if table_borders is False else 1
                        )
                    assert cell['content'][0]['paragraph'][
                        'paragraphStyle']['alignment'] == alignment
            assert first_style(rows[0][0])['bold'] is True
            assert first_style(rows[1][0])['bold'] is True
            assert first_style(rows[1][1])['link']['url'] == 'https://example.com'
            assert first_style(rows[2][1])['weightedFontFamily'][
                'fontFamily'] == 'Roboto Mono'
            runs = rows[2][2]['content'][0]['paragraph']['elements']
            assert any(run.get('textRun', {}).get('textStyle', {}).get(
                'strikethrough') for run in runs
                if 'gone' in run.get('textRun', {}).get('content', ''))
            for label in ('left', 'anchor', 'right', 'before', 'after'):
                assert any(paragraph_text(item) == f'{marker} {label}\n'
                           for item in content)
            anchor = next(i for i, item in enumerate(content)
                          if paragraph_text(item) == marker + ' anchor\n')
            if tool == 'docs_insert_before':
                assert before < after < anchor
            elif tool == 'docs_insert_after':
                assert anchor < before < after
            report['cells'] = values
            read = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            sections = read.structured_content['sections']
            markdown = '\n'.join(section['markdown'] for section in sections)
            assert marker + ' before' in markdown
            assert marker + ' after' in markdown
            assert '<table>' in markdown
            report['checks_passed'] = True

    try:
        asyncio.run(run())
    finally:
        evidence.write_text(json.dumps(report, indent=2, ensure_ascii=False))


def paragraph_text(item):
    """Return only text runs from a native paragraph."""
    return ''.join(e.get('textRun', {}).get('content', '')
                   for e in item.get('paragraph', {}).get('elements', []))


def cell_text(cell):
    """Read native cell paragraph text in source order."""
    return ''.join(paragraph_text(item) for item in cell['content'])


def first_style(cell):
    """Inspect the first native text run in a populated cell."""
    run = cell['content'][0]['paragraph']['elements'][0]['textRun']
    return run['textStyle']


def native_character_count(content):
    """Count real text characters, including native cell terminators."""
    total = 0
    for item in content:
        total += len(paragraph_text(item))
        if 'table' in item:
            total += sum(native_character_count(cell['content'])
                         for row in item['table']['tableRows']
                         for cell in row['tableCells'])
    return total
