"""Replay list operations against an independent UTF-16 document buffer."""

import asyncio

import pytest
from fastmcp import Client

from gdocs_scope_mcp import docs_edit, server
from gdocs_scope_mcp.md2requests import (
    inserted_text_from_requests,
    markdown_to_requests,
)


def replay(requests, *, start=6):
    """Apply insertions and tab-removing bullets; observe exact style spans."""
    buffer = ('prefix\nSUFFIX\n').encode('utf-16-le')
    styles = []
    lists = []
    for request in requests:
        if 'insertText' in request:
            insert = request['insertText']
            at = insert['location']['index'] * 2
            buffer = (buffer[:at] + insert['text'].encode('utf-16-le')
                      + buffer[at:])
        elif 'updateTextStyle' in request:
            update = request['updateTextStyle']
            span = update['range']
            text = buffer[span['startIndex'] * 2:span['endIndex'] * 2]
            styles.append((text.decode('utf-16-le'), update['textStyle']))
        elif 'createParagraphBullets' in request:
            update = request['createParagraphBullets']
            span = update['range']
            left, right = span['startIndex'] * 2, span['endIndex'] * 2
            text = buffer[left:right].decode('utf-16-le')
            lines = text.split('\n')
            lists.append((update['bulletPreset'], [
                (line.lstrip('\t'), len(line) - len(line.lstrip('\t')))
                for line in lines
            ]))
            clean = '\n'.join(line.lstrip('\t') for line in lines)
            buffer = buffer[:left] + clean.encode('utf-16-le') + buffer[right:]
    assert buffer.decode('utf-16-le').startswith('prefix')
    assert buffer.decode('utf-16-le').endswith('\nSUFFIX\n')
    inserted = buffer[start * 2: -len('\nSUFFIX\n'.encode('utf-16-le'))]
    return inserted.decode('utf-16-le'), styles, lists


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('ordered', [False, True])
def test_nested_list_preserves_source_order_and_styles(
    newline_before, ordered,
):
    """Keep item depths, styles, emoji, and neighbouring prose intact."""
    marker = '1.' if ordered else '-'
    markdown = (
        f'Before\n\n{marker} **Parent🦷**\n'
        f'    {marker} [Child](https://example.com)\n'
        f'        {marker} Grandchild\n{marker} Last\n\nAfter'
    )
    requests = markdown_to_requests(
        markdown, start=6, newline_before=newline_before,
    )
    inserted, styles, lists = replay(requests)
    expected = 'Before\nParent🦷\nChild\nGrandchild\nLast\nAfter'
    expected = '\n' + expected if newline_before else expected + '\n'
    assert inserted == expected
    assert inserted_text_from_requests(requests) == expected
    assert styles == [
        ('Parent🦷', {'bold': True}),
        ('Child', {'link': {'url': 'https://example.com'}}),
    ]
    assert lists == [(
        ('NUMBERED_DECIMAL_ALPHA_ROMAN' if ordered
         else 'BULLET_DISC_CIRCLE_SQUARE'),
        [('Parent🦷', 0), ('Child', 1), ('Grandchild', 2), ('Last', 0)],
    )]
    clear = next(r['deleteParagraphBullets'] for r in requests
                 if 'deleteParagraphBullets' in r)
    assert clear['range']['startIndex'] == 6 + int(newline_before)
    assert clear['range']['endIndex'] < (
        6 + len(''.join(r['insertText']['text'] for r in requests
                      if 'insertText' in r).encode('utf-16-le')) // 2 + 1
    )


@pytest.mark.parametrize('newline_before', [False, True])
def test_separate_lists_run_after_styles_in_reverse_order(newline_before):
    """Removing earlier tabs must not invalidate later style/list positions."""
    requests = markdown_to_requests(
        '- One\n  - *Nested*\n\nBetween\n\n1. Two\n   1. **Deep🦷**\n\nAfter',
        start=6, newline_before=newline_before,
    )
    inserted, styles, lists = replay(requests)
    expected = 'One\nNested\nBetween\nTwo\nDeep🦷\nAfter'
    expected = '\n' + expected if newline_before else expected + '\n'
    assert inserted == inserted_text_from_requests(requests) == expected
    assert styles == [('Nested', {'italic': True}), ('Deep🦷', {'bold': True})]
    assert lists == [
        ('NUMBERED_DECIMAL_ALPHA_ROMAN', [('Two', 0), ('Deep🦷', 1)]),
        ('BULLET_DISC_CIRCLE_SQUARE', [('One', 0), ('Nested', 1)]),
    ]


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('loose', [False, True])
def test_soft_wrapped_items_remain_single_paragraphs(newline_before, loose):
    """Markdown source line wrapping must not produce additional bullets."""
    gap = '\n\n' if loose else '\n'
    markdown = '- **First**\n  *continued*' + gap + '- Second'
    requests = markdown_to_requests(
        markdown, start=6, newline_before=newline_before,
    )
    inserted, styles, lists = replay(requests)
    expected = 'First continued\nSecond'
    expected = '\n' + expected if newline_before else expected + '\n'
    assert inserted == expected
    assert styles == [
        ('First', {'bold': True}), ('continued', {'italic': True}),
    ]
    assert lists == [(
        'BULLET_DISC_CIRCLE_SQUARE', [('First continued', 0), ('Second', 0)],
    )]


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('rich', [False, True])
def test_list_receipt_describes_final_text(mock_docs, operation, rich):
    """Receipts count visible text rather than the temporary nesting tabs."""
    markdown = '- Parent\n  - Child\n- Last'
    if operation == 'append':
        result = docs_edit.append('example', markdown, rich=rich)
        preview = result.appended
    else:
        result = getattr(docs_edit, operation)(
            'example', 'Introduction', markdown, rich=rich,
        )
        preview = result.inserted_text
    expected = 'Parent\nChild\nLast' if rich else markdown
    expected = (
        expected + '\n' if operation == 'insert_before' else '\n' + expected
    )
    assert preview == expected
    assert result.inserted_char_count == len(expected)
    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert any('createParagraphBullets' in r for r in requests) is rich


@pytest.mark.parametrize('markdown', [
    '- Parent\n  1. Mixed',
    '- First paragraph\n\n  Second paragraph',
    '3. Custom start',
    '- ',
])
def test_unsupported_list_forms_fail_before_writes(mock_docs, markdown):
    """Return structured errors for unsupported shapes before any writes."""
    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_append', {
                'doc_id': 'example', 'text': markdown,
            }, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error is True
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert 'rich=False' in result.structured_content['suggested_action']
    mock_docs.batchUpdate.assert_not_called()
