"""Base class for DTEK HTML oordinator implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...api.dtek.html import DtekAPIHtml
from .base import DtekCoordinatorBase

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class DtekCoordinatorHtml(DtekCoordinatorBase):
    """Class to manage fetching DTEK outage data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the DtekCoordinatorBase class."""
        super().__init__(hass=hass, config_entry=config_entry)
        self.api = DtekAPIHtml(self.group)
