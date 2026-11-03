"""Exercise public formatting contracts, native ranges and revision races."""

import asyncio

import pytest
from fastmcp import Client

from gdocs_scope_mcp.colors import native_color
from gdocs_scope_mcp.documents.formatting import format_colors
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.server import mcp

from .test_literal_rendering import native_document
from .test_revision_guards import change_prefix, race_docs  # noqa: F401


@pytest.mark.parametrize('paragraph', [False, True])
def test_format_only_requested_properties(mock_docs, simple_document, paragraph):
    """Check native UTF-16 ranges and property-specific update masks."""
    simple_document.update(native_document([('prefix😀 Target suffix', {'bold': True})]))
    result = format_colors('test', 'Target', paragraph=paragraph,
                           background_color='light orange 2')
    assert result.ok and result.occurrences_found == 1
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['writeControl'] == {'requiredRevisionId': 'revision'}
    requests = body['requests']
    assert len(requests) == 1
    op = requests[0]['updateParagraphStyle' if paragraph else 'updateTextStyle']
    if paragraph:
        assert op['paragraphStyle'] == {'shading': {
            'backgroundColor': native_color('light orange 2')}}
        assert op['fields'] == 'shading.backgroundColor'
        assert op['range'] == {'startIndex': 1, 'endIndex': 24}
    else:
        assert op['textStyle'] == {'backgroundColor': native_color('light orange 2')}
        assert op['fields'] == 'backgroundColor'
        assert op['range'] == {'startIndex': 10, 'endIndex': 16}


def test_reset_does_not_clear_other_styles(mock_docs):
    """Reset one property and set another without clearing emphasis."""
    format_colors('test', 'Target phrase', occurrence=1, foreground_color='reset',
                  background_color='yellow')
    request = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]
    update = request['updateTextStyle']
    assert update['fields'] == 'foregroundColor,backgroundColor'
    assert update['textStyle'] == {'backgroundColor': native_color('yellow')}


def test_ambiguity_and_explicit_occurrence(mock_docs, simple_document):
    """Require unique anchors unless a specific occurrence is selected."""
    simple_document.update(native_document([('same same', {})]))
    with pytest.raises(ToolFailureError) as caught:
        format_colors('test', 'same', foreground_color='red')
    assert caught.value.failure.code == 'TARGET_AMBIGUOUS'
    mock_docs.batchUpdate.assert_not_called()
    format_colors('test', 'same', foreground_color='red', occurrence=2)
    assert mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0][
        'updateTextStyle']['range'] == {'startIndex': 6, 'endIndex': 10}


@pytest.mark.usefixtures('mock_docs')
def test_heading_scope():
    """Identify the selected subtree in the successful receipt."""
    result = format_colors('test', 'Target phrase', occurrence=1, heading_id='parent',
                           foreground_color='blue')
    assert result.scope == 'heading_subtree' and result.heading_id == 'parent'


@pytest.mark.parametrize('paragraph', [False, True])
def test_independent_change_rebases_formatting(race_docs, paragraph):
    """Recompute source positions after an independent paragraph edit."""
    race_docs['change'] = change_prefix
    result = format_colors('test', 'Target phrase', occurrence=1, paragraph=paragraph,
                           background_color='yellow')
    assert result.ok
    before, after = race_docs['writes']
    assert next(iter(after['requests'][0].values()))['range']['startIndex'] > (
        next(iter(before['requests'][0].values()))['range']['startIndex'])


def test_changed_target_styles_abort(race_docs):
    """Reject collaborator formatting changes on the original target."""
    def change(document):
        document['body']['content'][2]['paragraph']['elements'][0][
            'textRun']['textStyle'] = {'italic': True}
    race_docs['change'] = change
    with pytest.raises(ToolFailureError) as caught:
        format_colors('test', 'Target phrase', occurrence=1, background_color='yellow')
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    assert len(race_docs['writes']) == 1


def test_palette_and_validation_through_mcp(mock_docs):
    """Expose palette/schema validation without unnecessary Google access."""
    async def run():
        async with Client(mcp) as client:
            result = await client.call_tool('docs_get_color_palette', {})
            assert len(result.structured_content['rows']) == 8
            assert result.structured_content['rows'][3][2] == {
                'name': 'light orange 2', 'hex': '#F9CB9C'}
            mock_docs.get.assert_not_called()
            for arguments in ({'foreground_color': 'lime'},
                              {'foreground_color': 123},
                              {'foreground_color': 'red', 'occurrence': 0}):
                result = await client.call_tool('docs_format_text', {
                    'doc_id': 'test', 'anchor_text': 'Target phrase',
                    **arguments,
                }, raise_on_error=False)
                assert result.is_error
            result = await client.call_tool('docs_format_text', {
                'doc_id': 'test', 'anchor_text': 'Target phrase',
            }, raise_on_error=False)
            assert result.is_error
            mock_docs.get.assert_not_called()
            result = await client.call_tool('docs_format_text', {
                'doc_id': 'test', 'anchor_text': 'Target phrase',
                'foreground_color': 'green', 'occurrence': 1,
            })
            assert result.structured_content['ok']
    asyncio.run(run())


@pytest.mark.parametrize('paragraph', [False, True])
def test_formatting_unknown_outcome_is_not_replayed(race_docs, paragraph):
    """Never replay a write after a lost server response."""
    race_docs['documents'].batchUpdate.return_value.execute.side_effect = TimeoutError()
    with pytest.raises(ToolFailureError) as caught:
        format_colors('test', 'Introduction', paragraph=paragraph,
                      background_color='yellow')
    assert caught.value.failure.code == 'WRITE_OUTCOME_UNKNOWN'
    race_docs['documents'].batchUpdate.assert_called_once()


def test_explicit_revision_never_rebases(race_docs):
    """Keep caller-provided preconditions strict across revision races."""
    race_docs['change'] = change_prefix
    with pytest.raises(ToolFailureError) as caught:
        format_colors('test', 'Introduction', background_color='yellow',
                      expected_revision_id='revision')
    assert caught.value.failure.code == 'EDIT_CONFLICT'
    assert len(race_docs['writes']) == 1


def test_case_insensitive_unicode_source_positions(mock_docs, simple_document):
    """Do not shift offsets when Unicode case folding changes text length."""
    simple_document.update(native_document([('İ prefix😀 TARGET', {})]))
    format_colors('test', 'target', foreground_color='red')
    update = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]['updateTextStyle']
    assert update['range'] == {'startIndex': 12, 'endIndex': 18}
