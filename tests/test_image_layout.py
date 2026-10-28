"""Verify native paragraph widths and image sizing in actual edit plans."""

# Imported fixtures keep names; explicit dimensions are contract examples.
# ruff: noqa: D103, PLR2004, F811

from copy import deepcopy

import pytest

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.image_layout import fit_images, paragraph_width
from gdocs_scope_mcp.md2requests import gpars_to_requests, html_to_gpars

from .test_revision_guards import race_docs  # noqa: F401
from .test_table_insertion import NativeBuffer

URI = 'https://example.com/image.png'


def pt(value):
    return {'magnitude': value, 'unit': 'PT'}


@pytest.fixture
def paged(simple_document):
    simple_document['documentStyle'] = {
        'pageSize': {'width': pt(612), 'height': pt(792)},
        'marginLeft': pt(72),
        'marginRight': pt(72),
        'documentFormat': {'documentMode': 'PAGES'},
    }
    return simple_document


def image_paragraph(markup=None):
    paragraphs = html_to_gpars(markup or f'<p><img src="{URI}"></p>', 1)
    return next(p for p in paragraphs if len(p))


def test_body_width_and_first_line_indentation(paged):
    paragraph = image_paragraph()
    assert paragraph_width(paged, 1, paragraph) == 468
    source = paged['body']['content'][0]['paragraph']['paragraphStyle']
    source.update(
        {'indentStart': pt(36), 'indentEnd': pt(18), 'indentFirstLine': pt(54)}
    )
    assert paragraph_width(paged, 1, paragraph) == 396


def test_section_margins_and_orientation(paged):
    style = {
        'marginLeft': pt(36),
        'marginRight': pt(18),
        'flipPageOrientation': True,
    }
    paged['body']['content'].insert(
        0,
        {
            'endIndex': 1,
            'sectionBreak': {'sectionStyle': style},
        },
    )
    assert paragraph_width(paged, 1, image_paragraph()) == 738
    paged['documentStyle']['pageSize'] = {'width': pt(792), 'height': pt(612)}
    assert paragraph_width(paged, 1, image_paragraph()) == 558


def test_named_style_inheritance_and_planned_override(paged):
    paged['namedStyles'] = {
        'styles': [
            {
                'namedStyleType': 'NORMAL_TEXT',
                'paragraphStyle': {'indentStart': pt(12), 'indentEnd': pt(6)},
            },
            {
                'namedStyleType': 'HEADING_1',
                'paragraphStyle': {'indentStart': pt(48)},
            },
        ]
    }
    assert paragraph_width(paged, 1, image_paragraph()) == 450
    heading = image_paragraph(f'<h3><img src="{URI}"></h3>')
    assert paragraph_width(paged, 1, heading) == 414
    paged['body']['content'][0]['paragraph']['paragraphStyle'][
        'indentStart'
    ] = pt(24)
    assert paragraph_width(paged, 1, heading) == 438


def test_existing_list_uses_native_level_indents(paged):
    paged['lists'] = {
        'list': {
            'listProperties': {
                'nestingLevels': [
                    {'indentStart': pt(30), 'indentFirstLine': pt(15)},
                    {'indentStart': pt(90), 'indentFirstLine': pt(70)},
                ]
            }
        }
    }
    paged['body']['content'][0]['paragraph']['bullet'] = {
        'listId': 'list',
        'nestingLevel': 1,
    }
    assert paragraph_width(paged, 1, image_paragraph()) == 378


def test_new_list_depth_and_continuation(paged):
    markup = (
        f'<ul><li><p><img src="{URI}"></p><p>Continuation '
        f'<img src="{URI}"></p><ul><li><img src="{URI}">'
        '</li></ul></li></ul>'
    )
    paragraphs = [p for p in html_to_gpars(markup, 1) if len(p)]
    assert [paragraph_width(paged, 1, p) for p in paragraphs] == [
        432,
        432,
        396,
    ]


@pytest.mark.parametrize(
    'unsupported',
    ['pageless', 'columns', 'cell', 'missing', 'invalid', 'nonpositive'],
)
def test_unsupported_layout_falls_back(paged, unsupported):
    if unsupported == 'pageless':
        paged['documentStyle']['documentFormat']['documentMode'] = 'PAGELESS'
    elif unsupported == 'columns':
        paged['body']['content'].insert(
            0,
            {
                'sectionBreak': {
                    'sectionStyle': {
                        'columnProperties': [{}, {}],
                    }
                }
            },
        )
    elif unsupported == 'cell':
        paged['body']['content'] = [
            {'startIndex': 1, 'endIndex': 20, 'table': {}}
        ]
    elif unsupported == 'missing':
        del paged['documentStyle']['pageSize']
    elif unsupported == 'invalid':
        paged['documentStyle']['marginLeft'] = {'magnitude': 72, 'unit': 'PX'}
    else:
        paged['documentStyle']['marginLeft'] = pt(1000)
    assert paragraph_width(paged, 1, image_paragraph()) is None


def test_explicit_dimensions_always_win(paged):
    paragraphs = html_to_gpars(
        f'<p><img src="{URI}" width="96"><img src="{URI}" height="48">'
        f'<img src="{URI}"></p>',
        1,
    )
    requests = gpars_to_requests(paragraphs)
    fit_images(requests, paragraphs, paged, 1)
    sizes = [
        r['insertInlineImage']['objectSize']
        for r in requests
        if 'insertInlineImage' in r
    ]
    assert sizes == [{'width': pt(72)}, {'height': pt(36)}, {'width': pt(468)}]


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after']
)
@pytest.mark.usefixtures('paged')
def test_edit_tools_apply_auto_size(mock_docs, operation):
    arguments = {'doc_id': 'example', 'text': f'![]({URI})'}
    if operation != 'append':
        arguments['anchor'] = 'Introduction'
    result = getattr(docs_edit, operation)(**arguments)
    assert result.ok
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    image = next(
        r['insertInlineImage'] for r in requests if 'insertInlineImage' in r
    )
    assert image['objectSize'] == {'width': pt(468)}


def test_retry_recalculates_width_from_new_snapshot(race_docs, paged):
    race_docs['document']['documentStyle'] = deepcopy(paged['documentStyle'])

    def change(document):
        document['documentStyle']['marginLeft'] = pt(108)

    race_docs['change'] = change
    assert docs_edit.append('example', f'![]({URI})').ok
    widths = [
        next(
            r['insertInlineImage']['objectSize']['width']['magnitude']
            for r in body['requests']
            if 'insertInlineImage' in r
        )
        for body in race_docs['writes']
    ]
    assert widths == [468, 432]


def test_body_images_around_table_and_cell_fallback(paged):
    native = NativeBuffer()
    markup = (f'<p>before <img src="{URI}"></p>'
              f'<table><tr><td><img src="{URI}"></td></tr></table>'
              f'<p>after <img src="{URI}"></p>')
    paragraphs = html_to_gpars(markup, native.start)
    plan = gpars_to_requests(paragraphs)
    plan.execute(native.service, 'test', size_images=lambda requests, group:
                 fit_images(requests, group, paged, 1))
    sizes = [r['insertInlineImage'].get('objectSize')
             for batch in native.batches for r in batch
             if 'insertInlineImage' in r]
    assert sizes == [{'width': pt(468)}, None, {'width': pt(468)}]
