"""Provide captured API data and an isolated Docs service for offline tests."""

import asyncio
import json
import os
import re
import struct
import sys
import tempfile
import zlib
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from gdocs_scope_mcp.diagnostics import capture_server_info
from gdocs_scope_mcp.google_api import clients, credentials

from .live_document_state import document_session, reset_document


@pytest.fixture(scope='session')
def isolated_mcp():
    """Provide a shared-session STDIO client tied to this checkout's source."""
    @asynccontextmanager
    async def connect(log, *, probe=False, environment=None):
        repo = Path(__file__).resolve().parents[1]
        executable = 'fastmcp' if probe else 'gdocs-scope-mcp'
        transport = StdioTransport(
            command=str(Path(sys.executable).parent / executable),
            args=(['run', str(repo / 'tests/probes/table_server.py'),
                   '--transport', 'stdio'] if probe else []),
            cwd=str(repo), env=(dict(os.environ) if environment is None
                               else environment), log_file=log,
            keep_alive=False,
        )
        info = None
        try:
            async with Client(transport) as client:
                identity = await client.call_tool('server_info', {})
                info = identity.structured_content
                assert info['source_fingerprint'] == (
                    capture_server_info().source_fingerprint
                )
                assert info['package_path'] == str(
                    repo / 'src/gdocs_scope_mcp',
                )
                yield client, info
        finally:
            if info is not None:
                assert not Path(f'/proc/{info["pid"]}').exists()

    return connect


@pytest.fixture(scope='session')
def live_document_reset(isolated_mcp, record_testsuite_property):
    """Retain the selected environment and external cleanup evidence."""
    environment = dict(os.environ)
    root = Path(tempfile.mkdtemp(prefix='gdocs-scope-mcp-live-session-',
                                 dir='/tmp'))
    report_path = root / 'report.json'
    record_testsuite_property('live_document_session_report', str(report_path))
    report = {}

    async def run(phase):
        report[phase] = {'status': 'running'}
        try:
            async with isolated_mcp(root / f'{phase}.stderr', probe=True,
                                    environment=environment) as (client, info):
                report[phase]['server'] = info
                report[phase]['state'] = await reset_document(
                    client, environment['GDOCS_SCOPE_MCP_LIVE_TEST_DOC'],
                )
            report[phase].update(status='passed', processes_reaped=True)
        except BaseException:
            report[phase]['status'] = 'failed'
            raise
        finally:
            report_path.write_text(json.dumps(report, indent=2))

    return lambda phase: asyncio.run(run(phase))


@pytest.fixture(scope='session')
def live_document_session(live_document_reset):
    """Hold the document lock through final cleanup of failed sessions."""
    doc_id = os.environ['GDOCS_SCOPE_MCP_LIVE_TEST_DOC']
    with document_session(doc_id, live_document_reset):
        yield doc_id


@pytest.fixture(autouse=True)
def live_document_guard(request):
    """Start cleanup only for opted-in, document-based live tests."""
    if (request.node.get_closest_marker('live') is not None
            and 'live_test_doc' in request.fixturenames):
        doc_id = request.getfixturevalue('live_test_doc')
        protected = request.getfixturevalue('live_document_session')
        assert doc_id == protected, (
            'The live target changed during the session.'
        )


@pytest.fixture
def live_test_doc():
    """Require an explicit target document before running a live test."""
    doc_id = os.environ.get('GDOCS_SCOPE_MCP_LIVE_TEST_DOC')
    if doc_id is None:
        pytest.skip('Set GDOCS_SCOPE_MCP_LIVE_TEST_DOC to a test document ID.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', doc_id):
        pytest.fail(
            'GDOCS_SCOPE_MCP_LIVE_TEST_DOC must contain a Google Doc ID, '
            'not an empty value, URL or whitespace.',
            pytrace=False,
        )
    return doc_id


@pytest.fixture
def image_png():
    """Generate a small valid RGB PNG containing no user data."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))

    header = struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0)
    pixels = b''.join(b'\x00' + bytes([32, 128, 224]) * 16 for _ in range(16))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


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
    monkeypatch.setattr(clients, 'build', lambda *_args, **_kwargs: service)
    monkeypatch.setattr(credentials, 'load_credentials', object)
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
