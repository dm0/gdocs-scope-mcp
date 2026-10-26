"""Check local image staging, preflight and cleanup at the MCP boundary."""

import asyncio
from unittest.mock import MagicMock

import httplib2
import pytest
from fastmcp import Client
from googleapiclient.errors import HttpError

from gdocs_scope_mcp import docs_edit, image_uploads, server

URL = 'https://drive.google.com/uc?id=temporary&export=download'
IMAGE_COUNT = 2


def api_error(status):
    """Build a predictable Google API failure without leaking response data."""
    return HttpError(httplib2.Response({'status': str(status)}), b'{}')


def call(operation, markup, **kwargs):
    """Call an insertion tool through MCP with fake Google APIs."""
    args = {'doc_id': 'example', 'text': markup, **kwargs}
    if operation != 'append':
        args['anchor'] = 'Introduction'

    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool('docs_' + operation, args,
                                          raise_on_error=False)

    return asyncio.run(run())


@pytest.fixture
def local_image(tmp_path, image_png):
    """Provide a real image with a path that requires file-URL escaping."""
    path = tmp_path / 'image with spaces 🦷.png'
    path.write_bytes(image_png)
    return path


@pytest.fixture
def services(mock_docs, monkeypatch):
    """Track ordered Docs/Drive API calls, preserving the document fixture."""
    drive = MagicMock()
    drive.files().create.return_value.execute.side_effect = [
        {'id': 'temporary'}, {'id': 'temporary2'},
    ]
    drive.permissions().create.return_value.execute.return_value = {
        'id': 'anyoneWithLink',
    }
    drive.files().get.return_value.execute.return_value = {
        'webContentLink': URL,
    }
    docs = MagicMock()
    docs.documents.return_value = mock_docs
    factory = MagicMock(side_effect=lambda api, _version: (
        drive if api == 'drive' else docs
    ))
    monkeypatch.setattr(docs_edit, '_get_service', factory)
    return mock_docs, drive, factory


@pytest.mark.parametrize(
    'operation', ['append', 'insert_before', 'insert_after'],
)
@pytest.mark.parametrize('html', [False, True])
@pytest.mark.parametrize('file_uri', [False, True])
def test_local_images_use_temporary_shared_sources(
    services, local_image, operation, html, file_uri,
):
    """Support both syntaxes and source forms, reusing repeated local files."""
    docs, drive, _factory = services
    source = local_image.as_uri() if file_uri else str(local_image)
    markup = (f'<img src="{source}" width="32">' if html
              else f'![x](<{source}>)')
    result = call(operation, f'😀 **Before** {markup} *After* {markup}',
                  upload_local_images=True)
    assert not result.is_error
    receipt = result.structured_content
    assert receipt['inserted_image_count'] == IMAGE_COUNT
    assert receipt['temporary_image_cleanup_pending'] == []
    drive.files().create.assert_called_once()
    create = drive.files().create.call_args.kwargs
    assert create['body']['name'].startswith('gdocs-scope-mcp-tmp-')
    assert create['body']['name'].endswith('.png')
    assert 'parents' not in create['body']
    assert 'image with spaces' not in create['body']['name']
    assert create['media_body'].mimetype() == 'image/png'
    drive.permissions().create.assert_called_once_with(
        fileId='temporary',
        body={'type': 'anyone', 'role': 'reader', 'allowFileDiscovery': False},
        fields='id',
    )
    requests = docs.batchUpdate.call_args.kwargs['body']['requests']
    images = [r['insertInlineImage'] for r in requests
              if 'insertInlineImage' in r]
    assert len(images) == IMAGE_COUNT
    assert all(image['uri'] == URL for image in images)
    drive.files().delete.assert_called_once_with(fileId='temporary')


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('rich', [False, True])
def test_local_upload_is_explicit_and_literal_mode_never_uploads(
    services, local_image, enabled, rich,
):
    """Do not share files implicitly, including when rich mode is disabled."""
    docs, drive, _factory = services
    result = call('append', f'![x]({local_image.as_uri()})',
                  rich=rich, upload_local_images=enabled)
    if enabled and rich:
        assert not result.is_error
        drive.files().create.assert_called_once()
    else:
        drive.files().create.assert_not_called()
        if rich:
            assert result.is_error
            docs.batchUpdate.assert_not_called()
        else:
            assert not result.is_error
            assert result.structured_content['inserted_image_count'] == 0


@pytest.mark.parametrize('bad_markup', [
    '<img src="file:///does-not-exist.png">',
    '<img src="file://remote-server/tmp/image.png">',
    '<img src="file:relative.png">',
    '<img src="data:image/png;base64,AA">',
    '<img src="relative.png">',
    '3. Unsupported custom list start',
    '<span data-mcp-entity="person">Missing email</span>',
    '<span data-mcp-entity="dropdown" '
    'data-mcp-definition-id="foreign">Missing definition</span>',
])
def test_whole_edit_is_validated_before_uploads(
    services, local_image, bad_markup,
):
    """A valid first image must not be shared if later content is invalid."""
    docs, drive, _factory = services
    result = call('append', f'![valid](<{local_image}>)\n\n{bad_markup}',
                  upload_local_images=True)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    drive.files().create.assert_not_called()
    docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('failure', ['share', 'metadata', 'batch', 'upload2'])
