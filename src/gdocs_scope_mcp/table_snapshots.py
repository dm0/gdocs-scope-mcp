"""Validate operation-specific expectations at checked table/cell positions."""

# Share the native read boundary without an import cycle.
# ruff: noqa: PLC0415

import time
from copy import deepcopy

from pydantic import BaseModel

from .models import GoogleDocumentTableCell
from .settings import get_settings
from .table_refs import Layout
from .table_tokens import address, decode, digest, encode, fail


def cell_state(document, cell):
    """Separate content/styles from absolute cell positions."""
    from .revision_guards import _normalized
    content, text_styles, paragraph_styles, shape = [], [], [], []
    kinds, list_ids = set(), set()
    for item in cell.get('content', []):
        paragraph = item.get('paragraph', {})
        values, styles, elements = [], [], []
        for element in paragraph.get('elements', []):
            normalized = _normalized(element)
            run = normalized.get('textRun')
            if run is not None:
                text = run.get('content', '')
                if values and isinstance(values[-1], str):
                    values[-1] += text
                else:
                    values.append(text)
                styles.append([len(text.encode('utf-16-le')) // 2,
                               run.get('textStyle', {})])
                elements.append('text')
            else:
                values.append(normalized)
                elements.append(sorted(normalized))
        content.append(values)
        text_styles.append(styles)
        bullet = paragraph.get('bullet')
        paragraph_styles.append([paragraph.get('paragraphStyle', {}), bullet])
        if bullet and bullet.get('listId'):
            list_ids.add(bullet['listId'])
        kinds.add(paragraph.get('paragraphStyle', {}).get('namedStyleType',
                                                          'NORMAL_TEXT'))
        shape.append(elements)
    styles = document.get('namedStyles', {}).get('styles', [])
    named_styles = [s for s in styles if s.get('namedStyleType') in kinds]
    list_styles = {i: document.get('lists', {}).get(i) for i in list_ids}
    return {'content': digest(content),
            'text_style': digest([text_styles, named_styles]),
            'paragraph_style': digest([paragraph_styles, named_styles,
                                       list_styles]),
            'cell_style': digest(cell.get('tableCellStyle', {})),
            'structure': digest([shape, cell.get('tableCellStyle', {}).get(
                'rowSpan'), cell.get('tableCellStyle', {}).get('columnSpan')])}


class CellLocation(BaseModel):
    """Report addresses alongside zero-based diagnostic coordinates."""

    address: str
    row: int
    column: int
    markdown: str
    markdown_char_count: int
    markdown_truncated: bool


class SnapshotResponse(BaseModel):
    """Issue or validate expectations for selected positional cells."""

    document_id: str
    table_ref: str
    revision_id: str
    base_token: str
    expires_at: int
    fields: list[str]
    cells: list[CellLocation]
    validated: bool


def snapshot(doc_id, table_ref, cells, fields, base_token=None):
    """Resolve a checked position and validate selected dependencies."""
    from .table_read import _fetch, _geometry, _model
    table = decode(table_ref, 'table', doc_id)
    requested = sorted(set(fields))
    baseline = decode(base_token, 'base', doc_id) if base_token else None
    if baseline is not None and baseline.expires <= int(time.time()):
        fail('SNAPSHOT_EXPIRED', 'The selected-cell snapshot has expired.')
    if len(set(cells)) != len(cells):
        fail('INVALID_ARGUMENT', 'Duplicate cell addresses are not allowed.')
    if baseline is not None:
        original = baseline.model_copy(update={
            'kind': 'table', 'expires': 0, 'fields': [], 'cells': {},
        })
        if (original != table or baseline.fields != requested
                or set(baseline.cells) != set(cells)):
            fail('INVALID_REFERENCE', 'Snapshot table/cells/fields differ.')
    document = _fetch(doc_id)
    entry = Layout(document).resolve(table)
    geometry, valid = _geometry(entry)
    if (not valid or any(rs != 1 or cs != 1 for _, _, _, rs, cs, _, _ in
                         geometry) or any('table' in child
                         for *_, cell in geometry
                         for child in cell.get('content', []))):
        fail('INVALID_ARGUMENT', 'Cell snapshots require verified unmerged '
             'geometry without nested tables in cells.')
    model = _model(document)
    available = {address(r, c): (r, c, cell)
                 for r, _, c, _, _, _, cell in geometry}
    states, locations = {}, []
    for selected in cells:
        if selected not in available:
            fail('INVALID_ARGUMENT', 'Selected address is outside the table.')
        r, c, cell = available[selected]
        state = cell_state(document, cell)
        states[selected] = {field: state[field] for field in requested}
        markup = GoogleDocumentTableCell.model_validate(
            deepcopy(cell),
        ).to_markdown(model)
        markup = markup[markup.index('>') + 1:-len('</td>')]
        locations.append(CellLocation(
            address=selected, row=r, column=c, markdown=markup[:2000],
            markdown_char_count=len(markup),
            markdown_truncated=len(markup) > 2000,  # noqa: PLR2004
        ))
    if baseline is not None and baseline.cells != states:
        fail('EDIT_CONFLICT', 'Selected content or properties changed.')
    issued = table.model_copy(update={
        'kind': 'base', 'fields': requested, 'cells': states,
        'expires': (int(time.time()) +
                    get_settings().table_snapshot_ttl_seconds),
    })
    return SnapshotResponse(
        document_id=doc_id, table_ref=table_ref,
        revision_id=document['revisionId'], base_token=encode(issued),
        expires_at=issued.expires, fields=requested, cells=locations,
        validated=baseline is not None,
    )
