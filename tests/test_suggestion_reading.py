"""Verify coherent projections, source scope metadata and safe references."""

# Native fields and numeric examples are explicit API contracts.
# ruff: noqa: D103, PLR2004
import asyncio
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastmcp import Client

from gdocs_scope_mcp import server
from gdocs_scope_mcp.documents import (
    editing as docs_edit,
    reading,
)
from gdocs_scope_mcp.documents.tabs import select
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.suggestions import reading as suggestions
from gdocs_scope_mcp.suggestions.index import index_document
from gdocs_scope_mcp.tables import reading as table_read
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_revision_guards import api_error


@pytest.fixture
def projections(monkeypatch, simple_document):
    """Serve each native projection independently through the API boundary."""
    state = {
        'inline': deepcopy(simple_document),
        'preview': deepcopy(simple_document),
        'calls': [],
    }
    service = MagicMock()

    def get(**kwargs):
        state['calls'].append(kwargs)
        request = MagicMock()
        request.uri = 'https://docs.test/v1/documents/example'
        key = (
            'preview'
            if kwargs.get('suggestionsViewMode')
            == 'PREVIEW_WITHOUT_SUGGESTIONS'
            else 'inline'
        )

        def execute():
            value = state[key]
            if isinstance(value, Exception):
                raise value
            return deepcopy(value)

        request.execute.side_effect = execute
        return request

    service.documents().get.side_effect = get
    monkeypatch.setattr(clients, 'get_service', lambda *_args: service)
    state['service'] = service
    return state


def mark(document, paragraph=2, sid='proposal'):
    document['body']['content'][paragraph]['paragraph']['elements'][0][
        'textRun'
    ]['suggestedInsertionIds'] = [sid]


def test_no_proposals_uses_one_fetch_and_compact_notice(projections):
    result = reading.read('example')
    assert len(projections['calls']) == 1
    assert result.suggestions.document_has_pending is False
    assert result.suggestions.selected_content_has_pending is False
    assert result.suggestions.suggestion_ids == []
    assert result.suggestions.view == 'without_suggestions'


def test_clean_content_with_source_scope_metadata(projections):
    mark(projections['inline'])
    projections['inline']['body']['content'][2]['paragraph']['elements'][0][
        'textRun'
    ]['content'] = 'Proposed insertion\n'
    read = reading.read('example', ['parent'])
    assert 'Proposed insertion' not in read.sections[0].markdown
    assert 'Target phrase' in read.sections[0].markdown
    assert read.suggestions.selected_content_has_pending is True
    assert read.suggestions.suggestion_ids == ['proposal']
    other = reading.read('example', ['other'])
    assert other.suggestions.document_has_pending is True
    assert other.suggestions.selected_content_has_pending is False
    assert not other.suggestions.suggestion_ids


def test_hidden_insertion_still_belongs_to_requested_subtree(projections):
    mark(projections['inline'])
    projections['preview']['body']['content'].pop(2)
    result = reading.read('example', ['parent'])
    assert result.suggestions.selected_content_has_pending is True
    assert 'Target phrase\n' not in result.sections[0].markdown


def test_outline_uses_accepted_headings(projections):
    mark(projections['inline'], paragraph=3)
    projections['preview']['body']['content'].pop(3)
    outline = reading.get_tree('example')
    assert 'nested' not in [section.id for section in outline.sections]
    result = reading.read('example', ['nested'])
    assert result.code == 'HEADING_NOT_FOUND'


def test_preview_does_not_mutate_source_used_for_edits(projections):
    mark(projections['inline'])
    projections['preview']['body']['content'][2]['paragraph']['elements'][0][
        'textRun'
    ]['content'] = 'Preview only\n'
    result = docs_edit.search_replace('example', 'Target phrase', 'changed')
    assert result.ok
    assert all(
        call['suggestionsViewMode'] == 'SUGGESTIONS_INLINE'
        for call in projections['calls']
    )


def test_revision_mismatch_retries_then_fails(projections):
    mark(projections['inline'])
    projections['preview']['revisionId'] = 'different'
    with pytest.raises(ToolFailureError) as error:
        reading.read('example')
    assert error.value.failure.code == 'EDIT_CONFLICT'
    assert len(projections['calls']) == 6


