"""Opt-in live check of a temporary Drive image through isolated STDIO MCP."""

import asyncio
import io
import json
import os
import urllib.request
import uuid
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from gdocs_scope_mcp import docs_edit
from gdocs_scope_mcp.diagnostics import capture_server_info

EXPECTED_HTML_POINTS = 24


@pytest.fixture
def isolated_mcp():
    """Provide a shared-session STDIO client tied to this checkout's source."""
    @asynccontextmanager
    async def connect(log):
        repo = Path(__file__).resolve().parents[1]
        transport = StdioTransport(
            command=str(repo / '.venv/bin/gdocs-scope-mcp'), args=[],
            cwd=str(repo), env=dict(os.environ), log_file=log,
            keep_alive=False,
        )
        async with Client(transport) as client:
            identity = await client.call_tool('server_info', {})
            info = identity.structured_content
            assert info['source_fingerprint'] == (
                capture_server_info().source_fingerprint
            )
            assert info['package_path'] == str(repo / 'src/gdocs_scope_mcp')
            yield client, info
        assert not Path(f'/proc/{info["pid"]}').exists()

    return connect


def test_temporary_drive_url_survives_source_deletion(
    live_test_doc, image_png, isolated_mcp,
):
    """Upload/share a source, insert through MCP, then delete and read back."""
    evidence = Path('/tmp/gdocs-scope-mcp-drive-probe.json')
    log = Path('/tmp/gdocs-scope-mcp-drive-probe.log')
    report = {'attempts': []}
    drive = docs_edit._get_service('drive', 'v3')
    docs = docs_edit._get_service('docs', 'v1')
    file_id = None
    permission_id = None
    marker = 'DRIVE_IMAGE_PROBE_' + uuid.uuid4().hex

    async def run():
        nonlocal file_id, permission_id
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            created = drive.files().create(
                body={'name': f'gdocs-scope-mcp-tmp-{uuid.uuid4().hex}.png'},
                media_body=MediaIoBaseUpload(io.BytesIO(image_png),
                                            mimetype='image/png'),
                fields='id,name,webContentLink,resourceKey,parents',
            ).execute()
            file_id = created['id']
            report['temporary_file'] = created
            permission = drive.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader',
                      'allowFileDiscovery': False},
                fields='id,type,role,allowFileDiscovery',
            ).execute()
            permission_id = permission['id']
            report['permission'] = permission
            created = drive.files().get(
                fileId=file_id, fields='id,webContentLink,resourceKey',
            ).execute()
            candidates = [created.get('webContentLink'),
                          f'https://drive.google.com/uc?export=download&id={file_id}']
            candidates = list(dict.fromkeys(uri for uri in candidates if uri))
            for uri in candidates:
                result = await client.call_tool('docs_append', {
                    'doc_id': live_test_doc,
                    'text': f'{marker} before ![probe]({uri}) after',
                }, raise_on_error=False)
                report['attempts'].append({
                    'uri': uri, 'is_error': result.is_error,
                    'result': result.structured_content,
                })
                if not result.is_error:
                    break
            assert not result.is_error, report['attempts']
            assert result.structured_content['inserted_image_count'] == 1

            drive.files().delete(fileId=file_id).execute()
            report['deleted'] = file_id
            with pytest.raises(HttpError) as missing:
                drive.files().get(fileId=file_id, fields='id').execute()
            assert missing.value.resp.status == HTTPStatus.NOT_FOUND
            file_id = None
            native = docs.documents().get(documentId=live_test_doc).execute()
            paragraph = next(
                p['paragraph'] for p in native['body']['content']
                if any(marker in e.get('textRun', {}).get('content', '')
                       for e in p.get('paragraph', {}).get('elements', []))
            )
            image = next(e['inlineObjectElement']['inlineObjectId']
                         for e in paragraph['elements']
                         if 'inlineObjectElement' in e)
            embedded = native['inlineObjects'][image][
                'inlineObjectProperties']['embeddedObject']
            report['embedded_image'] = {'id': image, 'properties': embedded}
            content_uri = embedded['imageProperties']['contentUri']
            with urllib.request.urlopen(content_uri, timeout=30) as response:
                assert response.headers['Content-Type'].startswith('image/')
                assert response.read()
            report['copy_accessible_after_source_deletion'] = True
            readback = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            assert not readback.is_error
            assert marker in json.dumps(readback.structured_content)
            report['mcp_readback_ok'] = True

    try:
        asyncio.run(run())
    finally:
        if file_id is not None:
            try:
                drive.files().delete(fileId=file_id).execute()
                report['deleted'] = file_id
            except Exception:
                if permission_id is not None:
                    drive.permissions().delete(
                        fileId=file_id, permissionId=permission_id,
                    ).execute()
                raise
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert not Path(f'/proc/{report["server_info"]["pid"]}').exists()