def test_uploads_are_removed_after_failed_operations(
    services, local_image, image_png, failure,
):
    """Clean up after sharing, link lookup, upload and document failures."""
    docs, drive, _factory = services
    second = local_image.with_name('second.png')
    second.write_bytes(image_png)
    if failure == 'share':
        drive.permissions().create.return_value.execute.side_effect = (
            api_error(403)
        )
    elif failure == 'metadata':
        drive.files().get.return_value.execute.return_value = {}
    elif failure == 'batch':
        docs.batchUpdate.return_value.execute.side_effect = api_error(400)
    else:
        drive.files().create.return_value.execute.side_effect = [
            {'id': 'temporary'}, api_error(503),
        ]
    result = call('append', f'![one](<{local_image}>) ![two](<{second}>)',
                  upload_local_images=True)
    assert result.is_error
    deleted = [c.kwargs['fileId'] for c in drive.files().delete.call_args_list]
    assert deleted == (['temporary', 'temporary2'] if failure == 'batch'
                       else ['temporary'])
    if failure != 'batch':
        docs.batchUpdate.assert_not_called()


def test_successful_write_is_not_reported_as_failed_when_cleanup_fails(
    services, local_image,
):
    """Keep success and expose the file requiring manual cleanup."""
    docs, drive, _factory = services
    drive.files().delete.return_value.execute.side_effect = api_error(503)
    result = call('append', f'![x](<{local_image}>)', upload_local_images=True)
    assert not result.is_error
    assert result.structured_content['temporary_image_cleanup_pending'] == [
        'temporary',
    ]
    docs.batchUpdate.assert_called_once()
    drive.permissions().delete.assert_called_once_with(
        fileId='temporary', permissionId='anyoneWithLink',
    )


def test_failed_cleanup_does_not_hide_original_document_failure(
    services, local_image, caplog,
):
    """Retain the primary API failure and log the residual public file ID."""
    docs, drive, _factory = services
    docs.batchUpdate.return_value.execute.side_effect = api_error(400)
    drive.files().delete.return_value.execute.side_effect = api_error(503)
    drive.permissions().delete.return_value.execute.side_effect = (
        api_error(503)
    )
    result = call('append', f'![x](<{local_image}>)', upload_local_images=True)
    assert result.is_error
    assert result.structured_content['code'] == 'INVALID_ARGUMENT'
    assert 'file_id=temporary' in caplog.text
    docs.batchUpdate.assert_called_once()


def test_remote_images_with_opt_in_do_not_create_drive_files(services):
    """No uploads are needed for edits already using public image URLs."""
    docs, drive, factory = services
    result = call('append', '![x](https://example.com/image.png)',
                  upload_local_images=True)
    assert not result.is_error
    assert factory.call_args_list[0].args == ('docs', 'v1')
    factory.assert_called_once()
    drive.files().create.assert_not_called()
    docs.batchUpdate.assert_called_once()


def test_local_size_limit_is_checked_before_drive_changes(
    services, local_image, monkeypatch,
):
    """Apply the bounded local upload limit before allocating a public file."""
    monkeypatch.setattr(image_uploads, 'MAX_LOCAL_IMAGE_BYTES', 8)
    docs, drive, _factory = services
    result = call('append', f'![x](<{local_image}>)', upload_local_images=True)
    assert result.is_error
    drive.files().create.assert_not_called()
    docs.batchUpdate.assert_not_called()


@pytest.mark.parametrize('content', [b'', b'not an image'])
def test_local_format_is_validated_before_upload(
    services, local_image, content,
):
    """A filename extension alone is not accepted as image format evidence."""
    docs, drive, _factory = services
    local_image.write_bytes(content)
    result = call('append', f'![x]({local_image.as_uri()})',
                  upload_local_images=True)
    assert result.is_error
    drive.files().create.assert_not_called()
    docs.batchUpdate.assert_not_called()


def test_bad_local_image_dimensions_fail_before_upload(services, local_image):
    """Local sources must pass the existing HTML attribute validation too."""
    docs, drive, _factory = services
    result = call('append', f'<img src="{local_image}" width="50%">',
                  upload_local_images=True)
    assert result.is_error
    drive.files().create.assert_not_called()
    docs.batchUpdate.assert_not_called()


def test_already_deleted_upload_is_not_reported_as_pending(
    services, local_image,
):
    """Treat a cleanup 404 as absence, without changing a successful write."""
    _docs, drive, _factory = services
    drive.files().delete.return_value.execute.side_effect = api_error(404)
    result = call('append', f'![x]({local_image.as_uri()})',
                  upload_local_images=True)
    assert not result.is_error
    assert result.structured_content['temporary_image_cleanup_pending'] == []
    drive.permissions().delete.assert_not_called()


def test_uncertain_permission_creation_revokes_discovered_public_access(
    services, local_image,
):
    """A lost share response must not prevent revoking public access."""
    docs, drive, _factory = services
    drive.permissions().create.return_value.execute.side_effect = (
        api_error(503)
    )
    drive.files().delete.return_value.execute.side_effect = api_error(503)
    drive.permissions().list.return_value.execute.return_value = {
        'permissions': [{'id': 'public', 'type': 'anyone'},
                        {'id': 'owner', 'type': 'user'}],
    }
    result = call('append', f'![x]({local_image.as_uri()})',
                  upload_local_images=True)
    assert result.is_error
    drive.permissions().delete.assert_called_once_with(
        fileId='temporary', permissionId='public',
    )
    docs.batchUpdate.assert_not_called()
