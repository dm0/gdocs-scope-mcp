"""Verify hierarchy and partial reads using synthetic and captured API data."""

# Fixture counts and offsets are intentional expectations in these tests.
# ruff: noqa: PLR2004

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.models import GoogleDocument


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


def test_reads_work_when_api_omits_inline_objects(simple_document, mock_docs):
    """Outline and section reads survive the response seen in live testing."""
    del simple_document['inlineObjects']

    outline = docs_edit.get_tree('example')
    result = docs_edit.read('example', ['nested'])

    assert [section.id for section in outline.sections] == [
        '', 'parent', 'nested', 'other',
    ]
    assert result.selected_headings == ['nested']
    assert 'Target phrase again' in result.subset_md[0]
    assert 'elsewhere' not in result.subset_md[0]
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
        documentId='example',
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


def test_captured_read_preserves_inline_and_paragraph_styles(
    captured_document,
    mock_docs,
):
    """Read captured formatting without a Google connection."""
    mock_docs.get.return_value.execute.side_effect = None
    mock_docs.get.return_value.execute.return_value = captured_document

    result = docs_edit.read('example', ['h.gieyzo6dbxcm'])

    text = result.subset_md[0]
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
    assert len(result.subset_md) == 1
    text = result.subset_md[0]
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
    assert len(result.subset_md) == 3
    text = ''.join(result.subset_md)
    assert (
        text.index('Introduction') < text.index('Parent') < text.index('Other')
    )
    assert text.count('Target phrase') == 3
    mock_docs.batchUpdate.assert_not_called()


def test_multiple_selected_sections_keep_document_order(mock_docs):
    """Selected independent sections are returned in document order."""
    result = docs_edit.read('example', ['other', 'nested'])

    assert len(result.subset_md) == 2
    assert 'Target phrase again' in result.subset_md[0]
    assert 'Target phrase elsewhere' in result.subset_md[1]
    mock_docs.batchUpdate.assert_not_called()
