"""Replace Markdown cells with selective snapshots and strict atomic writes."""

# Reuse the service boundary and rich converter without import cycles.
# ruff: noqa: PLC0415

import logging
import re
import time
from typing import Annotated, Literal

from bs4 import BeautifulSoup, Comment
from pydantic import BaseModel, ConfigDict, Field

from .code_reading import NATIVE_CODE_BOUNDARY
from .models import EditFailedResponse
from .revision_guards import MAX_ATTEMPTS, RevisionRaceError, submit
from .table_insertion import convert_table, shifted_requests
from .table_snapshots import (
    resolve_cells,
    validate_baseline,
    validate_states,
)
from .table_tokens import CellAddress, decode, fail
from .text_indices import utf16_length
from .tool_errors import ToolFailureError

log = logging.getLogger(__name__)
MAX_MARKDOWN = 100000
MAX_REQUESTS = 1000
# Docs strips these characters from insertText; reject them before calculating
# ranges, including characters produced by HTML numeric entity decoding.
STRIPPED_TEXT = re.compile(r'[\x00-\x08\x0c-\x1f\ue000-\uf8ff]')


class CellPatch(BaseModel):
    """Replace the full text/inline formatting at one A1 address."""

    model_config = ConfigDict(strict=True, extra='forbid')
    address: CellAddress
    markdown: Annotated[str, Field(strict=True, max_length=MAX_MARKDOWN)]


CellPatches = Annotated[
    list[CellPatch], Field(strict=True, min_length=1, max_length=100),
]


class PatchedCell(BaseModel):
    """Bound previews while retaining complete native character counts."""

    address: str
    text_preview: str
    text_char_count: int
    preview_truncated: bool
    inserted_utf16_count: int
    deleted_utf16_count: int


class PatchResponse(BaseModel):
    """Confirm one atomic patch or an all-empty no-op without a second read."""

    ok: Literal[True] = True
    document_id: str
    table_ref: str
    revision_id: str | None
    applied_count: int
    attempts: int
    committed_batches: Literal[0, 1]
    cells: list[PatchedCell]


def compile_cell(markdown):
    """Validate inline Markdown and reuse the table-cell converter."""
    from .md2requests import markdown_to_html
    if any(ord(c) < 32 and c not in '\t\r\n\v' for c in markdown):  # noqa: PLR2004
        fail('INVALID_ARGUMENT', 'Unsupported control character in cell text.')
    if any(0xd800 <= ord(c) <= 0xdfff for c in markdown):  # noqa: PLR2004
        fail('INVALID_ARGUMENT', 'Cell Markdown contains invalid Unicode.')
    soup = BeautifulSoup(markdown_to_html(markdown), 'html.parser')
    paragraphs = soup.find_all('p')
    if len(paragraphs) > 1 or any(p.attrs or p.parent is not soup
                                  for p in paragraphs):
        fail('INVALID_ARGUMENT', 'Use inline text and br for soft breaks.')
    if paragraphs and any(node is not paragraphs[0] and str(node).strip()
                          for node in soup.contents):
        fail('INVALID_ARGUMENT', 'Use only one paragraph of inline content.')
    for paragraph in paragraphs:
        paragraph.unwrap()
    allowed = {'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code', 'a',
               'sup', 'sub', 'br'}
    for node in soup.descendants:
        if isinstance(node, Comment):
            fail('INVALID_ARGUMENT', 'HTML comments are unsupported in cells.')
        if getattr(node, 'name', None) is None:
            continue
        attributes = {'href', 'title'} if node.name == 'a' else set()
        if node.name not in allowed or set(node.attrs) - attributes:
            fail('INVALID_ARGUMENT', 'Cell patches support inline formatting '
                 'and br only; objects, entities and block content are '
                 'unsupported.')
    # Mistune's terminal HTML newline is not part of the cell's text.
    fragment = soup.decode_contents().removesuffix('\n')
    table = BeautifulSoup('<table><tr><td>' + fragment + '</td></tr></table>',
                          'html.parser').table
    planned = convert_table(table, 0).cells[0][0]
    if STRIPPED_TEXT.search(planned.text):
        fail('INVALID_ARGUMENT', 'Cell text contains characters Google would '
             'strip, making planned style ranges unsafe.')
    # Cell paragraph properties survive; only text and inline styles change.
    planned.requests = [r for r in planned.requests
                        if 'updateParagraphStyle' not in r]
    if any(not set(r) <= {'insertText', 'updateTextStyle'}
           for r in planned.requests):
        fail('INVALID_ARGUMENT', 'Unsupported request in cell Markdown.')
    return planned


