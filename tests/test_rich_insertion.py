"""Verify the shared converter and literal insertion entry points."""


import pytest

from gdocs_scope_mcp.documents import editing as docs_edit
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests
from gdocs_scope_mcp.rich_text.models import InsertionTable
from gdocs_scope_mcp.rich_text.parsing import markdown_to_html


@pytest.mark.parametrize(
    ('markdown', 'style'),
    [
        ('# Title', 'TITLE'),
        ('## Subtitle', 'SUBTITLE'),
        ('### Heading', 'HEADING_1'),
        ('######## Heading', 'HEADING_6'),
    ],
)
@pytest.mark.parametrize('newline_before', [False, True])
def test_rich_heading_insertion(markdown, style, newline_before):
    """Heading styles cover only heading text on either insertion side."""
    requests = markdown_to_requests(
        markdown,
        start=12,
        newline_before=newline_before,
    )

    plain = markdown.split(' ', 1)[1]
    text = '\n' + plain if newline_before else plain + '\n'
    start = 13 if newline_before else 12
    assert requests[0] == {
        'insertText': {'location': {'index': 12}, 'text': text},
    }
    assert requests[1] == {
        'updateParagraphStyle': {
            'range': {'startIndex': start, 'endIndex': start + len(plain)},
            'paragraphStyle': {'namedStyleType': style},
            'fields': 'namedStyleType',
        }
    }


@pytest.mark.parametrize(
    ('markdown', 'style'),
    [
        ('**word**', {'bold': True}),
        ('*word*', {'italic': True}),
        ('***word***', {'bold': True, 'italic': True}),
    ],
)
@pytest.mark.parametrize('newline_before', [False, True])
def test_emphasis_styles_cover_only_inserted_word(
    markdown,
    style,
    newline_before,
):
    """Inline emphasis strips delimiters and formats only its text range."""
    requests = markdown_to_requests(
        f'A {markdown} end',
        start=12,
        newline_before=newline_before,
    )

    assert requests[0]['insertText']['text'] == (
        '\nA word end' if newline_before else 'A word end\n'
    )
    updates = [
        r['updateTextStyle'] for r in requests if 'updateTextStyle' in r
    ]
    assert len(updates) == 1
    start = 15 if newline_before else 14
    assert updates[0]['range'] == {'startIndex': start, 'endIndex': start + 4}
    assert updates[0]['textStyle'] == style
    assert set(updates[0]['fields'].split(',')) == set(style)


@pytest.mark.parametrize(
    'text', ['# literal\n- item\n**bold**', '', 'one\n\ntwo']
)
@pytest.mark.parametrize('side', ['before', 'after'])
def test_literal_insertion_preserves_input_exactly(mock_docs, text, side):
    """Literal mode preserves markup and blank lines without formatting."""
    insert = getattr(docs_edit, f'insert_{side}')
    result = insert(
        'example',
        'Introduction',
        text,
        rich=False,
    )

    inserted = text + '\n' if side == 'before' else '\n' + text
    assert result.inserted_text == inserted
    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests == [
        {
            'insertText': {
                'location': {'index': result.at_index},
                'text': inserted,
            },
        }
    ]


@pytest.mark.parametrize(
    ('markdown', 'expected'),
    [
        ('# Heading', '<h1>Heading</h1>\n'),
        ('~~removed~~', '<p><del>removed</del></p>\n'),
        (
            '[Example](https://example.com)',
            '<p><a href="https://example.com">Example</a></p>\n',
        ),
    ],
)
def test_markdown_html_stage(markdown, expected):
    """The HTML stage recognizes headings, strikethrough, and links."""
    assert markdown_to_html(markdown) == expected


@pytest.mark.parametrize(
    ('markup', 'expected_style'),
    [
        ('<b>word</b>', {'bold': True}),
        ('<i>word</i>', {'italic': True}),
        ('<u>word</u>', {'underline': True}),
    ],
)
def test_read_style_html_is_converted_to_text_style(markup, expected_style):
    """Convert supported HTML styles without inserting visible markup."""
    requests = markdown_to_requests(markup, start=12)

    assert requests[0]['insertText']['text'] == '\nword'
    styles = [r['updateTextStyle'] for r in requests if 'updateTextStyle' in r]
    assert len(styles) == 1
    assert styles[0]['textStyle'] == expected_style
    assert styles[0]['range'] == {'startIndex': 13, 'endIndex': 17}


def test_read_alignment_html_is_converted_to_paragraph_style():
    """Keep the centered paragraph syntax emitted by document reads."""
    requests = markdown_to_requests(
        '<p style="text-align: center;">word</p>', start=12,
    )

    assert requests[0]['insertText']['text'] == '\nword'
    styles = [
        r['updateParagraphStyle'] for r in requests
        if 'updateParagraphStyle' in r
    ]
    assert styles[0]['paragraphStyle']['alignment'] == 'CENTER'


def test_read_heading_anchor_is_not_inserted_as_visible_text():
    """Keep heading ID metadata out of visible inserted text."""
    requests = markdown_to_requests(
        '### <a id=heading-id></a>Heading', start=12,
    )

    assert requests[0]['insertText']['text'] == '\nHeading'
    styles = [
        r['updateParagraphStyle'] for r in requests
        if 'updateParagraphStyle' in r
    ]
    assert styles[0]['paragraphStyle']['namedStyleType'] == 'HEADING_1'