def test_local_image_uploads_through_all_tools(
    live_test_doc, image_png, isolated_mcp, tmp_path,
):
    """Exercise opt-in uploads, native readback and automatic deletion."""
    path = tmp_path / 'local image 🦷.png'
    path.write_bytes(image_png)
    drive = docs_edit._get_service('drive', 'v3')
    docs = docs_edit._get_service('docs', 'v1')
    evidence = Path('/tmp/gdocs-scope-mcp-local-images.json')
    log = Path('/tmp/gdocs-scope-mcp-local-images.log')
    report = {'operations': []}
    prefix = 'LOCAL_DRIVE_IMAGE_' + uuid.uuid4().hex

    async def run():
        async with isolated_mcp(log) as (client, info):
            report['server_info'] = info
            for operation in ('append', 'insert_before', 'insert_after'):
                marker = prefix + '_' + operation
                markup = (f'{marker} 😀 **Before🦷** '
                          f'![MD]({path.as_uri()}) *After🦷* '
                          f'<img src="{path}" width="32"> tail')
                arguments = {
                    'doc_id': live_test_doc, 'upload_local_images': True,
                    'text': markup,
                }
                if operation != 'append':
                    arguments['anchor'] = prefix + '_append'
                result = await client.call_tool('docs_' + operation, arguments)
                assert not result.is_error
                receipt = result.structured_content
                assert receipt['inserted_image_count'] == len(['MD', 'HTML'])
                assert receipt['temporary_image_cleanup_pending'] == []
                report['operations'].append({
                    'operation': operation, 'marker': marker,
                    'receipt': receipt,
                })
            native = docs.documents().get(documentId=live_test_doc).execute()
            temporary_ids = set()
            for item in report['operations']:
                paragraph = next(
                    p['paragraph'] for p in native['body']['content']
                    if any(item['marker'] in e.get('textRun', {}).get(
                        'content', '')
                           for e in p.get('paragraph', {}).get('elements', []))
                )
                elements = paragraph['elements']
                rendered = ''.join(
                    e.get('textRun', {}).get('content', '\ufffc')
                    for e in elements
                )
                assert rendered == (
                    item['marker'] + ' 😀 Before🦷 '
                    '\ufffc After🦷 \ufffc tail\n'
                )
                for style, expected in [('bold', 'Before🦷'),
                                        ('italic', 'After🦷')]:
                    styled = ''.join(
                        e['textRun']['content'] for e in elements
                        if e.get('textRun', {}).get('textStyle', {}).get(style)
                    )
                    assert styled == expected
                images = [e['inlineObjectElement']['inlineObjectId']
                          for e in elements if 'inlineObjectElement' in e]
                assert len(images) == len(['MD', 'HTML'])
                item['objects'] = images
                for object_id in images:
                    embedded = native['inlineObjects'][object_id][
                        'inlineObjectProperties']['embeddedObject']
                    properties = embedded['imageProperties']
                    query = parse_qs(urlsplit(properties['sourceUri']).query)
                    temporary_ids.add(query['id'][0])
                    with urllib.request.urlopen(
                        properties['contentUri'], timeout=30,
                    ) as response:
                        assert response.headers['Content-Type'].startswith(
                            'image/',
                        )
                        assert response.read()
                box = native['inlineObjects'][images[-1]][
                    'inlineObjectProperties']['embeddedObject']['size']
                assert box['width']['magnitude'] == EXPECTED_HTML_POINTS
                assert box['height']['magnitude'] == EXPECTED_HTML_POINTS
            for file_id in temporary_ids:
                with pytest.raises(HttpError) as missing:
                    drive.files().get(fileId=file_id, fields='id').execute()
                assert missing.value.resp.status == HTTPStatus.NOT_FOUND
            assert len(temporary_ids) == len(report['operations'])
            report['deleted_temporary_files'] = sorted(temporary_ids)
            report['native_readback_ok'] = True
            result = await client.call_tool('docs_read', {
                'doc_id': live_test_doc,
            })
            assert not result.is_error
            assert prefix in json.dumps(result.structured_content)
    try:
        asyncio.run(run())
    finally:
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2))
