"""Exercise local conversion and section targeting without Google API calls."""

import pytest

from gdocs_scope_mcp.md2requests import markdown_to_html
from gdocs_scope_mcp.models import (
    DocumentParagraph,
    DocumentSection,
    DocumentTree,
)


@pytest.fixture
def document_tree():
    """Provide repeated text in nested and unrelated sections."""
    nested = DocumentSection(
        title='Nested',
        id='nested',
        level='H2',
        paragraphs=[
            DocumentParagraph(
                start_index=20,
                end_index=34,
                text='Target phrase\n',
                markdown='Target phrase\n\n',
            )
        ],
    )
    parent = DocumentSection(
        title='Parent',
        id='parent',
        level='H1',
        sections=[nested],
    )
    other = DocumentSection(
        title='Other',
        id='other',
        level='H1',
        paragraphs=[
            DocumentParagraph(
                start_index=40,
                end_index=54,
                text='Target phrase\n',
                markdown='Target phrase\n\n',
            )
        ],
    )
    return DocumentTree(
        title='Example',
        document_id='example',
        revision_id='revision',
        sections=[parent, other],
        headings={'parent': parent, 'nested': nested, 'other': other},
    )


def test_heading_search_stays_within_subtree(document_tree):
    """A scoped search includes descendants and excludes sibling sections."""
    matches = document_tree.headings['parent'].find_all(
        'target',
        case_sensitive=False,
    )

    assert [
        match.section.id
        for match in document_tree.find_all('target', case_sensitive=False)
    ] == ['nested', 'other']
    assert [
        (
            match.section.id,
            match.paragraph.start_index + match.start_index,
            match.end_index,
        )
        for match in matches
    ] == [('nested', 20, 6)]


def test_markdown_preserves_inline_emphasis():
    """Markdown emphasis becomes HTML consumed by the request converter."""
    html = markdown_to_html('A **bold** and *italic* sentence.')

    assert html == (
        '<p>A <strong>bold</strong> and <em>italic</em> sentence.</p>\n'
    )


@pytest.fixture
def regex_document():
    """Keep every regex match in one paragraph to isolate case handling."""
    text = 'Ab7 !\n'
    section = DocumentSection(
        title='Example', id='example', level='H1',
        paragraphs=[DocumentParagraph(
            start_index=1, end_index=1 + len(text), text=text, markdown=text,
        )],
    )
    return DocumentTree(
        title='Example', document_id='example', revision_id='revision',
        sections=[section], headings={'example': section},
    )


@pytest.mark.xfail(
    strict=True,
    reason='Case-insensitive search lowercases regex character-class escapes.',
)
@pytest.mark.parametrize('scope', ['document', 'section'])
@pytest.mark.parametrize('first', [False, True])
@pytest.mark.parametrize(
    ('pattern', 'expected_spans'),
    [
        (r'\S+', [(0, 3), (4, 5)]),
        (r'\D+', [(0, 2), (3, 6)]),
        (r'\W+', [(3, 6)]),
    ],
)
def test_case_insensitive_regex_preserves_character_classes(
    regex_document, *, scope, first, pattern, expected_spans,
):
    """Case-insensitive matching must retain the original regex semantics."""
    target = (
        regex_document if scope == 'document'
        else regex_document.headings['example']
    )
    if first:
        match = target.find_first(pattern, case_sensitive=False, regex=True)
        assert match is not None
        matches = [match]
        expected_spans = expected_spans[:1]
    else:
        matches = target.find_all(pattern, case_sensitive=False, regex=True)

    assert [
        (match.start_index, match.end_index) for match in matches
    ] == expected_spans
