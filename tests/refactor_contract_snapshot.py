"""Capture representative conversion, rendering and edit behavior."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def capture_behavior(native_model, compiler, editing, client_module,  # noqa: PLR0917
                     service_attribute, failure_type):
    """Capture values with the same API fixture on both revisions."""
    document = {
        'documentId': 'contract-document', 'title': 'Contract document',
        'revisionId': 'revision-1', 'lists': {}, 'inlineObjects': {},
        'body': {'content': [{
            'startIndex': 1, 'endIndex': 12,
            'paragraph': {
                'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
                'elements': [
                    {'startIndex': 1, 'endIndex': 7,
                     'textRun': {'content': 'Hello ', 'textStyle': {}}},
                    {'startIndex': 7, 'endIndex': 12,
                     'textRun': {'content': '😀 X\n',
                                 'textStyle': {'bold': True}}},
                ],
            },
        }]},
    }
    rendered = native_model.model_validate(deepcopy(document)).to_markdown()
    cases = {
        'paragraphs': '### Heading\n\n**Bold😀** and [link](https://example.com)',
        'lists': '- First\n- Second',
        'code': '```python\nprint("😀")\n\n```',
        'image': 'Before ![image](https://example.com/image.png) after',
        'table': '| **A** | B |\n| --- | --- |\n| 😀 | C |',
    }
    requests = {}
    for name, markup in cases.items():
        with patch('gdocs_scope_mcp.code_reading.uuid4',
                   return_value=SimpleNamespace(hex='0' * 32)):
            plan = compiler.markdown_to_requests(markup, start=5)
        requests[name] = {
            'requests': plan if isinstance(plan, list)
            else list(plan.iter_requests()),
            'text': compiler.inserted_text_from_requests(plan),
        }
    service = MagicMock()
    docs = service.documents.return_value
    docs.get.return_value.execute.side_effect = lambda: deepcopy(document)
    docs.batchUpdate.return_value.execute.return_value = {
        'writeControl': {'requiredRevisionId': 'revision-2'},
    }
    receipts = []
    with patch.object(client_module, service_attribute, return_value=service):
        receipts.append(editing.append(
            'contract-document', '**New😀**', rich=True,
        ).model_dump(mode='json', by_alias=True))
        receipts.append(editing.search_replace(
            'contract-document', '😀 X', 'Changed',
        ).model_dump(mode='json', by_alias=True))
        receipts.append(editing.search_replace(
            'contract-document', 'absent', 'Changed',
        ).model_dump(mode='json', by_alias=True))
    try:
        compiler.markdown_to_requests('<table><tr><td colspan="2">X</td>'
                                      '</tr></table>')
    except failure_type as error:
        failure = error.failure.model_dump(mode='json', by_alias=True)
    else:
        raise AssertionError('Unsupported table must fail before writes')
    return {
        'rendered': rendered, 'conversions': requests, 'receipts': receipts,
        'batches': [call.kwargs for call in docs.batchUpdate.call_args_list],
        'failure': failure,
    }
