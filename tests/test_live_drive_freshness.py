"""Measure cross-service visibility without assuming immediate updates."""

# Imported reusable fixture names are intentional.
# ruff: noqa: F811

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from .native_snapshot_assertions import assert_tabs_unchanged
from .test_live_table_identity import table_probe  # noqa: F401

UI_OBSERVATION_SECONDS = 120


def test_live_drive_freshness(table_probe, monkeypatch):
    """Record three rapid edits and poll Drive metadata for a minute."""
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_ENABLED', 'false')

    async def run():
        async with table_probe('drive-freshness') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            tab_id = None
            try:
                created = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {
                        'title': 'mcp-freshness-' + uuid.uuid4().hex,
                    },
                }}], before)
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties']['tabId']
                baseline = await probe.call(0, 'probe_drive_freshness', {
                    'tab_id': tab_id, 'marker': 'not inserted',
                })
                probe.report['baseline'] = baseline
                probe.report['edits'] = []
                for _ in range(3):
                    previous = await probe.call(0, 'probe_drive_freshness', {
                        'tab_id': tab_id, 'marker': 'not inserted',
                    })
                    marker = 'Freshness ' + uuid.uuid4().hex
                    started = time.monotonic()
                    result = await probe.call(1, 'probe_batch', {
                        'requests': [{'insertText': {
                            'location': {'index': 1, 'tabId': tab_id},
                            'text': marker + '\n',
                        }}],
                        'write_control': {
                            'requiredRevisionId': previous['docs']['revision'],
                        },
                    })
                    assert result['accepted'], result
                    committed = time.monotonic()
                    sample = await probe.call(0, 'probe_drive_freshness', {
                        'tab_id': tab_id, 'marker': marker,
                    })
                    assert sample['docs']['marker_present']
                    assert sample['docs']['revision'] != previous['docs'][
                        'revision']
                    probe.report['edits'].append({
                        'write_ms': (committed - started) * 1000,
                        'before': previous, 'immediate': sample,
                        'observed_after_ack_ms': (
                            time.monotonic() - committed) * 1000,
                    })
                probe.report['delayed_samples'] = []
                for delay in (1, 5, 15, 30, 60):
                    await asyncio.sleep(max(0, delay - (
                        time.monotonic() - committed)))
                    sample = await probe.call(0, 'probe_drive_freshness', {
                        'tab_id': tab_id, 'marker': marker,
                    })
                    assert sample['docs']['marker_present']
                    probe.report['delayed_samples'].append({
                        'after_ack_ms': (time.monotonic() - committed) * 1000,
                        'sample': sample,
                    })
            finally:
                if tab_id:
                    current = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': tab_id}}], current,
                    )
                    after = await probe.call(0, 'probe_tabs_document')
                    assert_tabs_unchanged(before['tabs'], after['tabs'])
                    probe.report['tab_cleanup_passed'] = True

    asyncio.run(run())


def test_live_drive_freshness_ui(table_probe, monkeypatch):
    """Optionally observe a UI edit in a disposable tab for two minutes."""
    if os.environ.get('GDOCS_SCOPE_MCP_FRESHNESS_UI') != '1':
        pytest.skip('Set GDOCS_SCOPE_MCP_FRESHNESS_UI=1 for a manual UI edit.')
    monkeypatch.setenv('GOOGLE_DOCS_MCP_DOCUMENT_CACHE_ENABLED', 'false')

    async def run():
        async with table_probe('drive-freshness-ui') as probe:
            before = await probe.call(0, 'probe_tabs_document')
            title = 'mcp-freshness-ui-' + uuid.uuid4().hex
            marker = 'UI freshness ' + uuid.uuid4().hex
            tab_id = None
            try:
                created = await probe.batch([{'addDocumentTab': {
                    'tabProperties': {'title': title},
                }}], before)
                tab_id = created['response']['replies'][0]['addDocumentTab'][
                    'tabProperties']['tabId']
                arguments = {'tab_id': tab_id, 'marker': marker}
                probe.report['baseline'] = await probe.call(
                    0, 'probe_drive_freshness', arguments,
                )
                ready = Path('/tmp/gdocs-drive-freshness-ui-ready.json')
                ready.write_text(json.dumps({
                    'title': title, 'tab_id': tab_id, 'marker': marker,
                }))
                probe.report['samples'] = []
                started = time.monotonic()
                while time.monotonic() - started < UI_OBSERVATION_SECONDS:
                    sample = await probe.call(
                        0, 'probe_drive_freshness', arguments,
                    )
                    probe.report['samples'].append({
                        'elapsed_ms': (time.monotonic() - started) * 1000,
                        'sample': sample,
                    })
                    await asyncio.sleep(1)
                assert any(row['sample']['docs']['marker_present']
                           for row in probe.report['samples'])
            finally:
                if tab_id:
                    current = await probe.call(0, 'probe_tabs_document')
                    await probe.batch(
                        [{'deleteTab': {'tabId': tab_id}}], current,
                    )
                    after = await probe.call(0, 'probe_tabs_document')
                    assert_tabs_unchanged(before['tabs'], after['tabs'])
                    probe.report['tab_cleanup_passed'] = True

    asyncio.run(run())
