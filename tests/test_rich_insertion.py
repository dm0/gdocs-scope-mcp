"""Verify the shared converter and literal insertion entry points."""

import pytest

from google_docs_mcp import docs_edit
from google_docs_mcp.md2requests import markdown_to_html, markdown_to_requests


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
