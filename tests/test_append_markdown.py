"""Check append's shared Markdown conversion path and style ranges."""

from google_docs_mcp import docs_edit


def test_append_converts_headings_and_emphasis(mock_docs):
    """Append produces native paragraph and inline styles from Markdown."""
    docs_edit.append('example', '### Append heading\n\nA **bold** word.')

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