@pytest.mark.parametrize(
    'markdown', ['- first\n- second', '1. first\n2. second'],
    ids=['unordered', 'ordered'],
)
@pytest.mark.parametrize('newline_before', [False, True])
def test_markdown_lists_create_item_paragraphs_and_native_bullets(
    markdown, newline_before,
):
    """Keep each item in a separate paragraph with native list formatting."""
    requests = markdown_to_requests(
        markdown, start=12, newline_before=newline_before,
    )

    inserted = ''.join(
        request['insertText']['text'] for request in requests
        if 'insertText' in request
    )
    expected = '\nfirst\nsecond' if newline_before else 'first\nsecond\n'
    assert inserted == expected
    bullets = [
        request['createParagraphBullets'] for request in requests
        if 'createParagraphBullets' in request
    ]
    assert bullets
    assert all(item['bulletPreset'] for item in bullets)


@pytest.mark.parametrize('newline_before', [False, True])
def test_markdown_table_creates_native_structure_and_cell_text(newline_before):
    """Retain a rectangular table and insert each value into its own cell."""
    markdown = '| A | B |\n| --- | --- |\n| C | D |'
    assert '<table>' in markdown_to_html(markdown)

    plan = markdown_to_requests(
        markdown, start=12, newline_before=newline_before,
    )

    tables = [block for block in plan.blocks
              if isinstance(block, InsertionTable)]
    assert len(tables) == 1
    rows, columns = 2, 2
    assert len(tables[0].cells) == rows
    assert all(len(row) == columns for row in tables[0].cells)
    values = [
        r['insertText']['text'].strip('\n') for r in plan.iter_requests()
        if 'insertText' in r and r['insertText']['text'].strip('\n')
    ]
    assert sorted(values) == ['A', 'B', 'C', 'D']


@pytest.mark.parametrize(
    ('markdown', 'style'),
    [
        ('[word](https://example.com)',
         {'link': {'url': 'https://example.com'}}),
        ('~~word~~', {'strikethrough': True}),
    ],
    ids=['hyperlink', 'strikethrough'],
)
@pytest.mark.parametrize('newline_before', [False, True])
def test_inline_markdown_links_and_strikethrough_keep_style(
    markdown, style, newline_before,
):
    """Keep link targets and deleted-text styling on the intended text only."""
    requests = markdown_to_requests(
        f'A {markdown} end', start=12, newline_before=newline_before,
    )

    assert requests[0]['insertText']['text'] == (
        '\nA word end' if newline_before else 'A word end\n'
    )
    styles = [r['updateTextStyle'] for r in requests if 'updateTextStyle' in r]
    assert len(styles) == 1
    start = 14 + int(newline_before)
    assert styles[0]['range'] == {'startIndex': start, 'endIndex': start + 4}
    assert styles[0]['textStyle'] == style
    assert set(styles[0]['fields'].split(',')) == set(style)


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('block', [False, True], ids=['inline', 'block'])
def test_markdown_code_keeps_literal_text_and_font(block, newline_before):
    """Keep code text and whitespace while applying a dedicated code font."""
    code = 'first = 1\n  second = 2' if block else 'word'
    markdown = f'```python\n{code}\n```' if block else f'A `{code}` end'
    requests = markdown_to_requests(
        markdown, start=12, newline_before=newline_before,
    )

    plain = code if block else f'A {code} end'
    expected = '\n' + plain if newline_before else plain + '\n'
    inserted = ''.join(
        request['insertText']['text'] for request in requests
        if 'insertText' in request
    )
    assert inserted == expected
    code_styles = [
        request['updateTextStyle'] for request in requests
        if 'updateTextStyle' in request
        and 'weightedFontFamily' in request['updateTextStyle']['textStyle']
    ]
    assert code_styles
    start = 12 + int(newline_before) + (0 if block else 2)
    cursor = start
    for style in code_styles:
        assert style['range']['startIndex'] == cursor
        cursor = style['range']['endIndex']
    assert cursor == start + len(code)
    assert all(
        style['textStyle']['weightedFontFamily']['fontFamily']
        for style in code_styles
    )


@pytest.mark.parametrize('newline_before', [False, True])
@pytest.mark.parametrize('surrounded', [False, True], ids=['alone', 'in-text'])
def test_markdown_images_are_not_silently_omitted(newline_before, surrounded):
    """Retain an image at its intended position without fetching its URL."""
    uri = 'https://example.com/fixture-image.png'
    image = f'![Fixture image]({uri})'
    markdown = f'Before {image} after' if surrounded else image
    requests = markdown_to_requests(
        markdown, start=12, newline_before=newline_before,
    )

    images = [
        request['insertInlineImage'] for request in requests
        if 'insertInlineImage' in request
    ]
    assert len(images) == 1
    assert images[0]['uri'] == uri
    # Replay text/image insertions independently of the planner's ordering.
    prefix = '_' * 12
    buffer = prefix + '\n'
    for request in requests:
        if 'insertText' in request:
            insertion = request['insertText']
            content = insertion['text']
        elif 'insertInlineImage' in request:
            insertion = request['insertInlineImage']
            content = '\ufffc'
        else:
            continue
        index = insertion['location']['index']
        assert 0 <= index < len(buffer)
        buffer = buffer[:index] + content + buffer[index:]

    plain = 'Before \ufffc after' if surrounded else '\ufffc'
    expected = '\n' + plain if newline_before else plain + '\n'
    assert buffer == prefix + expected + '\n'
