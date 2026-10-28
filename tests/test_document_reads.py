"""Verify hierarchy and partial reads using synthetic and captured API data."""

# Fixture counts and offsets are intentional expectations in these tests.
# ruff: noqa: PLR2004

from copy import deepcopy

import pytest
from pydantic import TypeAdapter

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.models import (
    GoogleDocument,
    GoogleDocumentList,
    GoogleDocumentParagraphElement,
)


def test_absent_inline_objects_defaults_to_independent_empty_map(
    simple_document,
):
    """Documents without embedded objects accept the API's omitted field."""
    del simple_document['inlineObjects']
    first = GoogleDocument.model_validate(simple_document)
    second = GoogleDocument.model_validate(simple_document)

    assert first.inline_objects == {}
    assert second.inline_objects == {}
    assert first.inline_objects is not second.inline_objects


def test_absent_lists_defaults_to_independent_empty_map(simple_document):
    """Accept omitted list metadata when no paragraph references a list."""
    del simple_document['lists']

    first = GoogleDocument.model_validate(deepcopy(simple_document))
    second = GoogleDocument.model_validate(deepcopy(simple_document))

    assert first.lists == {}
    assert second.lists == {}
    assert first.lists is not second.lists
    first.lists['first-only'] = GoogleDocumentList(
        list_properties={'nestingLevels': []},
    )
    assert second.lists == {}


@pytest.mark.parametrize('operation', ['get_tree', 'read'])
def test_reads_work_when_api_omits_lists(
    simple_document, mock_docs, operation,
):
    """Read a document without lists when the API omits the empty map."""
    del simple_document['lists']

    result = getattr(docs_edit, operation)('example')

    assert result.document_id == 'example'
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('operation', ['get_tree', 'read'])
def test_reads_with_both_optional_collections_omitted(
    simple_document, mock_docs, operation,
):
    """Omitted empty maps preserve headings and content."""
    del simple_document['lists']
    del simple_document['inlineObjects']
    result = getattr(docs_edit, operation)('example')
    assert result.document_id == 'example'
    if operation == 'read':
        markdown = ''.join(section.markdown for section in result.sections)
        assert 'Introduction' in markdown
        assert 'Target phrase elsewhere' in markdown
    else:
        assert [section.id for section in result.sections] == [
            '', 'parent', 'nested', 'other',
        ]
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('omit_inline_objects', [False, True])
def test_targeted_edits_work_without_empty_lists(
    simple_document, mock_docs, omit_inline_objects,
):
    """Default collection metadata does not prevent heading-scoped edits."""
    del simple_document['lists']
    if omit_inline_objects:
        del simple_document['inlineObjects']
    result = docs_edit.search_replace(
        'example', 'Target phrase', 'Changed', heading_id='parent',
    )
    assert result.ok is True
    assert result.heading_id == 'parent'
    mock_docs.batchUpdate.assert_called_once()


@pytest.mark.parametrize(
    ('glyph', 'prefix'),
    [('DECIMAL', '1.'), ('GLYPH_TYPE_UNSPECIFIED', '-')],
)
def test_supplied_list_definitions_keep_rendering(
    simple_document, glyph, prefix,
):
    """Preserve supplied list IDs and numbering metadata."""
    simple_document['body']['content'][0]['paragraph']['bullet'] = {
        'listId': 'list-id', 'textStyle': {},
    }
    simple_document['lists'] = {'list-id': {'listProperties': {
        'nestingLevels': [{'glyphType': glyph}],
    }}}
    document = GoogleDocument.model_validate(simple_document)
    assert document.body.content[0].bullet.list_id == 'list-id'
    assert document.to_markdown().startswith(f'{prefix} Introduction\n')


@pytest.mark.parametrize('omit_lists', [False, True])
def test_missing_list_definition_is_not_invented(simple_document, omit_lists):
    """Retain the reference, but refuse to guess Markdown list formatting."""
    simple_document['body']['content'][0]['paragraph']['bullet'] = {
        'listId': 'missing-list', 'textStyle': {},
    }
    if omit_lists:
        del simple_document['lists']
    document = GoogleDocument.model_validate(simple_document)
    assert document.lists == {}
    assert document.body.content[0].bullet.list_id == 'missing-list'
    assert 'Introduction' in document.to_text()
    with pytest.raises(
        ValueError, match=r'missing list definition.*missing-list',
    ):
        document.to_markdown()
    assert document.lists == {}


