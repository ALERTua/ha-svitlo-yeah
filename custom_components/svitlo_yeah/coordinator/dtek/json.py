"""Base class for DTEK JSON oordinator implementations."""

import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryError

from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson
from custom_components.svitlo_yeah.const import DOMAIN, DTEK_PROVIDER_URLS

from .base import DtekCoordinatorBase

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class DtekCoordinatorJson(DtekCoordinatorBase):
    """Class to manage fetching DTEK outage data."""

    api: DtekAPIJson

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the DtekCoordinatorBase class."""
        super().__init__(hass=hass, config_entry=config_entry)
        urls = DTEK_PROVIDER_URLS.get(self.provider_id)
        if not urls:
            # For example a source that a later version of the integration removed
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="unknown_dtek_provider",
                translation_placeholders={"provider": str(self.provider_id)},
            )
        self.api = DtekAPIJson(hass, urls, self.group)

    def _source_data(self) -> dict | None:
        """Keep the fact and the preset schedule that the API reads."""
        if self.api.data is None:
            return None
        return {"fact": self.api.data, "preset": self.api.preset_data}

    def _restore_source_data(self, source: dict) -> None:
        """Give the kept schedule back to the API, until the source is fresh."""
        self.api.data = source.get("fact")
        self.api.preset_data = source.get("preset")
