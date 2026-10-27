"""
Edit Google Docs through text anchors and batch updates.

Edits Google Docs in-place using real batchUpdate requests, preserving
document history, comments, and suggestions. LLMs never touch indices.

Rich mode uses the shared Markdown converter for paragraphs and inline styles:
    # / ## / ### headings
    **bold**, *italic*, ***bold italic***

Native homogeneous lists and rectangular tables are supported.

Auth (in priority order):
    1. GOOGLE_DOCS_MCP_TOKEN env var  → path to standalone token JSON
    2. GOOGLE_DOCS_TOKEN_FILE env var → legacy gog-exported token JSON
    3. Default standalone path        → ~/.google-docs-mcp/token.json
    4. GOG_KEYRING_PASSWORD env var   → auto-export from gog
    5. Cached gog token               → /tmp/docs_edit_token_cache.json

Legacy GOOGLE_DRIVE_MCP_* env var aliases still work.

Python API:
    from gdocs_scope_mcp.docs_edit import read, search_replace, insert_after,
    insert_before,
                          delete_paragraph, append, batch_replace
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# isort: split
from .entities import collect_entities
from .entity_edit import INSERT_ENTITY_KINDS, validate_insertions
from .image_uploads import PreparedInsertion, rich_insertion_requests
from .md2requests import inserted_text_from_requests
from .models import (
    APPEND_PREVIEW_LIMIT,
    RECEIPT_ITEM_LIMIT,
    SHORT_PREVIEW_LIMIT,
    TEXT_PREVIEW_LIMIT,
    AppendSucceedResponse,
    DocumentOutline,
    DocumentParagraph,
    DocumentReadSection,
    DocumentSection,
    DocumentSubset,
    DocumentTree,
    EditFailedResponse,
    GoogleDocument,
    GoogleDocumentNamedStyleType,
    GoogleDocumentParagraph,
    GoogleDocumentSmartChip,
    GoogleDocumentTable,
    InsertSucceedResponse,
    ReplaceSucceedResponse,
)
from .table_insertion import TableInsertionPlan
from .text_indices import utf16_length
from .tool_errors import ToolFailureError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

# Standalone defaults (auth_setup.py output)
STANDALONE_TOKEN_PATHS = [
    Path.home() / '.google-docs-mcp' / 'token.json',
    Path.home() / '.google-drive-mcp' / 'token.json',
]
TOKEN_ENV_VAR = 'GOOGLE_DOCS_MCP_TOKEN'
TOKEN_ENV_ALIASES = (TOKEN_ENV_VAR, 'GOOGLE_DRIVE_MCP_TOKEN')
CLIENT_ID_ENV_VAR = 'GOOGLE_DOCS_MCP_CLIENT_ID'
CLIENT_SECRET_ENV_VAR = 'GOOGLE_DOCS_MCP_CLIENT_SECRET'
CLIENT_ID_ENV_ALIASES = (CLIENT_ID_ENV_VAR, 'GOOGLE_DRIVE_MCP_CLIENT_ID')
CLIENT_SECRET_ENV_ALIASES = (
    CLIENT_SECRET_ENV_VAR,
    'GOOGLE_DRIVE_MCP_CLIENT_SECRET',
)
APPS_SCRIPT_ID_ENV_VAR = 'GOOGLE_DOCS_MCP_APPS_SCRIPT_ID'
APPS_SCRIPT_ID_ENV_ALIASES = (
    APPS_SCRIPT_ID_ENV_VAR,
    'GOOGLE_DRIVE_MCP_APPS_SCRIPT_ID',
)
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCRIPT_API_BASE = 'https://script.googleapis.com/v1'

# Gog fallback paths (backward compat)
GOG_CREDENTIALS_PATH = Path('/config/gogcli/credentials.json')
GOG_TOKEN_CACHE = Path('/tmp/docs_edit_token_cache.json')


def _export_gog_token(email: str = 'david@harriethq.com') -> dict:
    """Export token from gog keyring using GOG_KEYRING_PASSWORD env var."""
    password = os.environ.get('GOG_KEYRING_PASSWORD')
    if not password:
        raise RuntimeError('GOG_KEYRING_PASSWORD not set')
    env = {**os.environ, 'GOG_KEYRING_PASSWORD': password}
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmp = f.name
    try:
        result = subprocess.run(
            [
                'gog',
                'auth',
                'tokens',
                'export',
                email,
                '--out',
                tmp,
                '--overwrite',
                '-y',
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f'gog token export failed: {result.stderr}')
        return json.loads(Path(tmp).read_text())
    finally:
        with suppress(OSError):
            Path(tmp).unlink()


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _load_token() -> dict:
    """
    Load token data. Priority:

      1. GOOGLE_DOCS_MCP_TOKEN env var   (standalone auth_setup.py output)
      2. GOOGLE_DRIVE_MCP_TOKEN env var  (backward-compatible alias)
      3. GOOGLE_DOCS_TOKEN_FILE env var  (legacy / gog compat)
      4. ~/.google-docs-mcp/token.json   (standalone default location)
      5. ~/.google-drive-mcp/token.json  (backward-compatible fallback)
      6. GOG_KEYRING_PASSWORD auto-export (gog compat)
      7. Cached gog token
    """
    # 1. Standalone env vars
    token_file = _first_env(*TOKEN_ENV_ALIASES)
    if token_file:
        return json.loads(Path(token_file).read_text())

    # 2. Legacy env var
    token_file = os.environ.get('GOOGLE_DOCS_TOKEN_FILE')
    if token_file:
        return json.loads(Path(token_file).read_text())

    # 3. Default standalone locations
    for token_path in STANDALONE_TOKEN_PATHS:
        if token_path.exists():
            return json.loads(token_path.read_text())

    # 4. Gog auto-export
    try:
        token = _export_gog_token()
        GOG_TOKEN_CACHE.write_text(json.dumps(token))
    except RuntimeError as e:
        log.warning('Gog auto-export failed: %s', e)
    else:
        return token

    # 5. Gog cache
    if GOG_TOKEN_CACHE.exists():
        log.info('Using cached gog token')
        return json.loads(GOG_TOKEN_CACHE.read_text())

    raise RuntimeError(
        'No Google credentials found.\n'
        'Run: gdocs-scope-mcp-auth --credentials ~/credentials.json\n'
        'Or set GOOGLE_DOCS_MCP_TOKEN to your token file path '
        '(legacy GOOGLE_DRIVE_MCP_TOKEN also works).'
    )


def _load_creds():
    """Return refreshed google.oauth2.credentials.Credentials."""
    token_data = _load_token()

    # Self-contained token — auth_setup.py embeds client_id / client_secret
    # directly
    # (also handle legacy _client_id / _client_secret with underscore prefix)
    client_id = token_data.get('client_id') or token_data.get('_client_id')
    client_secret = token_data.get('client_secret') or token_data.get(
        '_client_secret'
    )
    token_uri = token_data.get('token_uri') or token_data.get(
        '_token_uri', 'https://oauth2.googleapis.com/token'
    )

    # Environment override allows using external client credentials instead of
    # a credentials.json file.
    client_id = client_id or _first_env(*CLIENT_ID_ENV_ALIASES)
    client_secret = client_secret or _first_env(*CLIENT_SECRET_ENV_ALIASES)

    # Gog compat: read from separate credentials.json if not embedded
    if not client_id and GOG_CREDENTIALS_PATH.exists():
        gog_creds = json.loads(GOG_CREDENTIALS_PATH.read_text())
        client_id = gog_creds.get('client_id')
        client_secret = gog_creds.get('client_secret')

    if not client_id or not client_secret:
        raise RuntimeError(
            'No OAuth client credentials found. Re-run gdocs-scope-mcp-auth '
            'to generate a self-contained token, '
            f'or set {CLIENT_ID_ENV_VAR} and {CLIENT_SECRET_ENV_VAR} '
            '(legacy GOOGLE_DRIVE_MCP_* aliases also work).'
        )

    scopes = [
        s for s in token_data.get('scopes', []) if s not in ('email', 'openid')
    ]

    creds = Credentials(
        token=None,
        refresh_token=token_data['refresh_token'],
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds


def _get_service(api: str = 'docs', version: str = 'v1'):
    """Build a Google API service client."""
    return build(api, version, credentials=_load_creds())


SUGGESTIONS_VIEW_MODE = 'SUGGESTIONS_INLINE'


def _get_document(service, doc_id: str) -> dict:
    """
    Fetch a document with inline suggestions so returned indices stay usable

    for later batchUpdate calls.
    """
    return (
        service.documents()
        .get(
            documentId=doc_id,
            suggestionsViewMode=SUGGESTIONS_VIEW_MODE,
        )
        .execute()
    )


def _refresh_access_token_stdlib() -> str:
    """Refresh an OAuth access token without requiring googleapiclient."""
    token_data = _load_token()
    payload = urllib.parse.urlencode(
        {
            'client_id': token_data['client_id'],
            'client_secret': token_data['client_secret'],
            'refresh_token': token_data['refresh_token'],
            'grant_type': 'refresh_token',
        }
    ).encode('utf-8')
    req = urllib.request.Request(TOKEN_URL, data=payload, method='POST')
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))['access_token']


def _apps_script_api_request(
    access_token: str,
    method: str,
    path: str,
    body: dict | None = None,
) -> dict:
    req = urllib.request.Request(f'{SCRIPT_API_BASE}{path}', method=method)
    req.add_header('Authorization', f'Bearer {access_token}')
    req.add_header('Content-Type', 'application/json; charset=utf-8')
    if body is not None:
        req.data = json.dumps(body).encode('utf-8')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8')
        try:
            payload = json.loads(raw)
            message = payload.get('error', {}).get('message', raw)
        except json.JSONDecodeError:
            message = raw
        raise RuntimeError(
            f'Apps Script API request failed ({e.code}): {message}'
        ) from None


def _build_bookmark_bridge_files() -> list[dict]:
    code = r"""
