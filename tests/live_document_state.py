"""Manage test-owned Google Docs and durable cleanup evidence."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from gdocs_scope_mcp.google_api import clients

DOC_MIME = 'application/vnd.google-apps.document'


class LiveDocuments:
    """Track confirmed creations before checking or placing their contents."""

    def __init__(self, folder, root, connect, *, keep_on_failure=False):
        self.folder = folder
        self.root = root
        self.connect = connect
        self.keep_on_failure = keep_on_failure
        self.documents = []
        self.attempts = []
        self.drive = clients.get_service('drive', 'v3', cached=False).files()
        metadata = self.drive.get(
            fileId=folder, fields='id,mimeType,trashed,capabilities',
            supportsAllDrives=True,
        ).execute()
        assert metadata['mimeType'] == 'application/vnd.google-apps.folder'
        assert not metadata.get('trashed', False)
        assert metadata['capabilities']['canAddChildren']

    def save(self):
        """Persist every confirmed document ID, including incomplete setup."""
        (self.root / 'report.json').write_text(json.dumps({
            'folder_id': self.folder, 'attempts': self.attempts,
            'documents': self.documents,
        }, indent=2))

    def create(self, *, initial_text='', via_mcp=False):
        """Create in the folder, or exercise MCP creation when requested."""
        if initial_text and not via_mcp:
            raise ValueError('Initial text requires via_mcp=True.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        title = f'gdocs-scope-mcp-live-{stamp}-{uuid.uuid4().hex}'
        self.attempts.append({'title': title, 'via_mcp': via_mcp})
        self.save()
        if not via_mcp:
            created = self.drive.create(body={
                'name': title, 'mimeType': DOC_MIME, 'parents': [self.folder],
            }, fields='id,name,mimeType,parents',
                supportsAllDrives=True).execute()
            record = {'id': created['id'], 'title': title,
                      'status': 'created'}
            self.documents.append(record)
            self.save()
            assert created['name'] == title
            assert created['mimeType'] == DOC_MIME
            assert created['parents'] == [self.folder]
            record['status'] = 'placed'
            self.save()
            return {'id': created['id'], 'title': title,
                    'webViewLink': 'https://docs.google.com/document/d/'
                    + created['id'] + '/edit'}

        async def run():
            log = self.root / f'create-{len(self.documents)}.stderr'
            async with self.connect(log) as (client, info):
                result = await client.call_tool('docs_create', {
                    'title': title, 'initial_text': initial_text,
                }, raise_on_error=False)
                data = result.structured_content or {}
                created = (data.get('created_document')
                           if result.is_error else data)
                if created:
                    record = {'id': created['id'], 'title': title,
                              'server': info, 'status': 'created'}
                    self.documents.append(record)
                    self.save()
                assert not result.is_error, data
                assert created['title'] == title
            record['process_reaped'] = True
            self.save()
            return created

        created = asyncio.run(run())
        doc_id = created['id']
        metadata = self.drive.get(
            fileId=doc_id, fields='parents', supportsAllDrives=True,
        ).execute()
        move = {'fileId': doc_id, 'addParents': self.folder,
                'fields': 'id,name,mimeType,parents',
                'supportsAllDrives': True}
        if metadata.get('parents'):
            move['removeParents'] = ','.join(metadata['parents'])
        placed = self.drive.update(**move).execute()
        assert placed['id'] == doc_id
        assert placed['name'] == title
        assert placed['mimeType'] == DOC_MIME
        assert placed['parents'] == [self.folder]
        self.documents[-1]['status'] = 'placed'
        self.save()
        return created

    def finish(self, *, failed):
        """Retain failures on request or verify trashing every owned ID."""
        errors = []
        for document in self.documents:
            try:
                if failed and self.keep_on_failure:
                    document['status'] = 'retained'
                    continue
                metadata = self.drive.get(
                    fileId=document['id'], fields='id,name,mimeType',
                    supportsAllDrives=True,
                ).execute()
                assert metadata == {
                    'id': document['id'], 'name': document['title'],
                    'mimeType': DOC_MIME,
                }
                self.drive.update(
                    fileId=document['id'], body={'trashed': True},
                    supportsAllDrives=True,
                ).execute()
                cleaned = self.drive.get(
                    fileId=document['id'], fields='trashed',
                    supportsAllDrives=True,
                ).execute()
                assert cleaned['trashed'] is True
                document['status'] = 'trashed'
            except Exception as error:
                document['status'] = 'cleanup_failed'
                errors.append(error)
            finally:
                self.save()
        self.drive.close()
        if errors:
            raise errors[0]
