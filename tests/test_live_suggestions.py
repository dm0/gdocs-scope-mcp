"""Record native suggestion capabilities without exposing production tools."""

# Imported fixtures keep pytest names; response counts are API contracts.
# ruff: noqa: F811

import asyncio
import uuid

from gdocs_scope_mcp.suggestion_index import index_document

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


def tab(document, tab_id):
    """Select only the temporary top-level tab used by the investigation."""
    return next(
        t['documentTab']
        for t in document['tabs']
        if t['tabProperties']['tabId'] == tab_id
    )


def text(document, tab_id):
    """Inspect native text without Markdown rendering or style loss."""
    return ''.join(
        paragraph_text(p) for p in tab(document, tab_id)['body']['content']
    )


def changed_ids(response, kind):
    """Collect native IDs from per-request suggestion response entries."""
    return {
        sid
        for r in response.get('suggestionResponses', [])
        for sid in r.get(kind, [])
    }


async def cleanup_suggestion_tab(probe, tab_id, original_tabs):
    """Remove pending owned proposals before their temporary tab disappears."""
    try:
        native = await probe.call(0, 'probe_suggestions_document',
                                  {'threads': True})
        index = index_document(native)
        open_ids = {t['suggestionId'] for t in native.get('suggestions', [])
                    if t.get('status') == 'OPEN'}
        owned = sorted(sid for sid, locations in index.locations.items()
                       if sid in open_ids
                       and any(loc.tab_id == tab_id for loc in locations))
        for offset in range(0, len(owned), 50):
            await probe.call(0, 'docs_suggestions_manage', {
                'doc_id': native['documentId'], 'action': 'delete',
                'suggestion_ids': owned[offset:offset + 50],
            })
    finally:
        current = await probe.call(0, 'probe_tabs_document')
        await probe.batch([{'deleteTab': {'tabId': tab_id}}], current)
        after = await probe.call(0, 'probe_tabs_document')
        assert_tabs_unchanged(original_tabs, after['tabs'])
        probe.report['temporary_tab_removed'] = True


