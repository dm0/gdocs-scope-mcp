"""Validate cache hits, independent writes and payload savings over STDIO."""

# Imported fixture names and numeric request counts are intentional.
# ruff: noqa: F811, PLR2004

import asyncio
import time
import uuid

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import table_probe  # noqa: F401


def test_live_document_cache(
    live_test_doc, table_probe, monkeypatch, tmp_path,
):
    """Use a temporary large tab and confirm cleanup in two MCP processes."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_STORAGE', 'disk')
    monkeypatch.setenv(
        'GOOGLE_DOCS_MCP_DOCUMENT_CACHE_DIRECTORY', str(tmp_path),
    )

    async def run():
        async with table_probe('document-cache') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {
                        'title': 'mcp-cache-' + uuid.uuid4().hex,
                    },
                }}], before)
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties']['tabId']
                await probe.call(1, 'docs_append', {
                    'doc_id': live_test_doc, 'tab_id': tab_id,
                    'text': 'Cache benchmark line with ordinary text. ' * 2500,
                    'rich': False,
                })
                await probe.call(0, 'probe_get_measurements', {'reset': True})
                arguments = {'doc_id': live_test_doc, 'tab_id': tab_id}
                durations = []
                for _ in range(3):
                    started = time.monotonic()
                    await probe.call(0, 'docs_get_tree', arguments)
                    durations.append((time.monotonic() - started) * 1000)
                metrics = await probe.call(0, 'probe_get_measurements', {
                    'reset': True,
                })
                requests = metrics['requests']
                assert [r['revision_only'] for r in requests] == [
                    False, True, True,
                ], requests
                full = next(r for r in requests if not r['revision_only'])
                checks = [r for r in requests if r['revision_only']]
                assert full['response_bytes'] > 100000
                assert all(r['response_bytes'] < 1000 for r in checks)
                probe.report['benchmark'] = {
                    'mcp_call_ms': durations, 'native_gets': requests,
                }
                await probe.call(1, 'probe_get_measurements', {'reset': True})
                await probe.call(1, 'docs_get_tree', arguments)
                shared = await probe.call(1, 'probe_get_measurements', {
                    'reset': True,
                })
                assert [r['revision_only'] for r in shared['requests']] == [
                    True,
                ]
                probe.report['shared_process_hit'] = shared['requests']
                # A second process changes the revision behind the first cache.
                marker = 'Cache external change ' + uuid.uuid4().hex
                await probe.call(1, 'docs_append', {
                    **arguments, 'text': marker, 'rich': False,
                })
                refreshed = await probe.call(0, 'docs_read', arguments)
                assert marker in str(refreshed['sections'])
                metrics = await probe.call(0, 'probe_get_measurements', {
                    'reset': True,
                })
                assert [r['revision_only'] for r in metrics['requests']] == [
                    False,
                ]
                # A local write evicts the snapshot without waiting for TTL.
                await probe.call(0, 'docs_append', {
                    **arguments, 'text': 'Cache local change', 'rich': False,
                })
                await probe.call(0, 'probe_get_measurements', {'reset': True})
                refreshed = await probe.call(0, 'docs_read', arguments)
                assert 'Cache local change' in str(refreshed['sections'])
                metrics = await probe.call(0, 'probe_get_measurements')
                assert [r['revision_only'] for r in metrics['requests']] == [
                    False,
                ]
            finally:
                if tab_id:
                    current = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': tab_id}}], current,
                    )
                    after = await probe.call(0, 'probe_tabs_document')
                    assert_tabs_unchanged(before['tabs'], after['tabs'])

    asyncio.run(run())
