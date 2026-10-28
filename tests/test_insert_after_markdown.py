"""Check Markdown insertion after scoped anchors and the final paragraph."""

import asyncio

import pytest
from fastmcp import Client

from gdocs_scope_mcp import docs_edit, server


@pytest.mark.parametrize(
    ('anchor', 'scope', 'prefix', 'suffix'),
    [
        (
            'Introduction',
            None,
            '\nIntroduction',
            '\nParent\nTarget phrase\nNested\n'
            'Target phrase again\nOther\nTarget phrase elsewhere\n',
        ),
        (
            'Target phrase',
            'nested',
            '\nIntroduction\nParent\nTarget phrase\nNested\n'
            'Target phrase again',
            '\nOther\nTarget phrase elsewhere\n',
        ),
        (
            'Target phrase',
            'other',
            '\nIntroduction\nParent\nTarget phrase\nNested\n'
            'Target phrase again\nOther\nTarget phrase elsewhere',
            '\n',
        ),
    ],
)
def test_rich_after_keeps_anchor_and_following_paragraphs(
    simple_document,
    mock_docs,
    apply_insertions,
    *,
    anchor,
    scope,
    prefix,
    suffix,
):
    """First, middle, and final anchors retain valid paragraph boundaries."""
    result = docs_edit.insert_after(
        'example',
        anchor,
        '### New heading\n\nA **bold** and *italic* word.\n\nLast paragraph.',
        heading_id=scope,
    )

    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, styled = apply_insertions(simple_document, requests)
    inserted = '\nNew heading\nA bold and italic word.\nLast paragraph.'
    assert text == prefix + inserted + suffix
    assert result.ok is True
    assert result.insert_position == 'after'
    assert result.at_index == len(prefix)
    assert result.inserted_text == inserted
    assert result.rich is True
    assert any(
        value == 'New heading'
        and update.get('paragraphStyle', {}).get('namedStyleType')
        == 'HEADING_1'
        for value, update in styled
    )
    assert any(
        value == 'bold' and update.get('textStyle') == {'bold': True}
        for value, update in styled
    )
    assert any(
        value == 'italic' and update.get('textStyle') == {'italic': True}
        for value, update in styled
    )


@pytest.mark.parametrize('scope', ['nested', 'other'])
def test_literal_after_bypasses_both_parsers(
    monkeypatch,
    simple_document,
    mock_docs,
    apply_insertions,
    scope,
):
    """Literal mode keeps delimiters at middle and final paragraph anchors."""

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError('Literal insertion must not parse Markdown')

    monkeypatch.setattr(
        'gdocs_scope_mcp.image_uploads.html_to_gpars', unexpected_call,
    )
    result = docs_edit.insert_after(
        'example',
        'Target phrase',
        '**literal**\n\n# heading',
        heading_id=scope,
        rich=False,
    )

    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, styled = apply_insertions(simple_document, requests)
    assert result.rich is False
    assert result.insert_position == 'after'
    assert result.inserted_text == '\n**literal**\n\n# heading'
    if scope == 'nested':
        assert 'again\n**literal**\n\n# heading\nOther\n' in text
    else:
        assert text.endswith('elsewhere\n**literal**\n\n# heading\n')
    assert styled == []


@pytest.mark.parametrize(
    ('anchor', 'scope'),
    [
        ('Target phrase', 'missing'),
        ('Missing anchor', 'nested'),
    ],
)
def test_unavailable_after_target_does_not_write(mock_docs, anchor, scope):
    """Missing headings and anchors do not cause document updates."""
    result = docs_edit.insert_after(
        'example',
        anchor,
        '**text**',
        heading_id=scope,
    )

    assert result.ok is False
    mock_docs.batchUpdate.assert_not_called()


def test_mcp_after_forwards_heading_scope(
    simple_document,
    mock_docs,
    apply_insertions,
):
    """A real MCP call inserts after the scoped repeated anchor."""

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                'docs_insert_after',
                {
                    'doc_id': 'example',
                    'anchor': 'Target phrase',
                    'text': '**Scoped** insertion.',
                    'heading_id': 'nested',
                },
            )

    response = asyncio.run(call())

    assert response.is_error is False
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, _ = apply_insertions(simple_document, requests)
    assert text == (
        '\nIntroduction\nParent\nTarget phrase\nNested\n'
        'Target phrase again\nScoped insertion.\nOther\n'
        'Target phrase elsewhere\n'
    )
