"""
Load the Home Assistant test plugin, also on Windows.

The plugin imports ``homeassistant.runner``, which imports the POSIX-only
modules ``fcntl`` and ``resource``. On Windows this file puts stubs of these
modules in place first, and then loads the plugin. The ``-p no:homeassistant``
option in ``pyproject.toml`` stops the entry point of the plugin, because the
entry point imports the plugin before any conftest runs. pytest reads
``pytest_plugins`` only in the conftest of the root folder.
"""

import socket
import sys
import types
from typing import Any

if sys.platform == "win32":
    # Only the names that Home Assistant uses. The tests never take the lock
    # of the config folder and never change the limit of open files.
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_NB = 4
    fcntl.flock = lambda *_args: None
    sys.modules.setdefault("fcntl", fcntl)

    resource = types.ModuleType("resource")
    resource.RLIMIT_NOFILE = 7
    resource.getrlimit = lambda *_args: (8192, 8192)
    resource.setrlimit = lambda *_args: None
    sys.modules.setdefault("resource", resource)

    _real_socket = socket.socket
    _real_socketpair = socket.socketpair

    def _socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        """
        Make the socket pair of an event loop with the real socket class.

        On Windows the pair is two TCP sockets on 127.0.0.1. The plugin blocks
        the creation of such sockets in each test, and then no event loop starts.
        """
        blocked_socket = socket.socket
        socket.socket = _real_socket
        try:
            return _real_socketpair(*args, **kwargs)
        finally:
            socket.socket = blocked_socket

    socket.socketpair = _socketpair

pytest_plugins = "pytest_homeassistant_custom_component.plugins"
