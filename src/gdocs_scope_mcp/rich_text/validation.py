"""Internal rich_text.validation responsibilities."""


from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.errors import ToolFailureError


def image_failure(description: str) -> None:
    """Refuse unsupported images before submitting any document changes."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use an absolute public HTTP(S) PNG, JPEG or GIF URL '
        '(at most 2 kB). HTML dimensions must be positive pixel numbers in '
        'width/height attributes; omit CSS/srcset, or use rich=False.',
    ))


def unsupported_list(description: str) -> None:
    """Reject list forms that cannot yet preserve their structure."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use nonempty items containing ordinary paragraphs '
        'and homogeneous nested lists, with '
        'the same list kind at every nesting level, or use rich=False.',
    ))


IMAGE_URI_MAX_BYTES = 2048


def unsupported_table(description: str) -> None:
    """Reject unsupported table structures before any document writes."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use rectangular tables with inline cell content, '
        'without merged cells, nested tables or block content; or rich=False.',
    ))
