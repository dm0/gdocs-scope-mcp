"""Exercise Markdown insertion before anchors through the API and MCP."""

import asyncio

import pytest
from fastmcp import Client

from google_docs_mcp import docs_edit, server


def apply_insertions(document, requests):
    """Apply insertions to a text buffer and inspect emitted style ranges."""
    text = '\n' + ''.join(
        item['paragraph']['elements'][0]['textRun']['content']
        for item in document['body']['content']
    )
    styled = []
    for request in requests:
        if 'insertText' in request:
            insertion = request['insertText']
            index = insertion['location']['index']
            text = text[:index] + insertion['text'] + text[index:]
        else:
            update = next(iter(request.values()))
            span = update['range']
            assert 1 <= span['startIndex'] <= span['endIndex'] < len(text)
            styled.append(
                (
                    text[span['startIndex'] : span['endIndex']],
                    update,
                )
            )
    return text, styled


@pytest.fixture
def no_legacy_builder(monkeypatch):
    """Fail if the migrated insertion falls back to the old Markdown parser."""

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError('insert_before must use the new converter')

    monkeypatch.setattr(docs_edit, '_build_insert_requests', unexpected_call)


@pytest.mark.usefixtures('no_legacy_builder')
@pytest.mark.parametrize(
    ('anchor', 'scope', 'prefix', 'suffix'),
    [
        ('Introduction', None, '\n', 'Introduction\nParent\n'),
        (
            'Target phrase',
            'nested',
            '\nIntroduction\nParent\nTarget phrase\nNested\n',
            'Target phrase again\nOther\nTarget phrase elsewhere\n',
        ),
    ],
)
def test_markdown_before_anchor_keeps_paragraph_boundaries(
    simple_document,
    mock_docs,
    *,
    anchor,
    scope,
    prefix,
    suffix,
):
    """Rich insertion works at the document start and in a heading scope."""
    result = docs_edit.insert_before(
        'example',
        anchor,
        '### New heading\n\nA **bold** and *italic* word.\n\nLast paragraph.',
        heading_id=scope,
    )

    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, styled = apply_insertions(simple_document, requests)
    inserted = 'New heading\nA bold and italic word.\nLast paragraph.\n'
    assert text.startswith(prefix + inserted + suffix)
    assert result.ok is True
    assert result.insert_position == 'before'
    assert result.at_index == len(prefix)
    assert result.inserted_text == inserted
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


@pytest.mark.usefixtures('no_legacy_builder')
def test_literal_before_anchor_bypasses_markdown(
    monkeypatch,
    simple_document,
    mock_docs,
):
    """Literal mode preserves delimiters without invoking either converter."""

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError('Literal insertion must not parse Markdown')

    monkeypatch.setattr(docs_edit, 'markdown_to_requests', unexpected_call)
    result = docs_edit.insert_before(
        'example',
        'Introduction',
        '**literal**\n\n# heading',
        rich=False,
    )

    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text, styled = apply_insertions(simple_document, requests)
    assert text.startswith('\n**literal**\n\n# heading\nIntroduction\n')
    assert result.rich is False
    assert styled == []


@pytest.mark.parametrize(
    ('anchor', 'scope'),
    [
        ('Target phrase', 'missing'),
        ('Missing anchor', 'nested'),
    ],
)
def test_unavailable_before_target_does_not_write(mock_docs, anchor, scope):
    """Missing headings and anchors return failures without document edits."""
    result = docs_edit.insert_before(
        'example',
        anchor,
        '**text**',
        heading_id=scope,
    )

    assert result.ok is False
    mock_docs.batchUpdate.assert_not_called()


def test_mcp_before_forwards_heading_scope(simple_document, mock_docs):
    """A real in-process MCP call selects the nested repeated anchor."""

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                'docs_insert_before',
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
        'Scoped insertion.\nTarget phrase again\nOther\n'
        'Target phrase elsewhere\n'
    )
