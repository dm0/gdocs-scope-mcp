"""Check Google Docs positions independently of Python string offsets."""

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


@pytest.mark.xfail(
    strict=True,
    reason='Replacement ranges use code points instead of UTF-16 units.',
)
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


@pytest.mark.xfail(
    strict=True,
    reason='Converter style ranges count a non-BMP character as one unit.',
)
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


@pytest.mark.xfail(
    strict=True,
    reason='Later paragraph positions ignore the extra UTF-16 unit of emoji.',
)
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
