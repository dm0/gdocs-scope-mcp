"""Run independent native confirmations in test-owned disposable documents."""

import asyncio
import html
import importlib.util
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from study_execution import ROOT, FixtureBackend, translated

AUTHORIZED_FOLDER = '1j5SqJ2Iu95te9-u_9y_A0DyLcPbOheWt'
DOCUMENTS_SPEC = importlib.util.spec_from_file_location(
    'study_document_factory', ROOT / 'tests/live_document_state.py',
)
DOCUMENTS = importlib.util.module_from_spec(DOCUMENTS_SPEC)
DOCUMENTS_SPEC.loader.exec_module(DOCUMENTS)


async def owned_thread_call(function, *args, **kwargs):
    """Wait for confirmed creation or disposal even after cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def body_headings(outline):
    """Exclude the production reader's empty-ID preamble outline entry."""
    return [section for section in outline['sections'] if section['id']]


class LiveBackend(FixtureBackend):
    """Keep the same model-facing operations and native-state grading seam."""

    def __init__(self, client, control, document_id):
        """Restrict all model operations to this job's confirmed creation."""
        super().__init__(client)
        self.control = control
        self.document_id = document_id
        self.aliases = {'tabs': {}, 'headings': {}, 'comments': {}}
        self.strip_seed_blank = True
        self.references = []

    async def snapshot(self):
        """Read native comment/body state through an isolated probe server."""
        result = await self.control.call_tool('probe_suggestions_document', {
            'threads': True,
        })
        return result.structured_content

    async def control_call(self, name, args):
        """Execute setup/cleanup only through the existing probe MCP client."""
        result = await self.control.call_tool(name, args)
        return result.structured_content

    async def batch(self, requests):
        """Require the latest revision for every fixture setup batch."""
        result = await self.control_call('probe_batch', {
            'requests': requests, 'write_control': {
                'requiredRevisionId': (await self.snapshot())['revisionId'],
            },
        })
        if not result['accepted']:
            raise RuntimeError('Native fixture setup batch was rejected: '
                               + json.dumps(result))
        return result['response']

    def actual_call(self, call, variant):
        """Translate synthetic reference selectors into current native IDs."""
        result = translated(call, variant)
        args = result['arguments']
        args['doc_id'] = self.document_id
        for key, collection in (('tab_id', 'tabs'), ('heading_id', 'headings'),
                                ('comment_id', 'comments')):
            if args.get(key):
                inverse = {value: native for native, value
                           in self.aliases[collection].items()}
                args[key] = inverse[args[key]]
        if args.get('target', {}).get('heading_id'):
            inverse = {value: native for native, value
                       in self.aliases['headings'].items()}
            args['target']['heading_id'] = inverse[
                args['target']['heading_id']]
        return result

    async def seed(self, fixture):
        """Create synthetic tabs, headings and comments without direct APIs."""
        original = (await self.snapshot())['tabs'][0]['tabProperties']
        if original['title'] in {tab['title'] for tab in fixture['tabs']}:
            raise RuntimeError('Fresh default tab collides with fixture title')
        created = await self.batch([
            *[{'addDocumentTab': {'tabProperties': {
                'title': tab['title'], 'index': index,
            }}} for index, tab in enumerate(fixture['tabs'], start=1)],
            {'deleteTab': {'tabId': original['tabId']}},
        ])
        native_tabs = [reply['addDocumentTab']['tabProperties']['tabId']
                       for reply in created['replies']
                       if 'addDocumentTab' in reply]
        self.aliases['tabs'] = {
            native: tab['id'] for native, tab
            in zip(native_tabs, fixture['tabs'], strict=True)
        }
        for native_id, tab in zip(native_tabs, fixture['tabs'], strict=True):
            markup = []
            for paragraph in tab['paragraphs']:
                level = paragraph.get('level', 'NORMAL_TEXT')
                tag = ('h' + str(int(level.removeprefix('HEADING_')) + 2)
                       if level.startswith('HEADING_') else 'p')
                markup.append(f'<{tag}>{html.escape(paragraph["text"])}</{tag}>')
            await self.control_call('docs_append', {
                'doc_id': self.document_id, 'tab_id': native_id,
                'text': '\n'.join(markup),
            })
            outline = await self.control_call('docs_get_tree', {
                'doc_id': self.document_id, 'tab_id': native_id,
            })
            expected = [p for p in tab['paragraphs'] if p.get('heading_id')]
            sections = body_headings(outline)
            if len(sections) != len(expected):
                raise RuntimeError('Native seed produced unexpected headings')
            for section, paragraph in zip(sections, expected,
                                           strict=True):
                if section['title'].strip() != paragraph['text']:
                    raise RuntimeError('Native heading title mismatch')
                self.aliases['headings'][section['id']] = (
                    paragraph['heading_id'])
        anchor_tab = fixture['tabs'][0]
        anchor = next((p for p in anchor_tab['paragraphs']
                       if not p.get('heading_id')),
                      anchor_tab['paragraphs'][0])
        for thread in fixture.get('comments', []):
            receipt = await self.control_call('docs_add_comment', {
                'doc_id': self.document_id, 'tab_id': native_tabs[0],
                'anchor_text': thread.get('quote') or anchor['text'],
                'comment': thread['text'],
            })
            comment_id = receipt['comment_id']
            self.aliases['comments'][comment_id] = thread['id']
            if thread.get('resolved'):
                await self.control_call('docs_resolve_comment', {
                    'doc_id': self.document_id, 'comment_id': comment_id,
                })


