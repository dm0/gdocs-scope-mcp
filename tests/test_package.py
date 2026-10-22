"""Check installed entry points without starting or authenticating."""

from importlib.metadata import distribution

from google_docs_mcp import auth_setup, server


def test_current_and_legacy_entry_points_load():
    """Both command names resolve to the installed package's entry points."""
    expected = {
        'google-docs-mcp': server.main,
        'google-docs-mcp-auth': auth_setup.main,
        'google-drive-mcp': server.main,
        'google-drive-mcp-auth': auth_setup.main,
    }
    entry_points = {
        entry.name: entry
        for entry in distribution('google-docs-mcp').entry_points
        if entry.group == 'console_scripts'
    }

    for name, target in expected.items():
        assert entry_points[name].load() is target
