"""Verify atomic cell patches, native ranges and selective retries."""

# Imported pytest fixtures are requested by name in dependent fixtures/tests.
# ruff: noqa: F811
from copy import deepcopy
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp.tables import (
    patch as table_patch,
    reading as table_read,
    snapshots as table_snapshots,
)
from gdocs_scope_mcp.tables.patch import CellPatch
from gdocs_scope_mcp.text_indices import utf16_length
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture
def source(table_source, mock_docs):
    """Build native text indices and a successful atomic write response."""
    native = table_source([('parent', 1, [['same😀', ''], ['same😀', '']])])
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'writeControl': {'requiredRevisionId': 'committed'}, 'replies': [],
    }
    return native


def target(source, row=0, column=0):
    """Read a fixture cell without using production reference resolution."""
    table = next(x for x in source['body']['content'] if 'table' in x)
    return table['table']['tableRows'][row]['tableCells'][column]


def baseline(cells=None, fields=None):
    """Capture the same state an MCP agent would inspect before editing."""
    ref = table_read.tables_list('example').tables[0].table_ref
    snapshot = table_snapshots.snapshot('example', ref, cells or ['A1'],
                                        fields or ['content', 'text_style',
                                                   'paragraph_style'])
    return ref, snapshot.base_token


def patch(reference, token, changes=None):
    """Submit typed changes through the real production backend."""
    return table_patch.patch('example', reference, token, [
        CellPatch(address=address, markdown=text)
        for address, text in (changes or [('A1', '**new😀**<br>line')])
    ])


def reject(code, operation):
    """Keep expected conflicts distinct from accidental backend errors."""
    with pytest.raises(ToolFailureError) as caught:
        operation()
    assert caught.value.failure.code == code
    assert caught.value.failure.committed_batches == 0
    assert caught.value.failure.suggested_action


@pytest.mark.usefixtures('source')
def test_public_atomic_patch_schema_and_hint(mock_docs):
    """Return typed receipts and send exactly one batch for multiple cells."""
    ref, token = baseline(['A1', 'B2'])
    result = call('docs_table_patch', doc_id='example', table_ref=ref,
                  base_token=token, changes=[
                      {'address': 'A1', 'markdown': '**bold😀**<br>next'},
                      {'address': 'B2', 'markdown': '[link](https://example.com)'},
                  ])
    assert not result.is_error, result.structured_content
    data = result.structured_content
    assert data['applied_count'] == 2  # noqa: PLR2004
    assert data['committed_batches'] == data['attempts'] == 1
    assert data['revision_id'] == 'committed'
    assert [c['address'] for c in data['cells']] == ['A1', 'B2']
    assert data['cells'][0]['text_preview'] == 'bold😀\nnext'
    mock_docs.batchUpdate.assert_called_once()
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    assert not any('updateTableCellStyle' in r or 'updateParagraphStyle' in r
                   for r in body['requests'])


def test_descending_utf16_ranges_preserve_newlines(source, mock_docs):
    """Emoji and empty cells must not shift edits into another cell."""
    ref, token = baseline(['A1', 'B2'])
    before = deepcopy(source)
    patch(ref, token, [('A1', ''), ('B2', '**🦷**')])
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    deletion = next(r['deleteContentRange']['range'] for r in requests
                    if 'deleteContentRange' in r)
    p = target(source)['content'][0]
    assert deletion == {'startIndex': p['startIndex'],
                        'endIndex': p['endIndex'] - 1}
    assert deletion['endIndex'] - deletion['startIndex'] == utf16_length(
        'same😀',
    )
    insertion = next(r['insertText'] for r in requests if 'insertText' in r)
    assert insertion['text'] == '🦷'
    assert insertion['location']['index'] == target(source, 1, 1)[
        'content'][0]['startIndex']
    assert requests.index({'insertText': insertion}) < next(
        i for i, r in enumerate(requests) if 'deleteContentRange' in r
    )
    assert source == before


@pytest.mark.parametrize('markup', [
    '# heading', 'one\n\ntwo', '- list', '```py\ncode\n```',
    '![image](https://example.com/a.png)', '<hr>',
    '<table><tr><td>x</td></tr></table>',
    '<span data-mcp-entity="person" data-mcp-email="a@b.com">A</span>',
    '<p style="text-align:center">x</p>', '<span style="color:red">x</span>',
    '<!--hidden-->', 'a\x00b', 'a\ue000b', 'a&#xE000;b', 'a&#12;b',
    '<p>first</p>outside',
])
@pytest.mark.usefixtures('source')
def test_unsupported_markup_fails_before_any_write(markup, mock_docs):
    """Validate the entire patch before any document mutation."""
    ref, token = baseline(['A1', 'B2'])
    mock_docs.get.reset_mock()
    reject('INVALID_ARGUMENT', lambda: patch(
        ref, token, [('A1', 'valid'), ('B2', markup)],
    ))
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('markup', [
    '', 'plain', '**bold** *italic* <u>under</u> ~~strike~~',
    '`code` [link](https://example.com)', 'a<br/>b<br />c', 'soft\nwrap',
    'x<sup>2</sup> H<sub>2</sub>O', 'escaped &amp; &lt;tag&gt;',
])
def test_inline_subset_reuses_converter_without_paragraph_writes(markup):
    """Inline rich content compiles without objects or structural requests."""
    planned = table_patch.compile_cell(markup)
    assert '\n' not in planned.text
    assert all(set(r) <= {'insertText', 'updateTextStyle'}
               for r in planned.requests)


