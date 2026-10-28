"""Apply explicit table styles with property-level optimistic concurrency."""

# Share the native service/read boundary without module import cycles.
# ruff: noqa: PLC0415

import logging
import time
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self

from .models import EditFailedResponse
from .revision_guards import MAX_ATTEMPTS, RevisionRaceError, submit
from .table_refs import Layout
from .table_snapshots import resolve_cells, validate_baseline
from .table_style_state import (
    CELL_FIELDS,
    cell_at,
    edge_resource,
    neighbor,
    property_state,
)
from .table_tokens import CellAddress, coordinates, decode, fail
from .tool_errors import ToolFailureError

log = logging.getLogger(__name__)
Points = Annotated[float, Field(strict=True, ge=0, le=10000,
                                allow_inf_nan=False)]
Width = Annotated[float, Field(strict=True, ge=5, le=10000,
                               allow_inf_nan=False)]
Color = Annotated[str, Field(strict=True, pattern=r'^#[0-9a-fA-F]{6}$')]


class StyleInput(BaseModel):
    """Require explicit non-null properties and preserve omitted fields."""

    model_config = ConfigDict(strict=True, extra='forbid')

    @model_validator(mode='after')
    def explicit_properties(self) -> Self:
        """Avoid empty changes and accidental resets from explicit nulls."""
        properties = self.model_fields_set - {'address', 'column', 'row'}
        if not properties or any(getattr(self, p) is None for p in properties):
            raise ValueError('Specify at least one non-null style property')
        return self


class Border(StyleInput):
    """Specify a border or preserve omitted native components when known."""

    color: Color | None = None
    width: Points | None = None
    dash_style: Literal['SOLID', 'DOT', 'DASH'] | None = None


class CellStyle(StyleInput):
    """Choose cell/paragraph properties at one uppercase A1 address."""

    address: CellAddress
    background_color: Color | Literal['transparent'] | None = None
    vertical_alignment: Literal['TOP', 'MIDDLE', 'BOTTOM'] | None = None
    horizontal_alignment: Literal[
        'START', 'CENTER', 'END', 'JUSTIFIED',
    ] | None = None
    padding_top: Points | None = None
    padding_bottom: Points | None = None
    padding_left: Points | None = None
    padding_right: Points | None = None
    border_top: Border | None = None
    border_bottom: Border | None = None
    border_left: Border | None = None
    border_right: Border | None = None


class ColumnStyle(StyleInput):
    """Set a fixed point width or return a column to automatic distribution."""

    column: Annotated[str, Field(strict=True, pattern=r'^[A-Z]{1,5}$')]
    width: Width | Literal['auto']


class RowStyle(StyleInput):
    """Set a minimum height for a one-based row number."""

    row: Annotated[int, Field(strict=True, ge=1, le=100000)]
    min_height: Points


class FormatChanges(BaseModel):
    """Collect at most 100 explicit cell/row/column/table operations."""

    model_config = ConfigDict(strict=True, extra='forbid')
    cells: list[CellStyle] = Field(default_factory=list, max_length=100)
    columns: list[ColumnStyle] = Field(default_factory=list, max_length=100)
    rows: list[RowStyle] = Field(default_factory=list, max_length=100)
    header_rows: Annotated[
        int, Field(strict=True, ge=0, le=100000),
    ] | None = None

    @model_validator(mode='after')
    def bounded_nonempty(self) -> Self:
        """Reject duplicate targets and empty/oversized groups before reads."""
        if 'header_rows' in self.model_fields_set and self.header_rows is None:
            raise ValueError('header_rows must be a non-null integer')
        count = (len(self.cells) + len(self.columns) + len(self.rows) +
                 int(self.header_rows is not None))
        if not 1 <= count <= 100:  # noqa: PLR2004
            raise ValueError('Specify 1-100 formatting targets')
        for values, key in [(self.cells, 'address'), (self.columns, 'column'),
                            (self.rows, 'row')]:
            if len({getattr(v, key) for v in values}) != len(values):
                raise ValueError('Specify each cell/column/row only once')
        return self


class FormatResponse(BaseModel):
    """Confirm one atomic style batch without claiming text changes."""

    ok: Literal[True] = True
    document_id: str
    tab_id: str | None = None
    table_ref: str
    revision_id: str | None
    attempts: int
    committed_batches: Literal[1] = 1
    applied_count: int
    updated_properties: list[str]


def color(value):
    """Convert an opaque RGB color or an explicitly transparent background."""
    if value == 'transparent':
        return {}
    value = value.removeprefix('#')
    return {'color': {'rgbColor': {
        channel: int(value[i:i + 2], 16) / 255
        for channel, i in [('red', 0), ('green', 2), ('blue', 4)]
    }}}


