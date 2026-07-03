"""JSON-based DTEK API implementation using alternative data sources."""

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant

from ...const import DTEK_FRESH_DATA_DAYS
from .base import DtekAPIBase, FetchResult

LOGGER = logging.getLogger(__name__)


_UPDATE_DATE_FORMATS = (
    "%d.%m.%Y %H:%M",  # DD.MM.YYYY HH:MM
    "%H:%M %d.%m.%Y",  # HH:MM DD.MM.YYYY
)


def _parse_update_dt(update_dt: str | None) -> datetime | None:
    """Parse the ``update`` field into an aware UTC datetime, or None."""
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

    def __init__(
        self, hass: HomeAssistant, urls: list[str], group: str | None = None
    ) -> None:
        """Initialize the JSON DTEK API."""
        super().__init__(group)
        self.hass = hass
        self.session: aiohttp.ClientSession = async_get_clientsession(hass)
        self.urls = urls
        self.preset_data = None

    async def fetch_data(self, *, allow_stale_data: bool = False) -> FetchResult:
        """
        Fetch from JSON sources with freshness checking.

        Returns a :class:`FetchResult` so callers can tell apart three cases
        that would otherwise all collapse to ``data is None``:

        - ``FRESH``: a source returned data within the freshness window; it is
          stored in ``self.data``.
        - ``STALE``: sources responded, but all data is older than allowed.
          Only when ``allow_stale_data`` is True is the freshest stale source
          adopted into ``self.data`` (explicit setup consent); otherwise
          ``self.data`` is left untouched so stale data is never served at
          runtime.
        - ``UNAVAILABLE``: no source could be fetched/parsed at all.
        """
        stale_fact: dict | None = None
        stale_preset: dict | None = None
        stale_update_dt: datetime | None = None

        for url in self.urls:
            try:
                async with self.session.get(url, timeout=10) as response:
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
            LOGGER.debug("All JSON sources failed or were unreachable")
            return FetchResult.UNAVAILABLE

        if allow_stale_data:
            self.data = stale_fact
            self.preset_data = stale_preset
            LOGGER.debug(
                "Adopted stale data (updated %s) under explicit consent",
                stale_update_dt,
            )
        else:
            LOGGER.debug("All JSON sources returned stale data; not adopting")
        return FetchResult.STALE