def test_neighbor_edits_and_subset_snapshot_do_not_conflict(source, mock_docs):
    """Only patched cells consume expectations from a larger read snapshot."""
    ref, token = baseline(['A1', 'B1'])
    target(source, column=1)['content'][0]['paragraph']['elements'][0][
        'textRun']['content'] = 'independent neighbor\n'
    # Cell background is independent even inside the patched cell.
    target(source)['tableCellStyle']['backgroundColor'] = {
        'color': {'rgbColor': {'red': 1}},
    }
    source['revisionId'] = 'independent-write'
    assert patch(ref, token).attempts == 1
    assert mock_docs.batchUpdate.call_args.kwargs['body']['writeControl'] == {
        'requiredRevisionId': 'independent-write',
    }


@pytest.mark.parametrize('dependency', ['content', 'style', 'paragraph'])
def test_overlap_is_rejected_before_writing(source, mock_docs, dependency):
    """Do not overwrite a changed selected property."""
    ref, token = baseline()
    p = target(source)['content'][0]['paragraph']
    if dependency == 'content':
        p['elements'][0]['textRun']['content'] = 'overlap\n'
    elif dependency == 'style':
        p['elements'][0]['textRun']['textStyle']['bold'] = True
    else:
        p['paragraphStyle']['alignment'] = 'CENTER'
    reject('EDIT_CONFLICT', lambda: patch(ref, token))
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_weak_snapshot_or_wrong_targets_fail_before_reads(mock_docs):
    """Rich replacements need baseline text and styles for each target."""
    ref, token = baseline(fields=['content'])
    mock_docs.get.reset_mock()
    reject('INVALID_ARGUMENT', lambda: patch(ref, token))
    mock_docs.get.assert_not_called()
    ref, token = baseline(['A1'])
    mock_docs.get.reset_mock()
    reject('INVALID_REFERENCE', lambda: patch(ref, token, [('B2', 'bad')]))
    reject('INVALID_ARGUMENT', lambda: patch(
        ref, token, [('A1', 'one'), ('A1', 'two')],
    ))
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


def race_error():
    """Match the explicit Google revision-rejection contract."""
    return HttpError(Response({'status': '400'}),
                     b'{"error":{"message":"Revision does not match"}}')


def test_race_rebuilds_utf16_ranges_from_new_snapshot(
    source, table_source, mock_docs,
):
    """A longer preceding neighbor requires fresh positions on retry."""
    ref, token = baseline(['B2'])
    first_position = target(source, 1, 1)['content'][0]['startIndex']
    attempts = []

    def batch(**kwargs):
        """Interleave an independent write before rejecting the first CAS."""
        attempts.append(kwargs['body'])

        def execute():
            """Only an explicit rejected write is eligible for replay."""
            if len(attempts) == 1:
                newer = table_source([('parent', 1, [
                    ['same😀', 'longer collaborator🦷'], ['same😀', ''],
                ])])
                newer['revisionId'] = 'newer'
                raise race_error()
            return {'writeControl': {'requiredRevisionId': 'done'}}
        return SimpleNamespace(execute=execute)

    mock_docs.batchUpdate.side_effect = batch
    result = patch(ref, token, [('B2', 'ours😀')])
    assert result.attempts == 2  # noqa: PLR2004
    assert [a['writeControl'] for a in attempts] == [
        {'requiredRevisionId': 'revision'}, {'requiredRevisionId': 'newer'},
    ]
    positions = [next(r['insertText']['location']['index']
                      for r in a['requests'] if 'insertText' in r)
                 for a in attempts]
    assert positions[0] == first_position
    assert positions[1] > positions[0]


def test_overlap_on_retry_does_not_take_new_baseline(source, mock_docs):
    """A retry retains the agent's original expectations."""
    ref, token = baseline()

    def reject_and_change():
        """Commit another author's edit in the selected cell."""
        target(source)['content'][0]['paragraph']['elements'][0]['textRun'][
            'content'] = 'collaborator\n'
        source['revisionId'] = 'overlap'
        raise race_error()

    mock_docs.batchUpdate.return_value.execute.side_effect = reject_and_change
    reject('EDIT_CONFLICT', lambda: patch(ref, token))
    assert mock_docs.batchUpdate.call_count == 1


