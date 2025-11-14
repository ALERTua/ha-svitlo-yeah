"""DTEK Coordinator for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.translation import async_get_translations

from ..api.dtek import DtekAPI
from ..const import (
    CONF_GROUP,
    DOMAIN,
    REGION_SELECTION_DTEK_KEY,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
    UPDATE_INTERVAL,
)
from ..models import (
    ConnectivityState,
    PlannedOutageEventType,
)
from .coordinator import IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class DtekCoordinator(IntegrationCoordinator):
    """Class to manage fetching DTEK outages data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        self.group = config_entry.options.get(
            CONF_GROUP,
            config_entry.data.get(CONF_GROUP),
        )

        if not self.group:
            group_error = "Group configuration is required"
            LOGGER.error(group_error)
            raise ValueError(group_error)

        self.api: DtekAPI = DtekAPI(group=self.group)

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: self.translations.get(
                TRANSLATION_KEY_EVENT_PLANNED_OUTAGE
            ),
        }

    async def _async_update_data(self) -> None:
        """Fetch data from DTEK API."""
        await self.async_fetch_translations()
        await self.api.fetch_data(cache_minutes=UPDATE_INTERVAL)

    async def async_fetch_translations(self) -> None:
        """Fetch translations."""
        self.translations = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "common",
            [DOMAIN],
        )

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        return self.translations.get(REGION_SELECTION_DTEK_KEY) or ""

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        return ""

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE

        return ConnectivityState.STATE_NORMAL
