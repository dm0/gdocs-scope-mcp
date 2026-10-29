"""Resolve logical merged-cell heads without confusing covered placeholders."""

# Reuse the reader's verified geometry without import cycles.
# ruff: noqa: PLC0415
from dataclasses import dataclass

from gdocs_scope_mcp.tables.tokens import address, coordinates, digest, fail


@dataclass
class GridCell:
    """Retain one physical entry and its logical coordinates/spans."""

    row: int
    column: int
    physical: int
    row_span: int
    column_span: int
    native: dict

    @property
    def key(self):
        """Return the logical top-left coordinate."""
        return self.row, self.column

    @property
    def address(self):
        """Expose the logical head using the same A1 notation as reads."""
        return address(*self.key)


class Grid:
    """Require complete verified geometry and preserve physical metadata."""

    def __init__(self, entry):
        """Index each real head, covered slot and physical placeholder."""
        from gdocs_scope_mcp.tables.geometry import _geometry
        self.entry = entry
        geometry, valid = _geometry(entry)
        if (not valid or any(type(rs) is not int or type(cs) is not int
                             for _, _, _, rs, cs, _, _ in geometry)):
            fail('INVALID_ARGUMENT', 'Merged-cell operations require verified '
                 'logical geometry with integer spans.')
        if any('table' in child for *_, cell in geometry
               for child in cell.get('content', [])):
            fail('INVALID_ARGUMENT', 'Nested cell tables are unsupported.')
        self.heads, self.slots, self.members = {}, {}, {}
        physical_heads = {}
        for r, p, c, rs, cs, owner, native in geometry:
            if owner is not None:
                continue
            head = GridCell(r, c, p, rs, cs, native)
            self.heads[head.key] = head
            physical_heads[r, p] = head
            self.members[head.key] = []
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    self.slots[rr, cc] = head
        for r, p, c, rs, cs, owner, native in geometry:
            head = physical_heads[owner or (r, p)]
            if owner is not None and any(
                e.get('textRun', {}).get('content', '') not in {'', '\n'}
                for item in native.get('content', [])
                for e in item.get('paragraph', {}).get('elements', [])
            ):
                fail('INVALID_ARGUMENT', 'Covered placeholders contain text.')
            self.members[head.key].append(GridCell(r, c, p, rs, cs, native))

    def cell(self, selected):
        """Require a head address without redirecting covered slots."""
        key = coordinates(selected)
        head = self.slots.get(key)
        if head is None:
            fail('INVALID_ARGUMENT', 'Selected address is outside the table.')
        if head.key != key:
            fail('INVALID_ARGUMENT', f'{selected} is covered by '
                 f'{head.address}; '
                 'select the merged head explicitly.')
        return head

    def selection(self, start, end):
        """Accept a bounded rectangle containing only complete merged cells."""
        r0, c0 = coordinates(start)
        r1, c1 = coordinates(end)
        if r0 > r1 or c0 > c1 or (r1 - r0 + 1) * (c1 - c0 + 1) > 100:  # noqa: PLR2004
            fail('INVALID_ARGUMENT', 'Select an ordered rectangle of at most '
                 '100 logical slots.')
        found = {}
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                head = self.slots.get((r, c))
                if head is None:
                    fail('INVALID_ARGUMENT', 'Rectangle is outside the table.')
                if (head.row < r0 or head.column < c0 or
                        head.row + head.row_span > r1 + 1 or
                        head.column + head.column_span > c1 + 1):
                    fail('INVALID_ARGUMENT', 'Rectangle cuts through a merged '
                         'cell; include its entire logical span.')
                found[head.key] = head
        return [found[key] for key in sorted(found)]

    def borders(self, head):
        """Cover every neighboring segment of a merged cell's perimeter."""
        edges = []
        r, c, rs, cs = (head.row, head.column, head.row_span, head.column_span)
        for side, opposite, positions in [
            ('Top', 'Bottom', [(r - 1, cc) for cc in range(c, c + cs)]),
            ('Bottom', 'Top', [(r + rs, cc) for cc in range(c, c + cs)]),
            ('Left', 'Right', [(rr, c - 1) for rr in range(r, r + rs)]),
            ('Right', 'Left', [(rr, c + cs) for rr in range(r, r + rs)]),
        ]:
            own = head.native.get('tableCellStyle', {}).get('border' + side)
            for key in positions:
                adjacent = self.slots.get(key)
                value = (adjacent.native.get('tableCellStyle', {}).get(
                    'border' + opposite,
                ) if adjacent is not None else None)
                edges.append([own, value, {
                    'suggestedTableCellStyleChanges': (
                        adjacent.native.get('suggestedTableCellStyleChanges')
                        if adjacent is not None else None),
                }])
        return edges


def content_direction(document, entry):
    """Read the enclosing native section's direction, whose default is LTR."""
    value = 'LEFT_TO_RIGHT'
    for item in document.get('body', {}).get('content', []):
        if item.get('startIndex', 0) > entry.item['startIndex']:
            break
        if 'sectionBreak' in item:
            value = item['sectionBreak'].get('sectionStyle', {}).get(
                'contentDirection', 'LEFT_TO_RIGHT',
            )
    return value


def merge_state(document, grid, head):
    """Hash all physical members, metadata and perimeter dependencies."""
    from gdocs_scope_mcp.tables.deletion_state import deletion_state
    table = grid.entry.item['table']
    columns = table.get('tableStyle', {}).get('tableColumnProperties', [])
    return digest([
        [[m.row - head.row, m.column - head.column,
          deletion_state(document, grid.entry, m.row, m.physical,
                         logical_column=m.column, borders=[])]
         for m in grid.members[head.key]],
        grid.borders(head), content_direction(document, grid.entry),
        [table['tableRows'][r].get('tableRowStyle', {})
         for r in range(head.row, head.row + head.row_span)],
        [columns[c] if c < len(columns) else {}
         for c in range(head.column, head.column + head.column_span)],
    ])
