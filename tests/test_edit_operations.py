"""Check text edits offline through the mocked Google API boundary."""

# Fixture counts and offsets are intentional expectations in these tests.
# ruff: noqa: PLR2004

import pytest

from gdocs_scope_mcp import docs_edit


def edited_text(document, mock_docs):
    """Apply emitted ASCII edits to an independent text buffer."""
    text = '\n' + ''.join(
        item['paragraph']['elements'][0]['textRun']['content']
        for item in document['body']['content']
    )
    mock_docs.batchUpdate.assert_called_once()
    assert mock_docs.batchUpdate.call_args.kwargs['documentId'] == 'example'
    for request in mock_docs.batchUpdate.call_args.kwargs['body']['requests']:
        if 'insertText' in request:
            insert = request['insertText']
            index = insert['location']['index']
            text = text[:index] + insert['text'] + text[index:]
        else:
            span = request['deleteContentRange']['range']
            text = text[: span['startIndex']] + text[span['endIndex'] :]
    return text


@pytest.mark.parametrize('replacement', ['Changed', ''])
def test_scoped_replace_targets_nested_section(
    simple_document, mock_docs, replacement
):
    """Replace or remove a nested match and preserve surrounding sections."""
    result = docs_edit.search_replace(
        'example',
        'target phrase',
        replacement,
        heading_id='nested',
    )

    assert result.ok is True
    assert result.replaced == 'Target phrase'
    assert edited_text(simple_document, mock_docs) == (
        '\nIntroduction\nParent\nTarget phrase\nNested\n'
        f'{replacement} again\nOther\nTarget phrase elsewhere\n'
    )


def test_targeted_occurrence_replace(simple_document, mock_docs):
    """An occurrence number selects the second matching paragraph."""
    result = docs_edit.search_replace(
        'example', 'Target phrase', 'Changed', occurrence=2
    )

    assert result.ok is True
    assert result.occurrences_found == 3
    assert (
        'Nested\nChanged again\nOther\nTarget phrase elsewhere'
        in edited_text(
            simple_document,
            mock_docs,
        )
    )


@pytest.mark.parametrize(
    'kwargs',
    [
        {'heading_id': 'missing'},
        {'heading_id': 'nested', 'occurrence': 2},
        {'occurrence': 4},
    ],
)
def test_unavailable_target_returns_failure_without_writing(mock_docs, kwargs):
    """Unavailable headings and occurrences do not issue updates."""
    result = docs_edit.search_replace(
        'example', 'Target phrase', 'Changed', **kwargs
    )

    assert result.ok is False
    assert result.description
    assert result.suggested_action
    mock_docs.batchUpdate.assert_not_called()


def test_missing_search_text_does_not_write(mock_docs):
    """An absent search phrase reports a recoverable failure."""
    result = docs_edit.search_replace('example', 'Absent phrase', 'Changed')

    assert result.ok is False
    mock_docs.batchUpdate.assert_not_called()


def test_unscoped_replace_all_uses_native_api(mock_docs):
    """Literal replace-all uses the API and reports the changed count."""
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'replaceAllText': {'occurrencesChanged': 3}}],
    }

    result = docs_edit.search_replace(
        'example', 'Target phrase', 'Changed', occurrence=0
    )

    assert result.ok is True
    assert result.occurrences_changed == 3
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_called_once_with(
        documentId='example',
        body={
            'requests': [
                {
                    'replaceAllText': {
                        'containsText': {
                            'text': 'Target phrase',
                            'matchCase': True,
                        },
                        'replaceText': 'Changed',
                    }
                }
            ]
        },
    )


def test_batch_replace_preserves_indices_across_length_changes(
    simple_document, mock_docs
):
    """Different-length edits preserve untouched surrounding text."""
    result = docs_edit.batch_replace(
        'example',
        [
            {'find': 'Introduction', 'replace': 'Short'},
            {'find': 'again', 'replace': 'a much longer ending'},
            {'find': 'elsewhere', 'replace': ''},
        ],
    )

    assert result['ok'] is True
    assert result['applied'] == 3
    assert edited_text(simple_document, mock_docs) == (
        '\nShort\nParent\nTarget phrase\nNested\n'
        'Target phrase a much longer ending\nOther\nTarget phrase \n'
    )


def test_batch_replace_all_occurrences(simple_document, mock_docs):
    """Batch replace-all changes every literal match within a single update."""
    result = docs_edit.batch_replace(
        'example',
        [
            {'find': 'Target phrase', 'replace': 'New', 'occurrence': 0},
        ],
    )

    assert result['applied'] == 3
    text = edited_text(simple_document, mock_docs)
    assert 'Target phrase' not in text
    assert text.count('New') == 3


def test_batch_validation_does_not_apply_partial_changes(mock_docs):
    """A later missing match prevents earlier replacements from writing."""
    with pytest.raises(ValueError, match='Text not found'):
        docs_edit.batch_replace(
            'example',
            [
                {'find': 'Introduction', 'replace': 'Changed'},
                {'find': 'Absent phrase', 'replace': 'Changed'},
            ],
        )

    mock_docs.batchUpdate.assert_not_called()


def test_delete_matching_paragraphs_preserves_remaining_text(
    simple_document, mock_docs
):
    """Case-insensitive deletion removes all matched paragraphs together."""
    result = docs_edit.delete_paragraph('example', 'target PHRASE')

    assert result['ok'] is True
    assert result['deleted_count'] == 3
    assert edited_text(simple_document, mock_docs) == (
        '\nIntroduction\nParent\nNested\nOther\n'
    )
