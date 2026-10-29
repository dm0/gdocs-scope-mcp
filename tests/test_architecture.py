"""Enforce package boundaries for eager and deferred Python imports."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'src/gdocs_scope_mcp'
PREFIX = 'gdocs_scope_mcp'


def import_graph():
    """Resolve all local imports, including imports nested in functions."""
    paths = {}
    for path in ROOT.rglob('*.py'):
        parts = path.relative_to(ROOT).with_suffix('').parts
        if parts[-1] == '__init__':
            parts = parts[:-1]
        paths['.'.join([PREFIX, *parts])] = path
    graph = {name: set() for name in paths}
    for name, path in paths.items():
        parent = name.rpartition('.')[0]
        if parent in paths:
            graph[name].add(parent)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                parent = node.module or ''
                if node.level:
                    package = (name.split('.') if path.name == '__init__.py'
                               else name.split('.')[:-1])
                    depth = len(package) - node.level + 1
                    parent = '.'.join(package[:depth]
                                      + ([parent] if parent else []))
                targets = [parent, *[parent + '.' + a.name
                                     for a in node.names]]
            else:
                continue
            graph[name].update(t for t in targets if t in paths)
    return graph


def test_all_imports_are_acyclic():
    """Reject cycles even when deferred imports conceal them at startup."""
    graph = import_graph()
    visited = set()

    def visit(node, stack):
        assert node not in stack, ' -> '.join([*stack, node])
        if node in visited:
            return
        for dependency in sorted(graph[node]):
            visit(dependency, [*stack, node])
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])


def test_transport_dependencies_stay_at_the_boundary():
    """Lower layers must not depend on MCP adapters or FastMCP."""
    allowed = {'server', '__main__', 'tool_logging', 'tool_errors'}
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == 'tools' or path.stem in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names]
                     if isinstance(node, ast.Import) else
                     [node.module or ''] if isinstance(node, ast.ImportFrom)
                     else [])
            for name in names:
                assert not name.startswith(('fastmcp', 'mcp.',
                                            PREFIX + '.tools',
                                            PREFIX + '.server',
                                            PREFIX + '.tool_errors')), relative


def test_pure_rich_text_has_no_execution_dependencies():
    """Parsers and plans must remain usable without an API execution layer."""
    pure = {'models', 'validation', 'paragraphs', 'paragraph_requests',
            'cells', 'parsing', 'plans', 'compiler'}
    prohibited = {'google_api', 'revision_guards', 'entity_edit',
                  'rich_text.execution', 'rich_text.insertion',
                  'rich_text.image_uploads', 'documents.editing'}
    graph = import_graph()
    for module in pure:
        node = PREFIX + '.rich_text.' + module
        assert not any(dep == PREFIX + '.' + target
                       or dep.startswith(PREFIX + '.' + target + '.')
                       for dep in graph[node] for target in prohibited)


def test_shared_utilities_stay_below_feature_operations():
    """Keep table geometry/references and document source mapping reusable."""
    graph = import_graph()
    foundational = {
        'tables.geometry', 'tables.refs', 'tables.references', 'tables.tokens',
        'tables.grid', 'tables.style_state', 'tables.deletion_state',
        'documents.parsing', 'documents.targeting', 'documents.native_models',
        'documents.rendering', 'documents.snapshots',
    }
    prohibited = {
        'documents.editing', 'documents.reading', 'tables.reading',
        'tables.patch', 'tables.formatting', 'tables.structure',
        'tables.merge', 'suggestions.writing', 'rich_text.insertion',
    }
    for name in foundational:
        assert not (graph[PREFIX + '.' + name]
                    & {PREFIX + '.' + p for p in prohibited}), name


def test_shared_apis_do_not_import_private_helpers():
    """Cross-module consumers use explicit internal APIs."""
    for path in ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.ImportFrom)
                    and (node.module or '').startswith(PREFIX)):
                assert not any(a.name.startswith('_') for a in node.names), (
                    path.relative_to(ROOT), node.lineno,
                )