@asynccontextmanager
async def live_backend(case, variant, output, *, reference_mode=False):
    """Create, seed and verify trashing one independent document per job."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = os.environ.get('GDOCS_SCOPE_MCP_LIVE_TEST_FOLDER')
    if folder != AUTHORIZED_FOLDER:
        raise ValueError('Explicitly opt in with the authorized test folder')
    keep = os.environ.get('GDOCS_SCOPE_MCP_LIVE_KEEP_ON_FAILURE', '0')
    if keep not in {'0', '1'}:
        raise ValueError('LIVE_KEEP_ON_FAILURE must be 0 or 1')
    documents = await asyncio.to_thread(
        DOCUMENTS.LiveDocuments, folder, output, None,
        keep_on_failure=keep == '1',
    )
    identities = []
    report = {'case': case['id'], 'variant': variant, 'folder_id': folder,
              'started_at': time.time()}
    failed = True
    try:
        created = await owned_thread_call(documents.create)
        report['document_id'] = created['id']
        report['created_at'] = time.time()
        env = {**os.environ,
               'GDOCS_SCOPE_MCP_LIVE_TEST_DOC': created['id'],
               'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive',
               'GDOCS_SCOPE_MCP_DOCUMENT_CACHE_ENABLED': 'false',
               'GDOCS_SCOPE_MCP_WRITE_REVISION_MODE': 'required',
               'GDOCS_SCOPE_MCP_COMMENT_UI_WAIT': '0'}
        control_transport = StdioTransport(
            command=str(Path(sys.executable).parent / 'fastmcp'),
            args=['run', str(ROOT / 'tests/probes/table_server.py'),
                  '--transport', 'stdio'], cwd=str(ROOT),
            env={**env, 'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': 'baseline'},
            log_file=output / 'control.stderr', keep_alive=False,
        )
        transport = StdioTransport(
            command=str(Path(sys.executable).parent / 'gdocs-scope-mcp'),
            args=[], cwd=str(ROOT), env={
                **env, 'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant,
            }, log_file=output / 'native.stderr', keep_alive=False,
        )
        async with Client(control_transport) as control, Client(
            transport,
        ) as client:
            for connected in (control, client):
                info = (await connected.call_tool('server_info', {})
                        ).structured_content
                identities.append(info)
                assert info['package_path'] == str(
                    ROOT / 'src/gdocs_scope_mcp',
                )
            backend = LiveBackend(client, control, created['id'])
            await backend.seed(case['fixture'])
            if not reference_mode:
                reference = json.loads((output.parents[1] / 'live-references'
                                        / (case['id'] + '.json')).read_text())
                backend.references = reference['states']
            yield backend, identities[-1]
            failed = False
    finally:
        try:
            await owned_thread_call(documents.finish, failed=failed)
        finally:
            report.update(
                documents=documents.documents, identities=identities,
                completed_at=time.time(),
                processes_reaped=all(not Path(f'/proc/{i["pid"]}').exists()
                                     for i in identities),
            )
            (output / 'live-cleanup.json').write_text(
                json.dumps(report, indent=2),
            )
        assert report['processes_reaped']


async def native_reference(case, output):
    """Calibrate a reference trajectory through actual STDIO MCP calls."""
    async with live_backend(case, 'baseline', output,
                            reference_mode=True) as (backend, identity):
        states = [await backend.state()]
        semantic = [await backend.state(semantic=True)]
        for call in case['oracle']:
            receipt = await backend.call(backend.actual_call(call, 'baseline'))
            if receipt.get('ok') is False:
                raise RuntimeError('Native oracle failed: '
                                   + json.dumps(receipt))
            states.append(await backend.state())
            semantic.append(await backend.state(semantic=True))
        return {'states': states, 'semantic': semantic, 'identity': identity}