def _native_value(name, value):
    """Translate a typed property without filling unspecified defaults."""
    if name == 'background_color':
        return color(value)
    if name.startswith('padding_'):
        return {'magnitude': value, 'unit': 'PT'}
    return value


def requirements(changes, baseline):
    """Choose baseline anchors before a native read."""
    required = []
    for change in changes.cells:
        for name in change.model_fields_set - {'address'}:
            field = ('paragraph.alignment' if name == 'horizontal_alignment'
                     else 'cell.' + name)
            required.append((change.address, field))
    positions = {a: coordinates(a) for a in sorted(baseline.cells)}
    for change in changes.columns:
        column = coordinates(change.column + '1')[1]
        anchors = [a for a, (_, c) in positions.items() if c == column]
        if not anchors:
            fail('INVALID_REFERENCE', 'Snapshot needs a cell in each column.')
        required.append((anchors[0], 'column.width'))
    for change in changes.rows:
        anchors = [a for a, (r, _) in positions.items() if r == change.row - 1]
        if not anchors:
            fail('INVALID_REFERENCE', 'Snapshot needs a cell in each row.')
        required.append((anchors[0], 'row.min_height'))
    if changes.header_rows is not None:
        if not positions:
            fail('INVALID_REFERENCE', 'Snapshot needs a table header anchor.')
        required.append((next(iter(positions)), 'table.header_rows'))
    if any(a not in baseline.cells or f not in baseline.cells[a]
           for a, f in required):
        fail('INVALID_REFERENCE', 'Snapshot lacks requested style fields.')
    return required


def _border(entry, row, column, side, updates):
    """Preserve omitted components on both halves of a shared border."""
    name = CELL_FIELDS['border_' + side]
    current = cell_at(entry, row, column).get('tableCellStyle', {}).get(
        name, {},
    )
    other = neighbor(entry, row, column, side)
    if other is not None:
        r, c, opposite = other
        adjacent = cell_at(entry, r, c).get('tableCellStyle', {}).get(
            CELL_FIELDS['border_' + opposite], {},
        )
        if any(current.get(k) != adjacent.get(k)
               for k in ('color', 'width', 'dashStyle') if k not in updates):
            fail('TARGET_CHANGED', 'Shared border has inconsistent omitted '
                 'components; explicitly specify its full style.')
    result = {**deepcopy(current), **updates}
    if not {'color', 'width', 'dashStyle'} <= result.keys():
        fail('INVALID_ARGUMENT', 'Inherited border values are unavailable; '
             'specify color, width and dash_style explicitly.')
    return result