function createBookmarkAtText(docId, anchorText, occurrence) {
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  var wanted = occurrence || 1;
  var found = null;

  for (var i = 0; i < wanted; i++) {
    found = body.findText(anchorText, found);
    if (!found) {
      throw new Error(
        'Anchor text not found for occurrence ' + wanted + ': ' + anchorText
      );
    }
  }

  var elem = found.getElement();
  var start = found.getStartOffset();
  var end = found.getEndOffsetInclusive();
  var pos = doc.newPosition(elem, start);
  var bookmark = doc.addBookmark(pos);
  return {
    bookmarkId: bookmark.getId(),
    matchText: elem.asText().getText().substring(start, end + 1)
  };
}
""".strip()

    manifest = {
        'timeZone': 'Europe/London',
        'exceptionLogging': 'STACKDRIVER',
        'runtimeVersion': 'V8',
        'oauthScopes': ['https://www.googleapis.com/auth/documents'],
        'executionApi': {'access': 'MYSELF'},
    }

    return [
        {'name': 'Code', 'type': 'SERVER_JS', 'source': code},
        {'name': 'appsscript', 'type': 'JSON', 'source': json.dumps(manifest)},
    ]


def _create_bookmark_via_apps_script(
    doc_id: str,
    anchor_text: str,
    occurrence: int = 1,
    *,
    script_id: str | None = None,
) -> dict:
    script_id = script_id or _first_env(*APPS_SCRIPT_ID_ENV_ALIASES)
    if not script_id:
        raise RuntimeError(
            'bookmark_jump requires a persistent Apps Script bridge. '
            f'Set {APPS_SCRIPT_ID_ENV_VAR} to the script project ID '
            '(legacy GOOGLE_DRIVE_MCP_APPS_SCRIPT_ID also works).'
        )

    access_token = _refresh_access_token_stdlib()
    _apps_script_api_request(
        access_token,
        'PUT',
        f'/projects/{script_id}/content',
        {'files': _build_bookmark_bridge_files()},
    )

    result = _apps_script_api_request(
        access_token,
        'POST',
        f'/scripts/{script_id}:run',
        {
            'function': 'createBookmarkAtText',
            'parameters': [doc_id, anchor_text, occurrence],
            'devMode': True,
        },
    )

    if 'error' in result:
        details = result.get('error', {}).get('details', [])
        detail = details[0] if details else {}
        message = (
            detail.get('errorMessage')
            or result.get('error', {}).get('message')
            or json.dumps(result['error'])
        )
        raise RuntimeError(f'Apps Script bookmark creation failed: {message}')

    payload = result.get('response', {}).get('result', {})
    bookmark_id = payload.get('bookmarkId')
    if not bookmark_id:
        raise RuntimeError(
            'Apps Script bookmark creation returned no bookmarkId'
        )

    return {
        'script_id': script_id,
        'bookmark_id': bookmark_id,
        'matched_text': payload.get('matchText', anchor_text),
    }


def _build_bookmark_jump_url(doc_id: str, bookmark_id: str) -> str:
    return f'https://docs.google.com/document/d/{doc_id}/edit#bookmark={bookmark_id}'


# ---------------------------------------------------------------------------
# Document structure helpers
# ---------------------------------------------------------------------------


@dataclass
class TextRun:
    """Store plain text and its inclusive/exclusive document indices."""

    text: str
    start: int  # Document index (inclusive)
    end: int  # Document index (exclusive)


@dataclass
class Paragraph:
    """Store source indices and plain text for an editable paragraph."""

    text: str
    style: str
    start: int  # Start of paragraph including leading newline-like element
    end: int  # End of paragraph (exclusive)
    runs: list[TextRun]


def _extract_paragraphs(doc: dict) -> list[Paragraph]:
    """Extract paragraphs with full structure from a Docs API response."""
    paragraphs = []
    for elem in doc.get('body', {}).get('content', []):
        if 'paragraph' not in elem:
            continue
        para = elem['paragraph']
        style = para.get('paragraphStyle', {}).get(
            'namedStyleType', 'NORMAL_TEXT'
        )
        runs = []
        full_text = ''
        for pe in para.get('elements', []):
            if 'textRun' in pe:
                content = pe['textRun']['content']
                runs.append(
                    TextRun(
                        text=content,
                        start=pe['startIndex'],
                        end=pe['endIndex'],
                    )
                )
                full_text += content
        # Strip trailing newline for display (Google Docs always ends
        # paragraphs with \n)
        display_text = full_text.rstrip('\n')
        paragraphs.append(
            Paragraph(
                text=display_text,
                style=style,
                start=elem['startIndex'],
                end=elem['endIndex'],
                runs=runs,
            )
        )
    return paragraphs


# def _paragraph_to_md(item: dict[str, ]):


def _paragraph_text_map(elements: list[dict]) -> list[tuple[int, int, str]]:
    """Keep original run positions while omitting non-text display elements."""
    text_map = []
    offset = 0
    for element in elements:
        if 'textRun' in element:
            text = element['textRun']['content']
            text_map.append((offset, element['startIndex'], text))
            offset += len(text)
    return text_map


def _table_source_paragraphs(table: dict) -> list[DocumentParagraph]:
    """Retain cell paragraphs and their terminal boundaries in source order."""
    paragraphs = []
    for row in table['tableRows']:
        for cell in row['tableCells']:
            for item in cell['content']:
                if 'paragraph' in item:
                    text_map = _paragraph_text_map(
                        item['paragraph']['elements'],
                    )
                    paragraphs.append(DocumentParagraph(
                        start_index=item['startIndex'],
                        end_index=item['endIndex'],
                        text=''.join(run[2] for run in text_map),
                        text_map=text_map,
                        markdown='',
                        table_cell_end_index=cell['endIndex'] - 1,
                    ))
                elif 'table' in item:
                    paragraphs.extend(_table_source_paragraphs(item['table']))
    return paragraphs


def _parse_document_tree(doc: dict) -> DocumentTree:
    """Extract document hierarchy from a Docs API response."""

    # Dummy section if there is text before headings
    last: DocumentSection = DocumentSection(
        title='',
        id='',
        level=GoogleDocumentNamedStyleType.NORMAL_TEXT.compact,
        paragraphs=[
            DocumentParagraph(start_index=0, end_index=0, text='', markdown='')
        ],
    )
    top_level: list[DocumentSection] = [last]

    # Model validators flatten API payloads in place; retain source text first.
    source_maps = [
        _paragraph_text_map(
            source.get('paragraph', {}).get('elements', []),
        )
        for source in doc['body']['content']
    ]
    table_paragraphs = {
        source['startIndex']: _table_source_paragraphs(source['table'])
        for source in doc['body']['content'] if 'table' in source
    }
    google_doc = GoogleDocument.model_validate(doc)

    headings = {}

    for text_map, elem in zip(
        source_maps, google_doc.body.content, strict=True,
    ):
        if not isinstance(elem, GoogleDocumentParagraph):
            # Display markup does not extend the preceding editable paragraph.
            last.paragraphs[-1].markdown += elem.to_markdown(google_doc)
            if isinstance(elem, GoogleDocumentTable):
                last.paragraphs.extend(table_paragraphs[elem.start_index])
            continue
        paragraph = DocumentParagraph(
            start_index=elem.start_index,
            end_index=elem.end_index,
            # Rendered paragraph separators are not editable source characters.
            text=''.join(run[2] for run in text_map),
            text_map=text_map,
            markdown=elem.to_markdown(google_doc),
        )
        if elem.paragraph_style.heading_id is None:
            last.paragraphs.append(paragraph)
            continue

        title = paragraph.text
        if any(isinstance(element, GoogleDocumentSmartChip)
               for element in elem.elements):
            title = ''.join(element.to_text(google_doc)
                            for element in elem.elements)
            if paragraph.text.endswith('\n'):
                title += '\n'
        section = DocumentSection(
            title=title,
            id=elem.paragraph_style.heading_id,
            level=elem.paragraph_style.named_style_type.compact,
            ancestor_ids=[],
            paragraphs=[paragraph],
            sections=[],
        )

        headings[section.id] = section

        # Nest under correct parent
        parent = last
        # Traverse up
        if parent.level_index > section.level_index:
            while parent and parent.level_index >= section.level_index:
                parent = parent.parent
        # The same level => use sibling parent
        elif parent.level_index == section.level_index:
            parent = parent.parent

        section.parent = parent
        if parent is not None:
            parent.sections.append(section)
            section.ancestor_ids = [*parent.ancestor_ids, parent.id]
        else:
            top_level.append(section)

        last = section
    # Remove dummy section if empty
    if not top_level[0].markdown:
        top_level = top_level[1:]
    return DocumentTree(
        sections=top_level,
        headings=headings,
        title=google_doc.title,
        revision_id=google_doc.revision_id,
        document_id=google_doc.document_id,
    )


def _build_full_text_map(
    paragraphs: list[Paragraph],
) -> tuple[str, list[tuple[int, int, str]]]:
    """
    Return (full_text, text_map) where:

    - full_text is all characters concatenated from all text runs
    - text_map retains (Python offset, API start index, original run text),
      allowing conversion to UTF-16 without losing source-run boundaries.
    """
    parts = []
    text_map = []
    offset = 0
    for para in paragraphs:
        for run in para.runs:
            text_map.append((offset, run.start, run.text))
            parts.append(run.text)
            offset += len(run.text)
    return ''.join(parts), text_map


def _full_text_pos_to_doc_index(
    pos: int, text_map: list[tuple[int, int, str]], *, end: bool = False,
) -> int:
    """Map Python offsets to UTF-16; range ends prefer the preceding run."""
    for ft_offset, doc_start, text in text_map:
        run_end = ft_offset + len(text)
        if ft_offset <= pos < run_end or (end and ft_offset < pos == run_end):
            return doc_start + utf16_length(text[:pos - ft_offset])
    if text_map:
        ft_offset, doc_start, text = text_map[-1]
        if pos == ft_offset + len(text):
            return doc_start + utf16_length(text)
    raise ValueError(
        f'Position {pos} is not within any text run in the document.'
    )


def _full_text_range_to_doc_indices(
    start: int, end: int, full_text: str,
    text_map: list[tuple[int, int, str]],
) -> tuple[int, int]:
    """Reject a text range spanning omitted document structure."""
    try:
        doc_start = _full_text_pos_to_doc_index(start, text_map)
        doc_end = _full_text_pos_to_doc_index(end, text_map, end=True)
    except ValueError:
        raise ToolFailureError(EditFailedResponse(
            code='INVALID_ARGUMENT',
            description='The match has no reliable text-run source range.',
            suggested_action='Target nonempty text within a source text run.',
        )) from None
    if doc_end - doc_start != utf16_length(full_text[start:end]):
        raise ToolFailureError(EditFailedResponse(
            code='INVALID_ARGUMENT',
            description='The match crosses non-contiguous document structure.',
            suggested_action=(
                'Target text within a single paragraph or contiguous body '
                'paragraphs; do not match across tables or non-text objects.'
            ),
        ))
    return doc_start, doc_end


def _normalize_anchor_excerpt(anchor_text: str, limit: int = 220) -> str:
    compact = re.sub(r'\s+', ' ', anchor_text.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + '…'


def _render_comment_with_anchor_text(comment: str, anchor_text: str) -> str:
    excerpt = _normalize_anchor_excerpt(anchor_text)
    if not excerpt:
        return comment
    if excerpt in comment:
        return comment
    return f'{comment}\n\nAnchored text: “{excerpt}”'


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def read(
    doc_id: str, heading_ids: list[str] | None = None,
) -> DocumentSubset | EditFailedResponse:
    """
    Read Google document or its parts including all nested headings.
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)

    google_doc = _parse_document_tree(doc)

    if heading_ids is None:
        roots = google_doc.sections
        selected = None
        unknown = []
    else:
        requested = set(heading_ids)
        resolved = requested.intersection(google_doc.headings)
        unknown = list(dict.fromkeys(
            item for item in heading_ids if item not in google_doc.headings
        ))
        if heading_ids and not resolved:
            return EditFailedResponse(
                code='HEADING_NOT_FOUND',
                description='None of the requested heading IDs were found.',
                suggested_action='Call docs_get_tree to refresh heading IDs, '
                'then retry with IDs from the current outline.',
            )
        roots = [
            item for item in google_doc.descendants()
            if item.id in resolved
            and not resolved.intersection(item.ancestor_ids)
        ]
        selected = [item.id for item in roots]

    return DocumentSubset(
        sections=[
            DocumentReadSection(
                heading_id=item.id or None, markdown=item.subtree_markdown(),
            ) for item in roots
        ],
        unknown_heading_ids=unknown,
        selected_headings=selected,
        partial=heading_ids is not None,
        title=google_doc.title,
        revision_id=google_doc.revision_id,
        document_id=google_doc.document_id,
    )


