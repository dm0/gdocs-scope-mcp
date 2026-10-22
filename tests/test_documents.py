"""Exercise local conversion and section targeting without Google API calls."""

import pytest

from google_docs_mcp.docs_edit import _build_insert_requests
from google_docs_mcp.md2requests import markdown_to_html
from google_docs_mcp.models import (
    DocumentParagraph,
    DocumentSection,
    DocumentTree,
)


@pytest.fixture
def document_tree():
    """Provide repeated text in nested and unrelated sections."""
    nested = DocumentSection(
        title='Nested', id='nested', level='H2',
        paragraphs=[DocumentParagraph(
            start_index=20, end_index=34,
            text='Target phrase\n', markdown='Target phrase\n\n',
        )],
    )
    parent = DocumentSection(
        title='Parent', id='parent', level='H1', sections=[nested],
    )
    other = DocumentSection(
        title='Other', id='other', level='H1',
        paragraphs=[DocumentParagraph(
            start_index=40, end_index=54,
            text='Target phrase\n', markdown='Target phrase\n\n',
        )],
    )
    return DocumentTree(
        title='Example', document_id='example', revision_id='revision',
        sections=[parent, other],
        headings={'parent': parent, 'nested': nested, 'other': other},
    )


def test_heading_search_stays_within_subtree(document_tree):
    """A scoped search includes descendants and excludes sibling sections."""
    matches = document_tree.headings['parent'].find_all(
        'target', case_sensitive=False,
    )

    assert [
        match.section.id
        for match in document_tree.find_all('target', case_sensitive=False)
    ] == ['nested', 'other']
    assert [
        (match.section.id,
         match.paragraph.start_index + match.start_index, match.end_index)
        for match in matches
    ] == [('nested', 20, 6)]


def test_markdown_preserves_inline_emphasis():
    """Markdown emphasis becomes HTML consumed by the request converter."""
    html = markdown_to_html('A **bold** and *italic* sentence.')

    assert html == (
        '<p>A <strong>bold</strong> and <em>italic</em> sentence.</p>\n'
    )


def test_plain_insertion_keeps_markdown_literal():
    """Plain insertion preserves delimiters and requested boundaries."""
    requests, inserted_text = _build_insert_requests(
        12, '**literal**', prefix='\n', suffix='\n', rich=False,
    )

    assert inserted_text == '\n**literal**\n'
    assert requests == [{
        'insertText': {'location': {'index': 12}, 'text': inserted_text},
    }]
