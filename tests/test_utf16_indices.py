"""Check Google Docs positions independently of Python string offsets."""

from unittest.mock import MagicMock

import pytest

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.md2requests import markdown_to_requests


@pytest.fixture
def set_document_text(simple_document):
    """Build one API paragraph whose source bounds use UTF-16 code units."""
    def set_text(text):
        end = 1 + len(text.encode('utf-16-le')) // 2
        simple_document['body']['content'] = [{
            'startIndex': 1, 'endIndex': end,
            'paragraph': {
                'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                'elements': [{
                    'startIndex': 1, 'endIndex': end,
                    'textRun': {'content': text, 'textStyle': {}},
                }],
            },
        }]

    return set_text


@pytest.fixture
def set_document_runs(simple_document):
    """Supply API run boundaries computed independently in UTF-16 units."""
    def populate(runs):
        elements = []
        index = 1
        for text in runs:
            end = index + len(text.encode('utf-16-le')) // 2
            elements.append({
                'startIndex': index, 'endIndex': end,
                'textRun': {'content': text, 'textStyle': {}},
            })
            index = end
        simple_document['body']['content'] = [{
            'startIndex': 1, 'endIndex': index,
            'paragraph': {
                'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                'elements': elements,
            },
        }]
        return ''.join(runs)

    return populate


@pytest.mark.parametrize('operation', ['search_replace', 'batch_replace'])
@pytest.mark.parametrize(
    ('text', 'find', 'replacement', 'source_range', 'replacement_units'),
    [
        ('😀 Target\n', 'Target', 'X', (4, 10), 1),
        ('Prefix Target\n', 'Target', '😀', (8, 14), 2),
        ('😀\n', '😀', 'X', (1, 3), 1),
    ],
    ids=['emoji-before-match', 'emoji-replacement', 'emoji-match'],
)
def test_replacement_ranges_use_utf16_units(
    set_document_text, mock_docs, *, operation, text, find, replacement,
    source_range, replacement_units,
):
    """Respect source and replacement lengths measured in Google API units."""
    set_document_text(text)
    if operation == 'search_replace':
        result = docs_edit.search_replace('example', find, replacement)
        assert result.ok is True
    else:
        result = docs_edit.batch_replace(
            'example', [{'find': find, 'replace': replacement}],
        )
        assert result['ok'] is True

    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    start, end = source_range
    assert requests[0]['insertText']['location']['index'] == start
    assert requests[1]['deleteContentRange']['range'] == {
        'startIndex': start + replacement_units,
        'endIndex': end + replacement_units,
    }


@pytest.mark.parametrize('newline_before', [False, True])
def test_style_ranges_after_emoji_use_utf16_units(newline_before):
    """Format the word after an emoji without shifting the styled range."""
    requests = markdown_to_requests(
        '😀 **word**', start=12, newline_before=newline_before,
    )
    styles = [r['updateTextStyle'] for r in requests if 'updateTextStyle' in r]
    expected_start = 15 + int(newline_before)

    assert len(styles) == 1
    assert styles[0]['range'] == {
        'startIndex': expected_start, 'endIndex': expected_start + len('word'),
    }


@pytest.mark.parametrize('newline_before', [False, True])
def test_paragraph_after_emoji_uses_utf16_position(newline_before):
    """Account for an earlier non-BMP character when inserting a paragraph."""
    requests = markdown_to_requests(
        '😀\n\nNext', start=12, newline_before=newline_before,
    )
    indices = [
        r['insertText']['location']['index'] for r in requests
        if 'insertText' in r
    ]

    assert indices == [12, 15]


