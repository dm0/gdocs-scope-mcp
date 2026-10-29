"""Execute staged table plans using native readback and chained revisions."""

from copy import deepcopy

from gdocs_scope_mcp.contracts import EditFailedResponse
from gdocs_scope_mcp.documents.tabs import scope_requests, select
from gdocs_scope_mcp.errors import ToolFailureError
from gdocs_scope_mcp.revision_guards import (
    RevisionRaceError,
    submit as guarded_submit,
)
from gdocs_scope_mcp.rich_text.cells import shifted_requests
from gdocs_scope_mcp.rich_text.models import InsertionTable
from gdocs_scope_mcp.rich_text.paragraph_requests import (
    paragraph_text as inserted_text_from_requests,
)
from gdocs_scope_mcp.text_indices import utf16_length


class TableInsertionExecution:
    """Own mutable progress for one execution of a pure plan."""

    def __init__(self, plan):
        self.plan = plan
        self.completed_batches = 0

    def execute(self, service, doc_id: str,
                required_revision: str | None = None, *,
                table_borders: bool = True, tab_id=None,
                size_images=None) -> None:
        """Insert each table, read real cell locations, then populate it."""
        self.completed_batches = 0
        try:
            self._execute(service, doc_id, required_revision, table_borders,
                          tab_id, size_images=size_images)
        except (RevisionRaceError, ToolFailureError):
            raise
        except Exception as error:
            raise ToolFailureError(EditFailedResponse(
                code='PARTIAL_WRITE',
                committed_batches=self.completed_batches,
                description='Multi-stage table insertion stopped. Earlier '
                'stages may already have changed the document.',
                suggested_action='Read the document and inspect partial '
                'tables/content before retrying; do not repeat blindly.',
            )) from error


    def _execute(self, service, doc_id: str,
                 required_revision: str | None, table_borders: bool,
                 tab_id=None, *, size_images=None) -> None:
        """Guard each stage with the revision returned by the prior write."""

        documents = service.documents()
        revision = required_revision or documents.get(
            documentId=doc_id, suggestionsViewMode='SUGGESTIONS_INLINE',
        ).execute()['revisionId']

        def submit(requests):
            nonlocal revision
            response = guarded_submit(service, doc_id,
                                      scope_requests(requests, tab_id),
                                      revision,
                                      force_required=True)
            self.completed_batches += 1
            revision = response['writeControl']['requiredRevisionId']

        cursor = self.plan.start
        for group in self.plan.request_groups():
            if not isinstance(group, InsertionTable):
                requests = self.plan.paragraph_requests(group, cursor)
                if size_images is not None:
                    size_images(requests, group)
                submit(requests)
                cursor += utf16_length(inserted_text_from_requests(requests))
                continue
            submit([{
                'insertTable': {'rows': len(group.cells),
                                'columns': len(group.cells[0]),
                                'location': {'index': cursor}},
            }])
            native = documents.get(
                documentId=doc_id, includeTabsContent=True,
                suggestionsViewMode='SUGGESTIONS_INLINE',
            ).execute()
            native = select(native, tab_id)
            if native['revisionId'] != revision:
                raise RuntimeError('Document changed before cell lookup')
            table = next(item for item in _structural_elements(native['body'])
                         if item.get('startIndex') == cursor + 1
                         and 'table' in item)
            rows = table['table']['tableRows']
            if (len(rows) != len(group.cells)
                    or any(len(row['tableCells']) != len(planned)
                           for row, planned in zip(rows, group.cells,
                                                   strict=True))):
                raise RuntimeError('Created table shape changed before '
                                   'filling')
            cells = [cell for row in rows
                     for cell in row['tableCells']]
            planned = [cell for row in group.cells for cell in row]
            requests = []
            pairs = zip(cells, planned, strict=True)
            for source, cell in reversed(list(pairs)):
                position = source['content'][0]['startIndex']
                requests.extend(shifted_requests(cell.requests, position))
            border = {
                'width': {
                    'magnitude': 1 if table_borders else 0, 'unit': 'PT',
                },
                'color': {'color': {'rgbColor': {
                    'red': 0, 'green': 0, 'blue': 0,
                }}},
                'dashStyle': 'SOLID',
            }
            sides = ('borderTop', 'borderBottom', 'borderLeft', 'borderRight')
            requests.append({'updateTableCellStyle': {
                'tableStartLocation': {'index': table['startIndex']},
                'tableCellStyle': {side: deepcopy(border) for side in sides},
                'fields': ','.join(sides),
            }})
            submit(requests)
            cursor = table['endIndex'] + sum(
                utf16_length(c.text) for c in planned
            )


def _structural_elements(container: dict):
    """Walk body/cell structures so table insertion also works in cells."""
    for item in container.get('content', []):
        yield item
        if 'table' in item:
            for row in item['table']['tableRows']:
                for cell in row['tableCells']:
                    yield from _structural_elements(cell)
