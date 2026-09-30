"""
Mark every test in this folder as e2e, and give each e2e test the real network.

The default run deselects the e2e marker.
"""

import socket
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent

# The Home Assistant test plugin blocks sockets and DNS before each test.
# The collection imports this file before the first test starts, so these
# are still the real functions.
_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.socket.connect
_REAL_DNS = {
    name: getattr(socket, name)
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex")
}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add the e2e marker before the ``-m`` option deselects items."""
    for item in items:
        if item.path.is_relative_to(E2E_DIR):
            item.add_marker(pytest.mark.e2e)


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Put the real network back after the plugin blocked it for this test."""
    if not item.path.is_relative_to(E2E_DIR):
        return
    socket.socket = _REAL_SOCKET
    socket.socket.connect = _REAL_CONNECT
    for name, function in _REAL_DNS.items():
        setattr(socket, name, function)
