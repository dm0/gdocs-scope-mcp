"""Keep duplicate headings, text, metadata and tables local to each tab."""

# Imported fixtures intentionally retain their pytest names.
# ruff: noqa: F811

import asyncio
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastmcp import Client

from gdocs_scope_mcp import docs_edit, server, table_read, table_snapshots
from gdocs_scope_mcp.document_tabs import discover, scope_requests, select
from gdocs_scope_mcp.entity_edit import validate_insertions
from gdocs_scope_mcp.table_patch import CellPatch, patch
from gdocs_scope_mcp.tool_errors import ToolFailureError

from .test_revision_guards import api_error
from .test_table_discovery import call, table_source  # noqa: F401


@pytest.fixture
def tabs(table_source, mock_docs):
    """Use identical native positions and heading/table content in all tabs."""
    original = table_source()
    payload = {
        k: deepcopy(v)
        for k, v in original.items()
        if k not in {'documentId', 'title', 'revisionId'}
    }

    def tab(identifier, children=None):
        return {
            'tabProperties': {'tabId': identifier, 'title': identifier},
            'documentTab': deepcopy(payload),
            'childTabs': children or [],
        }

    result = {k: original[k] for k in ('documentId', 'title', 'revisionId')}
    result['tabs'] = [tab('first', [tab('nested')]), tab('second')]
    mock_docs.get.return_value.execute.side_effect = lambda: deepcopy(result)
    return result


@pytest.mark.usefixtures('tabs')
def test_discovery_hierarchy_and_read_only(mock_docs):
    """Expose nested IDs without creating markers or changing revisions."""
    result = call('docs_tabs_list', doc_id='example')
    assert not result.is_error
    data = result.structured_content
    assert data['default_tab_id'] == 'first'
    assert [
        (t['tab_id'], t['parent_tab_id'], t['depth']) for t in data['tabs']
    ] == [('first', None, 0), ('nested', 'first', 1), ('second', None, 0)]
    assert 'body' not in str(data)
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('tab_id', [None, 'first', 'nested', 'second'])
@pytest.mark.usefixtures('tabs')
def test_reads_outline_and_table_refs_share_tab(mock_docs, tab_id):
    """Duplicate headings and indices cannot make refs interchangeable."""
    actual = tab_id or 'first'
    outline = docs_edit.get_tree('example', tab_id=tab_id)
    read = docs_edit.read('example', ['parent'], tab_id=tab_id)
    listing = table_read.tables_list('example', tab_id=tab_id)
    assert outline.tab_id == read.tab_id == listing.snapshot.tab_id == actual
    assert [t.tab_id for t in outline.tabs] == ['first', 'nested', 'second']
    assert read.tab_title == actual
    expected_scope = 'selected_tab' if tab_id else 'first_tab'
    assert listing.snapshot.scope == expected_scope
    table = table_read.table_read(
        'example', listing.tables[0].table_ref, tab_id=tab_id
    )
    assert table.snapshot.tab_id == actual
    assert docs_edit.get_full_tree('example', tab_id=tab_id).tab_id == actual
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('single_tab', [False, True])
@pytest.mark.parametrize('selected_tab', [None, 'nested'])
def test_outline_includes_complete_tab_inventory(
    tabs, mock_docs, single_tab, selected_tab,
):
    """Return all tab IDs/titles from the same snapshot as the outline."""
    if single_tab:
        tabs['tabs'] = [tabs['tabs'][0]['childTabs'][0]]
    expected = discover(tabs).model_dump()['tabs']
    result = call('docs_get_tree', doc_id='example', tab_id=selected_tab)
    assert not result.is_error
    data = result.structured_content
    assert data['tabs'] == expected
    assert data['tab_id'] == (selected_tab or expected[0]['tab_id'])
    assert len(data['tabs']) == (1 if single_tab else 3)
    assert all('body' not in t and 'documentTab' not in t
               for t in data['tabs'])
    mock_docs.get.assert_called_once()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize(
    'tool,extra',
    [
        ('docs_read', {}),
        ('docs_get_tree', {}),
        ('docs_tables_list', {}),
        ('docs_append', {'text': 'must not write'}),
        ('docs_insert_before', {'anchor': 'parent', 'text': 'x'}),
        ('docs_insert_after', {'anchor': 'parent', 'text': 'x'}),
        (
            'docs_search_replace',
            {'find': 'same', 'replace': 'x', 'occurrence': 0},
        ),
        ('docs_delete_paragraph', {'anchor': 'Tail'}),
        (
            'docs_batch_replace',
            {
                'replacements': [{'find': 'Tail', 'replace': 'x'}],
            },
        ),
        ('docs_add_comment', {'anchor_text': 'Tail', 'comment': 'x'}),
    ],
)
@pytest.mark.usefixtures('tabs')
def test_missing_explicit_tab_never_falls_back(mock_docs, tool, extra):
    """Validate explicit selectors before any native or Drive mutation."""
    result = call(tool, doc_id='example', tab_id='missing', **extra)
    assert result.is_error
    assert result.structured_content['code'] == 'RESOURCE_NOT_FOUND'
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('tab_id', ['', 'bad id', 'x' * 257, 7])
def test_invalid_selector_rejected_before_api(mock_docs, tab_id):
    """MCP schemas reject malformed IDs before obtaining a document."""
    result = call('docs_read', doc_id='example', tab_id=tab_id)
    assert result.is_error
    mock_docs.get.assert_not_called()


