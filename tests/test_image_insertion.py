"""Verify native Markdown/HTML images with independent UTF-16 replay."""


import asyncio
import json

import httplib2
import pytest
from fastmcp import Client
from googleapiclient.errors import HttpError

from gdocs_scope_mcp import server
from gdocs_scope_mcp.rich_text.compiler import (
    html_to_gpars,
    inserted_text_from_requests,
    markdown_to_requests,
)

URI = 'https://example.com/image.png?x=1&y=2'
OTHER_URI = 'https://example.com/second.jpg'


def test_image_paragraph_diagnostic_rendering():
    """Insertion-only objects retain the paragraph rendering interface."""
    paragraphs = html_to_gpars(f'<p>Before <img src="{URI}"> after</p>')
    paragraph = next(p for p in paragraphs if len(p))
    assert paragraph.to_text(None) == 'Before \ufffc after\n\n'
    assert paragraph.to_markdown(None) == f'Before ![](<{URI}>) after\n\n'


def call(operation, arguments):
    """Exercise MCP within the project's synchronous pytest setup."""
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_' + operation, arguments,
                                          raise_on_error=False)

    return asyncio.run(run())


def replay(requests, original, start):
    """Apply mutations and styles to two-byte cells, including object slots."""
    encoded = original.encode('utf-16-le')
    cells = [[encoded[i:i + 2], {}, None] for i in range(0, len(encoded), 2)]
    for request in requests:
        if 'insertText' in request or 'insertInlineImage' in request:
            image = 'insertInlineImage' in request
            item = request['insertInlineImage' if image else 'insertText']
            index = item['location']['index']
            assert 1 <= index < len(cells)
            data = ('\ufffc' if image else item['text']).encode('utf-16-le')
            inserted = [
                [data[i:i + 2], {}, item['uri'] if image else None]
                for i in range(0, len(data), 2)
            ]
            cells[index:index] = inserted
            continue
        item = next(iter(request.values()))
        left, right = item['range']['startIndex'], item['range']['endIndex']
        assert 1 <= left < right < len(cells)
        if 'updateTextStyle' in request:
            for cell in cells[left:right]:
                cell[1].update(item['textStyle'])
        if 'createParagraphBullets' in request:
            # Match the documented removal of leading nesting tabs.
            for index in reversed(range(left, right)):
                if cells[index][0] != b'\t\x00':
                    continue
                previous = index - 1
                while previous >= left and cells[previous][0] == b'\t\x00':
                    previous -= 1
                if previous < left or cells[previous][0] == b'\n\x00':
                    del cells[index]
    text = b''.join(cell[0] for cell in cells).decode('utf-16-le')
    return text, cells[start:]


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('html', [False, True], ids=['markdown', 'html'])
def test_multiple_images_preserve_utf16_text_and_styles(html, newline_before):
    """Keep objects between styled runs without counting them as text runs."""
    image = f'<img src="{URI.replace("&", "&amp;")}" alt="label" title="t">'
    if not html:
        image = f'![label]({URI} "t")'
    markup = f'😀 **Before🦷** {image} *After🦷* ![two]({OTHER_URI}) tail'
    plain = '😀 Before🦷 \ufffc After🦷 \ufffc tail'
    expected = '\n' + plain if newline_before else plain + '\n'
    prefix = '\nPrefix 😀\n'
    start = len(prefix.encode('utf-16-le')) // 2
    requests = markdown_to_requests(
        markup, start=start, newline_before=newline_before,
    )
    result, cells = replay(requests, prefix + 'Suffix🦷\n', start)
    assert result == prefix + expected + 'Suffix🦷\n'
    assert inserted_text_from_requests(requests) == expected
    assert [c[2] for c in cells if c[2]] == [URI, OTHER_URI]
    for style, label in [('bold', 'Before🦷'), ('italic', 'After🦷')]:
        observed = b''.join(c[0] for c in cells if c[1].get(style))
        assert observed.decode('utf-16-le') == label
    assert all(not c[1] for c in cells if c[2])
    assert all('\ufffc' not in r['insertText']['text'] for r in requests
               if 'insertText' in r)