def test_missing_revision_and_permission_fallback_are_unknown(projections):
    mark(projections['inline'])
    del projections['inline']['revisionId']
    del projections['preview']['revisionId']
    read = reading.read('example')
    assert read.revision_id is None
    assert read.suggestions.document_has_pending is None
    assert read.suggestions.detection == 'unavailable'
    projections['inline'] = api_error('Not allowed to view suggestions', 403)
    read = reading.read('example')
    assert read.suggestions.selected_content_has_pending is None


def test_failed_projection_never_returns_inline_mixture(projections):
    mark(projections['inline'])
    projections['preview'] = api_error('Unavailable', 503)
    with pytest.raises(Exception, match='Unavailable'):
        reading.read('example')


def test_text_and_paragraph_format_suggestions_are_detected(simple_document):
    paragraph = simple_document['body']['content'][2]['paragraph']
    paragraph['suggestedParagraphStyleChanges'] = {'paragraph-style': {}}
    paragraph['elements'][0]['textRun']['suggestedTextStyleChanges'] = {
        'text-style': {'textStyle': {'bold': True}},
    }
    index = index_document(simple_document)
    notice = index.notice(simple_document, ['parent'])
    assert notice.suggestion_ids == ['paragraph-style', 'text-style']
    assert notice.selected_content_has_pending is True
    assert (
        index.notice(simple_document, ['other']).selected_content_has_pending
        is False
    )


def test_named_style_and_list_inheritance(simple_document):
    simple_document['suggestedNamedStylesChanges'] = {
        'heading-style': {
            'namedStyles': {
                'styles': [
                    {
                        'namedStyleType': 'HEADING_2',
                        'paragraphStyle': {'lineSpacing': 200},
                    }
                ]
            },
        }
    }
    simple_document['body']['content'][2]['paragraph']['bullet'] = {
        'listId': 'list',
    }
    simple_document['lists'] = {
        'list': {
            'suggestedListPropertiesChanges': {'list-style': {}},
        }
    }
    index = index_document(simple_document)
    assert index.notice(simple_document, ['parent']).suggestion_ids == [
        'heading-style',
        'list-style',
    ]
    assert (
        index.notice(simple_document, ['other']).selected_content_has_pending
        is None
    )


def test_normal_style_inheritance_is_not_claimed_absent(simple_document):
    simple_document['suggestedNamedStylesChanges'] = {
        'normal-style': {
            'namedStyles': {
                'styles': [
                    {
                        'namedStyleType': 'NORMAL_TEXT',
                        'textStyle': {'bold': True},
                    }
                ]
            },
        }
    }
    index = index_document(simple_document)
    notice = index.notice(simple_document, ['nested'])
    assert notice.selected_content_has_pending is None
    assert notice.detection == 'partial'


def test_unknown_native_metadata_is_explicit(simple_document):
    simple_document['body']['content'][2]['paragraph'][
        'suggestedFuturePropertyChanges'
    ] = {'future': {}}
    notice = index_document(simple_document).notice(
        simple_document, ['parent']
    )
    assert notice.document_has_pending is True
    assert notice.selected_content_has_pending is None
    assert notice.detection == 'partial'


def test_document_style_affects_all_selected_body_content(simple_document):
    simple_document['suggestedDocumentStyleChanges'] = {'page': {}}
    index = index_document(simple_document)
    assert (
        index.notice(simple_document, ['other']).selected_content_has_pending
        is True
    )
    assert (
        index.notice(simple_document, []).selected_content_has_pending is False
    )


def test_section_style_proposals_cover_section_body(simple_document):
    simple_document['body']['content'].insert(
        0,
        {
            'endIndex': 1,
            'sectionBreak': {
                'suggestedSectionStyleChanges': {'section': {}},
            },
        },
    )
    assert (
        index_document(simple_document)
        .notice(
            simple_document,
            ['other'],
        )
        .selected_content_has_pending
        is True
    )


