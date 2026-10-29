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

import logging
import re

from gdocs_scope_mcp.documents import fetching, parsing, targeting
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.rich_text.insertion import insert_content

# isort: split
from gdocs_scope_mcp.contracts import (
    APPEND_PREVIEW_LIMIT,
    RECEIPT_ITEM_LIMIT,
    SHORT_PREVIEW_LIMIT,
    TEXT_PREVIEW_LIMIT,
    EditFailedResponse,
)
from gdocs_scope_mcp.documents.receipts import (
    AppendSucceedResponse,
    InsertSucceedResponse,
    ReplaceSucceedResponse,
)
from gdocs_scope_mcp.entities import collect_entities
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.revision_guards import (
    depend_on,
    guarded_edit,
    require_native_precondition,
    submit,
)
from gdocs_scope_mcp.text_indices import utf16_length

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

SUGGESTIONS_VIEW_MODE = 'SUGGESTIONS_INLINE'


# ---------------------------------------------------------------------------
# Document structure helpers
# ---------------------------------------------------------------------------


# def _paragraph_to_md(item: dict[str, ]):


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


# Preserve the public positional calling convention.
@guarded_edit
def search_replace(  # noqa: PLR0911, PLR0917
    doc_id: str,
    find: str,
    replace: str,
    occurrence: int = 1,
    heading_id: str | None = None,
    regex: bool = False,
    *, tab_id: str | None = None,
    expected_revision_id: str | None = None,  # noqa: ARG001 - decorator
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

    service = clients.get_service('docs', 'v1')

    # Replace-all: use the native replaceAllText API (fast, atomic)
    if occurrence == 0 and not regex and heading_id is None:
        require_native_precondition()
        fetching.get_document(service, doc_id, tab_id=tab_id)
        result = submit(service, doc_id, [{
            'replaceAllText': {
                'containsText': {'text': find, 'matchCase': True},
                'replaceText': replace,
            },
        }], native=True)
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
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)
    tree = parsing.parse_document_tree(doc)
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
        doc_start, doc_end = targeting.full_text_range_to_doc_indices(
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

    depend_on(doc, doc_start, doc_end)
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

    submit(service, doc_id, requests)

    return ReplaceSucceedResponse(
        document_id=doc_id, heading_id=heading_id,
        scope='heading_subtree' if heading_id is not None else 'document',
        replaced=old_text, at_index=doc_start, occurrences_found=len(found),
        occurrences_found_complete=True,
        applied=1,
        replaced_char_count=len(old_text),
        preview_truncated=len(old_text) > SHORT_PREVIEW_LIMIT,
    )


@guarded_edit
def insert_after(
    doc_id: str,
    anchor: str,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, upload_local_images: bool = False, table_borders: bool = True,
    expected_revision_id: str | None = None,  # noqa: ARG001 - decorator
    tab_id: str | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert Markdown paragraphs after the paragraph containing `anchor`.

    The inserted text becomes a separate paragraph (newline appended
    automatically).
    The search can be scoped to the specified heading (and nested subheadings).
    """
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)
    tree = parsing.parse_document_tree(doc)

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
    depend_on(doc, found.paragraph.start_index, found.paragraph.end_index)

    (
        inserted_text, image_count, entity_count, cleanup_pending,
    ) = insert_content(
        service, doc_id, text, insert_index, rich=rich,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
        tab_id=doc.get('_mcp_tab_id'),
        document=doc,
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


@guarded_edit
def insert_before(
    doc_id: str,
    anchor: str,
    text: str,
    heading_id: str | None = None,
    rich: bool = True,
    *, upload_local_images: bool = False, table_borders: bool = True,
    expected_revision_id: str | None = None,  # noqa: ARG001 - decorator
    tab_id: str | None = None,
) -> InsertSucceedResponse | EditFailedResponse:
    """
    Insert Markdown paragraphs before the paragraph containing `anchor`.

    The inserted text becomes a separate paragraph (newline appended
    automatically).
    The search can be scoped to the specified heading (and nested subheadings).
    """
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)
    tree = parsing.parse_document_tree(doc)

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
    depend_on(doc, found.paragraph.start_index, found.paragraph.end_index)

    (
        inserted_text, image_count, entity_count, cleanup_pending,
    ) = insert_content(
        service, doc_id, text, insert_index, rich=rich, newline_before=False,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
        tab_id=doc.get('_mcp_tab_id'),
        document=doc,
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


@guarded_edit
def delete_paragraph(doc_id: str, anchor: str, *,
                     tab_id: str | None = None,
                     expected_revision_id: str | None = None,  # noqa: ARG001
                     ) -> dict:
    """
    Delete the paragraph(s) containing `anchor` text.

    Deletes ALL paragraphs matching the anchor (case-insensitive substring).
    The mandatory final Body newline remains as an empty paragraph. Count
    paragraphs whose content was removed, including a cleared final paragraph;
    an already-empty final paragraph is not counted.
    """
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)
    paragraphs = parsing.extract_paragraphs(doc)

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
        depend_on(doc, t.start, t.end)
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
        submit(service, doc_id, requests)

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


@guarded_edit(append=True)
def append(
    doc_id: str, text: str, rich: bool = True, *,
    upload_local_images: bool = False,
    table_borders: bool = True,
    tab_id: str | None = None,
    expected_revision_id: str | None = None,  # noqa: ARG001 - decorator
) -> AppendSucceedResponse:
    """
    Append Markdown or literal text and return a compact typed receipt.
    """
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)

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
    ) = insert_content(
        service, doc_id, text, insert_index, rich=rich,
        upload_local_images=upload_local_images,
        required_revision=doc.get('revisionId'),
        table_borders=table_borders,
        tab_id=doc.get('_mcp_tab_id'),
        document=doc,
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


@guarded_edit
def batch_replace(doc_id: str, replacements: list[dict], *,
                  tab_id: str | None = None,
                  expected_revision_id: str | None = None,  # noqa: ARG001
                  ) -> dict:
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
    service = clients.get_service('docs', 'v1')
    doc = fetching.get_document(service, doc_id, tab_id=tab_id)
    paragraphs = parsing.extract_paragraphs(doc)
    full_text, text_map = targeting.build_full_text_map(paragraphs)

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
                ds, de = targeting.full_text_range_to_doc_indices(
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
            ds, de = targeting.full_text_range_to_doc_indices(
                ft_start, ft_end, full_text, text_map,
            )
            changes.append((ds, de, replace_text, full_text[ft_start:ft_end]))

    # Sort by doc_start DESCENDING (apply end-of-doc first so indices stay
    # valid)
    changes.sort(key=lambda c: c[0], reverse=True)
    for start, end, _, _ in changes:
        depend_on(doc, start, end)

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

    submit(service, doc_id, requests)

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