@pytest.mark.parametrize(
    'operation',
    ['replace', 'replace_all', 'before', 'after', 'append', 'delete', 'batch'],
)
@pytest.mark.usefixtures('tabs')
def test_text_writes_are_scoped(mock_docs, operation):
    """Write locations and native replace-all criteria always name one tab."""
    kwargs = {'tab_id': 'nested'}
    if operation == 'replace':
        result = docs_edit.search_replace('example', 'Tail', 'new', **kwargs)
    elif operation == 'replace_all':
        result = docs_edit.search_replace(
            'example', 'same', 'new', occurrence=0, **kwargs
        )
    elif operation in {'before', 'after'}:
        result = getattr(docs_edit, 'insert_' + operation)(
            'example',
            'parent',
            'new',
            rich=False,
            **kwargs,
        )
    elif operation == 'append':
        result = docs_edit.append('example', 'new', rich=False, **kwargs)
    elif operation == 'delete':
        result = docs_edit.delete_paragraph('example', 'Tail', **kwargs)
    else:
        result = docs_edit.batch_replace(
            'example',
            [
                {'find': 'Tail', 'replace': 'new'},
            ],
            **kwargs,
        )
    assert (
        result['tab_id'] if isinstance(result, dict) else result.tab_id
    ) == 'nested'
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['requests'] == scope_requests(body['requests'], 'nested')
    assert 'nested' in str(body['requests'])
    if operation == 'replace_all':
        assert body['requests'][0]['replaceAllText']['tabsCriteria'] == {
            'tabIds': ['nested'],
        }
        assert 'writeControl' not in body
    else:
        assert body['writeControl'] == {'requiredRevisionId': 'revision'}


@pytest.mark.usefixtures('tabs')
def test_default_native_replace_all_restricts_first_tab(mock_docs):
    """Google's all-tabs default must not expand our first-tab default."""
    docs_edit.search_replace('example', 'same', 'new', occurrence=0)
    request = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]
    assert request['replaceAllText']['tabsCriteria'] == {'tabIds': ['first']}


