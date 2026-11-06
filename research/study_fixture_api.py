"""Deterministic Google Docs API seam for the bounded tool-interface study.

The production MCP adapters, parsing, rendering, targeting and editing remain
unchanged. This fixture implements plain paragraphs, inline styles, headings
and native comment status only. It is not a Google service or live evidence.
Unsupported native requests fail atomically before any fixture mutation.
"""

import json
from copy import deepcopy
from itertools import groupby

from googleapiclient.errors import HttpError
from httplib2 import Response

from gdocs_scope_mcp.text_indices import utf16_length


def reject(message, status=400):
    """Raise a structured API rejection without credentials or transport."""
    raise HttpError(Response({'status': str(status)}), json.dumps({
        'error': {'message': message},
    }).encode())


class FixtureRequest:
    """Expose the request URI/execute seam used by production comment reads."""

    def __init__(self, execute):
        """Retain one deferred synthetic API operation."""
        self.operation = execute
        self.uri = 'https://docs.googleapis.com/v1/documents/study_fixture'

    def execute(self):
        """Return a fresh result for this fixture request."""
        return self.operation()


class FixtureAPI:
    """Maintain UTF-16 text, paragraph styles and native comment posts."""

    def __init__(self, specification):
        """Create native state without consulting the scenario's answer key."""
        self.document_id = specification.get('document_id', 'study_fixture')
        self.title = specification.get('title', 'Study fixture')
        self.revision = 0
        self.tabs = []
        for number, tab in enumerate(specification['tabs']):
            chars = []
            for paragraph in tab['paragraphs']:
                style = {
                    'namedStyleType': paragraph.get('level', 'NORMAL_TEXT'),
                }
                if paragraph.get('heading_id'):
                    style['headingId'] = paragraph['heading_id']
                chars.extend({'char': char, 'textStyle': deepcopy(
                    paragraph.get('text_style', {})),
                    'paragraphStyle': deepcopy(style)}
                    for char in paragraph['text'].rstrip('\n') + '\n')
            self.tabs.append({'id': tab['id'], 'title': tab['title'],
                              'index': number, 'chars': chars})
        self.comments = []
        for number, thread in enumerate(specification.get('comments', [])):
            self.comments.append({
                'commentId': thread['id'], 'anchorId': 'a' + str(number),
                'plainTextQuote': thread.get('quote', ''),
                'status': 'RESOLVED' if thread.get('resolved') else 'OPEN',
                'headPost': {'postId': 'head-' + str(number),
                             'content': thread['text'],
                             'author': {'displayName': 'Study author',
                                        'me': True},
                             'createTime': '2026-11-06T00:00:00Z'},
                'replies': [],
            })

    def documents(self):
        """Match discovery-service documents().get/batchUpdate usage."""
        return self

    def snapshot(self):
        """Compile native paragraph runs from synthetic characters."""
        tabs = []
        for tab in self.tabs:
            content = []
            index = 1
            chars = tab['chars']
            start = 0
            for end, char in enumerate(chars):
                if char['char'] != '\n':
                    continue
                paragraph = chars[start:end + 1]
                elements = []
                cursor = index
                for style, runs in groupby(paragraph,
                                           key=lambda item: item['textStyle']):
                    text = ''.join(item['char'] for item in runs)
                    width = utf16_length(text)
                    elements.append({
                        'startIndex': cursor, 'endIndex': cursor + width,
                        'textRun': {'content': text,
                                    'textStyle': deepcopy(style)},
                    })
                    cursor += width
                content.append({
                    'startIndex': index, 'endIndex': cursor,
                    'paragraph': {'paragraphStyle': deepcopy(
                        paragraph[0]['paragraphStyle']), 'elements': elements},
                })
                index = cursor
                start = end + 1
            tabs.append({
                'tabProperties': {'tabId': tab['id'], 'title': tab['title'],
                                  'index': tab['index']},
                'documentTab': {'body': {'content': content},
                                'lists': {}, 'inlineObjects': {}},
            })
        return {'documentId': self.document_id, 'title': self.title,
                'revisionId': 'r' + str(self.revision), 'tabs': tabs,
                'comments': deepcopy(self.comments)}

    def get(self, *, documentId, **_kwargs):  # noqa: N803
        """Obtain the fixture only; no other document can be accessed."""
        self.check_document(documentId)
        return FixtureRequest(self.snapshot)

    def check_document(self, document_id):
        """Reject foreign IDs before any read or mutation."""
        if document_id != self.document_id:
            reject('This study grants access only to its fixture.', 403)

    def batchUpdate(self, *, documentId, body):  # noqa: N802, N803
        """Execute production request batches on a private atomic copy."""
        self.check_document(documentId)
        return FixtureRequest(lambda: self.apply(body))

    def apply(self, body):
        """Validate revisions and commit a complete synthetic batch once."""
        control = body.get('writeControl', {})
        expected = control.get('requiredRevisionId')
        if expected is not None and expected != 'r' + str(self.revision):
            reject('Revision does not match the latest revision.')
        candidate = deepcopy(self)
        replies = [candidate.apply_request(request)
                   for request in body['requests']]
        candidate.revision += 1
        self.tabs = candidate.tabs
        self.comments = candidate.comments
        self.revision = candidate.revision
        return {'replies': replies, 'commentUpdateState': 'ALL_SAVED',
                'writeControl': {'requiredRevisionId':
                                 'r' + str(self.revision)}}

    def selected_tab(self, location):
        """Select a native tab ID without falling back after a missing ID."""
        tab_id = location.get('tabId', self.tabs[0]['id'])
        tab = next((tab for tab in self.tabs if tab['id'] == tab_id), None)
        if tab is None:
            reject('Tab was not found.')
        return tab

    def offset(self, chars, index):
        """Map a checked native index without splitting a UTF-16 surrogate."""
        cursor = 1
        for offset, char in enumerate(chars):
            if cursor == index:
                return offset
            cursor += utf16_length(char['char'])
        if cursor == index:
            return len(chars)
        return reject('Index does not match a UTF-16 character boundary.')

    def apply_request(self, request):
        """Handle only the predeclared native operations needed by fixtures."""
        name, payload = next(iter(request.items()))
        if name == 'addCommentReply':
            thread = next((thread for thread in self.comments
                           if thread['commentId'] == payload['commentId']),
                          None)
            if thread is None:
                reject('Comment does not exist.')
            post = {**deepcopy(payload['post']),
                    'postId': 'post-' + str(self.revision)
                    + '-' + str(len(thread['replies'])),
                    'author': {'displayName': 'Study author', 'me': True}}
            thread['replies'].append(post)
            if post.get('commentAction') in {'RESOLVE', 'REOPEN'}:
                thread['status'] = ('RESOLVED' if post['commentAction']
                                    == 'RESOLVE' else 'OPEN')
            return {'addCommentReply': {'post': post}}
        if name == 'deleteComment':
            thread = next((thread for thread in self.comments
                           if thread['commentId'] == payload['commentId']),
                          None)
            if thread is None:
                reject('Comment does not exist.')
            thread['headPost']['deleted'] = True
            return {}
        if name == 'insertText':
            tab = self.selected_tab(payload['location'])
            chars = tab['chars']
            start = self.offset(chars, payload['location']['index'])
            inherited = chars[min(start, len(chars) - 1)]
            chars[start:start] = [
                {**deepcopy(inherited), 'char': char}
                for char in payload['text']
            ]
            return {}
        if name in {'deleteContentRange', 'updateTextStyle',
                    'updateParagraphStyle', 'deleteParagraphBullets'}:
            tab = self.selected_tab(payload['range'])
            chars = tab['chars']
            start = self.offset(chars, payload['range']['startIndex'])
            end = self.offset(chars, payload['range']['endIndex'])
            if name == 'deleteContentRange':
                if end == len(chars):
                    reject('The mandatory final newline cannot be deleted.')
                del chars[start:end]
            elif name == 'updateTextStyle':
                for char in chars[start:end]:
                    self.update_style(char['textStyle'], payload['textStyle'],
                                      payload['fields'])
            elif name == 'updateParagraphStyle':
                par_start = 0
                for par_end, char in enumerate(chars):
                    if char['char'] == '\n':
                        if par_start < end and par_end + 1 > start:
                            for item in chars[par_start:par_end + 1]:
                                self.update_style(item['paragraphStyle'],
                                                  payload['paragraphStyle'],
                                                  payload['fields'])
                        par_start = par_end + 1
            return {}
        return reject('Native operation is outside the fixture API: ' + name)

    @staticmethod
    def update_style(style, value, fields):
        """Implement the top-level field masks exercised by these scenarios."""
        if fields == '*':
            style.clear()
            style.update(deepcopy(value))
            return
        for field in fields.split(','):
            if '.' in field:
                reject('Nested field masks are outside this fixture profile.')
            if field in value:
                style[field] = deepcopy(value[field])
            else:
                style.pop(field, None)
