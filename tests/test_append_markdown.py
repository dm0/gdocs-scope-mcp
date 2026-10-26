"""Check append's shared Markdown conversion path and style ranges."""

import asyncio
import json

import pytest
from fastmcp import Client

from gdocs_scope_mcp import docs_edit, server
from gdocs_scope_mcp.models import AppendSucceedResponse

EXPECTED_PREVIEW_LIMIT = 200


def test_append_converts_headings_and_emphasis(simple_document, mock_docs):
    """Append produces native paragraph and inline styles from Markdown."""
    result = docs_edit.append(
        'example',
        '### Append heading\n\nA **bold** word.',
    )

    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert any(
        r.get('updateParagraphStyle', {})
        .get('paragraphStyle', {})
        .get(
            'namedStyleType',
        )
        == 'HEADING_1'
        for r in requests
    )
    assert any(
        r.get('updateTextStyle', {}).get('textStyle') == {'bold': True}
        for r in requests
    )
    inserted = ''.join(
        r['insertText']['text'] for r in requests if 'insertText' in r
    )
    assert inserted == '\nAppend heading\nA bold word.'
    assert isinstance(result, AppendSucceedResponse)
    assert result.model_dump() == {
        'ok': True,
        'scope': 'document_end',
        'heading_id': None,
        'document_id': 'example',
        'rich': True,
        'at_index': simple_document['body']['content'][-1]['endIndex'] - 1,
        'appended': inserted,
        'inserted_char_count': len(inserted),
        'inserted_image_count': 0,
        'inserted_entity_count': 0,
        'temporary_image_cleanup_pending': [],
        'preview_truncated': False,
    }


def test_append_preserves_boundaries_and_style_offsets(
    simple_document,
    mock_docs,
):
    """Trailing insertion keeps append's leading breaks and style ranges."""
    original = '\n' + ''.join(
        item['paragraph']['elements'][0]['textRun']['content']
        for item in simple_document['body']['content']
    )
    docs_edit.append(
        'example',
        '### Heading\n\nA **bold** and *italic* word.\n\nLast.',
    )

    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    text = original
    styles = []
    for request in requests:
        if 'insertText' in request:
            insertion = request['insertText']
            index = insertion['location']['index']
            text = text[:index] + insertion['text'] + text[index:]
        elif 'updateTextStyle' in request:
            update = request['updateTextStyle']
            span = update['range']
            styles.append(
                (
                    text[span['startIndex'] : span['endIndex']],
                    update['textStyle'],
                )
            )
        elif 'updateParagraphStyle' in request:
            update = request['updateParagraphStyle']
            span = update['range']
            if update['paragraphStyle']['namedStyleType'] == 'HEADING_1':
                assert text[span['startIndex'] : span['endIndex']] == 'Heading'

    assert text == original[:-1] + (
        '\nHeading\nA bold and italic word.\nLast.\n'
    )
    assert styles == [('bold', {'bold': True}), ('italic', {'italic': True})]


@pytest.mark.parametrize(
    'text',
    [
        '**буквально**\n\n# Heading 😊',
        '',
        'one\n\ntwo\n',
    ],
)
def test_literal_append_preserves_input_without_conversion(
    monkeypatch,
    simple_document,
    mock_docs,
    apply_insertions,
    text,
):
    """Literal append bypasses Markdown and preserves delimiters and breaks."""

    def unexpected_conversion(*_args, **_kwargs):
        raise AssertionError('Literal append must not parse Markdown')

    monkeypatch.setattr(
        'gdocs_scope_mcp.image_uploads.markdown_to_requests',
        unexpected_conversion,
    )
    result = docs_edit.append('example', text, rich=False)

    mock_docs.batchUpdate.assert_called_once_with(
        documentId='example',
        body={
            'requests': [
                {
                    'insertText': {
                        'location': {'index': result.at_index},
                        'text': '\n' + text,
                    },
                }
            ]
        },
    )
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    actual, styles = apply_insertions(simple_document, requests)
    original = '\n' + ''.join(
        item['paragraph']['elements'][0]['textRun']['content']
        for item in simple_document['body']['content']
    )
    assert actual == original[:-1] + '\n' + text + '\n'
    assert styles == []
    assert result.rich is False
    assert result.appended == '\n' + text
    assert result.inserted_char_count == len(text) + 1
    assert result.preview_truncated is False


@pytest.mark.parametrize('rich', [False, True])
@pytest.mark.parametrize('length', [199, 200])
def test_append_preview_reports_truncation(mock_docs, rich, length):
    """Preview bounds and total counts include the paragraph break."""
    result = docs_edit.append('example', 'я' * length, rich=rich)

    inserted = '\n' + 'я' * length
    assert result.appended == inserted[:EXPECTED_PREVIEW_LIMIT]
    assert result.inserted_char_count == len(inserted)
    assert result.preview_truncated is (len(inserted) > EXPECTED_PREVIEW_LIMIT)
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('rich', [False, True])
def test_mcp_append_exposes_structured_receipt(mock_docs, rich):
    """The MCP schema and both result channels expose the typed fields."""

    async def call():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == 'docs_append')
            result = await client.call_tool(
                'docs_append',
                {
                    'doc_id': 'example',
                    'text': '**word**',
                    'rich': rich,
                },
            )
            return tool, result

    tool, result = asyncio.run(call())

    expected_fields = {
        'ok',
        'scope',
        'heading_id',
        'document_id',
        'rich',
        'at_index',
        'appended',
        'inserted_char_count',
        'inserted_image_count',
        'inserted_entity_count',
        'temporary_image_cleanup_pending',
        'preview_truncated',
    }
    success_schema = next(
        branch
        for branch in tool.outputSchema['anyOf']
        if branch['title'] == 'AppendSucceedResponse'
    )
    assert set(success_schema['properties']) == expected_fields
    assert (
        success_schema['properties']['appended']['maxLength']
        == EXPECTED_PREVIEW_LIMIT
    )
    assert result.is_error is False
    assert set(result.structured_content) == expected_fields
    assert json.loads(result.content[0].text) == result.structured_content
    assert result.structured_content['appended'] == (
        '\nword' if rich else '\n**word**'
    )
    assert result.structured_content['rich'] is rich
    mock_docs.batchUpdate.assert_called_once()


def test_append_does_not_report_success_when_update_fails(mock_docs):
    """A failed API update propagates without producing a success receipt."""
    mock_docs.batchUpdate.return_value.execute.side_effect = RuntimeError(
        'Simulated update failure',
    )

    with pytest.raises(RuntimeError, match='Simulated update failure'):
        docs_edit.append('example', 'New paragraph')
