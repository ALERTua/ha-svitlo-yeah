"""Base class for DTEK JSON oordinator implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...api.dtek.json import DtekAPIJson
from ...models import DTEK_PROVIDER_URLS
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
        self.api = DtekAPIJson(DTEK_PROVIDER_URLS[self.provider_id], self.group)