@pytest.mark.usefixtures('source')
def test_contention_is_bounded_and_explicitly_retryable(mock_docs):
    """Stop after three confirmed rejections without claiming an overlap."""
    ref, token = baseline()
    mock_docs.batchUpdate.return_value.execute.side_effect = race_error()
    reject('REVISION_RETRY_EXHAUSTED', lambda: patch(ref, token))
    assert mock_docs.batchUpdate.call_count == 3  # noqa: PLR2004


@pytest.mark.parametrize(('failure', 'code'), [
    (TimeoutError(), 'WRITE_OUTCOME_UNKNOWN'),
    (HttpError(Response({'status': '503'}), b'{}'), 'WRITE_OUTCOME_UNKNOWN'),
])
@pytest.mark.usefixtures('source')
def test_unknown_write_outcome_is_never_replayed(mock_docs, failure, code):
    """Transport/server failures may have committed; do not replay them."""
    ref, token = baseline()
    mock_docs.batchUpdate.return_value.execute.side_effect = failure
    reject(code, lambda: patch(ref, token))
    assert mock_docs.batchUpdate.call_count == 1


def test_cell_clear_to_empty_can_be_a_noop(source, mock_docs):  # noqa: ARG001
    """An already empty cell needs no batch or invented mutation."""
    ref, token = baseline(['B2'])
    result = patch(ref, token, [('B2', '')])
    assert result.committed_batches == 0
    assert result.applied_count == 1
    mock_docs.batchUpdate.assert_not_called()


def test_real_tab_id_is_sent_on_every_native_operation(source, mock_docs):
    """Default-first-tab reads still target the verified tab explicitly."""
    source['tabs'] = [{'tabProperties': {'tabId': 'first'},
                       'documentTab': {'body': source['body']}}]
    ref, token = baseline()
    patch(ref, token)
    for request in mock_docs.batchUpdate.call_args.kwargs['body']['requests']:
        value = next(iter(request.values()))
        assert value.get('range', value.get('location'))['tabId'] == 'first'


@pytest.mark.parametrize('bad', [
    [], [{'address': 'a1', 'markdown': 'x'}],
    [{'address': 'A1', 'markdown': 1}],
    [{'address': 'A1', 'markdown': 'x', 'oops': 1}],
])
def test_typed_inputs_reject_invalid_changes_before_api(mock_docs, bad):
    """Strict schemas reject wrong types, empty input and unknown fields."""
    result = call('docs_table_patch', doc_id='example', table_ref='unused',
                  base_token='unused', changes=bad)
    assert result.is_error
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('damage', ['paragraphs', 'object', 'suggestion',
                                   'code', 'range'])
def test_unsupported_native_cell_shapes_are_rejected(source, damage):
    """Reject native structures that cannot be replaced as ordinary text."""
    native = deepcopy(target(source))
    paragraph = native['content'][0]['paragraph']
    if damage == 'paragraphs':
        native['content'].append(deepcopy(native['content'][0]))
    elif damage == 'object':
        paragraph['elements'].append({'inlineObjectElement': {
            'inlineObjectId': 'image-id',
        }})
    elif damage == 'suggestion':
        paragraph['elements'][0]['suggestedInsertionIds'] = ['suggestion']
    elif damage == 'code':
        paragraph['elements'][0]['textRun']['content'] = '\ue907\n'
    else:
        native['content'][0]['endIndex'] += 1
    reject('TARGET_CHANGED' if damage == 'range' else 'INVALID_ARGUMENT',
           lambda: table_patch._plain_cell(native))


def test_compiler_rejects_invalid_unicode():
    """Validate Unicode before planning outside the MCP boundary."""
    reject('INVALID_ARGUMENT', lambda: table_patch.compile_cell('\ud800'))


@pytest.mark.usefixtures('source')
def test_expired_patch_baseline_is_rejected_before_reads(mock_docs,
                                                       monkeypatch):
    """An expired snapshot cannot be silently renewed by an editing call."""
    ref, token = baseline()
    mock_docs.get.reset_mock()
    monkeypatch.setattr(table_patch.time, 'time', lambda: 99999999999)
    reject('SNAPSHOT_EXPIRED', lambda: patch(ref, token))
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_total_markdown_limit_fails_before_reads(mock_docs):
    """Keep aggregate input bounded even when each typed change is valid."""
    ref, token = baseline(['A1', 'B1'])
    mock_docs.get.reset_mock()
    reject('INVALID_ARGUMENT', lambda: patch(
        ref, token, [('A1', 'a' * 60000), ('B1', 'b' * 60000)],
    ))
    mock_docs.get.assert_not_called()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('source')
def test_native_request_limit_fails_before_writes(mock_docs):
    """Fragmented rich text must not produce an unbounded batch."""
    ref, token = baseline()
    reject('INVALID_ARGUMENT', lambda: patch(
        ref, token, [('A1', '**x** ' * 1001)],
    ))
    mock_docs.batchUpdate.assert_not_called()