def test_reads_work_when_api_omits_inline_objects(simple_document, mock_docs):
    """Outline and section reads survive the response seen in live testing."""
    del simple_document['inlineObjects']

    outline = docs_edit.get_tree('example')
    result = docs_edit.read('example', ['nested'])

    assert [section.id for section in outline.sections] == [
        '', 'parent', 'nested', 'other',
    ]
    assert result.selected_headings == ['nested']
    assert 'Target phrase again' in result.sections[0].markdown
    assert 'elsewhere' not in result.sections[0].markdown
    mock_docs.batchUpdate.assert_not_called()


def test_captured_outline_preserves_heading_identity(
    captured_document, mock_docs
):
    """The real response exposes all eight heading levels in document order."""
    mock_docs.get.return_value.execute.side_effect = None
    mock_docs.get.return_value.execute.return_value = captured_document

    outline = docs_edit.get_tree('example')

    assert outline.document_id == captured_document['documentId']
    assert outline.revision_id == captured_document['revisionId']
    assert outline.title == captured_document['title']
    assert [section.level for section in outline.sections] == [
        'Title',
        'Subtitle',
        'H1',
        'H2',
        'H3',
        'H4',
        'H5',
        'H6',
    ]
    assert [section.id for section in outline.sections] == [
        'h.1u5asdm7paas',
        'h.qql6xgrsy7kg',
        'h.wi1xejbgcq9a',
        'h.ucmukko8l9u',
        'h.gieyzo6dbxcm',
        'h.gtzf01obrmf4',
        'h.zdmakxby81jn',
        'h.sv2zrm3haied',
    ]
    assert outline.sections[-1].ancestor_ids == [
        s.id for s in outline.sections[:-1]
    ]
    mock_docs.get.assert_called_once_with(
        documentId='example', includeTabsContent=True,
        suggestionsViewMode='SUGGESTIONS_INLINE',
    )
    mock_docs.batchUpdate.assert_not_called()


def test_tree_keeps_preamble_and_sibling_boundaries(simple_document):
    """Heading nesting retains preamble text and stops at sibling sections."""
    tree = docs_edit._parse_document_tree(simple_document)

    assert [s.id for s in tree.sections] == ['', 'parent', 'other']
    assert [s.id for s in tree.headings['parent'].subtree()] == [
        'parent',
        'nested',
    ]
    assert tree.headings['nested'].ancestor_ids == ['parent']
    assert tree.headings['other'].ancestor_ids == []
    assert 'Introduction' in tree.sections[0].text
    assert 'elsewhere' not in tree.headings['parent'].subtree_text()


@pytest.mark.parametrize('split_runs', [False, True])
def test_editable_tree_preserves_api_paragraph_text(
    boundary_document, split_runs,
):
    """Searchable text retains exactly the source paragraph's terminator."""
    document = boundary_document(split_runs=split_runs)
    source_texts = [
        ''.join(element['textRun']['content']
                for element in source['paragraph']['elements'])
        for source in document['body']['content']
    ]
    tree = docs_edit._parse_document_tree(document)
    section = tree.headings['boundary']

    assert section.subtree_text() == 'Prefix !\nMiddle ?\nBoundarySentinel\n'
    for paragraph, text in zip(section.paragraphs, source_texts, strict=True):
        assert paragraph.text == text
        assert len(paragraph.text) == (
            paragraph.end_index - paragraph.start_index
        )


