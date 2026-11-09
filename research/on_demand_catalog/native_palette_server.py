"""Serve the unchanged product catalog with a research-only execution guard."""

import json
import os
from pathlib import Path

from fastmcp.server.middleware import Middleware

from gdocs_scope_mcp.server import create_server, run_server

ALLOWED = {'server_info', 'docs_get_color_palette'}
MAX_CALLS = 6


class PaletteGuard(Middleware):
    """Block document/account operations while retaining their descriptors."""

    def __init__(self, directory):
        """Confine all execution evidence to the private run directory."""
        self.directory = directory
        self.count = 0

    async def on_call_tool(self, context, call_next):
        """Reject out-of-scope requests before any application operation."""
        name = context.message.name
        self.count += 1
        allowed = name in ALLOWED and self.count <= MAX_CALLS
        with (self.directory / 'calls.jsonl').open('a') as journal:
            journal.write(json.dumps({'tool': name, 'allowed': allowed,
                                      'pid': os.getpid()}) + '\n')
        if not allowed:
            raise ValueError('Only bounded palette and identity reads allowed')
        return await call_next(context)


def main():
    """Launch a dedicated native STDIO server for one compatibility trial."""
    directory = Path(os.environ['GDOCS_PALETTE_RUN_DIR'])
    (directory / 'process.json').write_text(json.dumps({'pid': os.getpid()}))
    server = create_server(consolidate_insertion=True, consolidate_status=True)
    server.add_middleware(PaletteGuard(directory))
    run_server(server)


if __name__ == '__main__':
    main()
