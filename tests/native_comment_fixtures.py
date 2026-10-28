"""Provide API-shaped native comments without any credential/network access."""

from copy import deepcopy


def comment_thread(
    identifier='comment-id',
    content='Comment body',
    *,
    resolved=False,
    replies=None,
):
    """Keep thread, anchor and post IDs distinct in API-shaped fixtures."""
    return {
        'commentId': identifier,
        'anchorId': 'anchor-' + identifier,
        'plainTextQuote': 'Target phrase',
        'status': 'RESOLVED' if resolved else 'OPEN',
        'headPost': {
            'postId': 'head-id',
            'content': content,
            'author': {'displayName': 'Author', 'me': True},
            'createTime': '2026-10-23T09:00:00Z',
        },
        'replies': replies
        if replies is not None
        else [
            {
                'postId': 'reply-id',
                'content': 'Reply body',
                'author': {'displayName': 'Author', 'me': True},
            }
        ],
    }


def native_batch(name='insertComment', payload=None):
    """Return the independently specified native response for one request."""
    payload = payload or {}
    if name == 'insertComment':
        reply = {
            name: {
                'commentThread': comment_thread(
                    content=payload.get('content', 'Comment body'),
                )
            }
        }
    elif name == 'addCommentReply':
        reply = {
            name: {
                'post': {
                    'postId': 'reply-id',
                    **deepcopy(payload.get('post', {})),
                }
            }
        }
    else:
        reply = {}
    return {
        'commentUpdateState': 'ALL_SAVED',
        'replies': [reply],
        'writeControl': {'requiredRevisionId': 'committed'},
    }


def wire_native_comments(mock_docs, document):
    """Simulate comments while preserving other configured API replies."""
    document['comments'] = [comment_thread()]
    mock_docs.get.return_value.uri = (
        'https://docs.googleapis.com/v1/documents/example?alt=json'
    )

    def execute():
        """Dispatch by native operation without intercepting ordinary edits."""
        requests = mock_docs.batchUpdate.call_args.kwargs['body']['requests']
        if not requests:
            return mock_docs.batchUpdate.return_value.execute.return_value
        request = requests[0]
        name, payload = next(iter(request.items()))
        if name in {
            'insertComment',
            'addCommentReply',
            'updateCommentPost',
            'deleteComment',
            'deleteCommentReply',
        }:
            return native_batch(name, payload)
        return mock_docs.batchUpdate.return_value.execute.return_value

    mock_docs.batchUpdate.return_value.execute.side_effect = execute