def plan(document, entry, changes, available):
    """Build field masks and coalesce shared border updates."""
    location = {'index': entry.item['startIndex']}
    if document.get('_mcp_tab_id'):
        location['tabId'] = document['_mcp_tab_id']
    requests, borders = [], {}

    def update_cell(row, column, values):
        """Restrict writes to the requested native cell style fields."""
        requests.append({'updateTableCellStyle': {
            'tableRange': {'tableCellLocation': {
                'tableStartLocation': location, 'rowIndex': row,
                'columnIndex': column,
            }, 'rowSpan': 1, 'columnSpan': 1},
            'tableCellStyle': values, 'fields': ','.join(sorted(values)),
        }})

    for change in changes.cells:
        row, column, cell = available[change.address]
        if cell.get('suggestedTableCellStyleChanges'):
            fail('INVALID_ARGUMENT', 'Suggested cell styles are unsupported.')
        values = {}
        for name in change.model_fields_set - {'address'}:
            value = getattr(change, name)
            if name.startswith('border_'):
                side = name.removeprefix('border_')
                updates = {}
                for key in value.model_fields_set:
                    if key == 'color':
                        native = color(value.color)
                    elif key == 'width':
                        native = {'magnitude': value.width, 'unit': 'PT'}
                    else:
                        native = value.dash_style
                    updates[{'dash_style': 'dashStyle'}.get(key, key)] = native
                resource = edge_resource(row, column, side)
                saved = borders.setdefault(resource, [row, column, side, {}])
                if any(k in saved[3] and saved[3][k] != v
                       for k, v in updates.items()):
                    fail('INVALID_ARGUMENT', 'Shared border updates conflict.')
                saved[3].update(updates)
            elif name == 'horizontal_alignment':
                content = cell.get('content', [])
                if not content or any('paragraph' not in p for p in content):
                    fail('INVALID_ARGUMENT', 'Alignment requires paragraphs.')
                if any(p['paragraph'].get('suggestedParagraphStyleChanges')
                       for p in content):
                    fail('INVALID_ARGUMENT', 'Alignment suggestions present.')
                bounds = {'startIndex': content[0]['startIndex'],
                          'endIndex': content[-1]['endIndex']}
                if document.get('_mcp_tab_id'):
                    bounds['tabId'] = document['_mcp_tab_id']
                requests.append({'updateParagraphStyle': {
                    'range': bounds, 'paragraphStyle': {'alignment': value},
                    'fields': 'alignment',
                }})
            else:
                values[CELL_FIELDS[name]] = _native_value(name, value)
        if values:
            update_cell(row, column, values)
    for row, column, side, updates in borders.values():
        other = neighbor(entry, row, column, side)
        if other and cell_at(entry, *other[:2]).get(
            'suggestedTableCellStyleChanges',
        ):
            fail('INVALID_ARGUMENT', 'Adjacent style suggestions unsupported.')
        update_cell(row, column, {CELL_FIELDS['border_' + side]:
                                  _border(entry, row, column, side, updates)})
    table = entry.item['table']
    for change in changes.columns:
        if table.get('suggestedTableStyleChanges'):
            fail('INVALID_ARGUMENT', 'Suggested table styles are unsupported.')
        column = coordinates(change.column + '1')[1]
        if column >= table['columns']:
            fail('INVALID_ARGUMENT', 'Column is outside the table.')
        values = {'widthType': 'EVENLY_DISTRIBUTED'}
        if change.width != 'auto':
            values = {'widthType': 'FIXED_WIDTH',
                      'width': {'magnitude': change.width, 'unit': 'PT'}}
        requests.append({'updateTableColumnProperties': {
            'tableStartLocation': location, 'columnIndices': [column],
            'tableColumnProperties': values, 'fields': 'widthType,width',
        }})
    for change in changes.rows:
        if change.row > table['rows']:
            fail('INVALID_ARGUMENT', 'Row is outside the table.')
        if table['tableRows'][change.row - 1].get(
            'suggestedTableRowStyleChanges',
        ):
            fail('INVALID_ARGUMENT', 'Suggested row styles are unsupported.')
        requests.append({'updateTableRowStyle': {
            'tableStartLocation': location, 'rowIndices': [change.row - 1],
            'tableRowStyle': {'minRowHeight': {
                'magnitude': change.min_height, 'unit': 'PT',
            }}, 'fields': 'minRowHeight',
        }})
    if changes.header_rows is not None:
        if changes.header_rows > table['rows']:
            fail('INVALID_ARGUMENT', 'Header row count exceeds table height.')
        if any(r.get('suggestedTableRowStyleChanges')
               for r in table['tableRows']):
            fail('INVALID_ARGUMENT', 'Suggested row styles are unsupported.')
        requests.append({'pinTableHeaderRows': {
            'tableStartLocation': location,
            'pinnedHeaderRowsCount': changes.header_rows,
        }})
    return requests


def format_table(doc_id, table_ref, base_token, changes, *, tab_id=None):
    """Recheck properties and commit one strictly guarded style batch."""
    from . import docs_edit
    from .table_read import _fetch
    table = decode(table_ref, 'table', doc_id)
    baseline = decode(base_token, 'base', doc_id)
    required = requirements(changes, baseline)
    selected = sorted({a for a, _ in required})
    validate_baseline(table, baseline, selected, baseline.fields, subset=True)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        validate_baseline(table, baseline, selected, baseline.fields,
                          subset=True)
        document = _fetch(doc_id, tab_id=tab_id)
        available = resolve_cells(document, table, selected)
        entry = Layout(document).resolve(table)
        for address, field in required:
            row, column, _ = available[address]
            actual = property_state(entry, row, column, field, document)
            if baseline.cells[address][field] != actual:
                fail('EDIT_CONFLICT', 'A requested style property changed.')
        requests = plan(document, entry, changes, available)
        try:
            result = submit(docs_edit._get_service(), doc_id, requests,
                            document['revisionId'], force_required=True)
        except RevisionRaceError:
            if attempt == MAX_ATTEMPTS:
                break
            log.info('edit=docs_table_format status=revision_retry attempt=%s',
                     attempt)
            time.sleep(0.05 * (2 ** (attempt - 1)))
            continue
        return FormatResponse(
            document_id=doc_id, tab_id=document.get('_mcp_tab_id'),
            table_ref=table_ref,
            revision_id=result.get('writeControl', {}).get(
                'requiredRevisionId',
            ),
            attempts=attempt, applied_count=(
                len(changes.cells) + len(changes.columns) + len(changes.rows) +
                int(changes.header_rows is not None)),
            updated_properties=sorted({field for _, field in required}),
        )
    raise ToolFailureError(EditFailedResponse(
        code='REVISION_RETRY_EXHAUSTED',
        description='The formatting batch lost three strict revision races.',
        suggested_action='Retry later with the same snapshot if still valid. '
        'Reread requested properties if they conflict. No batch committed.',
    ))
