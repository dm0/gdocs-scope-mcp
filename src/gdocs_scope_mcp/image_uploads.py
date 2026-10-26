"""Stage opt-in local images in temporary, link-shared Drive files."""

import io
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .md2requests import (
    _image_failure,
    gpars_to_requests,
    html_to_gpars,
    markdown_to_html,
    markdown_to_requests,
)
from .table_insertion import TableInsertionPlan

logger = logging.getLogger('gdocs_scope_mcp')
MAX_LOCAL_IMAGE_BYTES = 50_000_000


@dataclass
class PreparedInsertion:
    """Keep planned requests and report uploads left behind after cleanup."""

    requests: list[dict] | TableInsertionPlan
    cleanup_pending: list[str] = field(default_factory=list)


def _local_image(uri: str) -> tuple[Path, bytes, str] | None:
    """Load an absolute local PNG/JPEG/GIF once, before any Drive changes."""
    if uri.startswith('/'):
        # Mistune percent-encodes spaces/non-ASCII in Markdown destinations.
        path = Path(unquote(uri))
    elif uri.lower().startswith('file:'):
        try:
            parsed = urlsplit(uri)
        except ValueError:
            _image_failure('Local image file URL is invalid.')
        if (parsed.netloc not in {'', 'localhost'} or parsed.query
                or parsed.fragment):
            _image_failure('Local file URLs must have no remote host, query '
                           'or fragment.')
        path = Path(unquote(parsed.path))
    else:
        return None
    if not path.is_absolute():
        _image_failure('Local images require an absolute server-side path.')
    try:
        path = path.resolve(strict=True)
        if not path.is_file():
            _image_failure('Local image path must refer to a regular file.')
        with path.open('rb') as stream:
            content = stream.read(MAX_LOCAL_IMAGE_BYTES)
    except OSError:
        _image_failure('Local image file could not be read by the MCP server.')
    if not content or len(content) >= MAX_LOCAL_IMAGE_BYTES:
        _image_failure('Local images must be nonempty and smaller than 50 MB.')
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif content.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif content.startswith((b'GIF87a', b'GIF89a')):
        mime = 'image/gif'
    else:
        _image_failure('Local image must contain PNG, JPEG or GIF data.')
    return path, content, mime


def _remove_upload(drive, file_id: str, permission_id: str | None) -> bool:
    """Permanently delete a source, revoking link access if deletion fails."""
    try:
        drive.files().delete(fileId=file_id).execute()
    except HttpError as error:
        if error.resp.status == HTTPStatus.NOT_FOUND:
            return True
    except Exception:  # noqa: BLE001 - cleanup must not mask the write outcome
        pass
    else:
        return True
    try:
        if permission_id is None:
            permissions = drive.permissions().list(
                fileId=file_id, fields='permissions(id,type)',
            ).execute().get('permissions', [])
            ids = [p['id'] for p in permissions if p['type'] == 'anyone']
        else:
            ids = [permission_id]
        for permission in ids:
            drive.permissions().delete(
                fileId=file_id, permissionId=permission,
            ).execute()
    except Exception:  # noqa: BLE001 - report cleanup failure without retrying edits
        logger.error('Temporary image cleanup and access revocation failed '
                     'file_id=%s; remove this file manually', file_id)
    else:
        logger.warning('Temporary image deletion failed; link access revoked '
                       'file_id=%s; remove this file manually', file_id)
    return False


@contextmanager
def rich_insertion_requests(
    text: str, start: int, *, newline_before: bool = True,
    upload_local_images: bool = False, drive_factory: Callable,
) -> Iterator[PreparedInsertion]:
    """Validate the edit, stage local images, and always attempt cleanup."""
    if not upload_local_images:
        yield PreparedInsertion(markdown_to_requests(
            text, start, newline_before=newline_before,
        ))
        return
    soup = BeautifulSoup(markdown_to_html(text), 'html.parser')
    sources = {}
    for image in soup.find_all('img'):
        uri = str(image.get('src', ''))
        local = _local_image(uri)
        if local is None:
            continue
        path, content, mime = local
        if path not in sources:
            placeholder = 'https://gdocs-scope-mcp.invalid/' + uuid.uuid4().hex
            sources[path] = (placeholder, content, mime)
        image['src'] = sources[path][0]
    # Unsupported lists, other image sources, and bad dimensions must fail
    # before even one upload or public permission is created.
    planned = PreparedInsertion(gpars_to_requests(
        html_to_gpars(str(soup), start), newline_before=newline_before,
    ))
    if not sources:
        yield planned
        return
    drive = drive_factory()
    uploads = {}
    try:
        for placeholder, content, mime in sources.values():
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg',
                      'image/gif': '.gif'}[mime]
            created = drive.files().create(
                body={
                    'name': 'gdocs-scope-mcp-tmp-' + uuid.uuid4().hex + suffix,
                    'appProperties': {'gdocs-scope-mcp': 'temporary-image'},
                },
                media_body=MediaIoBaseUpload(
                    io.BytesIO(content), mimetype=mime,
                ),
                fields='id',
            ).execute()
            file_id = created['id']
            uploads[file_id] = None
            permission = drive.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader',
                      'allowFileDiscovery': False}, fields='id',
            ).execute()
            uploads[file_id] = permission['id']
            metadata = drive.files().get(
                fileId=file_id, fields='webContentLink',
            ).execute()
            link = metadata.get('webContentLink')
            if not link:
                _image_failure('Drive did not return a temporary image '
                               'download link; the document was not changed.')
            if isinstance(planned.requests, TableInsertionPlan):
                planned.requests.replace_image_uri(placeholder, link)
                continue
            for request in planned.requests:
                image = request.get('insertInlineImage')
                if image and image['uri'] == placeholder:
                    image['uri'] = link
        yield planned
    finally:
        for file_id, permission_id in uploads.items():
            if not _remove_upload(drive, file_id, permission_id):
                planned.cleanup_pending.append(file_id)
