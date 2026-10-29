"""Verify the optional CI network allow-list rejects external connections."""

import socket

import pytest
from pytest_socket import SocketBlockedError, SocketConnectBlockedError


def test_ci_blocks_external_connections(request):
    """Require the CI flags to reject a reserved external address locally."""
    if not request.config.getoption('--disable-socket'):
        pytest.skip('Only relevant when the offline CI flags are enabled.')
    # TEST-NET-1 is a documentation-only address, not a Google endpoint.
    with (
        pytest.raises((SocketBlockedError, SocketConnectBlockedError)),
        socket.create_connection(('192.0.2.1', 443), timeout=0.01),
    ):
        pytest.fail('The CI network guard allowed an external socket.')
