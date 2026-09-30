"""Shared helpers that fake the aiohttp responses of the DTEK JSON sources."""

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson


def make_response(payload: dict | None = None, *, raise_error: bool = False):
    """Build a mocked aiohttp response yielding `payload` from .text()."""
    resp = AsyncMock()
    if raise_error:
        resp.raise_for_status = MagicMock(side_effect=Exception("Connection failed"))
    else:
        resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value=json.dumps(payload) if payload is not None else ""
    )
    return resp


def get_cm(response):
    """Wrap a response in an async context manager (as ``session.get`` returns)."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def set_session_responses(api: DtekAPIJson, responses: list) -> None:
    """Configure ``api.session.get`` so each URL fetch yields the next response."""
    api.session.get = MagicMock(side_effect=[get_cm(r) for r in responses])
