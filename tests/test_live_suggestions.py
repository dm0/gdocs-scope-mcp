"""Record native suggestion capabilities without exposing production tools."""

# Imported fixtures keep pytest names; response counts are API contracts.
# ruff: noqa: F811

import asyncio
import uuid

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
                    current = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': tab_id}}],
                        current,
                    )
                    after = await probe.call(0, 'probe_tabs_document')
                    assert after['tabs'] == before['tabs']
                    probe.report['temporary_tab_removed'] = True

    asyncio.run(run())
