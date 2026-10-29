"""Verify literal text survives native reads and rich-content compilation."""

from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from gdocs_scope_mcp.documents import editing, parsing, reading
from gdocs_scope_mcp.documents.native_models import GoogleDocument
from gdocs_scope_mcp.rich_text.compiler import markdown_to_requests
from gdocs_scope_mcp.rich_text.models import InsertionTable
from gdocs_scope_mcp.rich_text.parsing import html_to_gpars


def native_document(runs, *, paragraph_style=None):
    """Build independently indexed native runs, retaining source text."""
    elements = []
    index = 1
    for text, style in [*runs, ('\n', {})]:
        end = index + len(text.encode('utf-16-le')) // 2
        elements.append({'startIndex': index, 'endIndex': end,
                         'textRun': {'content': text, 'textStyle': style}})
        index = end
    return {
        'documentId': 'example', 'title': 'Literal text',
        'revisionId': 'revision',
        'body': {'content': [{
            'startIndex': 1, 'endIndex': index,
            'paragraph': {'elements': elements, 'paragraphStyle': {
                'namedStyleType': 'NORMAL_TEXT', **(paragraph_style or {}),
            }},
        }]},
    }


def compiled_text(markdown):
    """Observe inserted characters independently of reader markup."""
    requests = markdown_to_requests(markdown, newline_before=False)
    text = ''.join(r['insertText']['text'] for r in requests
                   if 'insertText' in r)
    return text, requests


@pytest.mark.parametrize('text', [
    'Use <b>literal</b> &amp; **stars** 😀',
    r'\*literal\* _word_ ~~strike~~ ^up^ ~down~ `code`',
    '[label](https://example.com) ![image](https://example.com/a.png)',
    '# Heading', '1. Ordinary text', '2) Another item',
    '- Ordinary text', '+ Ordinary text', '---', '===', '> Quote',
    'https://example.com and www.example.com',
    '  indented text', '\tindented text',
    'before\u000b# after\u000b1. still literal',
])
@pytest.mark.parametrize('split', [False, True])
def test_literal_text_round_trip(text, split):
    """Do not interpret plain text as markup, including split native runs."""
    runs = [(char, {}) for char in text] if split else [(text, {})]
    source = native_document(runs)
    markdown = GoogleDocument.model_validate(deepcopy(source)).to_markdown()
    inserted, requests = compiled_text(markdown)
    assert inserted == text + '\n'
    assert not any('createParagraphBullets' in r or 'insertInlineImage' in r
                   or 'updateTextStyle' in r for r in requests)
    assert [r['updateParagraphStyle']['paragraphStyle'] for r in requests
            if 'updateParagraphStyle' in r] == [
        {'namedStyleType': 'NORMAL_TEXT'},
    ]


@pytest.mark.parametrize('paragraph_style', [
    {}, {'alignment': 'CENTER'},
    {'namedStyleType': 'HEADING_2', 'headingId': 'literal-heading'},
])
def test_formatted_literal_runs_preserve_styles(paragraph_style):
    """Literal punctuation and generated formatting remain distinguishable."""
    url = 'https://example.com/?a="quoted"&b={value}&c=%2F'
    runs = [('Before ', {}), ('**bold🦷**', {'bold': True}),
            (' <i>literal</i> ', {}),
            ('[linked]', {'italic': True, 'link': {'url': url}}),
            (' after', {})]
    document = native_document(runs, paragraph_style=paragraph_style)
    markdown = GoogleDocument.model_validate(document).to_markdown()
    inserted, requests = compiled_text(markdown)
    assert inserted == ''.join(text for text, _ in runs) + '\n'
    buffer = inserted.encode('utf-16-le')
    styled = []
    for request in requests:
        if 'updateTextStyle' in request:
            update = request['updateTextStyle']
            span = update['range']
            text = buffer[span['startIndex'] * 2:span['endIndex'] * 2]
            styled.append((text.decode('utf-16-le'), update['textStyle']))
    assert styled == [('**bold🦷**', {'bold': True}),
                      ('[linked]', {'italic': True, 'link': {'url': url}})]


