"""Verify native comment persistence and anchoring through isolated MCP."""


# Imported pytest fixtures intentionally retain their registered names.
# ruff: noqa: F811

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from .test_live_table_identity import table_probe  # noqa: F401

pytestmark = pytest.mark.live


def test_live_native_comment_lifecycle(live_test_doc, table_probe):
    """Read native anchors, reply/edit/resolve/reopen/delete, then restore."""

    async def run():
        async with table_probe('native-comments') as probe:
            before = await probe.read()
            probe.initial_body = before['body']
            probe.start = before['body']['content'][-1]['endIndex'] - 1
            marker = 'MCP_NATIVE_COMMENT_' + uuid.uuid4().hex
            anchor = marker + ' 😀 anchor'
            comment_id = None
            args = {'doc_id': live_test_doc}
            try:
                await probe.call(
                    0,
                    'docs_append',
                    {
                        **args,
                        'text': anchor + '\n' + anchor,
                        'rich': False,
                    },
                )
                created = await probe.call(
                    0,
                    'docs_add_comment',
                    {
                        **args,
                        'anchor_text': anchor,
                        'occurrence': 2,
                        'comment': 'Native MCP review ' + marker,
                    },
                )
                probe.report['created'] = created
                comment_id = created['comment_id']
                thread_args = {**args, 'comment_id': comment_id}
                read = await probe.call(0, 'docs_read_comments', thread_args)
                thread = read['comments'][0]
                probe.report['native_anchor'] = thread
                assert thread['anchored'] and thread['ranges']
                assert anchor in thread['quoted_text']
                assert thread['head_post_id'] == created['post_id']
                assert (
                    thread['ranges'][0]['start_index'] == created['at_index']
                )
                assert (await probe.read()).get('namedRanges', {}) == (
                    before.get('namedRanges', {})
                )
                if os.environ.get('GDOCS_SCOPE_MCP_COMMENT_UI_WAIT') == '1':
                    root = Path('/tmp/gdocs-native-comment-ui')
                    root.with_suffix('.done').unlink(missing_ok=True)
                    root.with_suffix('.json').write_text(json.dumps(created))
                    deadline = time.monotonic() + 180
                    while not root.with_suffix('.done').exists():
                        if time.monotonic() > deadline:
                            raise TimeoutError(
                                'Native comment UI review timed out'
                            )
                        await asyncio.sleep(0.25)
                reply = await probe.call(
                    0,
                    'docs_reply_to_comment',
                    {
                        **thread_args,
                        'reply': 'First reply',
                    },
                )
                await probe.call(
                    0,
                    'docs_edit_comment',
                    {
                        **thread_args,
                        'content': 'Edited native head ' + marker,
                    },
                )
                await probe.call(
                    0,
                    'docs_edit_comment',
                    {
                        **thread_args,
                        'post_id': reply['reply_id'],
                        'content': 'Edited reply',
                    },
                )
                read = await probe.call(0, 'docs_read_comments', thread_args)
                assert (
                    read['comments'][0]['content']
                    == 'Edited native head ' + marker
                )
                assert any(
                    p['content'] == 'Edited reply'
                    for p in read['comments'][0]['replies']
                )
                await probe.call(0, 'docs_resolve_comment', thread_args)
                read = await probe.call(0, 'docs_read_comments', thread_args)
                assert read['comments'][0]['resolved']
                await probe.call(
                    0,
                    'docs_reopen_comment',
                    {
                        **thread_args,
                        'reply': 'Reopened for verification',
                    },
                )
                read = await probe.call(0, 'docs_read_comments', thread_args)
                assert not read['comments'][0]['resolved']
                await probe.call(
                    0,
                    'docs_delete_comment_reply',
                    {
                        **thread_args,
                        'reply_id': reply['reply_id'],
                    },
                )
                await probe.call(0, 'docs_delete_comment', thread_args)
                comment_id = None
                read = await probe.call(
                    0,
                    'docs_read_comments',
                    {
                        **args,
                        'include_resolved': True,
                    },
                )
                assert all(
                    c['id'] != created['comment_id'] for c in read['comments']
                )
                probe.report['checks_passed'] = True
            finally:
                if comment_id:
                    await probe.call(
                        0,
                        'docs_delete_comment',
                        {
                            **args,
                            'comment_id': comment_id,
                        },
                    )

    asyncio.run(run())
