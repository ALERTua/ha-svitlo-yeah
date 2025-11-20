"""Base class for DTEK Coordinator implementations."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_utils

from ...const import (
    CONF_GROUP,
    CONF_PROVIDER,
    DEBUG,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from ...models import (
    ConnectivityState,
    PlannedOutageEventType,
)
from ..coordinator import IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ...api.dtek.base import DtekAPIBase

LOGGER = logging.getLogger(__name__)


class DtekCoordinatorBase(IntegrationCoordinator):
    """Class to manage fetching DTEK outages data."""

    config_entry: ConfigEntry
    api: DtekAPIBase

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        # Get configuration
        self.provider_id = config_entry.options.get(
            CONF_PROVIDER,
            config_entry.data.get(CONF_PROVIDER),
        )
        if not self.provider_id:
            provider_required_msg = (
                "Provider not set in configuration - this should not happen "
                "with proper config flow"
            )
            provider_error = "Provider configuration is required"
            LOGGER.error(provider_required_msg)
            raise ValueError(provider_error)

        self.group = config_entry.options.get(
            CONF_GROUP,
            config_entry.data.get(CONF_GROUP),
        )
        if not self.group:
            group_required_msg = (
                "Group not set in configuration - this should not happen "
                "with proper config flow"
            )
            group_error = "Group configuration is required"
            LOGGER.error(group_required_msg)
            raise ValueError(group_error)

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

        # Coordinator-level caching (per provider)
        now = dt_utils.now()
        await self.api.fetch_data()
        LOGGER.debug("Fetched fresh data for %s", self)

        # Check if outage data has changed (used for last_data_change attribute)
        current_events = self.api.get_events(now, now + datetime.timedelta(hours=24))
        self.check_outage_data_changed(current_events)

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        if DEBUG:
            LOGGER.debug(
                "Getting translation for %s from %s",
                self.provider_id,
                self.translations,
            )
        key = f"component.svitlo_yeah.common.{self.provider_id}"
        return self.translations.get(key)

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        return ""

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE

        return ConnectivityState.STATE_NORMAL