def test_escaping_does_not_change_source_maps(mock_docs, simple_document):
    """Reads expose escaped display text while edits retain original UTF-16."""
    text = '**🦷** &amp; <b>literal</b>'
    simple_document.update(native_document([(text, {})]))
    source = deepcopy(simple_document)
    read = reading.read('example')
    inserted, _ = compiled_text(read.sections[0].markdown)
    assert inserted == text + '\n'
    tree = parsing.parse_document_tree(source)
    paragraph = tree.sections[0].paragraphs[-1]
    assert paragraph.text == text + '\n'
    assert paragraph.text_map == [(0, 1, text), (len(text),
        1 + len(text.encode('utf-16-le')) // 2, '\n')]
    mock_docs.batchUpdate.assert_not_called()
    result = editing.search_replace('example', '&amp;', 'kept')
    assert result.ok
    requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
    span = next(r['deleteContentRange']['range'] for r in requests
                if 'deleteContentRange' in r)
    start = 1 + len('**🦷** '.encode('utf-16-le')) // 2
    assert requests[0]['insertText']['location']['index'] == start
    # Replacement text is inserted first, shifting the old source range.
    assert span == {'startIndex': start + len('kept'),
                    'endIndex': start + len('kept') + len('&amp;')}


def test_literal_text_inside_native_table(table_document):
    """Raw HTML table blocks must decode literals without Markdown escapes."""
    text = '<b>literal</b> &amp; **plain** [x] 🦷'
    cell = table_document['body']['content'][2]['table']['tableRows'][0][
        'tableCells'][0]
    cell['content'] = native_document([(text, {'bold': True})])['body'][
        'content']
    model = GoogleDocument.model_validate(deepcopy(table_document))
    table = model.body.content[2]
    parsed = html_to_gpars(table.to_markdown(model))
    table = next(item for item in parsed if isinstance(item, InsertionTable))
    assert table.cells[0][0].text == text
    updates = [r['updateTextStyle']['textStyle']
               for r in table.cells[0][0].requests
               if 'updateTextStyle' in r]
    assert updates == [{'bold': True}]


def test_image_metadata_cannot_inject_markup():
    """Keep image labels and URLs inside their own escaped attributes."""
    document = native_document([('Before ', {})])
    elements = document['body']['content'][0]['paragraph']['elements']
    elements.insert(1, {'inlineObjectElement': {'inlineObjectId': 'image',
                                              'textStyle': {}}})
    title = '"] **fake** <b>title</b> &amp;'
    uri = 'https://example.com/a_(b).png?a="v"&b={text}'
    document['inlineObjects'] = {'image': {'objectId': 'image',
        'inlineObjectProperties': {'embeddedObject': {
            'title': title, 'imageProperties': {'contentUri': uri},
        }}}}
    markdown = GoogleDocument.model_validate(document).to_markdown()
    images = BeautifulSoup(markdown, 'html.parser').find_all('img')
    assert len(images) == 1
    assert images[0]['alt'] == title
    assert images[0]['src'] == uri
    _, requests = compiled_text(markdown)
    assert [r['insertInlineImage']['uri'] for r in requests
            if 'insertInlineImage' in r] == [uri]
    assert not any('updateTextStyle' in r for r in requests)


def test_heading_anchor_cannot_inject_markup():
    """Quote native heading metadata independently of literal heading text."""
    heading_id = 'id"><b>fake</b><a id="other'
    source = native_document([('Real **heading**', {})], paragraph_style={
        'namedStyleType': 'HEADING_1', 'headingId': heading_id,
    })
    markdown = GoogleDocument.model_validate(source).to_markdown()
    anchor = BeautifulSoup(markdown, 'html.parser').find('a')
    assert anchor['id'] == heading_id
    inserted, _ = compiled_text(markdown)
    assert inserted == 'Real **heading**\n'
