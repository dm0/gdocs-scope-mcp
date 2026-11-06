"""Execute production MCP operations and grade native fixture states."""

import json
import os
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

from bs4 import BeautifulSoup
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from gdocs_scope_mcp.rich_text.parsing import markdown_to_html

ROOT = Path(__file__).resolve().parents[2]
BLOCKED_TOOLS = {
    'docs_list', 'docs_create', 'docs_authorize', 'docs_select_files',
    'docs_authorization_complete', 'docs_authorization_status',
    'docs_suggest', 'docs_suggestions_manage',
    'docs_create_dropdown_definition', 'docs_select_dropdown',
    'docs_add_comment', 'docs_reply_to_comment', 'docs_edit_comment',
    'docs_delete_comment', 'docs_delete_comment_reply',
}


def translated(call, variant):
    """Express a baseline semantic action in a static treatment interface."""
    result = deepcopy(call)
    name, args = result['tool'], result['arguments']
    if variant in {'insertion', 'both'} and name in {
        'docs_append', 'docs_insert_before', 'docs_insert_after',
    }:
        target = {'position': ('append' if name == 'docs_append'
                               else name.removeprefix('docs_insert_'))}
        if name != 'docs_append':
            target['anchor'] = args.pop('anchor')
            if 'heading_id' in args:
                target['heading_id'] = args.pop('heading_id')
        args['target'] = target
        result['tool'] = 'docs_insert'
    if variant in {'status', 'both'} and name in {
        'docs_resolve_comment', 'docs_reopen_comment',
    }:
        args['action'] = ('resolve' if name == 'docs_resolve_comment'
                          else 'reopen')
        result['tool'] = 'docs_comment_status'
    return result


def style_value(value):
    """Normalize native RGB defaults and explicit false style properties."""
    if isinstance(value, dict):
        if 'rgbColor' in value:
            return {**value, 'rgbColor': {
                color: round(value['rgbColor'].get(color, 0), 6)
                for color in ('red', 'green', 'blue')
            }}
        return {key: style_value(child) for key, child in sorted(value.items())
                if child is not None and child is not False}
    if isinstance(value, list):
        return [style_value(child) for child in value]
    return value


def canonical(native, *, aliases=None, semantic=False, strip_seed_blank=False):
    """Keep content, styles and actions without diagnostic coordinates."""
    aliases = aliases or {}
    tabs = []
    for tab in native['tabs']:
        properties = tab['tabProperties']
        paragraphs = []
        for item in tab['documentTab']['body']['content']:
            if 'paragraph' not in item:
                if 'table' in item:
                    paragraphs.append({'native_block': 'table'})
                continue
            paragraph = item['paragraph']
            style = deepcopy(paragraph.get('paragraphStyle', {}))
            if style.get('namedStyleType', 'NORMAL_TEXT') == 'NORMAL_TEXT':
                style.pop('headingId', None)
            if 'headingId' in style:
                style['headingId'] = aliases.get('headings', {}).get(
                    style['headingId'], style['headingId'],
                )
            if semantic:
                style = {key: child for key, child in style.items()
                         if key in {'namedStyleType', 'headingId'}}
            characters = []
            for element in paragraph.get('elements', []):
                if 'textRun' not in element:
                    characters.append(['\ufffc', {'native_element': {
                        key: value for key, value in element.items()
                        if key not in {'startIndex', 'endIndex'}
                    }}])
                    continue
                run = element.get('textRun', {})
                text_style = style_value(run.get('textStyle', {}))
                if semantic:
                    text_style = {
                        key: child for key, child in text_style.items()
                        if key in {'bold', 'italic', 'underline',
                                   'strikethrough', 'foregroundColor',
                                   'backgroundColor', 'link'}
                    }
                characters.extend([char, text_style]
                                  for char in run.get('content', ''))
            paragraphs.append({'style': style_value(style),
                               'characters': characters})
        first_chars = paragraphs[0].get('characters', []) if paragraphs else []
        first_text = ''.join(c[0] for c in first_chars)
        if strip_seed_blank and first_text == '\n':
            paragraphs.pop(0)
        tabs.append({
            'id': aliases.get('tabs', {}).get(properties['tabId'],
                                            properties['tabId']),
            'title': properties['title'], 'paragraphs': paragraphs,
            'metadata': {
                key: value for key, value in tab['documentTab'].items()
                if key in {'namedRanges', 'dropdownDefinitions',
                           'inlineObjects', 'positionedObjects'} and value
            },
        })
    comments = [{
        'id': aliases.get('comments', {}).get(t['commentId'], t['commentId']),
        'text': t.get('headPost', {}).get('content', ''),
        'deleted': t.get('headPost', {}).get('deleted', False),
        'resolved': t.get('status') == 'RESOLVED',
        'replies': [{'text': p.get('content', ''),
                     'action': p.get('commentAction'),
                     'deleted': p.get('deleted', False)}
                    for p in t.get('replies', [])],
    } for t in native.get('comments', [])]
    return {'tabs': tabs, 'comments': sorted(comments, key=lambda t: t['id'])}