def test_captured_read_preserves_inline_and_paragraph_styles(
    captured_document,
    mock_docs,
):
    """Read captured formatting without a Google connection."""
    mock_docs.get.return_value.execute.side_effect = None
    mock_docs.get.return_value.execute.return_value = captured_document

    result = docs_edit.read('example', ['h.gieyzo6dbxcm'])

    text = result.sections[0].markdown
    for fragment in [
        '<b>bold</b>',
        '<i>italic</i>',
        '<u>underline</u>',
        '<s>strike-through</s>',
        '<sup>super-script</sup>',
        '<sub>sub-script</sub>',
        '<span style="font-variant: small-caps;">small-caps</span>',
        '<p style="text-align: right;">',
        '<p style="text-align: center;">',
        '<p style="text-align: justify;">',
        '  \nIt also includes multiple soft breaks',
    ]:
        assert fragment in text
    assert 'Text after title.' not in text
    mock_docs.batchUpdate.assert_not_called()


def test_partial_read_includes_descendants_and_heading_anchors(mock_docs):
    """A selected parent includes its nested heading and excludes siblings."""
    result = docs_edit.read('example', ['parent'])

    assert result.partial is True
    assert result.selected_headings == ['parent']
    assert len(result.sections) == 1
    text = result.sections[0].markdown
    assert '<a id=parent></a>Parent' in text
    assert '<a id=nested></a>Nested' in text
    assert 'Target phrase again' in text
    assert 'elsewhere' not in text
    assert 'Introduction' not in text
    mock_docs.batchUpdate.assert_not_called()


def test_full_read_includes_all_sections(mock_docs):
    """An unscoped read includes the preamble, nested content, and siblings."""
    result = docs_edit.read('example')

    assert result.partial is False
    assert result.selected_headings is None
    assert len(result.sections) == 3
    text = ''.join(section.markdown for section in result.sections)
    assert (
        text.index('Introduction') < text.index('Parent') < text.index('Other')
    )
    assert text.count('Target phrase') == 3
    mock_docs.batchUpdate.assert_not_called()


def test_multiple_selected_sections_keep_document_order(mock_docs):
    """Selected independent sections are returned in document order."""
    result = docs_edit.read('example', ['other', 'nested'])

    assert len(result.sections) == 2
    assert 'Target phrase again' in result.sections[0].markdown
    assert 'Target phrase elsewhere' in result.sections[1].markdown
    mock_docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize(
    ('kind', 'payload'),
    [
        ('horizontalRule', {'textStyle': {'bold': True}}),
        ('inlineObjectElement', {
            'inlineObjectId': 'fixture-image', 'textStyle': {'bold': True},
        }),
    ],
)
def test_non_text_paragraph_elements_keep_their_type(kind, payload):
    """Recognize supported non-text elements instead of an empty base model."""
    element = TypeAdapter(GoogleDocumentParagraphElement).validate_python({
        'startIndex': 1, 'endIndex': 2, kind: payload,
    })

    assert element.type == kind
    assert element.start_index == 1
    assert element.end_index == 2
    assert element.text_style.bold is True
    if kind == 'inlineObjectElement':
        assert element.inline_object_id == 'fixture-image'


def test_captured_inline_images_are_included_in_reads(
    captured_document, mock_docs,
):
    """Render captured image references using deterministic fixture URLs."""
    expected_images = []
    for index, obj in enumerate(captured_document['inlineObjects'].values()):
        embedded = obj['inlineObjectProperties']['embeddedObject']
        title = f'Fixture image {index}'
        uri = f'https://example.com/fixture-image-{index}.png'
        embedded['title'] = title
        embedded['imageProperties']['contentUri'] = uri
        expected_images.append(f'![{title}]({uri})')
    assert expected_images
    mock_docs.get.return_value.execute.side_effect = None
    mock_docs.get.return_value.execute.return_value = captured_document

    document = GoogleDocument.model_validate(deepcopy(captured_document))
    result = docs_edit.read('example')

    markdown = ''.join(section.markdown for section in result.sections)
    for image in expected_images:
        assert image in markdown
    for index in range(len(expected_images)):
        assert f'Fixture image {index}' in document.to_text()
    mock_docs.batchUpdate.assert_not_called()


