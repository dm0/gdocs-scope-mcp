"""Reset an explicitly selected disposable document through isolated MCP."""

import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path

from gdocs_scope_mcp.documents import tabs
from gdocs_scope_mcp.suggestions.index import index_document


@contextmanager
def document_session(doc_id, reset):
    """Exclude concurrent sessions and clean up after setup or test failure."""
    key = hashlib.sha256(doc_id.encode()).hexdigest()
    with Path(f'/tmp/gdocs-scope-mcp-live-{key}.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                'Another live test session is using this document.'
            ) from error
        try:
            reset('before')
            yield
        finally:
            reset('after')


def metadata_cleanup_requests(native):
    """Remove comments, tab-scoped ranges and all but the first root tab."""
    requests = [
        {'deleteComment': {'commentId': thread['commentId']}}
        for thread in native.get('comments', [])
        if not thread.get('headPost', {}).get('deleted', False)
    ]
    for tab, *_ in tabs.walk(native['tabs']):
        tab_id = tab['tabProperties']['tabId']
        ranges = tab['documentTab'].get('namedRanges', {})
        ids = {item['namedRangeId'] for group in ranges.values()
               for item in group.get('namedRanges', [])}
        requests.extend(tabs.scope_requests([
            {'deleteNamedRange': {'namedRangeId': identity}}
            for identity in sorted(ids)
        ], tab_id))
    requests.extend(
        {'deleteTab': {'tabId': tab['tabProperties']['tabId']}}
        for tab in [*native['tabs'][0].get('childTabs', []),
                    *native['tabs'][1:]]
    )
    return requests


async def reset_document(client, doc_id):
    """Reject proposals and restore a single empty tab with normal text."""
    async def call(tool, arguments=None):
        result = await client.call_tool(tool, arguments or {})
        assert not result.is_error
        return result.structured_content

    async def read():
        native = await call('probe_suggestions_document', {'threads': True})
        assert native['documentId'] == doc_id
        return native

    async def batch(requests):
        if not requests:
            return
        native = await read()
        result = await call('probe_batch', {
            'requests': requests,
            'write_control': {'requiredRevisionId': native['revisionId']},
        })
        assert result['accepted'], result
        if any('deleteComment' in request for request in requests):
            assert result['response']['commentUpdateState'] == 'ALL_SAVED'

    native = await read()
    pending = sorted(index_document(native).locations)
    for offset in range(0, len(pending), 50):
        result = await call('docs_suggestions_manage', {
            'doc_id': doc_id, 'action': 'reject',
            'suggestion_ids': pending[offset:offset + 50],
        })
        assert result['comment_update_state'] == 'ALL_SAVED'
        assert all(item['outcome'] in {'applied', 'already_decided'}
                   for item in result['results'])
    requests = metadata_cleanup_requests(await read())
    for offset in range(0, len(requests), 50):
        await batch(requests[offset:offset + 50])
    selected = tabs.select(await read())
    tab_id = selected['_mcp_tab_id']
    end = selected['body']['content'][-1]['endIndex'] - 1
    if end > 1:
        await batch(tabs.scope_requests([{'deleteContentRange': {
            'range': {'startIndex': 1, 'endIndex': end},
        }}], tab_id))
    selected = tabs.select(await read())
    paragraph = selected['body']['content'][-1]['paragraph']
    fields = set(paragraph['paragraphStyle']) - {'headingId'}
    fields.update({'namedStyleType', 'direction', 'indentStart',
                   'indentEnd', 'indentFirstLine'})
    requests = [
        {'deleteParagraphBullets': {'range': {
            'startIndex': 1, 'endIndex': 2,
        }}},
        {'updateParagraphStyle': {
            'range': {'startIndex': 1, 'endIndex': 2},
            'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT',
                               'direction': 'LEFT_TO_RIGHT'},
            'fields': ','.join(sorted(fields)),
        }},
    ]
    text_fields = {key for element in paragraph.get('elements', [])
                   for key in element.get('textRun', {}).get('textStyle', {})}
    if text_fields:
        requests.append({'updateTextStyle': {
            'range': {'startIndex': 1, 'endIndex': 2},
            'textStyle': {}, 'fields': ','.join(sorted(text_fields)),
        }})
    await batch(tabs.scope_requests(requests, tab_id))
    final = await read()
    assert len(final['tabs']) == 1
    assert not final['tabs'][0].get('childTabs')
    index = index_document(final)
    assert not index.locations and not index.unknown
    assert not metadata_cleanup_requests(final)
    selected = tabs.select(final)
    content = selected['body']['content']
    paragraphs = [item['paragraph'] for item in content if 'paragraph' in item]
    assert len(paragraphs) == 1
    assert all('paragraph' in item or 'sectionBreak' in item
               for item in content)
    paragraph = paragraphs[0]
    assert content[-1]['startIndex'] == 1
    assert content[-1]['endIndex'] == 2  # noqa: PLR2004 (terminal newline)
    assert not paragraph.get('bullet')
    assert paragraph['paragraphStyle']['namedStyleType'] == 'NORMAL_TEXT'
    assert paragraph['paragraphStyle']['direction'] == 'LEFT_TO_RIGHT'
    assert ''.join(element.get('textRun', {}).get('content', '')
                   for element in paragraph['elements']) == '\n'
    assert all('textRun' in element for element in paragraph['elements'])
    assert all(not element['textRun'].get('textStyle')
               for element in paragraph['elements'])
    return {'empty_body': True, 'root_tabs': 1, 'open_suggestions': 0,
            'active_comments': 0, 'named_ranges': 0}