def test_tabs_are_isolated_but_document_indicator_is_global(simple_document):
    second = deepcopy(simple_document)
    mark(second)
    native = {
        'documentId': 'example',
        'title': 'Example',
        'revisionId': 'r',
        'tabs': [
            {
                'tabProperties': {'tabId': 'first'},
                'documentTab': {'body': simple_document['body']},
            },
            {
                'tabProperties': {'tabId': 'second'},
                'documentTab': {'body': second['body']},
            },
        ],
    }
    notice = index_document(native).notice(select(native, 'first'))
    assert notice.document_has_pending is True
    assert notice.selected_content_has_pending is False


def test_notice_bounds_ids(simple_document):
    simple_document['body']['content'][2]['paragraph']['elements'][0][
        'textRun'
    ]['suggestedInsertionIds'] = [f's{i}' for i in range(120)]
    notice = index_document(simple_document).notice(simple_document)
    assert len(notice.suggestion_ids) == 100
    assert notice.suggestion_ids_truncated


def test_text_only_table_proposals_keep_valid_native_refs(
    projections, table_document
):
    projections['inline'] = deepcopy(table_document)
    projections['preview'] = deepcopy(table_document)
    cell = projections['inline']['body']['content'][2]['table']['tableRows'][
        0
    ]['tableCells'][0]
    cell['content'][0]['paragraph']['elements'][0]['textRun'][
        'suggestedDeletionIds'
    ] = ['cell-text']
    cell['content'][0]['paragraph']['elements'][0]['textRun']['content'] = (
        'inline proposal mixture\n'
    )
    result = reading.read('example')
    assert 'data-mcp-table-ref=' in ''.join(
        s.markdown for s in result.sections
    )
    assert result.suggestions.selected_content_has_pending is True
    listing = table_read.tables_list('example')
    cells = table_read.table_read('example', listing.tables[0].table_ref)
    assert 'inline proposal mixture' not in cells.rows[0].cells[0].markdown
    assert 'First' in cells.rows[0].cells[0].markdown


def test_structural_table_proposals_omit_unsafe_refs(
    projections, table_document
):
    projections['inline'] = deepcopy(table_document)
    projections['preview'] = deepcopy(table_document)
    table = deepcopy(projections['inline']['body']['content'][2])
    table['table']['suggestedInsertionIds'] = ['new-table']
    projections['inline']['body']['content'].insert(2, table)
    result = reading.read('example')
    markdown = ''.join(s.markdown for s in result.sections)
    assert '<table' in markdown
    assert 'data-mcp-table-ref=' not in markdown
    assert any('table references' in w for w in result.suggestions.warnings)
    with pytest.raises(ToolFailureError) as error:
        table_read.tables_list('example')
    assert error.value.failure.code == 'TARGET_CHANGED'


@pytest.fixture
def proposal_threads(projections):
    """Provide active and closed native threads with complete detail posts."""
    inline = projections['inline']
    mark(inline, 2, 'a')
    mark(inline, 6, 'b')
    inline['suggestions'] = [
        {
            'suggestionId': sid,
            'status': 'OPEN',
            'summaryText': sid,
            'headPost': {
                'postId': 'head-' + sid,
                'content': 'Complete head',
                'author': {'displayName': 'Author'},
            },
            'replies': [
                {'postId': f'reply-{i}', 'content': f'Reply {i}'}
                for i in range(3)
            ],
        }
        for sid in ['a', 'b']
    ] + [{'suggestionId': 'closed', 'status': 'ACCEPTED'}]
    return projections


@pytest.mark.usefixtures('proposal_threads')
def test_thread_list_scope_and_detail_replies():
    result = suggestions.read('example', heading_id='parent')
    assert [s.suggestion_id for s in result.suggestions] == ['a']
    assert result.suggestions[0].head_post is None
    detail = suggestions.read('example', suggestion_id='a', limit=2)
    assert detail.page_kind == 'replies'
    assert detail.suggestions[0].head_post.content == 'Complete head'
    assert len(detail.suggestions[0].replies) == 2
    assert detail.has_more
    following = suggestions.read(
        'example',
        suggestion_id='a',
        limit=2,
        page_token=detail.next_page_token,
    )
    assert [p.content for p in following.suggestions[0].replies] == ['Reply 2']
    assert following.has_more is False


@pytest.mark.usefixtures('proposal_threads')
def test_closed_threads_have_explicit_unknown_scope():
    result = suggestions.read('example', include_closed=True)
    closed = next(s for s in result.suggestions if s.suggestion_id == 'closed')
    assert closed.scope_match == 'unknown'
    assert closed.locations == []
    assert result.warnings
    detail = suggestions.read('example', suggestion_id='closed')
    assert detail.suggestions[0].status == 'ACCEPTED'