def failure(code, description):
    """Use the shared structured failure shape for scope/validation guards."""
    return {'ok': False, 'code': code, 'description': description,
            'suggested_action': 'Inspect fixture state and available tools.',
            'committed_batches': 0}


class FixtureBackend:
    """Proxy allowed model actions to the unchanged production MCP adapters."""

    def __init__(self, client):
        """Retain a client with explicit fixture-only document scope."""
        self.client = client
        self.document_id = 'study_fixture'
        self.aliases = {}
        self.strip_seed_blank = False

    async def snapshot(self):
        """Read controller-only native state through the test MCP boundary."""
        result = await self.client.call_tool('study_native_snapshot', {})
        return result.structured_content

    async def state(self, *, semantic=False):
        """Return a native-state projection, never a model success claim."""
        return canonical(await self.snapshot(), aliases=self.aliases,
                         semantic=semantic,
                         strip_seed_blank=self.strip_seed_blank)

    async def call(self, call):
        """Keep administrative actions and unrelated documents out of scope."""
        name, args = call['tool'], call['arguments']
        if name in BLOCKED_TOOLS or args.get('upload_local_images'):
            return failure('PERMISSION_DENIED',
                           'The action is outside study permissions.')
        if args.get('doc_id', self.document_id) != self.document_id:
            return failure('PERMISSION_DENIED',
                           'The study permits only its fixture document.')
        if isinstance(args.get('text'), str) and args.get('rich', True):
            markup = BeautifulSoup(markdown_to_html(args['text']),
                                   'html.parser')
            if (markup.find(['img', 'table'])
                    or markup.find(attrs={'data-mcp-entity': True})):
                return failure('PERMISSION_DENIED',
                               'Images, tables and chips are outside scope.')
        result = await self.client.call_tool(name, args, raise_on_error=False)
        payload = result.structured_content
        if payload is None:
            return failure('INVALID_ARGUMENT', 'The MCP call was rejected.')
        return payload


@asynccontextmanager
async def fixture_backend(case, variant, output):
    """Start and reap one STDIO server with a private answer-free fixture."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = output / 'fixture.json'
    path.write_text(json.dumps(case['fixture'], ensure_ascii=False, indent=2))
    transport = StdioTransport(
        command=sys.executable,
        args=[str(Path(__file__).with_name('study_fixture_server.py'))],
        cwd=str(ROOT), env={
            **os.environ, 'GDOCS_STUDY_FIXTURE': str(path),
            'GDOCS_SCOPE_MCP_TOOL_INTERFACE_VARIANT': variant,
            'GDOCS_SCOPE_MCP_ACCESS_MODE': 'full_drive',
            'GDOCS_SCOPE_MCP_DOCUMENT_CACHE_ENABLED': 'false',
            'GDOCS_SCOPE_MCP_WRITE_REVISION_MODE': 'required',
        }, log_file=output / 'fixture.stderr', keep_alive=False,
    )
    info = None
    try:
        async with Client(transport) as client:
            info = (await client.call_tool('server_info', {})
                    ).structured_content
            assert info['package_path'] == str(ROOT / 'src/gdocs_scope_mcp')
            yield FixtureBackend(client), info
    finally:
        if info is not None:
            assert not Path(f'/proc/{info["pid"]}').exists()


async def model_state(backend):
    """Supply complete decision state using production read tools only."""
    args = {'doc_id': backend.document_id}
    first = await backend.call({'tool': 'docs_get_tree', 'arguments': args})
    result = {'document_id': backend.document_id, 'tabs': []}
    for tab in first['tabs']:
        tab_args = {**args, 'tab_id': tab['tab_id']}
        result['tabs'].append({
            'outline': await backend.call({'tool': 'docs_get_tree',
                                            'arguments': tab_args}),
            'content': await backend.call({'tool': 'docs_read',
                                            'arguments': tab_args}),
        })
    result['comments'] = await backend.call({
        'tool': 'docs_read_comments',
        'arguments': {**args, 'include_resolved': True},
    })
    return result


async def reference_states(case, variant, output):
    """Execute the reference trajectory and retain every native prefix."""
    async with fixture_backend(case, variant, output) as (backend, info):
        states = [await backend.state()]
        for call in case['oracle']:
            result = await backend.call(translated(call, variant))
            if result.get('ok') is False:
                raise RuntimeError('Invalid reference trajectory: '
                                   + json.dumps(result))
            states.append(await backend.state())
        return {'states': states, 'identity': info}
