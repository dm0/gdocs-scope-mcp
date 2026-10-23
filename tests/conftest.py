"""Provide captured API data and an isolated Docs service for offline tests."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from google_docs_mcp import docs_edit


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
