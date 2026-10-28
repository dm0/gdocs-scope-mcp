"""Plan native tables and fill cells using indices read back from Google."""

# Deferred imports separate the paragraph converter and structural planner.
# ruff: noqa: PLC0415

import re
from copy import deepcopy
from dataclasses import dataclass, field

from bs4 import NavigableString, Tag

from .models import EditFailedResponse
from .revision_guards import (
    RevisionRaceError,
    submit as guarded_submit,
)
from .text_indices import utf16_length
from .tool_errors import ToolFailureError


def unsupported_table(description: str) -> None:
    """Reject unsupported table structures before any document writes."""
    raise ToolFailureError(EditFailedResponse(
        code='INVALID_ARGUMENT', description=description,
        suggested_action='Use rectangular tables with inline cell content, '
        'without merged cells, nested tables or block content; or rich=False.',
    ))


def shifted_requests(requests: list[dict], offset: int) -> list[dict]:
    """Translate relative cell requests without changing their styles."""
    result = deepcopy(requests)
    for request in result:
        operation = next(iter(request.values()))
        if 'location' in operation:
            operation['location']['index'] += offset
        if 'range' in operation:
            for key in ('startIndex', 'endIndex'):
                operation['range'][key] += offset
    return result


@dataclass
class TableCell:
    """Keep validated cell requests relative to its first paragraph."""

    requests: list[dict]
    text: str


@dataclass
class InsertionTable:
    """Retain a rectangular table separately from ordinary paragraphs."""

    start_index: int
    cells: list[list[TableCell]]

    def __len__(self) -> int:
        """Leave structural size to the native API instead of guessing it."""
        return 0


def convert_table(element: Tag, start: int) -> InsertionTable:
    """Validate simple Markdown/HTML tables and prepare every cell offline."""
    from .md2requests import (
        gpars_to_requests,
        html_to_gpars,
        inserted_text_from_requests,
    )

    if element.find('table') or element.find(['caption', 'colgroup', 'tfoot']):
        unsupported_table('Nested tables, captions and table column/footer '
                          'groups are unsupported.')
    for node in element.descendants:
        if node.find_parent(['td', 'th']) is not None:
            continue
        if isinstance(node, NavigableString) and not node.strip():
            continue
        if isinstance(node, Tag) and node.name in {
            'thead', 'tbody', 'tr', 'td', 'th',
        }:
            continue
        unsupported_table('Table content must be inside rows and cells.')
    rows = element.find_all('tr')
    if (any(row.parent.name not in {'table', 'thead', 'tbody'} for row in rows)
            or any(group.parent is not element
                   for group in element.find_all(['thead', 'tbody']))
            or any(cell.parent.name != 'tr'
                   for cell in element.find_all(['td', 'th']))):
        unsupported_table('Table rows and cells must be directly nested '
                          'inside their table or row group.')
    cells = []
    for row in rows:
        converted = []
        for cell in row.find_all(['td', 'th'], recursive=False):
            if any(str(cell.get(key, '1')) != '1'
                   for key in ('rowspan', 'colspan')):
                unsupported_table('Merged table cells are unsupported.')
            if cell.find(['p', 'div', 'ul', 'ol', 'pre', 'blockquote', 'hr',
                          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8',
                          'h9', 'h10']):
                unsupported_table('Table cells support inline content only.')
            alignment = cell.get('align')
            style = str(cell.get('style', '')).strip()
            if style:
                match = re.fullmatch(
                    r'text-align\s*:\s*(left|center|right)\s*;?', style,
                )
                if match is None:
                    unsupported_table('Only text-align is supported as a '
                                      'table cell CSS style.')
                alignment = match[1]
            if alignment not in {None, 'left', 'center', 'right'}:
                unsupported_table('Unsupported table cell alignment.')
            # Google Docs represents a soft line break as U+000B. Unlike \n,
            # it stays within the cell's single paragraph and survives the
            # text-run validator's removal of paragraph terminators.
            for line_break in cell.find_all('br'):
                line_break.replace_with(NavigableString('\u000b'))
            paragraphs = html_to_gpars(cell.decode_contents(), 0)
            requests = gpars_to_requests(paragraphs, newline_before=False)
            # The native cell already contains its mandatory final newline.
            insertions = [r['insertText'] for r in requests
                          if 'insertText' in r]
            if insertions:
                insertions[-1]['text'] = (
                    insertions[-1]['text'].removesuffix('\n')
                )
            requests = [r for r in requests
                        if 'insertText' not in r or r['insertText']['text']]
            text = inserted_text_from_requests(requests)
            if '\n' in text or '\r' in text:
                unsupported_table('Table cell text must fit a single '
                                  'paragraph; replace raw line breaks with '
                                  'spaces.')
            span = {'startIndex': 0, 'endIndex': max(1, utf16_length(text))}
            if cell.name == 'th':
                requests.append({'updateTextStyle': {
                    'range': span.copy(), 'textStyle': {'bold': True},
                    'fields': 'bold',
                }})
            if alignment is not None:
                requests.append({'updateParagraphStyle': {
                    'range': span.copy(), 'paragraphStyle': {'alignment': {
                        'left': 'START', 'center': 'CENTER', 'right': 'END',
                    }[alignment]}, 'fields': 'alignment',
                }})
            converted.append(TableCell(requests=requests, text=text))
        cells.append(converted)
    if (not cells or not cells[0]
            or any(len(row) != len(cells[0]) for row in cells)):
        unsupported_table('Tables must be nonempty and rectangular.')
    return InsertionTable(start_index=start, cells=cells)


