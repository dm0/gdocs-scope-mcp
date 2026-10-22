"""Capture process identity and the package's source snapshot at startup."""

import hashlib
import os
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ServerInfo(BaseModel):
    """Identity of the running server, independent of Google authentication."""

    model_config = ConfigDict(frozen=True)

    package_version: str
    source_fingerprint: str
    started_at: datetime
    pid: int
    package_path: str
    python_executable: str
    python_version: str
    fastmcp_version: str


def capture_server_info(package_path: Path | None = None) -> ServerInfo:
    """Snapshot package source and environment before serving tool requests."""
    package_path = (package_path or Path(__file__).parent).resolve()
    digest = hashlib.sha256()
    for path in sorted(package_path.rglob('*.py')):
        digest.update(path.relative_to(package_path).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return ServerInfo(
        package_version=version('google-docs-mcp'),
        source_fingerprint=digest.hexdigest(),
        started_at=datetime.now(timezone.utc),
        pid=os.getpid(),
        package_path=str(package_path),
        python_executable=sys.executable,
        python_version=platform.python_version(),
        fastmcp_version=version('fastmcp'),
    )
