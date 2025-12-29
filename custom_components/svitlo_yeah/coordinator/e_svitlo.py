"""E-Svitlo coordinator for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_utils

from ..api.e_svitlo import ESvitloClient
from ..const import (
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from ..models import ConnectivityState, ESvitloProvider, PlannedOutageEventType
from .coordinator import IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class ESvitloCoordinator(IntegrationCoordinator):
    """Coordinator for E-Svitlo API integration."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the E-Svitlo coordinator."""
        super().__init__(hass, config_entry)

        # Create provider from config entry data
        self.provider: ESvitloProvider = ESvitloProvider(
            user_name=config_entry.data["username"],
            password=config_entry.data["password"],
            account_id=config_entry.data.get("account_id"),
        )

        # Initialize API client
        self.api: ESvitloClient = ESvitloClient(hass, self.provider)

        # Set group to auto - will be updated after first API call
        self.group = "auto"

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        return self.provider.region_name

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        return self.config_entry.data.get(
            "address_str",
            f"E-Svitlo ({self.provider.user_name})",  # ty:ignore[unresolved-attribute]
        )

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: self.translations.get(
                TRANSLATION_KEY_EVENT_PLANNED_OUTAGE
            ),
            PlannedOutageEventType.EMERGENCY: self.translations.get(
                TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE
            ),
        }

    async def _async_update_data(self) -> None:  # ty:ignore[invalid-method-override]
        """Fetch data from E-Svitlo API."""
        LOGGER.debug("Updating E-Svitlo data")

        # Fetch translations
        await self.async_fetch_translations()

        # Ensure we have user info (including group) before fetching disconnections
        if isinstance(self.api, ESvitloClient):
            if not self.api.user_id or not self.api.group:
                await self.api.get_user_info()

            # Update group from API if available
            if self.api.group:
                self.group = self.api.group

            # Get disconnections data
            events = await self.api.get_disconnections()

            if events is not None:
                LOGGER.debug(
                    "Successfully updated E-Svitlo data with %d events", len(events)
                )
                # Check if outage data has changed
                now = dt_utils.now()
                current_events = self.api.get_events(now, now + timedelta(hours=24))
                self.check_outage_data_changed(current_events)
            else:
                LOGGER.warning("Failed to fetch E-Svitlo data")
                # Keep existing data if fetch fails

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        LOGGER.debug("Esvitlo _event_to_state: no event, setting electricity to None")
        return None

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.debug("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL
