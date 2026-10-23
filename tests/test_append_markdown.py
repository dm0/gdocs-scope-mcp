"""Check append's new Markdown path independently of the legacy builder."""

from google_docs_mcp import docs_edit


def test_append_does_not_use_legacy_builder(monkeypatch, mock_docs):
    """Native paragraph and inline styles come from the new converter alone."""

    def unexpected_legacy_call(*_args, **_kwargs):
        raise AssertionError('Append must not call the legacy builder')

    monkeypatch.setattr(
        docs_edit,
        '_build_insert_requests',
        unexpected_legacy_call,
    )
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
