"""Check read-to-write formatting for the supported HTML subset."""

import pytest

from gdocs_scope_mcp.documents import (
    editing as docs_edit,
    reading,
)
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests


@pytest.fixture
def formatted_document(simple_document):
    """Build native styles with independently calculated UTF-16 ranges."""
    content = []
    index = 1
    for runs, style in [
        ([('Copy heading', {})], {
            'namedStyleType': 'HEADING_1', 'headingId': 'original-id',
        }),
        ([('Before 😀 ', {}), ('Bold🦷', {'bold': True}), (' ', {}),
          ('Italic', {'italic': True}), (' ', {}),
          ('Under', {'underline': True}), (' tail', {})], {
            'namedStyleType': 'NORMAL_TEXT', 'alignment': 'CENTER',
        }),
    ]:
        start = index
        elements = []
        for text, text_style in [*runs, ('\n', {})]:
            end = index + len(text.encode('utf-16-le')) // 2
            elements.append({
                'startIndex': index, 'endIndex': end,
                'textRun': {'content': text, 'textStyle': text_style},
            })
            index = end
        content.append({
            'startIndex': start, 'endIndex': index,
            'paragraph': {'paragraphStyle': style, 'elements': elements},
        })
    simple_document['body']['content'] = content
    return simple_document


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('rich', [False, True])
def test_read_output_can_be_inserted_with_supported_styles(
    mock_docs, formatted_document, operation, rich,
):
    """Reuse reader HTML while keeping styles and heading IDs scoped."""
    read = reading.read('example', ['original-id'])
    markdown = read.sections[0].markdown
    assert '<a id=original-id></a>' in markdown
    assert '<b>Bold🦷</b>' in markdown
    assert '<p style="text-align: center;">' in markdown
    if operation == 'append':
        result = docs_edit.append('example', markdown, rich=rich)
    else:
        result = getattr(docs_edit, operation)(
            'example', 'Before 😀', markdown, rich=rich,
        )
    assert result.ok is True
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    source = '\0' + ''.join(
        element['textRun']['content']
        for item in formatted_document['body']['content']
        for element in item['paragraph']['elements']
    )
    buffer = source.encode('utf-16-le')
    styled = []
    paragraph_styles = []
    inserted = ''
    for request in requests:
        if 'insertText' in request:
            insert = request['insertText']
            offset = insert['location']['index'] * 2
            buffer = (buffer[:offset] + insert['text'].encode('utf-16-le')
                      + buffer[offset:])
            inserted += insert['text']
        elif 'updateTextStyle' in request:
            update = request['updateTextStyle']
            span = update['range']
            text = buffer[span['startIndex'] * 2:span['endIndex'] * 2]
            styled.append((text.decode('utf-16-le'), update['textStyle']))
        elif 'updateParagraphStyle' in request:
            paragraph_styles.append(request['updateParagraphStyle'])
    if rich:
        assert inserted == (
            '\nCopy heading\nBefore 😀 Bold🦷 Italic Under tail'
            if operation != 'insert_before'
            else 'Copy heading\nBefore 😀 Bold🦷 Italic Under tail\n'
        )
        assert styled == [
            ('Bold🦷', {'bold': True}), ('Italic', {'italic': True}),
            ('Under', {'underline': True}),
        ]
        assert [item['paragraphStyle'] for item in paragraph_styles] == [
            {'namedStyleType': 'HEADING_1'},
            {'namedStyleType': 'NORMAL_TEXT', 'alignment': 'CENTER'},
        ]
        assert 'original-id' not in str(requests)
    else:
        assert inserted == (
            markdown + '\n' if operation == 'insert_before'
            else '\n' + markdown
        )
        assert styled == paragraph_styles == []
        assert len(requests) == 1


@pytest.mark.parametrize('alignment', ['center', 'right', 'justify'])
@pytest.mark.parametrize('newline_before', [False, True])
def test_aligned_html_keeps_nested_styles_local(alignment, newline_before):
    """Nested styles do not leak to neighbouring text or paragraphs."""
    requests = markdown_to_requests(
        f'<p style="text-align: {alignment};">'
        '<b>A<i>B</i>C</b> plain</p>\n\nAfter',
        newline_before=newline_before,
    )
    styles = [r['updateTextStyle']['textStyle'] for r in requests
              if 'updateTextStyle' in r]
    assert styles == [
        {'bold': True}, {'bold': True, 'italic': True}, {'bold': True},
    ]
    paragraphs = [r['updateParagraphStyle']['paragraphStyle']
                  for r in requests if 'updateParagraphStyle' in r]
    assert paragraphs[0]['alignment'] == {
        'center': 'CENTER', 'right': 'END', 'justify': 'JUSTIFIED',
    }[alignment]
    assert paragraphs[-1] == {'namedStyleType': 'NORMAL_TEXT'}


@pytest.mark.parametrize('markup', [
    '<span style="color: red;">word</span>',
    '<unsupported attribute="ignored">word</unsupported>',
])
def test_unsupported_html_wrappers_keep_text_only(markup):
    """Unsupported wrappers retain their child text without applying styles."""
    requests = markdown_to_requests(markup)
    assert requests[0]['insertText']['text'] == '\nword'
    assert not any('updateTextStyle' in request for request in requests)
