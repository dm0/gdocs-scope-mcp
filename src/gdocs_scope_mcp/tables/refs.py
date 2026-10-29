"""Resolve table positions guarded by heading scope and structural hashes."""


# Native table traversal lives in the reader; import lazily to avoid cycles.
# ruff: noqa: PLC0415
from gdocs_scope_mcp.documents.tabs import require_matching_tab, select
from gdocs_scope_mcp.tables.tokens import Token, digest, fail


def first_tab(document):
    """Retain selected views; choose the first tab only for raw documents."""
    return select(document)


def structure(item):
    """Describe rows, physical cells, spans and recursive nested-table layout.

    Text, formatting, paragraph counts, heading titles and absolute native
    indices are intentionally absent. A text-only cell replacement can add
    paragraphs without changing table structure.
    """
    table = item['table']
    return [table.get('rows'), table.get('columns'), [
        [[cell.get('tableCellStyle', {}).get('rowSpan'),
          cell.get('tableCellStyle', {}).get('columnSpan'),
          [structure(child) for child in cell.get('content', [])
           if 'table' in child]] for cell in row.get('tableCells', [])]
        for row in table.get('tableRows', [])
    ]]


def section(entry):
    """Identify the direct heading section by its ancestor ID chain."""
    return tuple(h[1] for h in entry.headings)


class Layout:
    """Cache structural state only for one freshly fetched document."""

    def __init__(self, document):
        """Group top-level tables by their nearest heading hierarchy."""
        from gdocs_scope_mcp.tables.geometry import _tables
        self.document = document
        self.entries = _tables(document)
        self.by_path = {tuple(e.path): e for e in self.entries}
        self.sections = {}
        self.shapes = {tuple(e.path): digest(structure(e.item))
                       for e in self.entries}
        for entry in self.entries:
            if entry.parent_cell is None:
                self.sections.setdefault(section(entry), []).append(entry)
        self.inventories = {key: digest([
            self.shapes[tuple(e.path)] for e in entries
        ]) for key, entries in self.sections.items()}

    def reference(self, entry, *, kind='table', address=None):
        """Describe a section ordinal and optional nested position."""
        root = self.by_path[(entry.path[0],)]
        peers = self.sections[section(root)]
        nested = []
        parent = root
        for offset in range(1, len(entry.path), 3):
            row, cell, index = entry.path[offset:offset + 3]
            content = parent.item['table']['tableRows'][row]['tableCells'][
                cell]['content']
            indices = [i for i, item in enumerate(content) if 'table' in item]
            nested.append([row, cell, indices.index(index)])
            parent = self.by_path[tuple(entry.path[:offset + 3])]
        return Token(
            kind=kind, document=self.document['documentId'],
            tab=self.document.get('_mcp_tab_id'), section=list(section(root)),
            ordinal=next(i for i, peer in enumerate(peers)
                         if peer.path == root.path), nested=nested,
            structure=self.shapes[tuple(entry.path)],
            inventory=self.inventories[section(root)], address=address,
        )

    def resolve(self, token):
        """Validate section structure before following its table ordinal."""
        require_matching_tab(token.tab, self.document.get('_mcp_tab_id'))
        key = tuple(token.section)
        peers = self.sections.get(key, [])
        if (self.inventories.get(key) != token.inventory
                or token.ordinal >= len(peers)):
            fail('TARGET_CHANGED', 'The section table count/order/structure '
                 'changed, or its heading hierarchy no longer exists.')
        entry = peers[token.ordinal]
        for row, cell, ordinal in token.nested:
            try:
                content = entry.item['table']['tableRows'][row][
                    'tableCells'][cell]['content']
                indices = [i for i, item in enumerate(content)
                           if 'table' in item]
                path = (*entry.path, row, cell, indices[ordinal])
                entry = self.by_path[path]
            except (IndexError, KeyError):
                fail('TARGET_CHANGED', 'The nested table position changed.')
        if self.shapes[tuple(entry.path)] != token.structure:
            fail('TARGET_CHANGED', 'The target table structure changed.')
        return entry
