"""Serialize live confirmations on the authorized development document."""

import asyncio
import fcntl
import hashlib
import html
import importlib.util
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from study_execution import ROOT, FixtureBackend, translated

AUTHORIZED_DOC = '1jG0MECReTHJMH5HdsiZnsGjjRDLcoHvDyomuYdsiJZk'
LIVE_SERIAL = asyncio.Lock()
RESET_SPEC = importlib.util.spec_from_file_location(
    'study_document_reset', ROOT / 'tests/live_document_state.py',
)
RESET = importlib.util.module_from_spec(RESET_SPEC)
RESET_SPEC.loader.exec_module(RESET)


def body_headings(outline):
    """Exclude the production reader's empty-ID preamble outline entry."""
    return [section for section in outline['sections'] if section['id']]


class LiveBackend(FixtureBackend):
    """Keep the same model-facing operations and native-state grading seam."""

    def __init__(self, client, control):
        """Restrict all model operations to the already-authorized document."""
        super().__init__(client)
        self.control = control
        self.document_id = AUTHORIZED_DOC
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
            raise RuntimeError('Native fixture setup batch was rejected')
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
        original = (await self.snapshot())['tabs'][0]['tabProperties']['tabId']
        created = await self.batch([{'addDocumentTab': {'tabProperties': {
            'title': tab['title'],
        }}} for tab in fixture['tabs']])
        native_tabs = [reply['addDocumentTab']['tabProperties']['tabId']
                       for reply in created['replies']]
        self.aliases['tabs'] = {
            native: tab['id'] for native, tab
            in zip(native_tabs, fixture['tabs'], strict=True)
        }
        await self.batch([{'deleteTab': {'tabId': original}}])
        for native_id, tab in zip(native_tabs, fixture['tabs'], strict=True):
            markup = []
            for paragraph in tab['paragraphs']:
                level = paragraph.get('level', 'NORMAL_TEXT')
                tag = ('h' + str(int(level.removeprefix('HEADING_')) + 2)
                       if level.startswith('HEADING_') else 'p')
                markup.append(f'<{tag}>{html.escape(paragraph["text"])}</{tag}>')
            await self.control_call('docs_append', {
                'doc_id': AUTHORIZED_DOC, 'tab_id': native_id,
                'text': '\n'.join(markup),
            })
            outline = await self.control_call('docs_get_tree', {
                'doc_id': AUTHORIZED_DOC, 'tab_id': native_id,
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
                'doc_id': AUTHORIZED_DOC, 'tab_id': native_tabs[0],
                'anchor_text': thread.get('quote') or anchor['text'],
                'comment': thread['text'],
            })
            comment_id = receipt['comment_id']
            self.aliases['comments'][comment_id] = thread['id']
            if thread.get('resolved'):
                await self.control_call('docs_resolve_comment', {
                    'doc_id': AUTHORIZED_DOC, 'comment_id': comment_id,
                })


@asynccontextmanager
async def live_backend(case, variant, output, *, reference_mode=False):
    """Lock, reset, seed and restore the single explicitly authorized Doc."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(AUTHORIZED_DOC.encode()).hexdigest()
    lock_path = Path('/tmp/gdocs-scope-mcp-live-' + key + '.lock')
    async with LIVE_SERIAL:
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            env = {**os.environ,
                   'GDOCS_SCOPE_MCP_LIVE_TEST_DOC': AUTHORIZED_DOC,
                   'GDOCS_SCOPE_MCP_DOCUMENT_CACHE_ENABLED': 'false',
                   'GDOCS_SCOPE_MCP_WRITE_REVISION_MODE': 'required',
                   'GDOCS_SCOPE_MCP_COMMENT_UI_WAIT': '0'}
            control_transport = StdioTransport(
                command=str(Path(sys.executable).parent / 'fastmcp'),
                args=['run', str(ROOT / 'tests/probes/table_server.py'),
                      '--transport', 'stdio'], cwd=str(ROOT),
                env={
                    **env,
                    'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': 'baseline',
                },
                log_file=output / 'control.stderr', keep_alive=False,
            )
            transport = StdioTransport(
                command=str(Path(sys.executable).parent / 'gdocs-scope-mcp'),
                args=[], cwd=str(ROOT), env={
                    **env, 'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant,
                }, log_file=output / 'native.stderr', keep_alive=False,
            )
            identities = []
            report = {'case': case['id'], 'variant': variant}
            try:
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
                    report['before_reset'] = await RESET.reset_document(
                        control, AUTHORIZED_DOC,
                    )
                    try:
                        backend = LiveBackend(client, control)
                        await backend.seed(case['fixture'])
                        if not reference_mode:
                            reference = json.loads((output.parents[1]
                                                    / 'live-references'
                                                    / (case['id'] + '.json'))
                                                   .read_text())
                            backend.references = reference['states']
                        yield backend, identities[-1]
                    finally:
                        report['after_reset'] = await RESET.reset_document(
                            control, AUTHORIZED_DOC,
                        )
            finally:
                for info in identities:
                    assert not Path(f'/proc/{info["pid"]}').exists()
                report.update(identities=identities, processes_reaped=True)
                (output / 'live-cleanup.json').write_text(
                    json.dumps(report, indent=2),
                )


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