def test_horizontal_rule_is_included_in_reads(simple_document, mock_docs):
    """Expose the document's horizontal rule in the Markdown read result."""
    simple_document['body']['content'] = [{
        'startIndex': 1, 'endIndex': 3,
        'paragraph': {
            'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
            'elements': [
                {'startIndex': 1, 'endIndex': 2,
                 'horizontalRule': {'textStyle': {}}},
                {'startIndex': 2, 'endIndex': 3,
                 'textRun': {'content': '\n', 'textStyle': {}}},
            ],
        },
    }]

    result = docs_edit.read('example')

    markdown = ''.join(section.markdown for section in result.sections)
    assert '\n---\n' in markdown
    assert '\n---\n' in GoogleDocument.model_validate(
        deepcopy(simple_document),
    ).to_text()
    mock_docs.batchUpdate.assert_not_called()


def test_text_runs_and_unknown_elements_keep_existing_behavior(
    simple_document,
):
    """Recognized runs render normally; unknown element kinds remain opaque."""
    adapter = TypeAdapter(GoogleDocumentParagraphElement)
    document = GoogleDocument.model_validate(deepcopy(simple_document))
    text = adapter.validate_python({
        'startIndex': 5, 'endIndex': 10,
        'textRun': {'content': 'Word\n', 'textStyle': {'italic': True}},
    })
    assert text.type == 'textRun'
    assert (text.start_index, text.end_index) == (5, 10)
    assert text.to_text(document) == 'Word'
    assert text.to_markdown(document) == '<i>Word</i>'

    unknown = adapter.validate_python({
        'startIndex': 10, 'endIndex': 11,
        'futureElement': {'someMetadata': 'opaque'},
    })
    assert unknown.type == 'base'
    assert (unknown.start_index, unknown.end_index) == (10, 11)
    assert unknown.to_text(document) == ''
    assert unknown.to_markdown(document) == ''


@pytest.mark.parametrize('title', ['Image title', None])
def test_inline_object_title_is_optional_in_plain_text(simple_document, title):
    """Resolve a typed image reference without inventing a missing title."""
    simple_document['inlineObjects'] = {'image-id': {
        'objectId': 'image-id',
        'inlineObjectProperties': {'embeddedObject': {
            'title': title,
            'imageProperties': {'contentUri': 'https://example.com/image.png'},
        }},
    }}
    document = GoogleDocument.model_validate(simple_document)
    element = TypeAdapter(GoogleDocumentParagraphElement).validate_python({
        'startIndex': 1, 'endIndex': 2,
        'inlineObjectElement': {'inlineObjectId': 'image-id', 'textStyle': {}},
    })
    assert element.to_text(document) == (title or '')
    assert element.to_markdown(document) == (
        f'![{title or ""}](https://example.com/image.png)'
    )


def test_partial_read_contract_rejects_all_unknown_headings(mock_docs):
    """An entirely unresolved selection must not look like an empty section."""
    result = docs_edit.read('example', ['missing-heading'])

    assert getattr(result, 'ok', True) is False
    assert result.code == 'HEADING_NOT_FOUND'
    mock_docs.batchUpdate.assert_not_called()


def test_partial_read_contract_reports_found_and_unknown_headings(mock_docs):
    """Separate unresolved IDs from the sections actually returned."""
    result = docs_edit.read('example', ['missing-heading', 'nested'])

    assert result.selected_headings == ['nested']
    assert result.unknown_heading_ids == ['missing-heading']
    mock_docs.batchUpdate.assert_not_called()


def test_partial_read_contract_deduplicates_overlapping_subtrees(mock_docs):
    """Return nested content once when both ancestor and child are selected."""
    result = docs_edit.read('example', ['parent', 'nested'])

    markdown = ''.join(section.markdown for section in result.sections)
    assert markdown.count('Target phrase again') == 1
    assert result.selected_headings == ['parent']
    mock_docs.batchUpdate.assert_not_called()


def test_partial_read_contract_identifies_each_returned_section(mock_docs):
    """Associate each Markdown chunk with its resolved heading ID."""
    result = docs_edit.read('example', ['nested', 'other'])

    assert [section.heading_id for section in result.sections] == [
        'nested', 'other',
    ]
    assert 'Target phrase again' in result.sections[0].markdown
    assert 'Target phrase elsewhere' in result.sections[1].markdown
    mock_docs.batchUpdate.assert_not_called()
