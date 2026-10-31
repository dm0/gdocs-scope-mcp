"""Opt-in interactive Desktop Picker verification through isolated STDIO."""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from gdocs_scope_mcp.google_api.authorization import token_path

pytestmark = pytest.mark.live


def test_live_picker_selection_and_restart(isolated_mcp, live_test_doc):
    """Select the authorized document, then verify refresh across processes."""
    target = os.environ.get('GDOCS_SCOPE_MCP_LIVE_SELECTED_TOKEN')
    if not target:
        pytest.skip('Set LIVE_SELECTED_TOKEN for interactive Picker testing')
    token = Path(target).resolve()
    assert token != token_path().resolve()
    root = token.parent
    root.mkdir(parents=True, exist_ok=True)
    evidence = root / 'selection-report.json'
    environment = {
        **os.environ, 'GDOCS_SCOPE_MCP_ACCESS_MODE': 'selected_files',
        'GDOCS_SCOPE_MCP_TOKEN': str(token),
    }
    report = {}

    async def run():
        async with isolated_mcp(root / 'selection.stderr',
                                environment=environment) as (client, info):
            assert info['access_mode'] == 'selected_files'
            report['server'] = info
            started = await client.call_tool('docs_select_files', {
                'open_browser': False,
            })
            assert not started.is_error
            state = started.structured_content
            report['selection'] = state
            evidence.write_text(json.dumps(report, indent=2))
            print('PICKER_URL=' + state['authorization_url'], flush=True)
            deadline = time.monotonic() + 310
            while state['status'] == 'pending':
                assert time.monotonic() < deadline, 'Picker wait expired'
                await asyncio.sleep(1)
                result = await client.call_tool('docs_selection_status', {
                    'session_id': state['session_id'],
                })
                assert not result.is_error
                state = result.structured_content
            report['selection'] = state
            evidence.write_text(json.dumps(report, indent=2))
            assert state['status'] == 'completed', state
            assert live_test_doc in {item['id'] for item in state['documents']}
            read = await client.call_tool('docs_get_tree', {
                'doc_id': live_test_doc,
            })
            assert not read.is_error
            report['initial_read'] = 'passed'
        report['initial_process_reaped'] = True
        async with isolated_mcp(root / 'restart.stderr',
                                environment=environment) as (client, info):
            report['restarted_server'] = info
            read = await client.call_tool('docs_get_tree', {
                'doc_id': live_test_doc,
            })
            assert not read.is_error
            listing = await client.call_tool('docs_list', {'limit': 1})
            assert not listing.is_error
            report['restart_read_and_listing'] = 'passed'
        report['restart_process_reaped'] = True
    try:
        asyncio.run(run())
    finally:
        evidence.write_text(json.dumps(report, indent=2))
