"""Opt-in interactive Desktop Picker verification through isolated STDIO."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from gdocs_scope_mcp.google_api.access import DRIVE_FULL
from gdocs_scope_mcp.google_api.authorization import token_path

pytestmark = pytest.mark.live


async def complete_selection(client, state, root, report, evidence,
                             *, label='PICKER_URL'):
    """Wait for one browser response without retaining its sensitive URL."""
    callback_file = root / 'callback-url.txt'
    assert not callback_file.exists(), 'Remove the stale callback file first'
    report['selection'] = state
    report['manual_callback_file'] = str(callback_file)
    evidence.write_text(json.dumps(report, indent=2))
    print(label + '=' + state['authorization_url'], flush=True)
    print('CALLBACK_FILE=' + str(callback_file), flush=True)
    deadline = time.monotonic() + 310
    try:
        while state['status'] == 'pending':
            assert time.monotonic() < deadline, 'Authorization wait expired'
            await asyncio.sleep(1)
            if callback_file.exists():
                try:
                    submitted = await client.call_tool(
                        'docs_authorization_complete', {
                            'session_id': state['session_id'],
                            'callback_url': callback_file.read_text().strip(),
                        },
                    )
                    assert not submitted.is_error
                    report['manual_callback_submitted'] = True
                finally:
                    callback_file.unlink(missing_ok=True)
            result = await client.call_tool('docs_authorization_status', {
                'session_id': state['session_id'],
            })
            assert not result.is_error
            state = result.structured_content
        report['selection'] = state
        evidence.write_text(json.dumps(report, indent=2))
        assert state['status'] == 'completed', state
        return state
    finally:
        callback_file.unlink(missing_ok=True)


def test_live_full_authorization_and_restart(isolated_mcp, live_test_doc):
    """Request drive alone, then read with a fresh token across processes."""
    target = os.environ.get('GDOCS_SCOPE_MCP_LIVE_FULL_TOKEN')
    if not target:
        pytest.skip('Set LIVE_FULL_TOKEN for interactive full authorization')
    token = Path(target).resolve()
    assert token != token_path().resolve()
    assert not token.exists(), 'Use a new isolated full-token destination'
    root = token.parent
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    evidence = root / 'authorization-report.json'
    environment = {
        **os.environ, 'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive',
        'GDOCS_SCOPE_MCP_TOKEN': str(token),
    }
    report = {}

    async def read(client):
        result = await client.call_tool('docs_read', {'doc_id': live_test_doc})
        assert not result.is_error

    async def run():
        async with isolated_mcp(root / 'authorization.stderr',
                                environment=environment) as (client, info):
            assert info['access_mode'] == 'full_drive'
            report['server'] = info
            started = await client.call_tool('docs_authorize', {
                'open_browser': False,
            })
            assert not started.is_error
            state = started.structured_content
            query = parse_qs(urlsplit(state['authorization_url']).query)
            assert query['scope'] == [DRIVE_FULL]
            assert 'trigger_onepick' not in query
            report['requested_scopes'] = query['scope']
            state = await complete_selection(
                client, state, root, report, evidence,
                label='AUTHORIZATION_URL',
            )
            assert state['documents'] == []
            saved = json.loads(token.read_text())
            assert saved['scopes'] == [DRIVE_FULL]
            assert saved['refresh_token'] and 'access_token' not in saved
            report['saved_scopes'] = saved['scopes']
            await read(client)
            report['initial_read'] = 'passed'
        report['initial_process_reaped'] = True
        async with isolated_mcp(root / 'restart.stderr',
                                environment=environment) as (client, info):
            report['restarted_server'] = info
            await read(client)
            listing = await client.call_tool('docs_list', {'limit': 1})
            assert not listing.is_error
            report['restart_read_and_listing'] = 'passed'
        report['restart_process_reaped'] = True

    try:
        asyncio.run(run())
    finally:
        (root / 'callback-url.txt').unlink(missing_ok=True)
        evidence.write_text(json.dumps(report, indent=2))


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
    callback_file = root / 'callback-url.txt'
    assert not callback_file.exists(), 'Remove the stale callback file first'
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
            state = await complete_selection(
                client, state, root, report, evidence,
            )
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
        callback_file.unlink(missing_ok=True)
        evidence.write_text(json.dumps(report, indent=2))


@pytest.mark.skipif(
    os.environ.get('GDOCS_SCOPE_MCP_LIVE_ADDITIONAL_SELECTION') != '1',
    reason='Requires permission to create, select and trash one test Doc.',
)
def test_live_additional_selection(
    isolated_mcp, live_test_doc, live_document_factory,
):
    """Select a second document and retain both reads after a restart."""
    target = os.environ.get('GDOCS_SCOPE_MCP_LIVE_SELECTED_TOKEN')
    if not target:
        pytest.skip('Set LIVE_SELECTED_TOKEN to an existing narrow token')
    token = Path(target).resolve()
    assert token.exists() and token != token_path().resolve()
    root = token.parent / 'additional'
    root.mkdir(mode=0o700)
    evidence = root / 'selection-report.json'
    environment = {
        **os.environ, 'GDOCS_SCOPE_MCP_ACCESS_MODE': 'selected_files',
        'GDOCS_SCOPE_MCP_TOKEN': str(token),
    }
    marker = 'PICKER40' + uuid.uuid4().hex
    created = live_document_factory(initial_text=marker, via_mcp=True)
    title = created['title']
    report = {'created_document': created}

    async def verify_reads(client):
        for doc_id in (live_test_doc, created['id']):
            result = await client.call_tool('docs_read', {'doc_id': doc_id})
            assert not result.is_error
            if doc_id == created['id']:
                assert marker in json.dumps(result.structured_content)

    async def run():
        try:
            print('SELECT_DOCUMENT=' + title, flush=True)
            async with isolated_mcp(root / 'selection.stderr',
                                    environment=environment) as (client, info):
                report['server'] = info
                # App-created files may already be visible with drive.file;
                # this test proves reselection and retained access, not denial.
                initial = await client.call_tool('docs_read', {
                    'doc_id': created['id'],
                }, raise_on_error=False)
                if initial.is_error:
                    assert initial.structured_content['code'] in {
                        'RESOURCE_NOT_FOUND', 'PERMISSION_DENIED',
                    }
                report['second_read_before_selection'] = (
                    'denied' if initial.is_error else 'available'
                )
                started = await client.call_tool('docs_select_files', {
                    'open_browser': False,
                })
                assert not started.is_error
                state = await complete_selection(
                    client, started.structured_content, root, report, evidence,
                )
                assert {item['id'] for item in state['documents']} == {
                    created['id'],
                }
                assert state['documents'][0]['name'] == title
                await verify_reads(client)
                report['both_reads'] = 'passed'
            report['selection_process_reaped'] = True
            async with isolated_mcp(root / 'restart.stderr',
                                    environment=environment) as (client, info):
                report['restarted_server'] = info
                await verify_reads(client)
                report['restart_both_reads'] = 'passed'
            report['restart_process_reaped'] = True
        finally:
            evidence.write_text(json.dumps(report, indent=2))

    try:
        asyncio.run(run())
    finally:
        (root / 'callback-url.txt').unlink(missing_ok=True)
        evidence.write_text(json.dumps(report, indent=2))