@pytest.mark.usefixtures('tabs')
def test_tables_and_snapshots_reject_cross_tab_reuse(mock_docs):
    """Matching layouts and text never authorize writes in another tab."""
    first = table_read.tables_list('example').tables[0].table_ref
    listing = table_read.tables_list('example', tab_id='second')
    second = listing.tables[0].table_ref
    assert first != second
    baseline = table_snapshots.snapshot(
        'example', second, ['A1'], ['content', 'text_style'], tab_id='second'
    )
    for tab_id in (None, 'first', 'nested'):
        with pytest.raises(ToolFailureError):
            table_read.table_read('example', second, tab_id=tab_id)
        with pytest.raises(ToolFailureError):
            patch(
                'example',
                second,
                baseline.base_token,
                [CellPatch(address='A1', markdown='changed')],
                tab_id=tab_id,
            )
    mock_docs.batchUpdate.assert_not_called()
    patch(
        'example',
        second,
        baseline.base_token,
        [CellPatch(address='A1', markdown='changed')],
        tab_id='second',
    )
    body = mock_docs.batchUpdate.call_args.kwargs['body']
    assert body['requests'] == scope_requests(body['requests'], 'second')


@pytest.mark.usefixtures('tabs')
def test_page_token_bound_to_tab():
    """Continuation cannot silently resume a matching layout in another tab."""
    page = table_read.tables_list('example', limit=1, tab_id='second')
    with pytest.raises(ToolFailureError):
        table_read.tables_list(
            'example', limit=1, page_token=page.next_page_token, tab_id='first'
        )


def test_selection_uses_only_selected_metadata(tabs):
    """Never borrow lists, named ranges or definitions from another tab."""
    tabs['tabs'][0]['documentTab']['dropdownDefinitions'] = {'first': {}}
    child = tabs['tabs'][0]['childTabs'][0]['documentTab']
    child['dropdownDefinitions'] = {'nested': {}}
    child['namedRanges'] = {'local': {}}
    selected = select(tabs, 'nested')
    assert selected['dropdownDefinitions'] == {'nested': {}}
    assert selected['namedRanges'] == {'local': {}}
    assert 'tabs' not in selected
    assert select(selected) is selected
    with pytest.raises(ToolFailureError):
        select(selected, 'first')


def test_duplicate_tab_ids_and_legacy_explicit_selection(tabs):
    """Reject ambiguous native IDs and do not invent IDs for old fixtures."""
    tabs['tabs'][1]['tabProperties']['tabId'] = 'first'
    with pytest.raises(ToolFailureError):
        discover(tabs)
    with pytest.raises(ToolFailureError):
        select({'body': {}}, 'missing')


def test_request_scoping_is_immutable_and_rejects_mismatch():
    """Scope ranges, nested table locations and named-range criteria safely."""
    requests = [
        {
            'createNamedRange': {
                'name': 'code',
                'range': {
                    'startIndex': 1,
                    'endIndex': 4,
                },
            }
        },
        {'deleteNamedRange': {'name': 'code'}},
        {
            'mergeTableCells': {
                'tableRange': {
                    'tableCellLocation': {
                        'tableStartLocation': {'index': 1},
                    }
                }
            }
        },
    ]
    before = deepcopy(requests)
    scoped = scope_requests(requests, 'nested')
    assert requests == before
    assert scoped[0]['createNamedRange']['range']['tabId'] == 'nested'
    assert scoped[1]['deleteNamedRange']['tabsCriteria'] == {
        'tabIds': ['nested'],
    }
    assert (
        scoped[2]['mergeTableCells']['tableRange']['tableCellLocation'][
            'tableStartLocation'
        ]['tabId']
        == 'nested'
    )
    with pytest.raises(ToolFailureError):
        scope_requests(scoped, 'other')


