"""JSON-based DTEK API implementation using alternative data sources."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import aiohttp

from ...const import DTEK_FRESH_DATA_DAYS
from .base import DtekAPIBase

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

    async def fetch_data(self) -> None:
        """Fetch from JSON sources with freshness checking."""
        for url in self.urls:
            try:
                async with aiohttp.ClientSession() as session:
                    response = await session.get(url, timeout=10)
                    response.raise_for_status()
                    json_data = await response.text()
                    json_data = json.loads(json_data)

                    fact = json_data["fact"]
                    if _is_data_sufficiently_fresh(fact):
                        self.data = fact
                        LOGGER.debug("Successfully fetched fresh data from %s", url)
                        return

                    LOGGER.debug(
                        "Data from %s is stale (>2 days), trying next source", url
                    )

            except Exception as e:  # noqa: BLE001
                LOGGER.debug("Failed to fetch from %s: %s", url, e)
                continue

        # All sources failed/stale - use most recent data if available
        if self.data is None:
            LOGGER.debug("All JSON sources failed or returned stale data")
        else:
            LOGGER.debug(
                "Using stale data as fallback since no fresh sources available"
            )
