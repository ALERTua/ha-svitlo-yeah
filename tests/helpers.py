"""Shared helpers that fake the aiohttp responses of the provider sources."""

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson


def make_response(payload: dict | list | None = None, *, raise_error: bool = False):
    """
    Build a mocked aiohttp response that yields `payload`.

    DTEK JSON sources read the payload with ``.text()``, and Yasno reads it with
    ``.json()``, so the response answers both.
    """
    resp = AsyncMock()
    if raise_error:
        resp.raise_for_status = MagicMock(side_effect=Exception("Connection failed"))
    else:
        resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value=json.dumps(payload) if payload is not None else ""
    )
    resp.json = AsyncMock(return_value=payload)
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


def fake_session(routes: dict[str, dict | list]) -> MagicMock:
    """
    Build a session whose ``get(url)`` answers with ``routes[url]``.

    A URL that is not in ``routes`` raises KeyError. A caller that does not
    catch it fails the test. ``DtekAPIJson.fetch_data`` catches each error of
    a source, so for DTEK a missing route becomes ``FetchResult.UNAVAILABLE``.
    """
    session = MagicMock()
    session.get = MagicMock(
        side_effect=lambda url, **_: get_cm(make_response(routes[url]))
    )
    return session
