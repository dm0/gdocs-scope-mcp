"""Expose safe no-op operations with copied production MCP annotations."""

import json
import os
from pathlib import Path

from fastmcp import FastMCP

ROOT = Path(os.environ['GDOCS_NATIVE_PROBE_DIR'])
SPEC = json.loads((ROOT / 'fixture.json').read_text())
mcp = FastMCP('native-approval-fixture')


def register(name, annotations):
    """Record a synthetic execution, confined to the test journal."""

    @mcp.tool(name=name, annotations=annotations)
    def operation(nonce: str) -> dict:
        """Return the test nonce and append one local journal entry."""
        record = {'tool': name, 'nonce': nonce, 'pid': os.getpid()}
        with (ROOT / 'executions.jsonl').open('a') as output:
            output.write(json.dumps(record) + '\n')
        return {'ok': True, **record}


for tool_name, metadata in SPEC.items():
    register(tool_name, metadata['annotations'])


if __name__ == '__main__':
    (ROOT / 'fixture-process.json').write_text(
        json.dumps({'pid': os.getpid()})
    )
    mcp.run(transport='stdio', show_banner=False)
