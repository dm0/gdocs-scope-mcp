"""Internal tables.geometry responsibilities."""


from dataclasses import dataclass


def _text(item):
    """Read source heading text without exposing indices or Markdown markup."""
    return ''.join(e.get('textRun', {}).get('content', '')
                   for e in item.get('paragraph', {}).get('elements', []))



@dataclass
class _Table:
    """Keep a native structural path private to the current snapshot."""

    item: dict
    path: list[int]
    headings: list[tuple[int, str, str]]
    parent_cell: tuple[list[int], int, int] | None = None



def _tables(document):
    """Walk tables in preorder, retaining nesting paths and heading scope."""
    def walk(content, path, inherited, parent=None):
        """Use independent heading stacks inside cells, retaining ancestry."""
        headings = list(inherited)
        for index, item in enumerate(content):
            style = item.get('paragraph', {}).get('paragraphStyle', {})
            heading = style.get('headingId')
            if heading:
                kind = style.get('namedStyleType', '')
                level = int(kind[-1]) if kind.startswith('HEADING_') else 0
                headings = [h for h in headings if h[0] < level]
                headings.append((level, heading, _text(item).rstrip('\n')))
            if 'table' not in item:
                continue
            current = [*path, index]
            yield _Table(item, current, list(headings), parent)
            for r, row in enumerate(item['table'].get('tableRows', [])):
                for c, cell in enumerate(row.get('tableCells', [])):
                    yield from walk(cell.get('content', []),
                                    [*current, r, c], headings,
                                    (current, r, c))
    return list(walk(document.get('body', {}).get('content', []), [], []))



def _geometry(entry):
    """Map spans conservatively, preserving API placeholder entries."""
    table = entry.item['table']
    height, width = table.get('rows', 0), table.get('columns', 0)
    rows = table.get('tableRows', [])
    valid = (len(rows) == height and height > 0 and width > 0
             and height * width <= MAX_GRID_AREA)
    if not valid:
        return [(r, c, c, cell.get('tableCellStyle', {}).get('rowSpan'),
                 cell.get('tableCellStyle', {}).get('columnSpan'), None, cell)
                for r, row in enumerate(rows)
                for c, cell in enumerate(row.get('tableCells', []))], False
    occupied = {}
    result = []
    for r, row in enumerate(rows):
        cells = row.get('tableCells', [])
        explicit = len(cells) == width
        cursor = 0
        for physical, cell in enumerate(cells):
            if explicit:
                c = physical
            else:
                while (r, cursor) in occupied:
                    cursor += 1
                c = cursor
            style = cell.get('tableCellStyle', {})
            rs, cs = style.get('rowSpan'), style.get('columnSpan')
            owner = occupied.get((r, c)) if explicit else None
            result.append((r, physical, c, rs, cs, owner, cell))
            if not all(isinstance(n, int) and n > 0 for n in (rs, cs)):
                valid = False
                continue
            if owner is not None:
                # A covered physical slot must not introduce another span.
                nonempty = any(_text(item).strip() or 'table' in item
                               or any('textRun' not in e for e in
                                      item.get('paragraph', {}).get(
                                          'elements', []))
                               for item in cell.get('content', []))
                if rs != 1 or cs != 1 or nonempty:
                    valid = False
                continue
            if (r + rs > height or c + cs > width
                    or rs * cs > MAX_GRID_AREA):
                valid = False
                continue
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    if (rr, cc) in occupied:
                        valid = False
                    occupied[rr, cc] = (r, physical)
            cursor = c + cs
    valid = valid and len(occupied) == height * width
    return result, valid



MAX_GRID_AREA = 100_000

