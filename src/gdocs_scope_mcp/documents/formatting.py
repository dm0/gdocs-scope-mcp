"""Apply bounded color changes to anchored native text and paragraphs."""

import re
from typing import Literal

from pydantic import Field

from gdocs_scope_mcp.colors import native_color, validate_setting
from gdocs_scope_mcp.contracts import DocumentEditReceipt, EditFailedResponse
from gdocs_scope_mcp.documents import fetching, parsing, targeting
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.revision_guards import depend_on, guarded_edit, submit


class FormatResponse(DocumentEditReceipt):
    """Describe one atomic formatting change without exposing coordinates."""

    ok: Literal[True] = True
    applied: int = 1
    occurrences_found: int
    updated_properties: list[str] = Field(default_factory=list)


def format_failure(code: str, description: str) -> None:
    """Raise a shared structured failure with anchor recovery advice."""
    raise ToolFailureError(EditFailedResponse(
        code=code, description=description,
        suggested_action='Read the selected tab/heading, choose a unique '
        'text anchor or explicit positive occurrence, and provide at least '
        'one Google palette name, #RRGGBB or reset.',
    ))


@guarded_edit
def format_colors(
    doc_id: str, anchor_text: str, *, paragraph: bool = False,
    foreground_color: str | None = None,
    background_color: str | None = None,
    occurrence: int | None = None, heading_id: str | None = None,
    tab_id: str | None = None,
    expected_revision_id: str | None = None,  # noqa: ARG001 - decorator
) -> FormatResponse:
    """Update requested native properties under existing revision guards."""
    values = {'foregroundColor': foreground_color,
              'backgroundColor': background_color}
    values = {key: value for key, value in values.items() if value is not None}
    if (not anchor_text or not values or '\n' in anchor_text
            or (occurrence is not None and occurrence < 1)
            or (paragraph and foreground_color is not None)):
        format_failure('INVALID_ARGUMENT', 'Invalid formatting settings.')
    try:
        for value in values.values():
            validate_setting(value)
    except ValueError:
        format_failure('INVALID_ARGUMENT', 'Unknown or malformed color.')
    service = clients.get_service('docs', 'v1')
    document = fetching.get_document(service, doc_id, tab_id=tab_id)
    tree = parsing.parse_document_tree(document)
    scope = tree if heading_id is None else tree.headings.get(heading_id)
    if scope is None:
        format_failure('HEADING_NOT_FOUND', 'The heading is missing.')
    matches = scope.find_all(re.escape(anchor_text), False, True)
    matches.sort(key=lambda item: (
        item.paragraph.start_index, item.start_index,
    ))
    if not matches:
        format_failure('TEXT_NOT_FOUND', 'No ordinary text match was found.')
    if occurrence is None and len(matches) != 1:
        format_failure('TARGET_AMBIGUOUS', 'The anchor has multiple matches.')
    selected = (occurrence or 1) - 1
    if selected >= len(matches):
        format_failure('OCCURRENCE_NOT_FOUND', 'No such occurrence exists.')
    match = matches[selected]
    start, end = targeting.full_text_range_to_doc_indices(
        match.start_index, match.end_index,
        match.paragraph.text, match.paragraph.text_map,
    )
    if paragraph:
        start, end = match.paragraph.start_index, match.paragraph.end_index
        style = {'shading': {}} if background_color == 'reset' else {
            'shading': {'backgroundColor': native_color(background_color)},
        }
        operation = 'updateParagraphStyle'
        key, fields = 'paragraphStyle', 'shading.backgroundColor'
    else:
        style = {key: native_color(value) for key, value in values.items()
                 if value != 'reset'}
        operation = 'updateTextStyle'
        key, fields = 'textStyle', ','.join(values)
    depend_on(document, start, end)
    submit(service, doc_id, [{operation: {
        'range': {'startIndex': start, 'endIndex': end},
        key: style, 'fields': fields,
    }}])
    return FormatResponse(
        document_id=doc_id, heading_id=heading_id,
        scope='heading_subtree' if heading_id else 'document',
        occurrences_found=len(matches), updated_properties=fields.split(','),
    )