def _plain_cell(cell):
    """Require one native text paragraph with its mandatory final newline."""
    content = cell.get('content', [])
    if len(content) != 1 or 'paragraph' not in content[0]:
        fail('INVALID_ARGUMENT', 'Cell patches require one text paragraph.')
    paragraph = content[0]['paragraph']

    def suggested(value):
        """Reject suggestions whose native indices have extra meaning."""
        if isinstance(value, dict):
            return any((k.startswith('suggested') and v) or suggested(v)
                       for k, v in value.items())
        return isinstance(value, list) and any(suggested(v) for v in value)

    elements = paragraph.get('elements', [])
    if (paragraph.get('bullet') or suggested(cell) or not elements
            or any('textRun' not in e for e in elements)
            or paragraph.get('codeBlock') or
            paragraph.get('paragraphStyle', {}).get('codeBlock')):
        fail('INVALID_ARGUMENT', 'Lists, native code blocks, suggestions and '
             'non-text entities are unsupported patch targets.')
    text = ''.join(e['textRun'].get('content', '') for e in elements)
    if NATIVE_CODE_BOUNDARY in text:
        fail('INVALID_ARGUMENT', 'Native code delimiters are unsupported.')
    start, end = content[0]['startIndex'], content[0]['endIndex']
    if (not text.endswith('\n') or '\n' in text[:-1]
            or utf16_length(text) != end - start):
        fail('TARGET_CHANGED', 'Cell range is not one verified paragraph.')
    return start, end - 1


def plan_requests(document, available, compiled):
    """Plan cells from last to first so all ranges use the same fresh read."""
    entries = [(selected, *_plain_cell(value[2]))
               for selected, value in available.items()]
    requests, receipts = [], {}
    for selected, start, end in sorted(entries, key=lambda e: e[1],
                                        reverse=True):
        planned = compiled[selected]
        if end > start:
            requests.append({'deleteContentRange': {'range': {
                'startIndex': start, 'endIndex': end,
            }}})
        length = utf16_length(planned.text)
        converted = shifted_requests(planned.requests, start)
        insertions = [r for r in converted if 'insertText' in r]
        styles = [r for r in converted if 'updateTextStyle' in r]
        requests.extend(insertions)
        if length:
            # Plain Markdown must clear inherited links/emphasis/code styles.
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': start + length},
                'textStyle': {}, 'fields': '*',
            }})
            requests.extend(styles)
        receipts[selected] = PatchedCell(
            address=selected,
            text_preview=planned.text[:200].replace('\v', '\n'),
            text_char_count=len(planned.text),
            preview_truncated=len(planned.text) > 200,  # noqa: PLR2004
            inserted_utf16_count=length, deleted_utf16_count=end - start,
        )
    if len(requests) > MAX_REQUESTS:
        fail('INVALID_ARGUMENT', 'The patch exceeds 1000 native requests.')
    if document.get('_mcp_tab_id'):
        for request in requests:
            operation = next(iter(request.values()))
            operation.get('range', operation.get('location'))['tabId'] = (
                document['_mcp_tab_id']
            )
    return requests, receipts


def patch(doc_id, table_ref, base_token, changes):
    """Revalidate the original expected state after each confirmed CAS race."""
    from . import docs_edit
    from .table_read import _fetch
    table = decode(table_ref, 'table', doc_id)
    baseline = decode(base_token, 'base', doc_id)
    cells = [change.address for change in changes]
    if len(set(cells)) != len(cells):
        fail('INVALID_ARGUMENT', 'Duplicate patch addresses are not allowed.')
    validate_baseline(table, baseline, cells, baseline.fields, subset=True)
    if not {'content', 'text_style'} <= set(baseline.fields):
        fail('INVALID_ARGUMENT', 'Markdown patches require content and '
             'text_style snapshot expectations. Read a default snapshot.')
    if sum(len(c.markdown) for c in changes) > MAX_MARKDOWN:
        fail('INVALID_ARGUMENT', 'Patch Markdown exceeds 100000 characters.')
    compiled = {c.address: compile_cell(c.markdown) for c in changes}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        validate_baseline(table, baseline, cells, baseline.fields, subset=True)
        document = _fetch(doc_id)
        available = resolve_cells(document, table, cells)
        validate_states(document, baseline, available)
        requests, receipts = plan_requests(document, available, compiled)
        try:
            result = submit(docs_edit._get_service(), doc_id, requests,
                            document['revisionId'], force_required=True
                            ) if requests else {}
        except RevisionRaceError:
            if attempt == MAX_ATTEMPTS:
                break
            log.info('edit=docs_table_patch status=revision_retry attempt=%s',
                     attempt)
            time.sleep(0.05 * (2 ** (attempt - 1)))
            continue
        return PatchResponse(
            document_id=doc_id, table_ref=table_ref,
            revision_id=result.get('writeControl', {}).get(
                'requiredRevisionId', document['revisionId'],
            ), applied_count=len(changes), attempts=attempt,
            committed_batches=int(bool(requests)),
            cells=[receipts[selected] for selected in cells],
        )
    raise ToolFailureError(EditFailedResponse(
        code='REVISION_RETRY_EXHAUSTED',
        description='The patch lost three strict revision races; '
        'none of its batches committed.',
        suggested_action='Retry later with the same snapshot if it is still '
        'valid. Reread selected cells if it conflicts.',
    ))
