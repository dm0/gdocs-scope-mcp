"""Create and read one explicitly authorized disposable document over MCP."""

import asyncio
import json
import os
import uuid
from html import unescape
from pathlib import Path

import pytest

from gdocs_scope_mcp.google_api import clients

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get('GDOCS_SCOPE_MCP_LIVE_CREATE') != '1',
    reason='Requires explicit permission to create and trash one test Doc.',
)
def test_live_document_creation(isolated_mcp):
    """Read back initial content and trash only this newly created document."""
    marker = 'CREATE49' + uuid.uuid4().hex
    title = 'gdocs-scope-mcp disposable ' + marker
    text = marker + ' Initial content 🦷'
    log = Path('/tmp/gdocs-scope-mcp-document-creation.log')
    report = {'checks_passed': False, 'cleanup_passed': False,
              'processes_reaped': False}
    created = None

    async def run():
        nonlocal created
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            try:
                result = await client.call_tool('docs_create', {
                    'title': title, 'initial_text': text,
                }, raise_on_error=False)
                data = result.structured_content
                created = (
                    data.get('created_document') if result.is_error else data
                )
                report['created_document'] = created
                assert not result.is_error
                assert created['title'] == title
                assert created['webViewLink'] == (
                    'https://docs.google.com/document/d/'
                    + created['id'] + '/edit'
                )
                read = await client.call_tool('docs_read', {
                    'doc_id': created['id'],
                })
                assert not read.is_error
                content = '\n'.join(section['markdown'] for section in
                                    read.structured_content['sections'])
                assert text in unescape(content)
                report['checks_passed'] = True
            finally:
                if created is not None:
                    # Native cleanup is restricted to the confirmed new ID.
                    drive = clients.get_service('drive', 'v3', cached=False)
                    metadata = drive.files().get(
                        fileId=created['id'], fields='id,name,mimeType',
                    ).execute()
                    assert metadata['id'] == created['id']
                    assert metadata['name'] == title
                    assert metadata['mimeType'] == (
                        'application/vnd.google-apps.document'
                    )
                    drive.files().update(
                        fileId=created['id'], body={'trashed': True},
                    ).execute()
                    cleaned = drive.files().get(
                        fileId=created['id'], fields='trashed',
                    ).execute()
                    assert cleaned['trashed'] is True
                    report['cleanup_passed'] = True
        report['processes_reaped'] = True

    try:
        asyncio.run(run())
    finally:
        log.with_suffix('.json').write_text(json.dumps(report, indent=2))
