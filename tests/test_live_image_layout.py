"""Check automatic image widths using native readback through isolated MCP."""


# Imported fixtures intentionally retain names; dimensions are test contracts.
# ruff: noqa: F811

import asyncio
import uuid

import pytest

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import paragraph_text, table_probe  # noqa: F401


def selected(native, tab_id):
    """Find the temporary top-level tab without using the layout calculator."""
    return next(
        tab['documentTab']
        for tab in native['tabs']
        if tab['tabProperties']['tabId'] == tab_id
    )


def objects(tab):
    """Read actual native widths/heights in document order."""
    result = []
    for item in tab['body']['content']:
        paragraph = item.get('paragraph', {})
        for element in paragraph.get('elements', []):
            if 'inlineObjectElement' not in element:
                continue
            object_id = element['inlineObjectElement']['inlineObjectId']
            embedded = tab['inlineObjects'][object_id][
                'inlineObjectProperties'
            ]['embeddedObject']
            result.append(embedded['size'])
    return result


def test_live_image_layout(
    live_test_doc,
    table_probe,
    image_png,
    tmp_path,
    monkeypatch,
):
    """Size local images in ordinary, nested and indented paragraphs."""
    image_path = tmp_path / 'image.png'
    image_path.write_bytes(image_png)
    monkeypatch.setenv(
        'GDOCS_SCOPE_MCP_DOCUMENT_CACHE_DIRECTORY', str(tmp_path / 'cache')
    )

    async def run():
        async with table_probe('image-layout') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch(
                    [
                        {
                            'addDocumentTab': {
                                'tabProperties': {
                                    'title': 'mcp-images-' + uuid.uuid4().hex
                                },
                            }
                        }
                    ],
                    before,
                )
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties'
                ]['tabId']
                args = {
                    'doc_id': live_test_doc,
                    'tab_id': tab_id,
                    'upload_local_images': True,
                }
                result = await probe.call(
                    0,
                    'docs_append',
                    {
                        **args,
                        'text': (
                            f'<p>ordinary <img src="{image_path}"></p>'
                            '<ul><li>parent<ul><li>nested '
                            f'<img src="{image_path}"></li></ul></li></ul>'
                            f'<p>explicit <img src="{image_path}" '
                            'width="96"></p>'
                        ),
                    },
                )
                assert not result['temporary_image_cleanup_pending']
                native = await probe.call(1, 'probe_tabs_document')
                style = selected(native, tab_id).get(
                    'documentStyle', native.get('documentStyle', {}),
                )
                width = (
                    style['pageSize']['width']['magnitude']
                    - style['marginLeft']['magnitude']
                    - style['marginRight']['magnitude']
                )
                sizes = objects(selected(native, tab_id))
                assert [
                    s['width']['magnitude'] for s in sizes
                ] == pytest.approx(
                    [
                        width,
                        width - 72,
                        72,
                    ]
                )
                assert all(
                    s['height']['magnitude']
                    == pytest.approx(s['width']['magnitude'])
                    for s in sizes
                )
                await probe.call(
                    0,
                    'docs_append',
                    {
                        **args,
                        'text': 'image indent anchor',
                        'rich': False,
                    },
                )
                native = await probe.call(0, 'probe_tabs_document')
                anchor = next(
                    item
                    for item in selected(native, tab_id)['body']['content']
                    if 'image indent anchor' in paragraph_text(item)
                )
                await probe.batch(
                    [
                        {
                            'updateParagraphStyle': {
                                'range': {
                                    'startIndex': anchor['startIndex'],
                                    'endIndex': anchor['endIndex'],
                                    'tabId': tab_id,
                                },
                                'paragraphStyle': {
                                    'indentStart': {
                                        'magnitude': 54,
                                        'unit': 'PT',
                                    },
                                    'indentEnd': {
                                        'magnitude': 18,
                                        'unit': 'PT',
                                    },
                                },
                                'fields': 'indentStart,indentEnd',
                            }
                        }
                    ],
                    native,
                )
                result = await probe.call(
                    0,
                    'docs_insert_before',
                    {
                        **args,
                        'anchor': 'image indent anchor',
                        'text': f'![markdown]({image_path})',
                    },
                )
                assert not result['temporary_image_cleanup_pending']
                native = await probe.call(1, 'probe_tabs_document')
                sizes = objects(selected(native, tab_id))
                assert sizes[-1]['width']['magnitude'] == pytest.approx(
                    width - 72,
                )
                probe.report['native_image_sizes'] = sizes
            finally:
                if tab_id:
                    native = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': tab_id}}],
                        native,
                    )
                    after = await probe.call(0, 'probe_tabs_document')
                    assert_tabs_unchanged(before['tabs'], after['tabs'])
                    probe.report['temporary_tab_removed'] = True

    asyncio.run(run())
