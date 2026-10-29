"""Internal rich_text.insertion responsibilities."""


from contextlib import contextmanager, nullcontext

from gdocs_scope_mcp.entity_edit import (
    INSERT_ENTITY_KINDS,
    validate_insertions,
)
from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.image_layout import fit_images
from gdocs_scope_mcp.revision_guards import (
    insertion_context,
    submit,
)
from gdocs_scope_mcp.rich_text.compiler import (
    gpars_to_requests,
    inserted_text_from_requests,
)
from gdocs_scope_mcp.rich_text.execution import TableInsertionExecution
from gdocs_scope_mcp.rich_text.image_uploads import staged_local_images
from gdocs_scope_mcp.rich_text.parsing import html_to_gpars, markdown_to_html
from gdocs_scope_mcp.rich_text.plans import TableInsertionPlan
from gdocs_scope_mcp.rich_text.preparation import PreparedInsertion


@contextmanager
def rich_insertion_requests(
    text, start, *, newline_before=True, upload_local_images=False,
    drive_factory, validate_requests=None,
):
    """Prepare ordinary content or enter the opt-in image upload lifecycle."""
    if upload_local_images:
        with staged_local_images(
            text, start, newline_before=newline_before,
            drive_factory=drive_factory, validate_requests=validate_requests,
        ) as prepared:
            yield prepared
        return
    paragraphs = html_to_gpars(markdown_to_html(text), start)
    prepared = PreparedInsertion(
        gpars_to_requests(paragraphs, newline_before=newline_before),
        paragraphs=paragraphs,
    )
    if validate_requests:
        validate_requests(prepared.requests)
    yield prepared


def insert_content(
    service, doc_id: str, text: str, index: int, *, rich: bool,
    newline_before: bool = True, upload_local_images: bool = False,
    required_revision: str | None = None,
    table_borders: bool = True,
    tab_id: str | None = None,
    document: dict | None = None,
) -> tuple[str, int, int, list[str]]:
    """Apply a validated insertion within the temporary-image lifecycle."""
    if rich:
        context = rich_insertion_requests(
            text, index, newline_before=newline_before,
            upload_local_images=upload_local_images,
            drive_factory=lambda: clients.get_service('drive', 'v3'),
            validate_requests=lambda requests: validate_insertions(
                service, doc_id, requests, required_revision, tab_id=tab_id,
            ),
        )
    else:
        literal = '\n' + text if newline_before else text + '\n'
        context = nullcontext(PreparedInsertion([{'insertText': {
            'location': {'index': index}, 'text': literal,
        }}]))
    with insertion_context(context, index) as prepared:
        if rich:
            validate_insertions(service, doc_id, prepared.requests,
                                required_revision, tab_id=tab_id)
        inserted = inserted_text_from_requests(prepared.requests)
        if isinstance(prepared.requests, TableInsertionPlan):
            TableInsertionExecution(prepared.requests).execute(
                service, doc_id, required_revision,
                table_borders=table_borders,
                tab_id=tab_id,
                size_images=(lambda requests, paragraphs: fit_images(
                    requests, paragraphs, document or {}, index,
                )),
            )
            requests = list(prepared.requests.iter_requests())
        else:
            requests = prepared.requests
            if rich:
                fit_images(
                    requests, prepared.paragraphs, document or {}, index,
                )
            submit(service, doc_id, requests, required_revision)
    return (inserted, sum('insertInlineImage' in r for r in requests),
            sum(bool(INSERT_ENTITY_KINDS.intersection(r)) for r in requests),
            prepared.cleanup_pending)
