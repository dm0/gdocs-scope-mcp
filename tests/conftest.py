"""Provide captured API data and an isolated Docs service for offline tests."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gdocs_scope_mcp import docs_edit


@pytest.fixture
def captured_document():
    """Load the Google API response supplied in the workspace data folder."""
    path = Path(__file__).parent / 'fixtures' / 'google_document.json'
    return json.loads(path.read_text())


@pytest.fixture
def simple_document():
    """Build a text-only document with nested headings and repeated anchors."""
    content = []
    index = 1
    for text, heading, style in [
        ('Introduction\n', None, 'NORMAL_TEXT'),
        ('Parent\n', 'parent', 'HEADING_1'),
        ('Target phrase\n', None, 'NORMAL_TEXT'),
        ('Nested\n', 'nested', 'HEADING_2'),
        ('Target phrase again\n', None, 'NORMAL_TEXT'),
        ('Other\n', 'other', 'HEADING_1'),
        ('Target phrase elsewhere\n', None, 'NORMAL_TEXT'),
    ]:
        paragraph_style = {'namedStyleType': style}
        if heading:
            paragraph_style['headingId'] = heading
        content.append(
            {
                'startIndex': index,
                'endIndex': index + len(text),
                'paragraph': {
                    'paragraphStyle': paragraph_style,
                    'elements': [
                        {
                            'startIndex': index,
                            'endIndex': index + len(text),
                            'textRun': {'content': text, 'textStyle': {}},
                        }
                    ],
                },
            }
        )
        index += len(text)
    return {
        'documentId': 'example',
        'revisionId': 'revision',
        'title': 'Example',
        'body': {'content': content},
        'lists': {},
        'inlineObjects': {},
    }


@pytest.fixture
def mock_docs(monkeypatch, simple_document):
    """Mock the API boundary while exercising real parsing and edit logic."""
    service = MagicMock()
    documents = service.documents.return_value
    documents.get.return_value.execute.side_effect = lambda: deepcopy(
        simple_document
    )
    documents.batchUpdate.return_value.execute.return_value = {}
    monkeypatch.setattr(docs_edit, '_get_service', lambda *_args: service)
    return documents


@pytest.fixture
def boundary_document(simple_document):
    """Build adjacent API paragraphs with independently indexed text runs."""
    def build(*, split_runs=False):
        content = []
        index = 1
        for number, text in enumerate([
            'Prefix !\n', 'Middle ?\n', 'BoundarySentinel\n',
        ]):
            start = index
            runs = (
                [text[:-2], text[-2:-1], text[-1:]] if split_runs else [text]
            )
            elements = []
            for run in runs:
                elements.append({
                    'startIndex': index, 'endIndex': index + len(run),
                    'textRun': {'content': run, 'textStyle': {}},
                })
                index += len(run)
            style = {'namedStyleType': 'NORMAL_TEXT'}
            if number == 0:
                style = {
                    'namedStyleType': 'HEADING_1', 'headingId': 'boundary',
                }
            content.append({
                'startIndex': start, 'endIndex': index,
                'paragraph': {'paragraphStyle': style, 'elements': elements},
            })
        simple_document['body']['content'] = content
        return simple_document

    return build


@pytest.fixture
def apply_insertions():
    """Provide an ASCII text buffer that checks insert and style ranges."""

    def apply(document, requests):
        text = '\n' + ''.join(
            item['paragraph']['elements'][0]['textRun']['content']
            for item in document['body']['content']
        )
        styled = []
        for request in requests:
            if 'insertText' in request:
                insertion = request['insertText']
                index = insertion['location']['index']
                assert 1 <= index < len(text)
                text = text[:index] + insertion['text'] + text[index:]
            else:
                update = next(iter(request.values()))
                span = update['range']
                assert 1 <= span['startIndex'] <= span['endIndex'] < len(text)
                styled.append(
                    (
                        text[span['startIndex'] : span['endIndex']],
                        update,
                    )
                )
        return text, styled

    return apply


@pytest.fixture
def table_document(simple_document):
    """Provide table cells, paragraph scopes, and structural source gaps."""
    index = 1

    def paragraph(text, heading=None):
        nonlocal index
        start = index
        index += len(text.encode('utf-16-le')) // 2
        style = {'namedStyleType': 'NORMAL_TEXT'}
        if heading:
            style = {'namedStyleType': 'HEADING_1', 'headingId': heading}
        return {
            'startIndex': start, 'endIndex': index,
            'paragraph': {
                'paragraphStyle': style,
                'elements': [{
                    'startIndex': start, 'endIndex': index,
                    'textRun': {'content': text, 'textStyle': {}},
                }],
            },
        }

    content = [paragraph('Owner\n', 'owner'), paragraph('Before table\n')]
    table_start = index
    index += 1
    rows = []
    for row_texts in [
        [['First😀\n', 'Cell tail !\n'], ['Second\n']],
        [['Third\n'], ['Fourth\n']],
    ]:
        row_start = index
        index += 1
        cells = []
        for texts in row_texts:
            cell_start = index
            index += 1
            cell_content = [paragraph(text) for text in texts]
            cells.append({
                'startIndex': cell_start, 'endIndex': index,
                'content': cell_content,
                'tableCellStyle': {'rowSpan': 1, 'columnSpan': 1},
            })
        rows.append({
            'startIndex': row_start, 'endIndex': index, 'tableCells': cells,
        })
    index += 1
    content.append({
        'startIndex': table_start, 'endIndex': index,
        'table': {'rows': 2, 'columns': 2, 'tableRows': rows},
    })
    content.extend([
        paragraph('After table\n'), paragraph('Other\n', 'other'),
        paragraph('Second elsewhere\n'),
    ])
    simple_document['body']['content'] = content
    return simple_document