@pytest.mark.parametrize('newline_before', [False, True])
def test_images_across_heading_paragraphs_and_nested_lists(newline_before):
    """Include object slots when later paragraphs and nesting ranges move."""
    markup = (f'### Title ![one]({URI})\n\nBefore\n\n'
              f'- Parent\n  - ![two]({OTHER_URI}) **Child🦷**\n'
              '- End\n\nAfter')
    plain = 'Title \ufffc\nBefore\nParent\n\ufffc Child🦷\nEnd\nAfter'
    expected = '\n' + plain if newline_before else plain + '\n'
    requests = markdown_to_requests(
        markup, start=1, newline_before=newline_before,
    )
    text, cells = replay(requests, '\nSuffix\n', 1)
    assert text == '\n' + expected + 'Suffix\n'
    assert inserted_text_from_requests(requests) == expected
    assert b''.join(c[0] for c in cells if c[1].get('bold')).decode(
        'utf-16-le',
    ) == 'Child🦷'


@pytest.mark.parametrize(
    ('attributes', 'expected'),
    [
        ('', {}),
        ('width="96"', {'width': {'magnitude': 72, 'unit': 'PT'}}),
        ('height="48px"', {'height': {'magnitude': 36, 'unit': 'PT'}}),
        ('width="32" height="16"', {
            'width': {'magnitude': 24, 'unit': 'PT'},
            'height': {'magnitude': 12, 'unit': 'PT'},
        }),
    ],
)
def test_html_image_dimensions(attributes, expected):
    """Use optional pixel dimensions while keeping Google's aspect ratio."""
    requests = markdown_to_requests(f'<img src="{URI}" {attributes}>', start=1)
    image = next(r['insertInlineImage'] for r in requests
                 if 'insertInlineImage' in r)
    assert image.get('objectSize', {}) == expected
    assert image['uri'] == URI


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('html', [False, True])
@pytest.mark.parametrize('rich', [False, True])
def test_image_receipts_and_literal_mode(mock_docs, operation, html, rich):
    """Expose image-only receipts and preserve literal markup in all tools."""
    markup = f'<img src="{URI}" alt="label">' if html else f'![label]({URI})'
    arguments = {'doc_id': 'example', 'text': markup, 'rich': rich}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'
    result = call(operation, arguments)
    assert not result.is_error
    receipt = result.structured_content
    assert receipt['inserted_image_count'] == int(rich)
    plain = '\ufffc' if rich else markup
    expected = plain + '\n' if operation == 'insert_before' else '\n' + plain
    key = 'appended' if operation == 'append' else 'inserted_text'
    assert receipt[key] == expected
    assert receipt['inserted_char_count'] == len(expected)
    assert not receipt['preview_truncated']
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert sum('insertInlineImage' in r for r in requests) == int(rich)


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('markup', [
    '<img>', '<img src="">', '<img src="relative.png">',
    '<img src="file:///tmp/image.png">',
    '<img src="data:image/png;base64,AA">',
    '<img src="https://user:password@example.com/i.png">',
    '<img src="https://example.com/a b.png">',
    f'<img src="{URI}" width="0">', f'<img src="{URI}" height="-1">',
    f'<img src="{URI}" width="50%">',
    f'<img src="{URI}" style="width: 20px">',
    f'<img src="{URI}" srcset="other.png 2x">',
    f'<picture><img src="{URI}"></picture>',
    '<img src="https://example.com/' + 'x' * 2048 + '">',
])
def test_bad_images_fail_before_writes(mock_docs, operation, markup):
    """Refuse the entire mixed edit when any image cannot be represented."""
    arguments = {'doc_id': 'example', 'text': f'Before\n\n{markup}\n\nAfter'}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'
    result = call(operation, arguments)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert 'rich=False' in result.structured_content['suggested_action']
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
def test_rejected_image_has_recovery_guidance(mock_docs, operation):
    """Propagate API refusal without a successful or partial-edit receipt."""
    mock_docs.batchUpdate.return_value.execute.side_effect = HttpError(
        httplib2.Response({'status': '400'}),
        json.dumps({
            'error': {'message': 'Image could not be retrieved'},
        }).encode(),
    )
    arguments = {'doc_id': 'example', 'text': f'![label]({URI})'}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'
    result = call(operation, arguments)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert 'publicly accessible' in (
        result.structured_content['suggested_action']
    )
    mock_docs.batchUpdate.assert_called_once()
