"""Internal tables.rendering responsibilities."""

from copy import deepcopy

from gdocs_scope_mcp.documents.native_models import (
    GoogleDocument,
)
from gdocs_scope_mcp.tables.references import reference_map


def _model(document):
    """Render shared Markdown while leaving the native snapshot untouched."""
    return GoogleDocument.model_validate(deepcopy({
        **document, 'table_refs': reference_map(document),
    }))

