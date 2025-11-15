"""Init file for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform

from .const import (
    CONF_PROVIDER_TYPE,
    DEBUG,
    DOMAIN,
    PROVIDER_TYPE_DTEK,
    PROVIDER_TYPE_YASNO,
)
from .coordinator.dtek import DtekCoordinator
from .coordinator.yasno import YasnoCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]


if DEBUG:

    async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001
        """Set up the Svitlo Yeah integration (called once during startup)."""
        # Register debug service only when DEBUG is enabled

        async def trigger_data_change(call: Any) -> None:  # noqa: ARG001
            """Service to manually trigger data change detection (DEBUG only)."""
            for entry in hass.config_entries.async_entries(DOMAIN):
                if hasattr(entry, "runtime_data") and entry.runtime_data:
                    coordinator = entry.runtime_data
                    # Reset previous events to force change detection on next update
                    coordinator._previous_outage_events = []  # noqa: SLF001
                    await coordinator.async_refresh()

        hass.services.async_register(DOMAIN, "trigger_data_change", trigger_data_change)
        LOGGER.info("Debug service 'trigger_data_change' registered")

        return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a new entry."""
    LOGGER.info("Setup entry: %s", entry)

    provider_type = entry.options.get(
        CONF_PROVIDER_TYPE,
        entry.data.get(CONF_PROVIDER_TYPE, PROVIDER_TYPE_YASNO),
    )

    if provider_type == PROVIDER_TYPE_DTEK:
        coordinator = DtekCoordinator(hass, entry)
    else:
        coordinator = YasnoCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.info("Unload entry: %s", entry)
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
