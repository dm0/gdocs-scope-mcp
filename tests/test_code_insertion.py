"""Verify literal code, UTF-16 font ranges and surrounding prose."""

import asyncio

import pytest
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.md2requests import (
    inserted_text_from_requests,
    markdown_to_requests,
)
from gdocs_scope_mcp.models import GoogleDocumentTextStyle

CODE_FONT = 'Roboto Mono'
INLINE_COLOR = {'color': {'rgbColor': {
    'red': 24 / 255, 'green': 128 / 255, 'blue': 56 / 255,
}}}


def replay(requests, original, start):
    """Track UTF-16 cells, font inheritance and list tab removal."""
    raw = original.encode('utf-16-le')
    cells = [[raw[i:i + 2], 'BodyFont', None]
             for i in range(0, len(raw), 2)]
    for request in requests:
        if 'insertText' in request or 'insertInlineImage' in request:
            image = 'insertInlineImage' in request
            item = request['insertInlineImage' if image else 'insertText']
            index = item['location']['index']
            assert 1 <= index < len(cells)
            data = ('\ufffc' if image else item['text']).encode('utf-16-le')
            inherited = cells[index - 1][1:]
            cells[index:index] = [[data[i:i + 2], *inherited]
                                  for i in range(0, len(data), 2)]
            continue
        item = next(iter(request.values()))
        left, right = item['range']['startIndex'], item['range']['endIndex']
        assert 1 <= left < right < len(cells)
        if 'updateTextStyle' in request:
            font = item['textStyle'].get('weightedFontFamily')
            color = item['textStyle'].get('foregroundColor')
            if color:
                for cell in cells[left:right]:
                    cell[2] = color
            if font:
                for cell in cells[left:right]:
                    cell[1] = font['fontFamily']
        if 'createParagraphBullets' in request:
            for index in reversed(range(left, right)):
                if cells[index][0] != b'\t\x00':
                    continue
                previous = index - 1
                while previous >= left and cells[previous][0] == b'\t\x00':
                    previous -= 1
                if previous < left or cells[previous][0] == b'\n\x00':
                    del cells[index]
    text = b''.join(c[0] for c in cells).decode('utf-16-le')
    assert text.startswith(raw[:start * 2].decode('utf-16-le'))
    code = b''.join(c[0] for c in cells if c[1] == CODE_FONT)
    colored = b''.join(c[0] for c in cells if c[2] == INLINE_COLOR)
    return text, code.decode('utf-16-le'), colored.decode('utf-16-le')


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize(('markup', 'plain', 'code'), [
    ('A `one🦷` plain `two` end', 'A one🦷 plain two end', 'one🦷two'),
    ('A `` a`b `` end', 'A a`b end', 'a`b'),
    ('A `line\nwrap` end', 'A line wrap end', 'line wrap'),
    ('A <code>&lt;b&gt;literal&lt;/b&gt;</code> end',
     'A <b>literal</b> end', '<b>literal</b>'),
    ('Before\n\n```python\nfirst🦷 = 1\n\n\tsecond = 2  \n```\n\nAfter',
     'Before\nfirst🦷 = 1\n\n\tsecond = 2  \nAfter',
     'first🦷 = 1\n\n\tsecond = 2  '),
    ('Before\n\n```\n\nfirst\n\n\n```\n\nAfter',
     'Before\n\nfirst\n\n\nAfter', '\nfirst\n\n'),
    ('Before\n\n~~~js\n<b>x</b> **y** ![z](file:///not-real.png)\n~~~\n\nAfter',
     'Before\n<b>x</b> **y** ![z](file:///not-real.png)\nAfter',
     '<b>x</b> **y** ![z](file:///not-real.png)'),
    ('Before\n\n    first = 1\n      second = 2\n\nAfter',
     'Before\nfirst = 1\n  second = 2\nAfter', 'first = 1\n  second = 2'),
    ('Before\n\n<pre><code>first\n  second\n</code></pre>\n\nAfter',
     'Before\nfirst\n  second\nAfter', 'first\n  second'),
    ('`One` ![image](https://example.com/a.png) `Two🦷`',
     'One \ufffc Two🦷', 'OneTwo🦷'),
    ('- Parent\n  - `Child🦷`\n- End',
     'Parent\nChild🦷\nEnd', 'Child🦷'),
])
def test_code_preserves_literal_text_and_only_formats_code(
    markup, plain, code, newline_before,
):
    """Keep whitespace, escape sequences, image slots and adjacent prose."""
    prefix = '\nPrefix😀\n'
    start = len(prefix.encode('utf-16-le')) // 2
    requests = markdown_to_requests(
        markup, start=start, newline_before=newline_before,
    )
    text, styled_code, _ = replay(requests, prefix + 'Suffix🦷\n', start)
    expected = '\n' + plain if newline_before else plain + '\n'
    assert text == prefix + expected + 'Suffix🦷\n'
    assert styled_code == code
    assert inserted_text_from_requests(requests) == expected
    first_font = next(i for i, r in enumerate(requests)
                      if 'weightedFontFamily' in r.get(
                          'updateTextStyle', {}).get('textStyle', {}))
    assert all('insertText' not in r and 'insertInlineImage' not in r
               for r in requests[first_font:])