def get_tree(doc_id: str) -> DocumentOutline:
    """
    Fetch a Google Doc and return structured representation.
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)

    tree = _parse_document_tree(doc)
    flat_items = list(tree.descendants())

    return DocumentOutline(
        sections=flat_items,
        title=tree.title,
        revision_id=tree.revision_id,
        document_id=tree.document_id,
    )


def get_full_tree(doc_id: str) -> DocumentTree:
    """
    Fetch a Google Doc and return structured representation.
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)

    return _parse_document_tree(doc)


# Preserve the public positional calling convention.
def search_replace(  # noqa: PLR0911, PLR0917
    doc_id: str,
    find: str,
    replace: str,
    occurrence: int = 1,
    heading_id: str | None = None,
    regex: bool = False,
) -> ReplaceSucceedResponse | EditFailedResponse:
    """
    Find text in a document and replace a specific occurrence.

    Args:
        doc_id:     Google Doc ID
        find:       Text to find (or regex pattern if regex=True)
        replace:    Replacement text
        occurrence: Which occurrence to replace (1-based). 0 = replace all
                    only supported if regex=False and heading_id is None.
        heading_id: Scope search to this heading and all nested subheadings.
        regex:      Treat `find` as a regular expression

    Returns
    -------
        {"ok": True, "replaced": "old text", "at_index": 45,
        "occurrences_found": 3}
    """
    if occurrence == 0 and (regex or heading_id is not None):
        return EditFailedResponse(
            code='INVALID_ARGUMENT',
            description=(
                'Replace-all (occurrence=0) requires regex=False and '
                'heading_id=None.'
            ),
            suggested_action=(
                'Use a positive occurrence number for scoped or regex '
                'replacement, or set regex=False and omit heading_id '
                'to replace all literal matches across the whole document.'
            ),
        )

    service = _get_service('docs', 'v1')

    # Replace-all: use the native replaceAllText API (fast, atomic)
    if occurrence == 0 and not regex and heading_id is None:
        result = (
            service.documents()
            .batchUpdate(
                documentId=doc_id,
                body={
                    'requests': [
                        {
                            'replaceAllText': {
                                'containsText': {
                                    'text': find,
                                    'matchCase': True,
                                },
                                'replaceText': replace,
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        count = (
            result.get('replies', [{}])[0]
            .get('replaceAllText', {})
            .get('occurrencesChanged', 0)
        )
        return ReplaceSucceedResponse(
            document_id=doc_id, replaced=find, occurrences_changed=count,
            applied=count,
            replaced_char_count=len(find),
            preview_truncated=len(find) > SHORT_PREVIEW_LIMIT,
        )

    # Targeted occurrence: find index manually
    doc = _get_document(service, doc_id)
    tree = _parse_document_tree(doc)
    haystack = (
        tree if heading_id is None else tree.headings.get(heading_id, None)
    )
    if haystack is None:
        return EditFailedResponse(
            code='HEADING_NOT_FOUND',
            description=f"Heading with id '{heading_id}' was not "
            'found in the document',
            suggested_action=(
                'Run docs_get_tree to verify the exact heading id'
            ),
        )

    found = haystack.find_all(find, False, regex)
    if not found:
        where = 'document' if heading_id is None else 'requested heading'
        return EditFailedResponse(
            code='TEXT_NOT_FOUND',
            description=f"A paragraph containing '{find}' was not "
            f'found in the {where}',
            suggested_action=(
                'Run docs_read to verify the exact text to search for'
            ),
        )

    target_idx = occurrence - 1
    if target_idx >= len(found):
        where = 'Document' if heading_id is None else 'Requested heading'
        return EditFailedResponse(
            code='OCCURRENCE_NOT_FOUND',
            description=f'Occurrence {occurrence} not found. {where} has '
            f'{len(found)} occurrence(s) of {find!r}',
            suggested_action=(
                'Run docs_read to verify the exact occurrence number'
            ),
        )

    target = found[target_idx]

    try:
        doc_start, doc_end = _full_text_range_to_doc_indices(
            target.start_index, target.end_index,
            target.paragraph.text, target.paragraph.text_map,
        )
    except ToolFailureError as error:
        return error.failure

    old_text = target.paragraph.text[target.start_index : target.end_index]

    cell_end = target.paragraph.table_cell_end_index
    if cell_end is not None and doc_end > cell_end:
        return EditFailedResponse(
            code='INVALID_ARGUMENT',
            description=(
                'The table-cell match includes a protected cell boundary '
                'or text whose source positions cannot be mapped reliably.'
            ),
            suggested_action=(
                'Read the cell and target text within one paragraph, '
                'excluding its final cell newline and non-text elements.'
            ),
        )

    # Apply: delete old text, then insert replacement at same position
    requests = []
    if replace:
        requests.append(
            {
                'insertText': {
                    'location': {'index': doc_start},
                    'text': replace,
                }
            }
        )
        requests.append(
            {
                'deleteContentRange': {
                    'range': {
                        'startIndex': doc_start + utf16_length(replace),
                        'endIndex': doc_end + utf16_length(replace),
                    }
                }
            }
        )
    else:
        # Replacing with empty string = pure delete
        requests.append(
            {
                'deleteContentRange': {
                    'range': {'startIndex': doc_start, 'endIndex': doc_end}
                }
            }
        )

    service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests},
    ).execute()

    return ReplaceSucceedResponse(
        document_id=doc_id, heading_id=heading_id,
        scope='heading_subtree' if heading_id is not None else 'document',
        replaced=old_text, at_index=doc_start, occurrences_found=len(found),
        occurrences_found_complete=True,
        applied=1,
        replaced_char_count=len(old_text),
        preview_truncated=len(old_text) > SHORT_PREVIEW_LIMIT,
    )


def _insert_content(
    service, doc_id: str, text: str, index: int, *, rich: bool,
    newline_before: bool = True, upload_local_images: bool = False,
    required_revision: str | None = None,
    table_borders: bool = True,
) -> tuple[str, int, int, list[str]]:
    """Apply a validated insertion within the temporary-image lifecycle."""
    if rich:
        context = rich_insertion_requests(
            text, index, newline_before=newline_before,
            upload_local_images=upload_local_images,
            drive_factory=lambda: _get_service('drive', 'v3'),
            validate_requests=lambda requests: validate_insertions(
                service, doc_id, requests, required_revision,
            ),
        )
    else:
        literal = '\n' + text if newline_before else text + '\n'
        context = nullcontext(PreparedInsertion([{'insertText': {
            'location': {'index': index}, 'text': literal,
        }}]))
    with context as prepared:
        inserted = inserted_text_from_requests(prepared.requests)
        if isinstance(prepared.requests, TableInsertionPlan):
            prepared.requests.execute(
                service, doc_id, required_revision,
                table_borders=table_borders,
            )
            requests = list(prepared.requests.iter_requests())
        else:
            requests = prepared.requests
            body = {'requests': requests}
            if required_revision and any(
                INSERT_ENTITY_KINDS.intersection(r) or 'createNamedRange' in r
                for r in requests
            ):
                body['writeControl'] = {
                    'requiredRevisionId': required_revision,
                }
            service.documents().batchUpdate(
                documentId=doc_id, body=body,
            ).execute()
    return (inserted, sum('insertInlineImage' in r for r in requests),
            sum(bool(INSERT_ENTITY_KINDS.intersection(r)) for r in requests),
            prepared.cleanup_pending)


def insert_after(
    doc_id: str,
    anchor: str,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, upload_local_images: bool = False, table_borders: bool = True,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert Markdown paragraphs after the paragraph containing `anchor`.

    The inserted text becomes a separate paragraph (newline appended
    automatically).
    The search can be scoped to the specified heading (and nested subheadings).
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)
    tree = _parse_document_tree(doc)

    haystack = (
        tree if heading_id is None else tree.headings.get(heading_id, None)
    )
    if haystack is None:
        return EditFailedResponse(
            code='HEADING_NOT_FOUND',
            description=f"Heading with id '{heading_id}' was not "
            'found in the document',
            suggested_action=(
                'Run docs_get_tree to verify the exact heading id'
            ),
        )

    found = haystack.find_first(anchor, False)
    if found is None:
        where = 'document' if heading_id is None else 'requested heading'
        return EditFailedResponse(
            code='TEXT_NOT_FOUND',
            description=f"A paragraph containing anchor '{anchor}' was not "
            f'found in the {where}',
            suggested_action='Run docs_read to verify the exact anchor text',
        )

    # Split at the anchor's terminating newline, keeping it after the new text.
    # This also stays inside the valid insertion range at the document end.
    insert_index = found.paragraph.end_index - 1

    (
        inserted_text, image_count, entity_count, cleanup_pending,
    ) = _insert_content(
        service, doc_id, text, insert_index, rich=rich,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
    )

    return InsertSucceedResponse(
        document_id=doc_id, heading_id=heading_id,
        inserted_entity_count=entity_count,
        inserted_image_count=image_count,
        temporary_image_cleanup_pending=cleanup_pending,
        scope='heading_subtree' if heading_id is not None else 'document',
        inserted_char_count=len(inserted_text),
        preview_truncated=len(inserted_text) > TEXT_PREVIEW_LIMIT,
        anchor_char_count=len(found.paragraph.text),
        anchor_preview_truncated=(
            len(found.paragraph.text) > SHORT_PREVIEW_LIMIT
        ),
        anchor=found.paragraph.text,
        insert_position='after',
        at_index=insert_index,
        rich=rich,
        inserted_text=inserted_text,
    )


def insert_before(
    doc_id: str,
    anchor: str,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, upload_local_images: bool = False, table_borders: bool = True,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert Markdown paragraphs before the paragraph containing `anchor`.

    The inserted text becomes a separate paragraph (newline appended
    automatically).
    The search can be scoped to the specified heading (and nested subheadings).
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)
    tree = _parse_document_tree(doc)

    haystack = (
        tree if heading_id is None else tree.headings.get(heading_id, None)
    )
    if haystack is None:
        return EditFailedResponse(
            code='HEADING_NOT_FOUND',
            description=f"Heading with id '{heading_id}' was not "
            'found in the document',
            suggested_action=(
                'Run docs_get_tree to verify the exact heading id'
            ),
        )

    found = haystack.find_first(anchor, False)
    if found is None:
        where = 'document' if heading_id is None else 'requested heading'
        return EditFailedResponse(
            code='TEXT_NOT_FOUND',
            description=f"A paragraph containing anchor '{anchor}' was not "
            f'found in the {where}',
            suggested_action='Run docs_read to verify the exact anchor text',
        )

    # Insert at the start of the paragraph
    insert_index = found.paragraph.start_index

    (
        inserted_text, image_count, entity_count, cleanup_pending,
    ) = _insert_content(
        service, doc_id, text, insert_index, rich=rich, newline_before=False,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
    )

    return InsertSucceedResponse(
        document_id=doc_id, heading_id=heading_id,
        inserted_entity_count=entity_count,
        inserted_image_count=image_count,
        temporary_image_cleanup_pending=cleanup_pending,
        scope='heading_subtree' if heading_id is not None else 'document',
        inserted_char_count=len(inserted_text),
        preview_truncated=len(inserted_text) > TEXT_PREVIEW_LIMIT,
        anchor_char_count=len(found.paragraph.text),
        anchor_preview_truncated=(
            len(found.paragraph.text) > SHORT_PREVIEW_LIMIT
        ),
        anchor=found.paragraph.text,
        insert_position='before',
        at_index=insert_index,
        rich=rich,
        inserted_text=inserted_text,
    )


def delete_paragraph(doc_id: str, anchor: str) -> dict:
    """
    Delete the paragraph(s) containing `anchor` text.

    Deletes ALL paragraphs matching the anchor (case-insensitive substring).
    The mandatory final Body newline remains as an empty paragraph. Count
    paragraphs whose content was removed, including a cleared final paragraph;
    an already-empty final paragraph is not counted.
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)
    paragraphs = _extract_paragraphs(doc)

    targets = [p for p in paragraphs if anchor.lower() in p.text.lower()]
    if not targets:
        raise ToolFailureError(
            EditFailedResponse(
                code='TEXT_NOT_FOUND',
                description=f'No paragraph containing anchor: {anchor!r}',
                suggested_action='Run docs_read to verify the anchor text.',
            )
        )

    # Sort by start index descending so deleting earlier content doesn't shift
    # later indices
    targets.sort(key=lambda p: p.start, reverse=True)

    entities = collect_entities(doc)
    if any(target.start <= entity.start_index < target.end
           for target in targets for entity in entities):
        raise ToolFailureError(EditFailedResponse(
            code='INVALID_ARGUMENT',
            description='Paragraph deletion would remove a native smart chip.',
            suggested_action='Edit ordinary text around the chip. Native '
            'entity deletion is not supported by this tool.',
        ))

    terminal_newline = doc['body']['content'][-1]['endIndex'] - 1
    requests = []
    deleted = []
    deleted_char_counts = []
    deleted_preview_truncated = []
    for t in targets:
        end = min(t.end, terminal_newline)
        if t.start >= end:
            continue
        requests.append(
            {
                'deleteContentRange': {
                    'range': {
                        'startIndex': t.start,
                        'endIndex': end,
                    }
                }
            }
        )
        deleted.append(t.text[:SHORT_PREVIEW_LIMIT])
        deleted_char_counts.append(len(t.text))
        deleted_preview_truncated.append(len(t.text) > SHORT_PREVIEW_LIMIT)

    if requests:
        service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests},
        ).execute()

    return {
        'ok': True,
        'document_id': doc_id,
        'deleted_count': len(deleted),
        'deleted': deleted[:RECEIPT_ITEM_LIMIT],
        'deleted_char_counts': deleted_char_counts[:RECEIPT_ITEM_LIMIT],
        'deleted_preview_truncated': (
            deleted_preview_truncated[:RECEIPT_ITEM_LIMIT]
        ),
        'deleted_truncated': len(deleted) > RECEIPT_ITEM_LIMIT,
    }


def append(
    doc_id: str, text: str, rich: bool = True, *,
    upload_local_images: bool = False,
    table_borders: bool = True,
) -> AppendSucceedResponse:
    """
    Append Markdown or literal text and return a compact typed receipt.
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)

    # Find the last content index (end of the body, before the body's closing)
    body_content = doc.get('body', {}).get('content', [])
    if not body_content:
        raise ToolFailureError(
            EditFailedResponse(
                code='EMPTY_DOCUMENT',
                description='Document body is empty.',
                suggested_action='Run docs_read to inspect the document body.',
            )
        )

    # The last element's endIndex is the body end (exclusive).
    # We insert just before that.
    last_elem = body_content[-1]
    insert_index = last_elem['endIndex'] - 1

    (
        inserted_text, image_count, entity_count, cleanup_pending,
    ) = _insert_content(
        service, doc_id, text, insert_index, rich=rich,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
    )

    return AppendSucceedResponse(
        document_id=doc_id,
        inserted_entity_count=entity_count,
        inserted_image_count=image_count,
        temporary_image_cleanup_pending=cleanup_pending,
        rich=rich,
        at_index=insert_index,
        appended=inserted_text[:APPEND_PREVIEW_LIMIT],
        inserted_char_count=len(inserted_text),
        preview_truncated=len(inserted_text) > APPEND_PREVIEW_LIMIT,
    )


def batch_replace(doc_id: str, replacements: list[dict]) -> dict:
    """
    Apply multiple find→replace operations atomically (all or nothing).

    Replacements are sorted by position (end→start) automatically, so earlier
    indices remain valid throughout the batch.

    Args:
        doc_id:       Google Doc ID
        replacements: List of {"find": "...", "replace": "...", "occurrence":
        1}
                      `occurrence` defaults to 1. Use 0 for replace-all.

    Returns
    -------
        {"ok": True, "applied": N, "changes": [...]}
    """
    service = _get_service('docs', 'v1')
    doc = _get_document(service, doc_id)
    paragraphs = _extract_paragraphs(doc)
    full_text, text_map = _build_full_text_map(paragraphs)

    # Collect all changes with their document indices
    changes = []  # (doc_start, doc_end, replace_text, find_text)
    for rep in replacements:
        find = rep['find']
        replace_text = rep.get('replace', '')
        occurrence = rep.get('occurrence', 1)
        is_regex = rep.get('regex', False)

        # Build list of (ft_start, ft_end) tuples
        if is_regex:
            matches = [
                (m.start(), m.end()) for m in re.finditer(find, full_text)
            ]
        else:
            matches = []
            search_from = 0
            while True:
                pos = full_text.find(find, search_from)
                if pos == -1:
                    break
                matches.append((pos, pos + len(find)))
                search_from = pos + 1

        if not matches:
            raise ToolFailureError(
                EditFailedResponse(
                    code='TEXT_NOT_FOUND',
                    description=f'Text not found: {find!r}',
                    suggested_action='Run docs_read to verify search text.',
                )
            )

        if occurrence == 0:
            # Replace all
            for ft_start, ft_end in matches:
                ds, de = _full_text_range_to_doc_indices(
                    ft_start, ft_end, full_text, text_map,
                )
                changes.append(
                    (ds, de, replace_text, full_text[ft_start:ft_end])
                )
        else:
            idx = occurrence - 1
            if idx >= len(matches):
                raise ToolFailureError(
                    EditFailedResponse(
                        code='OCCURRENCE_NOT_FOUND',
                        description=(
                            f'Occurrence {occurrence} not found for {find!r}'
                        ),
                        suggested_action=(
                            'Run docs_read to verify the occurrence number.'
                        ),
                    )
                )
            ft_start, ft_end = matches[idx]
            ds, de = _full_text_range_to_doc_indices(
                ft_start, ft_end, full_text, text_map,
            )
            changes.append((ds, de, replace_text, full_text[ft_start:ft_end]))

    # Sort by doc_start DESCENDING (apply end-of-doc first so indices stay
    # valid)
    changes.sort(key=lambda c: c[0], reverse=True)

    # Build batchUpdate requests
    requests = []
    for ds, de, replace_text, _old_text in changes:
        if replace_text:
            requests.append(
                {
                    'insertText': {
                        'location': {'index': ds},
                        'text': replace_text,
                    }
                }
            )
            requests.append(
                {
                    'deleteContentRange': {
                        'range': {
                            'startIndex': ds + utf16_length(replace_text),
                            'endIndex': de + utf16_length(replace_text),
                        }
                    }
                }
            )
        else:
            requests.append(
                {
                    'deleteContentRange': {
                        'range': {'startIndex': ds, 'endIndex': de}
                    }
                }
            )

    service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests},
    ).execute()

    return {
        'ok': True,
        'document_id': doc_id,
        'applied': len(changes),
        'changes_truncated': len(changes) > RECEIPT_ITEM_LIMIT,
        'changes': [
            {
                'replaced': old[:SHORT_PREVIEW_LIMIT],
                'with': new[:TEXT_PREVIEW_LIMIT], 'at_index': ds,
                'replaced_char_count': len(old),
                'replacement_char_count': len(new),
                'preview_truncated': len(old) > SHORT_PREVIEW_LIMIT,
                'replacement_preview_truncated': len(new) > TEXT_PREVIEW_LIMIT,
            }
            for (ds, de, new, old) in sorted(
                changes, key=lambda c: c[0]
            )[:RECEIPT_ITEM_LIMIT]
        ],
    }


# Preserve the public positional calling convention.
def add_comment(  # noqa: PLR0917
    doc_id: str,
    comment: str,
    anchor_text: str,
    occurrence: int = 1,
    include_anchor_text: bool = True,
    bookmark_jump: bool = False,
    apps_script_id: str | None = None,
) -> dict:
    """
    Add a comment anchored to specific text in a Google Doc.

    Current implementation detail: this creates a Docs named range and then
    posts a Drive comment anchored to that named range.

    Important limitation: despite the named range, Google Docs still renders
    these API-created comments as "Original content deleted" in the UI rather
    than as a proper inline highlight. This function is kept for API-level
    comment access, but a real Apps Script automation path is being
    investigated
    for true inline Docs comments.

    Steps:
      1. Find anchor_text in the document → get character indices
      2. CreateNamedRangeRequest via batchUpdate → get named_range_id
      3. Drive API comments.create with anchor JSON → attached comment

    Args:
        doc_id:      Google Doc ID
        comment:     Comment text to post
        anchor_text: Text in the document to attach the comment to
        occurrence:  Which occurrence to anchor to (default 1 = first)

    Returns
    -------
        {"ok": True, "comment_id": "...", "anchored_to": "...", "at_index": N,
         "named_range_id": "..."}
    """
    docs_service = _get_service('docs', 'v1')
    doc = _get_document(docs_service, doc_id)
    paragraphs = _extract_paragraphs(doc)
    full_text, text_map = _build_full_text_map(paragraphs)

    # Find all occurrences of anchor_text
    matches = []
    search_from = 0
    while True:
        pos = full_text.find(anchor_text, search_from)
        if pos == -1:
            break
        matches.append((pos, pos + len(anchor_text)))
        search_from = pos + 1

    if not matches:
        raise ToolFailureError(
            EditFailedResponse(
                code='TEXT_NOT_FOUND',
                description=(
                    f'Anchor text not found in document: {anchor_text!r}'
                ),
                suggested_action='Run docs_read to verify the anchor text.',
            )
        )

    target_idx = occurrence - 1
    if target_idx >= len(matches):
        raise ToolFailureError(
            EditFailedResponse(
                code='OCCURRENCE_NOT_FOUND',
                description=(
                    f'Occurrence {occurrence} not found — document has '
                    f'{len(matches)} occurrence(s) of {anchor_text!r}'
                ),
                suggested_action='Run docs_read to verify occurrence number.',
            )
        )

    ft_start, ft_end = matches[target_idx]
    doc_start, doc_end = _full_text_range_to_doc_indices(
        ft_start, ft_end, full_text, text_map,
    )

    # Create a named range at the anchor position
    range_name = f'comment-anchor-{uuid.uuid4().hex[:12]}'
    result = (
        docs_service.documents()
        .batchUpdate(
            documentId=doc_id,
            body={
                'requests': [
                    {
                        'createNamedRange': {
                            'name': range_name,
                            'range': {
                                'startIndex': doc_start,
                                'endIndex': doc_end,
                                'segmentId': '',  # empty = main document body
                            },
                        }
                    }
                ]
            },
        )
        .execute()
    )

    named_range_id = (
        result.get('replies', [{}])[0]
        .get('createNamedRange', {})
        .get('namedRangeId')
    )
    if not named_range_id:
        raise RuntimeError(
            'Failed to create named range — no ID returned by Docs API'
        )

    # The correct anchor format for Google Docs is the bare named range ID
    # (e.g. "kix.abc123") as a plain string — NOT a JSON object.
    # quotedFileContent provides the fallback display text.
    drive = build('drive', 'v3', credentials=_load_creds())
    bookmark = None
    if bookmark_jump:
        bookmark = _create_bookmark_via_apps_script(
            doc_id,
            full_text[ft_start:ft_end],
            occurrence=occurrence,
            script_id=apps_script_id,
        )

    rendered_comment = (
        _render_comment_with_anchor_text(comment, full_text[ft_start:ft_end])
        if include_anchor_text
        else comment
    )
    if bookmark is not None:
        jump_url = _build_bookmark_jump_url(doc_id, bookmark['bookmark_id'])
        rendered_comment = f'{rendered_comment}\n\nJump: {jump_url}'
    comment_result = (
        drive.comments()
        .create(
            fileId=doc_id,
            body={
                'content': rendered_comment,
                'anchor': named_range_id,
                'quotedFileContent': {
                    'mimeType': 'text/html',
                    'value': full_text[ft_start:ft_end],
                },
            },
            fields='id,content,anchor',
        )
        .execute()
    )

    return {
        'ok': True,
        'document_id': doc_id,
        'comment_id': comment_result.get('id'),
        'anchored_to': full_text[ft_start:ft_end],
        'at_index': doc_start,
        'named_range_id': named_range_id,
        'comment_content': rendered_comment,
        'bookmark_id': bookmark['bookmark_id']
        if bookmark is not None
        else None,
        'bookmark_url': (
            _build_bookmark_jump_url(doc_id, bookmark['bookmark_id'])
            if bookmark is not None
            else None
        ),
        'apps_script_id': bookmark['script_id']
        if bookmark is not None
        else None,
    }
