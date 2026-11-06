"""Read initial content in a fixture-owned disposable document."""

import asyncio
import uuid
from html import unescape
from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def test_live_document_creation(isolated_mcp, live_document_factory):
    """Exercise docs_create with initial text and read the same document."""
    text = 'CREATE49' + uuid.uuid4().hex + ' Initial content 🦷'
    created = live_document_factory(initial_text=text, via_mcp=True)
    assert created['webViewLink'] == (
        'https://docs.google.com/document/d/' + created['id'] + '/edit'
    )

    async def run():
        log = Path('/tmp/gdocs-scope-mcp-document-creation.log')
        async with isolated_mcp(log) as (client, _info):
            read = await client.call_tool('docs_read', {
                'doc_id': created['id'],
            })
            assert not read.is_error
            content = '\n'.join(section['markdown'] for section in
                                read.structured_content['sections'])
            assert text in unescape(content)

    asyncio.run(run())
