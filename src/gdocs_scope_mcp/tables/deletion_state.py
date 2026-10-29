"""Hash native data removed by a structural operation, excluding indices."""


from gdocs_scope_mcp.revision_guards import _normalized
from gdocs_scope_mcp.tables.style_state import cell_at, property_state
from gdocs_scope_mcp.tables.tokens import digest


def deletion_state(document, entry, row, column, *, logical_column=None,
                   borders=None):
    """Protect a removed cell, its metadata and effective formatting."""
    cell = cell_at(entry, row, column)
    table = entry.item['table']
    styles = dict(table.get('tableStyle', {}))
    columns = styles.pop('tableColumnProperties', [])
    ranges = []
    start, end = cell['startIndex'], cell['endIndex']
    for group in document.get('namedRanges', {}).values():
        for item in group.get('namedRanges', []):
            overlapping = [
                {**r, 'startIndex': r.get('startIndex', 0) - start,
                 'endIndex': r.get('endIndex', 0) - start}
                for r in item.get('ranges', [])
                if r.get('startIndex', 0) < end
                and start < r.get('endIndex', 0)
            ]
            if overlapping:
                ranges.append([item.get('namedRangeId'), item.get('name'),
                               overlapping])
    # Body indices move after unrelated text edits; footnote/object metadata
    # remains part of the deletion footprint when referenced from this cell.
    extra, seen, kinds = [], set(), {'NORMAL_TEXT'}

    def referenced(collection, identifier):
        """Follow the metadata closure once, including cycles safely."""
        key = collection, identifier
        if key in seen:
            return
        seen.add(key)
        metadata = document.get(collection, {}).get(identifier)
        extra.append([collection, identifier, metadata])
        collect(metadata)

    def collect(value):
        """Include indirect object/list/dropdown/footnote contents."""
        if isinstance(value, dict):
            for key, child in value.items():
                collection = {
                    'footnoteId': 'footnotes', 'listId': 'lists',
                    'inlineObjectId': 'inlineObjects',
                    'dropdownDefinitionId': 'dropdownDefinitions',
                }.get(key)
                if collection:
                    referenced(collection, child)
                elif key == 'positionedObjectIds':
                    for identifier in child:
                        referenced('positionedObjects', identifier)
                elif key == 'namedStyleType':
                    kinds.add(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(cell)
    named = [s for s in document.get('namedStyles', {}).get('styles', [])
             if s.get('namedStyleType') in kinds]
    return digest([
        _normalized(cell),
        _normalized(extra), named, sorted(ranges), styles,
        table['tableRows'][row].get('tableRowStyle', {}),
        columns[logical_column if logical_column is not None else column]
        if (logical_column if logical_column is not None else column) < len(
            columns) else {},
        borders if borders is not None else [
            property_state(entry, row, column, 'cell.border_' + side)
            for side in ('top', 'bottom', 'left', 'right')
        ],
    ])