def test_code_style_combines_with_outer_emphasis_and_link():
    """Keep inline code's native font alongside explicit surrounding markup."""
    requests = markdown_to_requests(
        '[**`word`**](https://example.com)', start=1,
    )
    updates = [r['updateTextStyle'] for r in requests
               if 'updateTextStyle' in r]
    assert len(updates) == 1
    assert updates[0]['textStyle'] == {
        'bold': True, 'link': {'url': 'https://example.com'},
        'weightedFontFamily': {'fontFamily': CODE_FONT},
        'foregroundColor': INLINE_COLOR,
    }


def test_native_font_style_round_trips_through_typed_model():
    """Retain font metadata received from Google without losing its weight."""
    value = {
        'weightedFontFamily': {'fontFamily': CODE_FONT, 'weight': 400},
        'foregroundColor': INLINE_COLOR,
    }
    style = GoogleDocumentTextStyle.model_validate(value)
    assert style.model_dump(by_alias=True, exclude_unset=True) == value


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize(('markup', 'green'), [
    ('Before `one🦷` plain `two` after', 'one🦷two'),
    ('Before <code>html🦷</code> after', 'html🦷'),
    ('- `Parent`\n  - `Child🦷`\n- End', 'ParentChild🦷'),
    ('`Inline`\n\n```\nBlock\n```\n\nAfter `last`', 'Inlinelast'),
    ('Before\n\n<pre><code>Block</code></pre>\n\nAfter', ''),
])
def test_only_inline_code_uses_native_google_docs_green(
    markup, green, newline_before,
):
    """Match native #188038 without coloring blocks or neighbouring text."""
    requests = markdown_to_requests(
        markup, start=2, newline_before=newline_before,
    )
    _, _, colored = replay(requests, '\nXFollowing\n', 2)
    assert colored == green


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('rich', [False, True])
def test_code_insertion_receipts_and_literal_mode(mock_docs, operation, rich):
    """All insertion tools preserve code whitespace and receipt totals."""
    markup = 'Before `one🦷`\n\n```python\nfirst\n\n  second\n```\n\nAfter'
    plain = 'Before one🦷\nfirst\n\n  second\nAfter' if rich else markup
    arguments = {'doc_id': 'example', 'text': markup, 'rich': rich}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'

    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_' + operation, arguments)

    result = asyncio.run(run())
    assert not result.is_error
    key = 'appended' if operation == 'append' else 'inserted_text'
    expected = plain + '\n' if operation == 'insert_before' else '\n' + plain
    assert result.structured_content[key] == expected
    assert result.structured_content['inserted_char_count'] == len(expected)
    assert not result.structured_content['preview_truncated']
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    fonts = [r for r in requests if r.get('updateTextStyle', {}).get(
        'textStyle', {}).get('weightedFontFamily')]
    assert bool(fonts) == rich


def test_code_blocks_in_lists_fail_before_writes(mock_docs):
    """Do not accidentally create multiple bullets from a block in one item."""
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_append', {
                'doc_id': 'example', 'text': '- ```\n  first\n  second\n  ```',
            }, raise_on_error=False)

    result = asyncio.run(run())
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    mock_docs.batchUpdate.assert_not_called()
