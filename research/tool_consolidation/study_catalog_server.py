"""Expose four research catalogs without experimental product settings."""

import os

from gdocs_scope_mcp.server import create_server, run_server

VARIANT = os.environ['GDOCS_STUDY_TOOL_INTERFACE_VARIANT']
if VARIANT not in {'baseline', 'insertion', 'status', 'both'}:
    raise ValueError('Unknown research tool interface variant')
mcp = create_server(consolidate_insertion=VARIANT in {'insertion', 'both'},
                    consolidate_status=VARIANT in {'status', 'both'})


def main():
    """Serve this isolated research catalog over STDIO."""
    run_server(mcp)


if __name__ == '__main__':
    main()
