"""JSON-based DTEK API implementation using alternative data sources."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import aiohttp

from ...const import DTEK_FRESH_DATA_DAYS
from .base import DtekAPIBase

LOGGER = logging.getLogger(__name__)

_UPDATE_DATE_FORMATS = (
    "%d.%m.%Y %H:%M",  # DD.MM.YYYY HH:MM
    "%H:%M %d.%m.%Y",  # HH:MM DD.MM.YYYY
)


def _parse_update_dt(update_dt: str | None) -> datetime | None:
    """Parse the `update` field into an aware datetime, or return None."""
    if not update_dt:
        return None
    for fmt in _UPDATE_DATE_FORMATS:
        try:
            return datetime.strptime(update_dt, fmt).astimezone(UTC)
        except ValueError:
            continue
    return None


def _is_data_sufficiently_fresh(json_data: dict) -> bool:
    """Check if update_dt is within DTEK_FRESH_DATA_DAYS days."""
    parsed_dt = _parse_update_dt(json_data.get("update"))
    if parsed_dt is None:
        return False
    age_days = (datetime.now(UTC) - parsed_dt).days
    return age_days <= DTEK_FRESH_DATA_DAYS


class DtekAPIJson(DtekAPIBase):
    """DTEK API for JSON sources (GitHub raw files, etc.)."""

    def __init__(self, urls: list[str], group: str | None = None) -> None:
        """Initialize the JSON DTEK API."""
        super().__init__(group)
        self.urls = urls
        self.preset_data = None

    async def fetch_data(
        self,
        *,
        allow_stale_data: bool = False,
    ) -> tuple[bool, bool]:
        """
        Fetch from JSON sources with freshness checking.

        Returns (success, is_stale):
        - success: whether self.data was populated.
        - is_stale: True only when success is True and the data came
          from a stale source (only possible with allow_stale_data=True).

        When allow_stale_data is False, behavior matches the historical
        contract: stale data is rejected and self.data stays unchanged
        if no fresh source is found.
        """
        stale_fact: dict | None = None
        stale_preset: dict | None = None
        stale_update_dt: datetime | None = None

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
                        return True, False

                    candidate_dt = _parse_update_dt(fact.get("update"))
                    if candidate_dt is not None and (
                        stale_update_dt is None or candidate_dt > stale_update_dt
                    ):
                        stale_fact = fact
                        stale_preset = preset
                        stale_update_dt = candidate_dt
                    LOGGER.debug(
                        "Data from %s is stale (>%d days), trying next source",
                        url,
                        DTEK_FRESH_DATA_DAYS,
                    )

            except Exception as e:  # noqa: BLE001
                LOGGER.debug("Failed to fetch from %s: %s", url, e)
                continue

        if stale_fact is None:
            LOGGER.debug("All JSON sources failed; no data available")
            return False, False

        if not allow_stale_data:
            LOGGER.debug(
                "All JSON sources returned stale data; "
                "allow_stale_data is False, discarding"
            )
            return False, False

        self.data = stale_fact
        self.preset_data = stale_preset
        LOGGER.debug(
            "Using stale data (updated %s) as explicit fallback", stale_update_dt
        )
        return True, True