def test_catalog_optional_tab_selectors():
    """Applicable tools advertise an optional tab selector."""

    async def check():
        async with Client(server.mcp) as client:
            for tool in await client.list_tools():
                if tool.name in {
                    'server_info',
                    'docs_tabs_list',
                    'docs_list',
                    'docs_create',
                    'docs_read_comments',
                    'docs_reply_to_comment',
                    'docs_resolve_comment',
                    'docs_delete_comment',
                }:
                    continue
                assert 'tab_id' in tool.inputSchema['properties'], tool.name
                assert 'tab_id' not in tool.inputSchema.get('required', [])
                selector = tool.inputSchema['properties']['tab_id']
                description = selector.get('description') or next(
                    branch.get('description', '')
                    for branch in selector['anyOf']
                    if branch.get('type') == 'string'
                )
                assert 'docs_get_tree.tabs' in description
                assert 'single-tab' in description and 'null' in description

    asyncio.run(check())


@pytest.mark.parametrize('single_tab', [False, True])
@pytest.mark.parametrize('heading_ids', [None, ['parent']])
def test_read_discloses_tab_count_without_extra_discovery(
    tabs, mock_docs, single_tab, heading_ids,
):
    """Heading partialness never hides the existence of other tabs."""
    if single_tab:
        tabs['tabs'] = tabs['tabs'][:1]
        tabs['tabs'][0]['childTabs'] = []
    result = call('docs_read', doc_id='example', heading_ids=heading_ids)
    assert not result.is_error
    assert result.structured_content['tab_count'] == (1 if single_tab else 3)
    assert result.structured_content['partial'] == (heading_ids is not None)
    assert result.structured_content['tab_id'] == 'first'
    mock_docs.get.assert_called_once()
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('tab_id', [None, 'nested'])
@pytest.mark.parametrize('tool', [
    'docs_tables_list', 'docs_table_read', 'docs_table_snapshot',
    'docs_table_patch', 'docs_table_format', 'docs_table_structure',
])
@pytest.mark.usefixtures('tabs')
def test_table_responses_identify_effective_tab(mock_docs, tool, tab_id):
    """All table receipts expose the selected tab without decoding tokens."""
    listing = table_read.tables_list('example', tab_id=tab_id)
    reference = listing.tables[0].table_ref
    fields = (['cell.background_color'] if tool == 'docs_table_format'
              else ['content', 'text_style'])
    snapshot = table_snapshots.snapshot('example', reference, ['A1'], fields,
                                        tab_id=tab_id)
    arguments = {'doc_id': 'example', 'tab_id': tab_id}
    if tool != 'docs_tables_list':
        arguments['table_ref'] = reference
    if tool == 'docs_table_snapshot':
        arguments['cells'] = ['A1']
    if tool in {'docs_table_patch', 'docs_table_format',
                'docs_table_structure'}:
        arguments['base_token'] = snapshot.base_token
    if tool == 'docs_table_patch':
        arguments['changes'] = [{'address': 'A1', 'markdown': 'new'}]
    elif tool == 'docs_table_format':
        arguments['changes'] = {'cells': [{'address': 'A1',
                                           'background_color': '#112233'}]}
    elif tool == 'docs_table_structure':
        arguments['operation'] = {'type': 'insert_rows', 'row': 1,
                                 'position': 'after'}
    result = call(tool, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content['tab_id'] == (tab_id or 'first')
    if tool in {'docs_tables_list', 'docs_table_read', 'docs_table_snapshot'}:
        mock_docs.batchUpdate.assert_not_called()


@pytest.mark.usefixtures('tabs')
def test_tab_mismatch_gives_actionable_recovery_without_writes(mock_docs):
    """A forgotten selector is recoverable with the existing valid ref."""
    listing = table_read.tables_list('example', tab_id='second')
    reference = listing.tables[0].table_ref
    result = call('docs_table_read', doc_id='example', table_ref=reference)
    assert result.is_error
    error = result.structured_content
    assert error['code'] == 'TAB_MISMATCH'
    assert "tab_id='first'" in error['description']
    assert "tab_id='second'" in error['suggested_action']
    assert error['committed_batches'] == 0
    recovered = call('docs_table_read', doc_id='example',
                     table_ref=reference, tab_id='second')
    assert not recovered.is_error
    assert recovered.structured_content['tab_id'] == 'second'
    mock_docs.batchUpdate.assert_not_called()


def test_page_selector_error_precedes_revision_error(tabs):
    """Explain the wrong tab even if another edit also aged the cursor."""
    page = table_read.tables_list('example', limit=1, tab_id='second')
    tabs['revisionId'] = 'changed'
    with pytest.raises(ToolFailureError) as caught:
        table_read.tables_list('example', limit=1,
                               page_token=page.next_page_token)
    assert caught.value.failure.code == 'TAB_MISMATCH'
    assert "tab_id='second'" in caught.value.failure.suggested_action


@pytest.mark.parametrize('remove', [False, True])
def test_default_selection_pinned_during_retry(tabs, mock_docs, remove):
    """Reordering cannot redirect a retry to the new first tab."""
    writes = []

    def write():
        writes.append(deepcopy(mock_docs.batchUpdate.call_args.kwargs['body']))
        if len(writes) == 1:
            tabs['tabs'].reverse()
            if remove:
                tabs['tabs'].pop()
            tabs['revisionId'] = 'new-revision'
            raise api_error('The provided revision ID does not match the '
                            'current revision ID of the document.')
        return {}

    mock_docs.batchUpdate.return_value.execute.side_effect = write
    if remove:
        with pytest.raises(ToolFailureError):
            docs_edit.search_replace('example', 'Tail', 'new')
        assert len(writes) == 1
    else:
        result = docs_edit.search_replace('example', 'Tail', 'new')
        assert result.tab_id == 'first'
        assert len(writes) == 2  # noqa: PLR2004
        assert writes[1]['writeControl'] == {
            'requiredRevisionId': 'new-revision',
        }
    assert all(body['requests'] == scope_requests(body['requests'], 'first')
               for body in writes)


@pytest.mark.usefixtures('tabs')
def test_comment_anchor_and_bookmark_choose_same_tab(mock_docs,
                                                    monkeypatch):
    """Named ranges, Apps Script and jump URLs agree on the intended tab."""
    mock_docs.batchUpdate.return_value.execute.return_value = {
        'replies': [{'createNamedRange': {'namedRangeId': 'anchor'}}],
    }
    drive = MagicMock()
    drive.comments().create().execute.return_value = {'id': 'comment'}
    monkeypatch.setattr(docs_edit, 'build', lambda *_args, **_kwargs: drive)
    monkeypatch.setattr(docs_edit, '_load_creds', lambda: None)
    bridge = MagicMock(return_value={'bookmark_id': 'bookmark',
                                    'script_id': 'script'})
    monkeypatch.setattr(docs_edit, '_create_bookmark_via_apps_script', bridge)
    result = docs_edit.add_comment('example', 'comment', 'Tail',
                                   tab_id='nested', bookmark_jump=True)
    request = mock_docs.batchUpdate.call_args.kwargs['body']['requests'][0]
    assert request['createNamedRange']['range']['tabId'] == 'nested'
    assert bridge.call_args.kwargs['tab_id'] == 'nested'
    assert '?tab=nested#bookmark=bookmark' in result['bookmark_url']


def test_chip_preflight_uses_destination_definitions(tabs, mock_docs):
    """A source definition in another tab never authorizes a new instance."""
    definition = {'dropdownDefinitionProperties': {'options': [
        {'optionId': 'item'},
    ]}}
    tabs['tabs'][0]['documentTab']['dropdownDefinitions'] = {'def': definition}
    requests = [{'insertDropdown': {'dropdownDefinitionId': 'def',
                                     'selectedOptionId': 'item'}}]
    service = docs_edit._get_service()
    with pytest.raises(ToolFailureError):
        validate_insertions(service, 'example', requests, tab_id='nested')
    tabs['tabs'][0]['childTabs'][0]['documentTab']['dropdownDefinitions'] = {
        'def': definition,
    }
    validate_insertions(service, 'example', requests, tab_id='nested')
    mock_docs.batchUpdate.assert_not_called()
