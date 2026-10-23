"""Exercise the editing CLI without credentials or Google API requests."""

import json
from inspect import signature
from unittest.mock import MagicMock

import pytest

from gdocs_scope_mcp import docs_edit


@pytest.mark.xfail(
    strict=True,
    reason='CLI passes the regex flag into the positional heading_id slot.',
)
@pytest.mark.parametrize('regex', [False, True])
def test_cli_search_replace_forwards_regex_without_heading(
    monkeypatch, capsys, regex,
):
    """Bind CLI arguments to the backend signature and verify their use."""
    backend_signature = signature(docs_edit.search_replace)
    backend = MagicMock(return_value={'ok': True})
    monkeypatch.setattr(docs_edit, 'search_replace', backend)
    arguments = [
        'docs_edit', 'search_replace', 'example',
        '--find', 'Target phrase', '--replace', 'Changed',
    ]
    if regex:
        arguments.append('--regex')
    monkeypatch.setattr('sys.argv', arguments)

    docs_edit.main()

    backend.assert_called_once()
    bound = backend_signature.bind(
        *backend.call_args.args, **backend.call_args.kwargs,
    )
    bound.apply_defaults()
    assert bound.arguments['heading_id'] is None
    assert bound.arguments['regex'] is regex
    assert json.loads(capsys.readouterr().out)['ok'] is True


@pytest.mark.xfail(
    strict=True,
    reason='CLI sends Pydantic result models directly to json.dumps.',
)
@pytest.mark.parametrize(
    'arguments',
    [
        ['get', 'example'],
        ['insert_before', 'example', '--anchor', 'Introduction',
         '--text', 'New', '--plain'],
        ['insert_after', 'example', '--anchor', 'Introduction',
         '--text', 'New', '--plain'],
    ],
    ids=['get', 'insert-before', 'insert-after'],
)
def test_cli_serializes_typed_results(
    mock_docs, monkeypatch, capsys, arguments,
):
    """Serialize successful read and write receipts as JSON."""
    monkeypatch.setattr('sys.argv', ['docs_edit', *arguments])

    exit_code = 0
    try:
        docs_edit.main()
    except SystemExit as error:
        exit_code = error.code
    output = capsys.readouterr()

    if arguments[0] == 'get':
        mock_docs.batchUpdate.assert_not_called()
    else:
        mock_docs.batchUpdate.return_value.execute.assert_called_once()
    assert exit_code == 0, output.err
    result = json.loads(output.out)
    if arguments[0] == 'get':
        assert result['document_id'] == 'example'
        assert result['partial'] is False
        mock_docs.batchUpdate.assert_not_called()
    else:
        assert result['ok'] is True
        mock_docs.batchUpdate.assert_called_once()