def test_live_suggestion_lifecycle(
    live_test_doc, table_probe, monkeypatch, tmp_path
):
    """Check projections, decisions, formatting and revision guards."""
    monkeypatch.setenv(
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DIRECTORY', str(tmp_path)
    )

    async def run():
        async with table_probe('suggestions') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch(
                    [
                        {
                            'addDocumentTab': {
                                'tabProperties': {
                                    'title': 'mcp-suggest-' + uuid.uuid4().hex
                                },
                            }
                        }
                    ],
                    before,
                )
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                await probe.call(
                    0,
                    'docs_append',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': tab_id,
                        'text': 'Original text',
                        'rich': False,
                    },
                )

                async def read(view='SUGGESTIONS_INLINE', threads=False):
                    return await probe.call(
                        1,
                        'probe_suggestions_document',
                        {
                            'view': view,
                            'threads': threads,
                        },
                    )

                async def batch(
                    requests, mode='SUGGEST', target=False, revision=None
                ):
                    current = await read()
                    return await probe.call(
                        0,
                        'probe_suggestions_batch',
                        {
                            'requests': requests,
                            'mode': mode,
                            'target': target,
                            'revision': revision or current['revisionId'],
                        },
                    )

                async def insert(value, target=False):
                    result = await batch(
                        [
                            {
                                'insertText': {
                                    'location': {'index': 1, 'tabId': tab_id},
                                    'text': value,
                                }
                            }
                        ],
                        target=target,
                    )
                    assert result['accepted'], result
                    response = result['response']
                    assert response['commentUpdateState'] == 'ALL_SAVED'
                    ids = changed_ids(response, 'createdSuggestionIds')
                    assert ids
                    return ids

                base = await read()
                original = text(base, tab_id)
                ids = await insert('PROPOSED ')
                inline = await read(threads=True)
                assert text(inline, tab_id).startswith('PROPOSED ')
                assert (
                    text(await read('PREVIEW_WITHOUT_SUGGESTIONS'), tab_id)
                    == original
                )
                assert text(
                    await read('PREVIEW_SUGGESTIONS_ACCEPTED'), tab_id
                ).startswith('PROPOSED ')
                threads = [
                    s
                    for s in inline.get('suggestions', [])
                    if s['suggestionId'] in ids
                ]
                assert len(threads) == len(ids)
                probe.report['thread_fields'] = sorted(threads[0])
                rendered = await probe.call(
                    0,
                    'docs_read',
                    {
                        'doc_id': live_test_doc,
                        'tab_id': tab_id,
                    },
                )
                markdown = '\n'.join(
                    s['markdown'] for s in rendered['sections']
                )
                probe.report['current_reader_exposes_suggestion_ids'] = any(
                    sid in markdown for sid in ids
                )
                rejected = await batch(
                    [
                        {'rejectSuggestion': {'suggestionId': sid}}
                        for sid in ids
                    ],
                    mode='EDIT',
                )
                assert rejected['accepted'], rejected
                assert text(await read(), tab_id) == original
                probe.report['reject_state'] = rejected['response'].get(
                    'commentUpdateState'
                )

                ids = await insert('ACCEPTED ', target=True)
                accepted = await batch(
                    [
                        {'acceptSuggestion': {'suggestionId': sid}}
                        for sid in ids
                    ],
                    mode='EDIT',
                )
                assert accepted['accepted'], accepted
                assert text(
                    await read('PREVIEW_WITHOUT_SUGGESTIONS'), tab_id
                ).startswith('ACCEPTED ')

                ids = await insert('DELETED ')
                deleted = await batch(
                    [
                        {'deleteSuggestion': {'suggestionId': sid}}
                        for sid in ids
                    ],
                    mode='EDIT',
                )
                assert deleted['accepted'], deleted
                probe.report['delete_removes_inserted_text'] = not text(
                    await read(),
                    tab_id,
                ).startswith('DELETED ')

                original = text(await read(), tab_id)
                replacement = await batch(
                    [
                        {
                            'insertText': {
                                'location': {'index': 1, 'tabId': tab_id},
                                'text': 'REPLACED ',
                            }
                        },
                        {
                            'deleteContentRange': {
                                'range': {
                                    'startIndex': 10,
                                    'endIndex': 18,
                                    'tabId': tab_id,
                                }
                            }
                        },
                    ]
                )
                assert replacement['accepted'], replacement
                assert replacement['response']['commentUpdateState'] == (
                    'ALL_SAVED'
                )
                assert (
                    text(await read('PREVIEW_WITHOUT_SUGGESTIONS'), tab_id)
                    == original
                )
                assert text(
                    await read('PREVIEW_SUGGESTIONS_ACCEPTED'), tab_id
                ).startswith('REPLACED ')
                ids = changed_ids(
                    replacement['response'], 'createdSuggestionIds'
                )
                assert ids
                probe.report['replacement_suggestion_count'] = len(ids)
                rejected = await batch(
                    [
                        {'rejectSuggestion': {'suggestionId': sid}}
                        for sid in ids
                    ],
                    mode='EDIT',
                )
                assert rejected['accepted'], rejected
                assert text(await read(), tab_id) == original

                current = await read()
                unsupported = await batch(
                    [
                        {
                            'insertText': {
                                'location': {'index': 1, 'tabId': tab_id},
                                'text': 'SHOULD NOT APPEAR ',
                            }
                        },
                        {
                            'createNamedRange': {
                                'name': 'suggest-probe',
                                'range': {
                                    'startIndex': 1,
                                    'endIndex': 2,
                                    'tabId': tab_id,
                                },
                            }
                        },
                    ]
                )
                assert unsupported['accepted'] is False
                assert text(await read(), tab_id) == text(current, tab_id)
                probe.report['named_range_rejection'] = unsupported

                styled = await batch(
                    [
                        {
                            'updateTextStyle': {
                                'range': {
                                    'startIndex': 1,
                                    'endIndex': 3,
                                    'tabId': tab_id,
                                },
                                'textStyle': {'bold': True},
                                'fields': 'bold',
                            }
                        }
                    ]
                )
                assert styled['accepted'], styled
                assert styled['response']['commentUpdateState'] == 'ALL_SAVED'
                styled_read = await read()
                assert 'suggestedTextStyleChanges' in str(
                    tab(styled_read, tab_id)
                )
                probe.report['style_suggestion_created'] = bool(
                    changed_ids(
                        styled['response'],
                        'createdSuggestionIds',
                    )
                )

                stale = await batch(
                    [
                        {
                            'insertText': {
                                'location': {'index': 1, 'tabId': tab_id},
                                'text': 'STALE ',
                            }
                        }
                    ],
                    revision=base['revisionId'],
                )
                assert stale['accepted'] is False
                probe.report['stale_required_rejected'] = True
                probe.report['lifecycle_passed'] = True
            finally:
                if tab_id:
                    await cleanup_suggestion_tab(probe, tab_id, before['tabs'])

    asyncio.run(run())


