"""Read table style dependencies, including both shared border sides."""

from copy import deepcopy

from .table_tokens import digest, fail

CELL_FIELDS = {
    'background_color': 'backgroundColor',
    'vertical_alignment': 'contentAlignment',
    'padding_top': 'paddingTop', 'padding_bottom': 'paddingBottom',
    'padding_left': 'paddingLeft', 'padding_right': 'paddingRight',
    'border_top': 'borderTop', 'border_bottom': 'borderBottom',
    'border_left': 'borderLeft', 'border_right': 'borderRight',
}
OPPOSITE = {'top': ('bottom', -1, 0), 'bottom': ('top', 1, 0),
            'left': ('right', 0, -1), 'right': ('left', 0, 1)}


def cell_at(entry, row, column):
    """Access one cell after unmerged rectangular geometry was verified."""
    return entry.item['table']['tableRows'][row]['tableCells'][column]


def neighbor(entry, row, column, side):
    """Return the opposite half-edge only when it belongs to this table."""
    opposite, dr, dc = OPPOSITE[side]
    r, c = row + dr, column + dc
    table = entry.item['table']
    if 0 <= r < table['rows'] and 0 <= c < table['columns']:
        return r, c, opposite
    return None


def edge_resource(row, column, side):
    """Give two adjacent half-edges the same physical resource identity."""
    if side in {'top', 'bottom'}:
        return 'horizontal', row + int(side == 'bottom'), column
    return 'vertical', row, column + int(side == 'right')


def header_count(entry):
    """Require a verified contiguous prefix of native header row flags."""
    flags = [r.get('tableRowStyle', {}).get('tableHeader', False)
             for r in entry.item['table']['tableRows']]
    count = sum(flags)
    if flags != [True] * count + [False] * (len(flags) - count):
        fail('TARGET_CHANGED', 'Non-contiguous native table header rows.')
    return count


def property_value(entry, row, column, field, document=None):
    """Read only the requested native property, excluding unrelated content."""
    table = entry.item['table']
    cell = cell_at(entry, row, column)
    if field.startswith('cell.'):
        name = field.removeprefix('cell.')
        return deepcopy(cell.get('tableCellStyle', {}).get(CELL_FIELDS[name]))
    if field == 'paragraph.alignment':
        # Splitting a paragraph without changing its alignment is compatible.
        named = {s.get('namedStyleType'): s.get('paragraphStyle', {})
                 for s in (document or {}).get('namedStyles', {}).get(
                     'styles', [],
                 )}
        values = set()
        for item in cell.get('content', []):
            if 'paragraph' not in item:
                continue
            style = item['paragraph'].get('paragraphStyle', {})
            value = style.get('alignment', 'ALIGNMENT_UNSPECIFIED')
            if value == 'ALIGNMENT_UNSPECIFIED':
                inherited = named.get(style.get('namedStyleType',
                                                 'NORMAL_TEXT'), {})
                value = inherited.get('alignment', named.get(
                    'NORMAL_TEXT', {},
                ).get('alignment', 'ALIGNMENT_UNSPECIFIED'))
            values.add(value)
        return sorted(values)
    if field == 'column.width':
        properties = table.get('tableStyle', {}).get(
            'tableColumnProperties', [],
        )
        return deepcopy(properties[column]) if column < len(properties) else {}
    if field == 'row.min_height':
        return deepcopy(table['tableRows'][row].get('tableRowStyle', {}).get(
            'minRowHeight',
        ))
    if field == 'table.header_rows':
        return header_count(entry)
    raise ValueError('Unknown formatting field')


def property_state(entry, row, column, field, document=None):
    """Include the neighboring edge that a border update overwrites."""
    value = property_value(entry, row, column, field, document)
    if field.startswith('cell.border_'):
        side = field.removeprefix('cell.border_')
        other = neighbor(entry, row, column, side)
        adjacent = None
        if other is not None:
            r, c, opposite = other
            adjacent = property_value(entry, r, c, 'cell.border_' + opposite)
        value = [value, adjacent]
    return digest(value)