@dataclass
class TableInsertionPlan:
    """Store prevalidated blocks for a multi-batch native insertion."""

    blocks: list
    start: int
    newline_before: bool
    completed_batches: int = field(default=0, init=False)

    def paragraph_requests(self, paragraphs: list, start: int) -> list[dict]:
        """Rebase paragraph/run positions at the current native cursor."""
        from .md2requests import gpars_to_requests

        paragraphs = deepcopy(paragraphs)
        cursor = start
        for paragraph in paragraphs:
            offset = cursor - paragraph.start_index
            paragraph.start_index += offset
            paragraph.end_index += offset
            for run in paragraph.elements:
                run.start_index += offset
                run.end_index += offset
            cursor += len(paragraph)
        return gpars_to_requests(
            paragraphs, newline_before=self.newline_before,
        )

    def request_groups(self):
        """Yield paragraph groups and tables without changing source order."""
        paragraphs = []
        for block in self.blocks:
            if isinstance(block, InsertionTable):
                if paragraphs:
                    yield paragraphs
                    paragraphs = []
                yield block
            elif len(block) or block.code_block:
                paragraphs.append(block)
        if paragraphs:
            yield paragraphs

    def iter_requests(self):
        """Expose prevalidated image requests to temporary-upload staging."""
        for block in self.blocks:
            if isinstance(block, InsertionTable):
                for row in block.cells:
                    for cell in row:
                        yield from cell.requests
            elif len(block) or block.code_block:
                yield from self.paragraph_requests([block], self.start)

    def replace_image_uri(self, old: str, new: str) -> None:
        """Replace staged sources in both table cells and body paragraphs."""
        from .md2requests import InsertionImage

        for request in self.iter_requests():
            image = request.get('insertInlineImage')
            if image and image['uri'] == old:
                image['uri'] = new
        for block in self.blocks:
            if not isinstance(block, InsertionTable):
                for run in block.elements:
                    if isinstance(run, InsertionImage) and run.uri == old:
                        run.uri = new

    def text(self) -> str:
        """Render native paragraph text, excluding table structural indices."""
        from .md2requests import inserted_text_from_requests

        text = ''
        for group in self.request_groups():
            if isinstance(group, InsertionTable):
                text += '\n' + ''.join(cell.text.replace('\u000b', '\n') + '\n'
                                      for row in group.cells for cell in row)
            else:
                text += inserted_text_from_requests(
                    self.paragraph_requests(group, self.start),
                )
        return text

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
        from .document_tabs import scope_requests, select
        from .md2requests import inserted_text_from_requests

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

        cursor = self.start
        for group in self.request_groups():
            if not isinstance(group, InsertionTable):
                requests = self.paragraph_requests(group, cursor)
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
