"""JSON-based DTEK API implementation using alternative data sources."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import aiohttp

from ...const import DTEK_FRESH_DATA_DAYS
from .base import DtekAPIBase, FetchResult

LOGGER = logging.getLogger(__name__)


def _is_data_sufficiently_fresh(json_data: dict) -> bool:
    """Check if update_dt is within DTEK_FRESH_DATA_DAYS days."""
    update_dt = json_data.get("update")
    if not update_dt:
        return False

    date_formats = [
        "%d.%m.%Y %H:%M",  # DD.MM.YYYY HH:MM
        "%H:%M %d.%m.%Y",  # HH:MM DD.MM.YYYY
    ]

    for fmt in date_formats:
        try:
            parsed_dt = datetime.strptime(update_dt, fmt).astimezone(UTC)
            age_days = (datetime.now(UTC) - parsed_dt).days
            return age_days <= DTEK_FRESH_DATA_DAYS  # noqa: TRY300
        except ValueError:
            continue

    return False


class DtekAPIJson(DtekAPIBase):
    """DTEK API for JSON sources (GitHub raw files, etc.)."""

    def __init__(self, urls: list[str], group: str | None = None) -> None:
        """Initialize the JSON DTEK API."""
        super().__init__(group)
        self.urls = urls
        self.preset_data = None

    async def fetch_data(self) -> FetchResult:
        """
        Fetch from JSON sources with freshness checking.

        Returns the outcome so callers can tell apart three cases that would
        otherwise all look like ``data is None``:

        - ``FRESH``: a source returned data within the freshness window; it is
          stored in ``self.data``.
        - ``STALE``: at least one source responded, but all of it is too old.
          ``self.data`` is left untouched (any previously cached fresh data is
          kept) - we deliberately do not adopt stale data automatically.
        - ``UNAVAILABLE``: no source could be fetched/parsed at all.
        """
        saw_stale = False
        for url in self.urls:
            try:
                async with aiohttp.ClientSession() as session:
                    response = await session.get(url, timeout=10)
                    response.raise_for_status()
                    json_data = await response.text()
                    json_data = json.loads(json_data)

                    fact = json_data["fact"]
                    preset = json_data.get("preset", {})
                    if _is_data_sufficiently_fresh(fact):
                        self.data = fact
                        self.preset_data = preset
                        LOGGER.debug("Successfully fetched fresh data from %s", url)
                        return FetchResult.FRESH

                    saw_stale = True
                    LOGGER.debug(
                        "Data from %s is stale (>2 days), trying next source", url
                    )

            except Exception as e:  # noqa: BLE001
                LOGGER.debug("Failed to fetch from %s: %s", url, e)
                continue

        if saw_stale:
            LOGGER.debug("All JSON sources responded but returned stale data")
            return FetchResult.STALE

        LOGGER.debug("All JSON sources failed or were unreachable")
        return FetchResult.UNAVAILABLE
