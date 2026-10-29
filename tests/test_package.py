"""Check installed entry points without starting or authenticating."""


from importlib.metadata import distribution

from gdocs_scope_mcp import auth_setup, server


def test_renamed_entry_points_load():
    """New commands resolve to the installed package's entry points."""
    expected = {
        'gdocs-scope-mcp': server.main,
        'gdocs-scope-mcp-auth': auth_setup.main,
    }
    entry_points = {
        entry.name: entry
        for entry in distribution('gdocs-scope-mcp').entry_points
        if entry.group == 'console_scripts'
    }

    assert set(entry_points) == set(expected)
    for name, target in expected.items():
        assert entry_points[name].load() is target