def test_live_accepted_content_and_scoped_inspection(
    live_test_doc,
    table_probe,
    monkeypatch,
    tmp_path,
):
    """Read accepted content and inspect a replacement proposal separately."""
    monkeypatch.setenv(
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DIRECTORY', str(tmp_path)
    )

    async def run():
        async with table_probe('suggestion-reading') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch(
                    [
                        {
                            'addDocumentTab': {
                                'tabProperties': {
                                    'title': 'mcp-reading-' + uuid.uuid4().hex
                                },
                            }
                        }
                    ],
                    before,
                )
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                arguments = {'doc_id': live_test_doc, 'tab_id': tab_id}
                await probe.call(
                    0,
                    'docs_append',
                    {
                        **arguments,
                        'text': (
                            '### Target\n\nold wording\n\n'
                            '### Other\n\nuntouched'
                        ),
                    },
                )
                tree = await probe.call(0, 'docs_get_tree', arguments)
                headings = {
                    s['title'].strip(): s['id']
                    for s in tree['sections']
                    if s['id']
                }
                native = await probe.call(0, 'probe_tabs_document')
                source = next(
                    p
                    for p in tab(native, tab_id)['body']['content']
                    if paragraph_text(p).strip() == 'old wording'
                )
                start = source['startIndex']
                result = await probe.call(
                    0,
                    'probe_suggestions_batch',
                    {
                        'revision': native['revisionId'],
                        'requests': [
                            {
                                'insertText': {
                                    'location': {
                                        'index': start,
                                        'tabId': tab_id,
                                    },
                                    'text': 'new wording',
                                }
                            },
                            {
                                'deleteContentRange': {
                                    'range': {
                                        'startIndex': start
                                        + len('new wording'),
                                        'endIndex': start
                                        + len('new wordingold wording'),
                                        'tabId': tab_id,
                                    }
                                }
                            },
                        ],
                    },
                )
                assert result['accepted'], result
                assert result['response']['commentUpdateState'] == 'ALL_SAVED'
                ids = changed_ids(result['response'], 'createdSuggestionIds')
                assert ids
                read = await probe.call(
                    1,
                    'docs_read',
                    {
                        **arguments,
                        'heading_ids': [headings['Target']],
                    },
                )
                markdown = '\n'.join(s['markdown'] for s in read['sections'])
                assert 'old wording' in markdown
                assert 'new wording' not in markdown
                notice = read['suggestions']
                assert notice['view'] == 'without_suggestions'
                assert notice['document_has_pending'] is True
                assert notice['selected_content_has_pending'] is True
                assert ids <= set(notice['suggestion_ids'])
                other = await probe.call(
                    1,
                    'docs_read',
                    {
                        **arguments,
                        'heading_ids': [headings['Other']],
                    },
                )
                assert other['suggestions']['document_has_pending'] is True
                assert (
                    other['suggestions']['selected_content_has_pending']
                    is False
                )
                listing = await probe.call(
                    1,
                    'docs_suggestions_read',
                    {
                        **arguments,
                        'heading_id': headings['Target'],
                    },
                )
                assert ids <= {
                    s['suggestion_id'] for s in listing['suggestions']
                }
                sid = next(iter(ids))
                detail = await probe.call(
                    1,
                    'docs_suggestions_read',
                    {
                        **arguments,
                        'suggestion_id': sid,
                    },
                )
                item = next(
                    s
                    for s in detail['suggestions']
                    if s['suggestion_id'] == sid
                )
                assert item['status'] == 'OPEN'
                assert item['scope_match'] == 'matched'
                assert item['locations']
                assert item['head_post']
                current = await probe.call(0, 'probe_tabs_document')
                body = tab(current, tab_id)['body']['content']
                untouched = next(
                    p for p in body if paragraph_text(p).strip() == 'untouched'
                )
                formatted = await probe.call(
                    0,
                    'probe_suggestions_batch',
                    {
                        'revision': current['revisionId'],
                        'requests': [
                            {
                                'updateTextStyle': {
                                    'range': {
                                        'startIndex': untouched['startIndex'],
                                        'endIndex': untouched['endIndex'] - 1,
                                        'tabId': tab_id,
                                    },
                                    'textStyle': {'bold': True},
                                    'fields': 'bold',
                                }
                            }
                        ],
                    },
                )
                assert formatted['accepted'], formatted
                clean = await probe.call(
                    1,
                    'docs_read',
                    {
                        **arguments,
                        'heading_ids': [headings['Other']],
                    },
                )
                assert (
                    clean['suggestions']['selected_content_has_pending']
                    is True
                )
                assert '<b>' not in ''.join(
                    s['markdown'] for s in clean['sections']
                )
                current = await probe.call(0, 'probe_tabs_document')
                end = (
                    tab(current, tab_id)['body']['content'][-1]['endIndex'] - 1
                )
                heading_text = '\nProposed heading'
                proposed_heading = await probe.call(
                    0,
                    'probe_suggestions_batch',
                    {
                        'revision': current['revisionId'],
                        'requests': [
                            {
                                'insertText': {
                                    'location': {
                                        'index': end,
                                        'tabId': tab_id,
                                    },
                                    'text': heading_text,
                                }
                            },
                            {
                                'updateParagraphStyle': {
                                    'range': {
                                        'startIndex': end + 1,
                                        'endIndex': end + len(heading_text),
                                        'tabId': tab_id,
                                    },
                                    'paragraphStyle': {
                                        'namedStyleType': 'HEADING_1'
                                    },
                                    'fields': 'namedStyleType',
                                }
                            },
                        ],
                    },
                )
                assert proposed_heading['accepted'], proposed_heading
                after_tree = await probe.call(1, 'docs_get_tree', arguments)
                assert [
                    (s['id'], s['title']) for s in after_tree['sections']
                ] == [(s['id'], s['title']) for s in tree['sections']]
                probe.report['accepted_reading_passed'] = True
                probe.report['scoped_metadata_passed'] = True
                probe.report['native_thread_inspection_passed'] = True
            finally:
                if tab_id:
                    await cleanup_suggestion_tab(probe, tab_id, before['tabs'])

    asyncio.run(run())
