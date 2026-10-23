"""Verify the supported formatting subset in the existing insertion builder."""

import pytest

from google_docs_mcp.docs_edit import _build_insert_requests
from google_docs_mcp.md2requests import markdown_to_html


@pytest.mark.parametrize(
    ('markdown', 'style'),
    [
        ('# Title', 'TITLE'),
        ('## Subtitle', 'SUBTITLE'),
        ('### Heading', 'HEADING_1'),
        ('######## Heading', 'HEADING_6'),
    ],
)
def test_rich_heading_insertion(markdown, style):
    """Existing heading syntax produces native paragraph styles."""
    requests, text = _build_insert_requests(
        12, markdown, suffix='\n', rich=True
    )

    plain = markdown.split(' ', 1)[1]
    assert text == plain + '\n'
    assert requests[0] == {
        'insertText': {'location': {'index': 12}, 'text': text},
    }
    assert requests[1] == {
        'updateParagraphStyle': {
            'range': {'startIndex': 12, 'endIndex': 12 + len(plain)},
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
def test_emphasis_styles_cover_only_inserted_word(markdown, style):
    """Inline emphasis strips delimiters and formats only its text range."""
    requests, text = _build_insert_requests(
        12,
        f'A {markdown} end',
        suffix='\n',
        rich=True,
    )

    assert text == 'A word end\n'
    updates = [
        r['updateTextStyle'] for r in requests if 'updateTextStyle' in r
    ]
    assert len(updates) == 1
    assert updates[0]['range'] == {'startIndex': 14, 'endIndex': 18}
    assert updates[0]['textStyle'] == style
    assert set(updates[0]['fields'].split(',')) == set(style)


@pytest.mark.parametrize(
    ('items', 'preset'),
    [
        ('- one\n- two', 'BULLET_DISC_CIRCLE_SQUARE'),
        ('* one\n* two', 'BULLET_DISC_CIRCLE_SQUARE'),
        ('1. one\n2. two', 'NUMBERED_DECIMAL_NESTED'),
        ('1) one\n2) two', 'NUMBERED_DECIMAL_NESTED'),
    ],
)
def test_consecutive_list_items_share_native_list(items, preset):
    """Consecutive items become one native list to preserve numbering."""
    requests, text = _build_insert_requests(12, items, suffix='\n', rich=True)

    assert text == 'one\ntwo\n'
    bullets = [
        r['createParagraphBullets']
        for r in requests
        if 'createParagraphBullets' in r
    ]
    assert bullets == [
        {
            'range': {'startIndex': 12, 'endIndex': 20},
            'bulletPreset': preset,
        }
    ]


def test_normal_paragraph_separates_numbered_lists():
    """Ordinary text separates numbered list groups."""
    requests, text = _build_insert_requests(
        1,
        '1. one\nordinary\n1. two',
        suffix='\n',
        rich=True,
    )

    assert text == 'one\nordinary\ntwo\n'
    bullets = [
        r['createParagraphBullets']
        for r in requests
        if 'createParagraphBullets' in r
    ]
    assert [b['range'] for b in bullets] == [
        {'startIndex': 1, 'endIndex': 5},
        {'startIndex': 14, 'endIndex': 18},
    ]


@pytest.mark.parametrize(
    'text', ['# literal\n- item\n**bold**', '', 'one\n\ntwo']
)
def test_literal_insertion_preserves_input_exactly(text):
    """Literal mode preserves markup and blank lines without formatting."""
    requests, inserted = _build_insert_requests(
        7, text, suffix='\n', rich=False
    )

    assert inserted == text + '\n'
    assert requests == [
        {
            'insertText': {'location': {'index': 7}, 'text': text + '\n'},
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
