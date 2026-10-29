"""Specify safe edits around non-text elements for GitHub issue #23."""


import asyncio
import re

import pytest
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.documents import editing as docs_edit
from gdocs_scope_mcp.tool_errors import ToolFailureError


@pytest.fixture
def nontext_document(simple_document):
    """Build a mixed paragraph and independent UTF-16 source with an object."""
    def build(kind):
        index = 1

        def run(text):
            nonlocal index
            start = index
            index += len(text.encode('utf-16-le')) // 2
            return {
                'startIndex': start, 'endIndex': index,
                'textRun': {'content': text, 'textStyle': {}},
            }

        heading = run('Owner\n')
        start = index
        before = run('😀 BEFORE ')
        payload = {'textStyle': {}}
        if kind == 'inlineObjectElement':
            payload['inlineObjectId'] = 'fixture-image'
        obj = {'startIndex': index, 'endIndex': index + 1, kind: payload}
        index += 1
        # Both matches cross contiguous text runs after the non-text element.
        after = [run(text) for text in [
            'TAR', 'GET😀 middle TAR', 'GET😀 tail\n',
        ]]
        simple_document['body']['content'] = [
            {
                'startIndex': 1, 'endIndex': start,
                'paragraph': {
                    'paragraphStyle': {
                        'namedStyleType': 'HEADING_1', 'headingId': 'owner',
                    },
                    'elements': [heading],
                },
            },
            {
                'startIndex': start, 'endIndex': index,
                'paragraph': {
                    'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                    'elements': [before, obj, *after],
                },
            },
        ]
        simple_document['inlineObjects'] = {'fixture-image': {
            'objectId': 'fixture-image',
            'inlineObjectProperties': {'embeddedObject': {
                'title': 'Image title',
                'imageProperties': {
                    'contentUri': 'https://example.com/fixture.png',
                },
            }},
        }} if kind == 'inlineObjectElement' else {}
        # U+FFFC retains the object's occupied source unit; it is not a title
        # or Markdown rendering. The leading null retains API index zero.
        source = '\0Owner\n😀 BEFORE \ufffcTARGET😀 middle TARGET😀 tail\n'
        assert len(source.encode('utf-16-le')) // 2 == index
        return source

    return build


@pytest.mark.parametrize('kind', ['inlineObjectElement', 'horizontalRule'])
@pytest.mark.parametrize('regex', [False, True])
@pytest.mark.parametrize('occurrence', [1, 2])
@pytest.mark.parametrize('replacement', ['', 'Changed🦷'])
@pytest.mark.parametrize('heading_id', [None, 'owner'])
def test_targeted_edit_after_nontext_preserves_source(
    nontext_document, mock_docs, *, kind, regex, occurrence, replacement,
    heading_id,
):
    """Replace selected text while preserving the object and its neighbours."""
    source = nontext_document(kind)
    matches = list(re.finditer('TARGET😀', source))
    match = matches[occurrence - 1]
    start = len(source[:match.start()].encode('utf-16-le')) // 2
    end = len(source[:match.end()].encode('utf-16-le')) // 2
    result = docs_edit.search_replace(
        'example', 'TARGET😀', replacement, occurrence=occurrence,
        heading_id=heading_id, regex=regex,
    )
    assert result.ok is True
    assert result.at_index == start
    mock_docs.batchUpdate.assert_called_once()
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    shift = len(replacement.encode('utf-16-le')) // 2
    deletion = next(r['deleteContentRange'] for r in requests
                    if 'deleteContentRange' in r)
    assert deletion['range'] == {
        'startIndex': start + shift, 'endIndex': end + shift,
    }

    remaining = source.encode('utf-16-le')
    for request in requests:
        if 'insertText' in request:
            insertion = request['insertText']
            at = insertion['location']['index'] * 2
            remaining = (remaining[:at]
                         + insertion['text'].encode('utf-16-le')
                         + remaining[at:])
        else:
            span = request['deleteContentRange']['range']
            remaining = (remaining[:span['startIndex'] * 2]
                         + remaining[span['endIndex'] * 2:])
    expected = source[:match.start()] + replacement + source[match.end():]
    assert remaining == expected.encode('utf-16-le')
    assert remaining.decode('utf-16-le').count('\ufffc') == 1