@pytest.mark.parametrize('operation', ['search_replace', 'batch_replace'])
@pytest.mark.parametrize('replacement', ['', '🦷'])
@pytest.mark.parametrize('find', ['Target', 'Target😀'])
def test_non_bmp_edits_across_source_runs_preserve_neighbours(
    set_document_runs, mock_docs, operation, replacement, find,
):
    """Apply API requests to UTF-16 bytes and verify exact surviving text."""
    original = set_document_runs(['😀 ', 'Tar', 'get😀', ' suffix\n'])
    if operation == 'search_replace':
        result = docs_edit.search_replace('example', find, replacement)
        assert result.ok is True
        assert result.replaced == find
        assert result.replaced_char_count == len(find)
    else:
        result = docs_edit.batch_replace(
            'example', [{'find': find, 'replace': replacement}],
        )
        assert result['changes'][0]['replaced_char_count'] == len(find)
        assert result['changes'][0]['replacement_char_count'] == (
            len(replacement)
        )

    buffer = ('\n' + original).encode('utf-16-le')
    for request in mock_docs.batchUpdate.call_args.kwargs['body']['requests']:
        if 'insertText' in request:
            insert = request['insertText']
            at = insert['location']['index'] * 2
            buffer = (
                buffer[:at] + insert['text'].encode('utf-16-le') + buffer[at:]
            )
        else:
            span = request['deleteContentRange']['range']
            buffer = (
                buffer[:span['startIndex'] * 2]
                + buffer[span['endIndex'] * 2:]
            )
        buffer.decode('utf-16-le')  # Reject split surrogate pairs.
    assert buffer.decode('utf-16-le') == (
        '\n' + original.replace(find, replacement, 1)
    )


@pytest.mark.parametrize(
    ('runs', 'anchor', 'expected_range'),
    [
        (['😀 ', 'Tar', 'get😀', '\n'], 'Target😀', (4, 12)),
        (['A😀', 'B', '\n'], '😀', (2, 4)),
        (['😀', '😀', '\n'], '😀😀', (1, 5)),
    ],
)
def test_comment_named_range_uses_utf16_source_runs(
    set_document_runs, mock_docs, monkeypatch, *, runs, anchor, expected_range,
):
    """Anchor comments to whole characters across source-run boundaries."""
    set_document_runs(runs)
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'createNamedRange': {'namedRangeId': 'range-id'}}],
    }
    drive = MagicMock()
    drive.comments.return_value.create.return_value.execute.return_value = {
        'id': 'comment-id',
    }
    monkeypatch.setattr(docs_edit, 'build', lambda *_args, **_kwargs: drive)
    monkeypatch.setattr(docs_edit, '_load_creds', object)

    result = docs_edit.add_comment('example', 'Comment', anchor)

    request = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]
    assert request['createNamedRange']['range'] == {
        'startIndex': expected_range[0], 'endIndex': expected_range[1],
        'segmentId': '',
    }
    assert result['anchored_to'] == anchor
    assert result['at_index'] == expected_range[0]


def test_range_endpoint_keeps_preceding_run_boundary():
    """A range end excludes a source gap, while a start uses the next run."""
    first_end, second_start = 5, 9
    text_map = [(0, 3, '😀'), (1, second_start, 'X')]
    assert docs_edit._full_text_pos_to_doc_index(1, text_map) == second_start
    assert docs_edit._full_text_pos_to_doc_index(
        1, text_map, end=True,
    ) == first_end


@pytest.mark.parametrize('newline_before', [False, True])
def test_multiple_styled_runs_and_paragraphs_use_utf16(newline_before):
    """Keep styles and the next paragraph aligned after multiple emoji."""
    requests = markdown_to_requests(
        '😀 **🦷word** tail\n\nNext 𐐀', start=12,
        newline_before=newline_before,
    )
    insertions = [r['insertText'] for r in requests if 'insertText' in r]
    styles = [r['updateTextStyle'] for r in requests if 'updateTextStyle' in r]
    start = 15 + int(newline_before)

    assert styles[0]['range'] == {'startIndex': start, 'endIndex': start + 6}
    assert [r['location']['index'] for r in insertions] == [12, 27]
    assert ''.join(r['text'] for r in insertions) == (
        '\n😀 🦷word tail\nNext 𐐀' if newline_before
        else '😀 🦷word tail\nNext 𐐀\n'
    )
