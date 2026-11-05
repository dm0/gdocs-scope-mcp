"""Internal documents.targeting operations."""


from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents import parsing
from gdocs_scope_mcp.documents.styles import HEADING_ORDER
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.text_indices import utf16_length


def heading_insertion_point(document, heading_id, position):
    """Return a native body boundary and whether it needs a leading break."""
    content = document.get('body', {}).get('content', [])
    matches = [i for i, item in enumerate(content)
               if item.get('paragraph', {}).get('paragraphStyle', {}).get(
                   'headingId') == heading_id]
    if len(matches) != 1:
        raise ToolFailureError(EditFailedResponse(
            code='TARGET_AMBIGUOUS' if matches else 'HEADING_NOT_FOUND',
            description='The heading ID does not resolve to one body heading '
            'in the selected tab.',
            suggested_action='Run docs_get_tree for the selected tab and '
            'use an existing heading ID.',
        ))
    offset = matches[0]
    heading = content[offset]
    style = heading['paragraph']['paragraphStyle']['namedStyleType']
    if style not in HEADING_ORDER:
        raise ToolFailureError(EditFailedResponse(
            code='INVALID_ARGUMENT',
            description='Target has no heading level.',
            suggested_action='Choose a heading from docs_get_tree.',
        ))
    if position == 'before_subtree':
        return heading['startIndex'], False
    for item in content[offset + 1:]:
        level = item.get('paragraph', {}).get('paragraphStyle', {}).get(
            'namedStyleType')
        if level in HEADING_ORDER and HEADING_ORDER[level] <= (
            HEADING_ORDER[style]
        ):
            return item['startIndex'], False
    return content[-1]['endIndex'] - 1, True


def build_full_text_map(
    paragraphs: list[parsing.Paragraph],
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


def full_text_pos_to_doc_index(
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


def full_text_range_to_doc_indices(
    start: int, end: int, full_text: str,
    text_map: list[tuple[int, int, str]],
) -> tuple[int, int]:
    """Reject a text range spanning omitted document structure."""
    try:
        doc_start = full_text_pos_to_doc_index(start, text_map)
        doc_end = full_text_pos_to_doc_index(end, text_map, end=True)
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