def test_cursor_rejects_changed_thread_state_and_arguments(proposal_threads):
    page = suggestions.read('example', limit=1)
    assert page.has_more
    with pytest.raises(ToolFailureError) as error:
        suggestions.read('example', limit=2, page_token=page.next_page_token)
    assert error.value.failure.code == 'STALE_REFERENCE'
    proposal_threads['inline']['suggestions'][0]['summaryText'] = 'Changed'
    with pytest.raises(ToolFailureError) as error:
        suggestions.read('example', limit=1, page_token=page.next_page_token)
    assert error.value.failure.code == 'STALE_REFERENCE'
    assert 'suggestion' in error.value.failure.description


def test_bounded_summary_and_missing_thread_metadata(proposal_threads):
    proposal_threads['inline']['suggestions'][0]['summaryText'] = 'x' * 3000
    result = suggestions.read('example', suggestion_id='a')
    assert len(result.suggestions[0].summary) == 2000
    assert result.suggestions[0].summary_truncated
    proposal_threads['inline']['suggestions'] = []
    result = suggestions.read('example', suggestion_id='a')
    assert result.suggestions[0].status == 'UNKNOWN'
    assert result.suggestions[0].locations


@pytest.mark.usefixtures('proposal_threads')
def test_missing_id_and_accepted_heading_scope_fail():
    with pytest.raises(ToolFailureError) as error:
        suggestions.read('example', suggestion_id='missing')
    assert error.value.failure.code == 'RESOURCE_NOT_FOUND'
    with pytest.raises(ToolFailureError) as error:
        suggestions.read('example', heading_id='missing')
    assert error.value.failure.code == 'HEADING_NOT_FOUND'


def test_hidden_proposed_heading_does_not_cut_accepted_scope(projections):
    inline = projections['inline']
    mark(inline, 3, 'hidden-heading')
    inline['body']['content'][3]['paragraph']['paragraphStyle'][
        'namedStyleType'
    ] = 'HEADING_1'
    projections['preview']['body']['content'].pop(3)
    mark(inline, 4, 'body-change')
    result = reading.read('example', ['parent'])
    assert set(result.suggestions.suggestion_ids) == {
        'hidden-heading',
        'body-change',
    }


def test_heading_identity_mismatch_is_not_silently_mapped(projections):
    mark(projections['inline'])
    projections['inline']['body']['content'][1]['paragraph']['elements'][0][
        'textRun'
    ]['content'] = 'A different native heading\n'
    outline = reading.get_tree('example')
    assert 'parent' in outline.suggestions.unavailable_heading_ids
    result = reading.read('example', ['parent'])
    assert result.code == 'TARGET_CHANGED'
    whole = reading.read('example')
    assert whole.sections
    assert whole.suggestions.detection == 'partial'


def test_unlocated_open_thread_is_not_reported_absent(simple_document):
    simple_document['suggestions'] = [
        {'suggestionId': 'unlocated', 'status': 'OPEN'}
    ]
    notice = index_document(simple_document).notice(simple_document)
    assert notice.document_has_pending is True
    assert notice.selected_content_has_pending is None


def test_empty_selection_remains_empty_when_detection_is_partial(
    simple_document,
):
    simple_document['suggestedNamedStylesChanges'] = {'style': {}}
    notice = index_document(simple_document).notice(simple_document, [])
    assert notice.document_has_pending is True
    assert notice.selected_content_has_pending is False
    assert notice.suggestion_ids == []


@pytest.mark.parametrize(
    'arguments',
    [
        {'limit': 0},
        {'limit': 101},
        {'limit': True},
        {'suggestion_id': ''},
        {'heading_id': ''},
        {'tab_id': ''},
        {'page_token': 'x' * 8193},
    ],
)
def test_inspection_input_validation_precedes_api(projections, arguments):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(
                'docs_suggestions_read',
                {
                    'doc_id': 'example',
                    **arguments,
                },
                raise_on_error=False,
            )

    result = asyncio.run(run())
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert not projections['calls']
