"""Verify combined inline styles, URL targets and UTF-16 range boundaries."""

import pytest

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.md2requests import markdown_to_requests


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize(
    ('markup', 'label', 'style'),
    [
        ('[**Bold🦷**](https://example.com/a?x=1&y=2#part)', 'Bold🦷',
         {'bold': True, 'link': {'url': 'https://example.com/a?x=1&y=2#part'}}),
        ('~~*Gone*~~', 'Gone', {'italic': True, 'strikethrough': True}),
        ('[~~Gone~~](https://example.com)', 'Gone',
         {'strikethrough': True, 'link': {'url': 'https://example.com'}}),
        ('<a href="https://example.com"><u>Under</u></a>', 'Under',
         {'underline': True, 'link': {'url': 'https://example.com'}}),
        ('<s>Gone</s>', 'Gone', {'strikethrough': True}),
        ('https://example.com/path', 'https://example.com/path',
         {'link': {'url': 'https://example.com/path'}}),
        ('<https://example.com/path>', 'https://example.com/path',
         {'link': {'url': 'https://example.com/path'}}),
    ],
)
def test_combined_styles_keep_exact_url_and_range(
    markup, label, style, newline_before,
):
    """Keep surrounding text plain, including next to non-BMP characters."""
    start = 12
    prefix = '😀 Before '
    requests = markdown_to_requests(
        prefix + markup + ' after', start=start,
        newline_before=newline_before,
    )
    inserted = requests[0]['insertText']['text']
    assert inserted == (
        '\n' + prefix + label + ' after' if newline_before
        else prefix + label + ' after\n'
    )
    updates = [
        r['updateTextStyle'] for r in requests if 'updateTextStyle' in r
    ]
    assert len(updates) == 1
    update = updates[0]
    span = update['range']
    buffer = inserted.encode('utf-16-le')
    actual = buffer[(span['startIndex'] - start) * 2:
                    (span['endIndex'] - start) * 2].decode('utf-16-le')
    assert actual == label
    assert update['textStyle'] == style
    assert set(update['fields'].split(',')) == set(style)


@pytest.mark.parametrize('newline_before', [False, True])
def test_multiple_inline_styles_do_not_leak(newline_before):
    """Keep distinct links and adjacent strikes independently scoped."""
    requests = markdown_to_requests(
        '[One](https://example.com/1) plain ~~Two~~ '
        '[*Three*](https://example.com/3) end',
        newline_before=newline_before,
    )
    text = requests[0]['insertText']['text'].encode('utf-16-le')
    observed = []
    for request in requests:
        if 'updateTextStyle' not in request:
            continue
        update = request['updateTextStyle']
        span = update['range']
        label = text[span['startIndex'] * 2:span['endIndex'] * 2]
        observed.append((label.decode('utf-16-le'), update['textStyle']))
    assert observed == [
        ('One', {'link': {'url': 'https://example.com/1'}}),
        ('Two', {'strikethrough': True}),
        ('Three', {'italic': True, 'link': {'url': 'https://example.com/3'}}),
    ]


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
def test_links_and_strikes_remain_literal_when_requested(mock_docs, operation):
    """Literal mode preserves Markdown, raw anchors and automatic URLs."""
    text = '[One](https://example.com) ~~Two~~ <s>Three</s> https://example.org'
    if operation == 'append':
        result = docs_edit.append('example', text, rich=False)
    else:
        result = getattr(docs_edit, operation)(
            'example', 'Introduction', text, rich=False,
        )
    mock_docs.batchUpdate.assert_called_once()
    assert mock_docs.batchUpdate.call_args.kwargs['body']['requests'] == [{
        'insertText': {
            'location': {'index': result.at_index},
            'text': text + '\n' if operation == 'insert_before'
            else '\n' + text,
        },
    }]