@pytest.mark.parametrize('kind', ['inlineObjectElement', 'horizontalRule'])
@pytest.mark.parametrize('regex', [False, True])
def test_targeted_match_crossing_nontext_is_refused_before_write(
    nontext_document, mock_docs, *, kind, regex,
):
    """Do not treat text on either side of an object as contiguous source."""
    nontext_document(kind)
    result = docs_edit.search_replace(
        'example', 'BEFORE TARGET😀', 'Changed',
        heading_id='owner', regex=regex,
    )
    assert result.ok is False
    assert result.code == 'INVALID_ARGUMENT'
    assert result.suggested_action
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('kind', ['inlineObjectElement', 'horizontalRule'])
@pytest.mark.parametrize('replacement', ['', 'Changed🦷'])
def test_targeted_edit_ending_at_object_uses_preceding_run(
    nontext_document, mock_docs, *, kind, replacement,
):
    """An exclusive range end before an object must not include its unit."""
    source = nontext_document(kind)
    find = '😀 BEFORE '
    start = len(source[:source.index(find)].encode('utf-16-le')) // 2
    end = len(source[:source.index('\ufffc')].encode('utf-16-le')) // 2
    result = docs_edit.search_replace('example', find, replacement)
    assert result.ok is True
    assert result.at_index == start
    shift = len(replacement.encode('utf-16-le')) // 2
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[-1]['deleteContentRange']['range'] == {
        'startIndex': start + shift, 'endIndex': end + shift,
    }


@pytest.mark.parametrize('kind', ['inlineObjectElement', 'horizontalRule'])
@pytest.mark.parametrize('crossing', [False, True])
def test_nontext_targeted_edits_through_mcp(
    nontext_document, mock_docs, *, kind, crossing,
):
    """Expose safe success receipts and structured refusals on the MCP wire."""
    nontext_document(kind)

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_search_replace', {
                'doc_id': 'example',
                'find': 'BEFORE TARGET😀' if crossing else 'TARGET😀',
                'replace': '', 'heading_id': 'owner',
            }, raise_on_error=False)

    result = asyncio.run(call())
    assert result.is_error is crossing
    if crossing:
        assert result.structured_content['code'] == 'INVALID_ARGUMENT'
        assert result.structured_content['suggested_action']
        mock_docs.batchUpdate.assert_not_called()
    else:
        assert result.structured_content['applied'] == 1
        mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize('kind', ['inlineObjectElement', 'horizontalRule'])
@pytest.mark.parametrize('crossing', [False, True])
def test_batch_replacement_retains_nontext_gap_protection(
    nontext_document, mock_docs, *, kind, crossing,
):
    """The shared mapper preserves existing batch source-range protection."""
    source = nontext_document(kind)
    replacements = [{
        'find': 'BEFORE TARGET😀' if crossing else 'TARGET😀', 'replace': '',
    }]
    if crossing:
        with pytest.raises(ToolFailureError) as failure:
            docs_edit.batch_replace('example', replacements)
        assert failure.value.failure.code == 'INVALID_ARGUMENT'
        mock_docs.batchUpdate.assert_not_called()
    else:
        result = docs_edit.batch_replace('example', replacements)
        assert result['applied'] == 1
        at = source.index('TARGET😀')
        start = len(source[:at].encode('utf-16-le')) // 2
        end = start + len('TARGET😀'.encode('utf-16-le')) // 2
        requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
        assert requests == [{'deleteContentRange': {'range': {
            'startIndex': start, 'endIndex': end,
        }}}]


def test_table_cell_text_after_nontext_uses_source_run(
    table_document, mock_docs,
):
    """Keep cell-boundary protection while permitting adjacent mapped text."""
    cell = table_document['body']['content'][2]['table']['tableRows'][0][
        'tableCells'
    ][0]
    paragraph = cell['content'][0]
    start = paragraph['startIndex']
    original = paragraph['paragraph']['elements'][0]
    original['startIndex'] += 1
    original['textRun']['content'] = original['textRun']['content'][1:]
    paragraph['paragraph']['elements'] = [{
        'startIndex': start, 'endIndex': start + 1,
        'horizontalRule': {'textStyle': {}},
    }, original]
    result = docs_edit.search_replace(
        'example', 'irst😀', '', heading_id='owner',
    )
    assert result.ok is True
    assert result.at_index == start + 1
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    assert requests == [{'deleteContentRange': {'range': {
        'startIndex': start + 1, 'endIndex': paragraph['endIndex'] - 1,
    }}}]
