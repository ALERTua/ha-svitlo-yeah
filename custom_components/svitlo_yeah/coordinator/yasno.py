"""Coordinator for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

import datetime

from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_utils

from ..api.yasno import YasnoApi
from ..const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_REGION,
    DEBUG,
    DOMAIN,
    PROVIDER_DTEK_FULL,
    PROVIDER_DTEK_SHORT,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from ..models import (
    ConnectivityState,
    PlannedOutageEventType,
    YasnoProvider,
    YasnoRegion,
)
from .coordinator import IntegrationCoordinator

LOGGER = logging.getLogger(__name__)


def _simplify_provider_name(provider_name: str) -> str:
    """Simplify provider names for cleaner display in device names."""
    # Replace long DTEK provider names with just "ДТЕК"
    if PROVIDER_DTEK_FULL in provider_name.upper():
        return PROVIDER_DTEK_SHORT

    # Add more provider simplifications here as needed
    return provider_name


class YasnoCoordinator(IntegrationCoordinator):
    """Class to manage fetching Yasno outages data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        # Get configuration values
        self.region_id = config_entry.options.get(
            CONF_REGION,
            config_entry.data.get(CONF_REGION),
        )
        self.provider_id = config_entry.options.get(
            CONF_PROVIDER,
            config_entry.data.get(CONF_PROVIDER),
        )
        self.group = config_entry.options.get(
            CONF_GROUP,
            config_entry.data.get(CONF_GROUP),
        )

        if not self.region_id:
            region_required_msg = (
                "Region not set in configuration - this should not happen "
                "with proper config flow"
            )
            region_error = "Region configuration is required"
            LOGGER.error(region_required_msg)
            raise ValueError(region_error)

        if not self.provider_id:
            provider_required_msg = (
                "Provider not set in configuration - this should not happen "
                "with proper config flow"
            )
            provider_error = "Provider configuration is required"
            LOGGER.error(provider_required_msg)
            raise ValueError(provider_error)

        if not self.group:
            group_required_msg = (
                "Group not set in configuration - this should not happen "
                "with proper config flow"
            )
            group_error = "Group configuration is required"
            LOGGER.error(group_required_msg)
            raise ValueError(group_error)

        self._region: YasnoRegion | None = None
        self.api = YasnoApi()

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        if DEBUG:
            LOGGER.debug("Event names mapped to translations: %s", self.translations)
        return {
            PlannedOutageEventType.DEFINITE: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_PLANNED_OUTAGE)}"
                f"{self._group_str}"
            ),
            PlannedOutageEventType.EMERGENCY: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE)}"
                f"{self._group_str}"
            ),
        }

    async def _async_update_data(self) -> None:  # ty:ignore[invalid-method-override]
        """Fetch data from Svitlo Yeah API."""
        await self.async_fetch_translations()

        self.api = YasnoApi(
            region_id=self.region_id,
            provider_id=self.provider_id,
            group=self.group,
        )

        # Fetch outages data (now async with aiohttp, not blocking)
        await self.api.fetch_data()

        # Check if outage data has changed (used for last_data_change attribute)
        now = dt_utils.now()
        current_events = self.api.get_events(now, now + datetime.timedelta(hours=24))
        self.check_outage_data_changed(current_events)

    async def async_fetch_translations(self) -> None:
        """Fetch translations."""
        self.translations = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "common",
            [DOMAIN],
        )
        LOGGER.debug(
            "Translations for %s:\n%s", self.hass.config.language, self.translations
        )

    @property
    def region(self) -> YasnoRegion | None:
        """Get the configured region."""
        if not self._region:
            self._region = self.api.get_region_by_id(self.region_id)  # ty:ignore[possibly-missing-attribute]
            LOGGER.debug("Caching region to %s", self._region)
        return self._region

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        if not self.region:
            LOGGER.debug("Trying to get region_name without region")
            return ""

        return self.region.name or ""

    @property
    def provider(self) -> YasnoProvider | None:
        """Get the configured provider."""
        if not self.region:
            LOGGER.debug("Trying to get provider without region")
            return None

        return next(
            (_ for _ in self.region.dsos if _.provider_id == self.provider_id), None
        )

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        if not self.provider:
            LOGGER.debug("Trying to get provider_name without provider")
            return ""

        return _simplify_provider_name(self.provider.name)

    def get_scheduled_events_between(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get scheduled outage events."""
        events = self.api.get_scheduled_events(start_date, end_date)
        output = [self._get_scheduled_calendar_event(_, rrule=None) for _ in events]
        return [_ for _ in output if _]

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.debug("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL
