"""Coordinator for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from homeassistant.helpers.translation import async_get_translations

from ..api.yasno import YasnoApi
from ..const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_REGION,
    DOMAIN,
    PROVIDER_DTEK_FULL,
    PROVIDER_DTEK_SHORT,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from ..models import (
    ConnectivityState,
    PlannedOutageEventType,
)
from .coordinator import IntegrationCoordinator

LOGGER = logging.getLogger(__name__)


class YasnoCoordinator(IntegrationCoordinator):
    """Class to manage fetching Yasno outages data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        # Get configuration values
        self.region = config_entry.options.get(
            CONF_REGION,
            config_entry.data.get(CONF_REGION),
        )
        self.provider = config_entry.options.get(
            CONF_PROVIDER,
            config_entry.data.get(CONF_PROVIDER),
        )
        self.group = config_entry.options.get(
            CONF_GROUP,
            config_entry.data.get(CONF_GROUP),
        )

        if not self.region:
            region_required_msg = (
                "Region not set in configuration - this should not happen "
                "with proper config flow"
            )
            region_error = "Region configuration is required"
            LOGGER.error(region_required_msg)
            raise ValueError(region_error)

        if not self.provider:
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

        # Initialize with names first, then we'll update with IDs when we fetch data
        self.region_id = None
        self.provider_id = None
        self._provider_name = ""  # Cache the provider name

        # Initialize API and resolve IDs
        self.api = YasnoApi()
        # Note: We'll resolve IDs and update API during first data update

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

    async def _resolve_ids(self) -> None:
        """Resolve region and provider IDs from names."""
        if not self.api.regions_data:
            await self.api.fetch_yasno_regions()

        if self.region:
            region_data = self.api.get_region_by_name(self.region)
            if region_data:
                self.region_id = region_data["id"]
                if self.provider:
                    provider_data = self.api.get_yasno_provider_by_name(
                        self.region, self.provider
                    )
                    if provider_data:
                        self.provider_id = provider_data["id"]
                        # Cache the provider name for device naming
                        self._provider_name = provider_data["name"]

    async def _async_update_data(self) -> None:
        """Fetch data from Svitlo Yeah API."""
        await self.async_fetch_translations()

        # Resolve IDs if not already resolved
        if self.region_id is None or self.provider_id is None:
            await self._resolve_ids()

            # Update API with resolved IDs
            self.api = YasnoApi(
                region_id=self.region_id,
                provider_id=self.provider_id,
                group=self.group,
            )

        # Fetch outages data (now async with aiohttp, not blocking)
        await self.api.fetch_data()

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
    def region_name(self) -> str:
        """Get the configured region name."""
        return self.region or ""

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        # Return cached name if available (but apply simplification first)
        if self._provider_name:
            return self._simplify_provider_name(self._provider_name)

        # Fallback to lookup if not cached yet
        if not self.api.regions_data:
            return ""

        region_data = self.api.get_region_by_name(self.region)
        if not region_data:
            return ""

        providers = region_data.get("dsos", [])
        for provider in providers:
            if (provider_name := provider.get("name", "")) == self.provider:
                # Cache the simplified name
                self._provider_name = provider_name
                return self._simplify_provider_name(provider_name)

        return ""

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.warning("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL

    def _simplify_provider_name(self, provider_name: str) -> str:
        """Simplify provider names for cleaner display in device names."""
        # Replace long DTEK provider names with just "ДТЕК"
        if PROVIDER_DTEK_FULL in provider_name.upper():
            return PROVIDER_DTEK_SHORT

        # Add more provider simplifications here as needed
        return provider_name
