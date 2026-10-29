"""Enforce package boundaries for eager and deferred Python imports."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'src/gdocs_scope_mcp'
PREFIX = 'gdocs_scope_mcp'


def import_graph():
    """Resolve all local imports, including imports nested in functions."""
    paths = {PREFIX + '.' + '.'.join(
        p.relative_to(ROOT).with_suffix('').parts): p
             for p in ROOT.rglob('*.py')}
    graph = {name: set() for name in paths}
    for name, path in paths.items():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                parent = node.module or ''
                if node.level:
                    parent = '.'.join(name.split('.')[:-node.level]
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
