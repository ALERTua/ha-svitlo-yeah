"""Base class for DTEK JSON oordinator implementations."""

import logging
from typing import TYPE_CHECKING

from ...api.dtek.json import DtekAPIJson
from ...const import DTEK_PROVIDER_URLS
from .base import DtekCoordinatorBase

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class DtekCoordinatorJson(DtekCoordinatorBase):
    """Class to manage fetching DTEK outage data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the DtekCoordinatorBase class."""
        super().__init__(hass=hass, config_entry=config_entry)
        self.api = DtekAPIJson(hass, DTEK_PROVIDER_URLS[self.provider_id], self.group)

    def _source_data(self) -> dict | None:
        """Keep the fact and the preset schedule that the API reads."""
        if self.api.data is None:
            return None
        return {"fact": self.api.data, "preset": self.api.preset_data}

    def _restore_source_data(self, source: dict) -> None:
        """Give the kept schedule back to the API, until the source is fresh."""
        self.api.data = source.get("fact")
        self.api.preset_data = source.get("preset")
