"""Init file for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_PROVIDER_TYPE,
    DOMAIN,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
)
from .coordinator.coordinator import (
    STORE_VERSION,
    group_not_listed_issue_id,
    store_key,
)
from .coordinator.dtek.json import DtekCoordinatorJson
from .coordinator.e_svitlo import ESvitloCoordinator
from .coordinator.yasno import YasnoCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator.coordinator import SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SvitloYeahConfigEntry) -> bool:
    """Set up a new entry."""
    LOGGER.info("Setup entry: %s", entry)
    provider_type = entry.options.get(
        CONF_PROVIDER_TYPE,
        entry.data.get(CONF_PROVIDER_TYPE),
    )

    if provider_type == PROVIDER_TYPE_DTEK_JSON:
        coordinator = DtekCoordinatorJson(hass, entry)
    elif provider_type == PROVIDER_TYPE_YASNO:
        coordinator = YasnoCoordinator(hass, entry)
    elif provider_type == PROVIDER_TYPE_E_SVITLO:
        coordinator = ESvitloCoordinator(hass, entry)
    else:
        # Nothing can make the entry usable, so the user adds it again
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unknown_provider_type",
            translation_placeholders={"provider_type": str(provider_type)},
        )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: SvitloYeahConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SvitloYeahConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    LOGGER.info("Unload entry: %s", entry)
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # The next setup asks the source again and creates the issue if needed.
        ir.async_delete_issue(hass, DOMAIN, group_not_listed_issue_id(entry.entry_id))
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: SvitloYeahConfigEntry) -> None:
    """Delete the last data that the entry kept for a restart."""
    await Store(hass, STORE_VERSION, store_key(entry.entry_id)).async_remove()
