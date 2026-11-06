"""Expose production MCP tools against one isolated deterministic fixture."""

import json
import os
from pathlib import Path

from study_fixture_api import FixtureAPI

from gdocs_scope_mcp.google_api import clients
from gdocs_scope_mcp.server import main, mcp

SPECIFICATION = json.loads(Path(os.environ['GDOCS_STUDY_FIXTURE']).read_text())
API = FixtureAPI(SPECIFICATION)


def fixture_service(*_args, **_kwargs):
    """Replace only the Google client seam, never application operations."""
    return API


clients.get_service = fixture_service


@mcp.tool
def study_native_snapshot() -> dict:
    """Read synthetic state for the controller, never the evaluated model."""
    return API.snapshot()


if __name__ == '__main__':
    main()
