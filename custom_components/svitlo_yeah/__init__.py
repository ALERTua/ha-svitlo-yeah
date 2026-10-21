"""Init file for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING, NoReturn

from homeassistant.components import persistent_notification
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_PROVIDER_TYPE,
    DOMAIN,
    ISSUE_PROVIDER_REMOVED,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_YASNO,
    REMOVED_PROVIDERS,
)
from .coordinator.coordinator import (
    STORE_VERSION,
    async_integration_title,
    group_not_listed_issue_id,
    store_key,
)
from .coordinator.dtek.json import DtekCoordinatorJson
from .coordinator.yasno import (
    YasnoCoordinator,
    address_not_found_issue_id,
    group_changed_notification_id,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator.coordinator import SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]


def provider_removed_issue_id(entry_id: str) -> str:
    """Return the id of the repair issue about an entry of a removed provider."""
    return f"{ISSUE_PROVIDER_REMOVED}_{entry_id}"


async def _async_stop_removed_provider(
    hass: HomeAssistant, entry: SvitloYeahConfigEntry, provider: str
) -> NoReturn:
    """
    Stop the setup of an entry whose provider a release removed.

    A repair issue names the entry and tells the user to delete it. The
    integration never deletes an entry itself.
    """
    integration = await async_integration_title(hass)
    ir.async_create_issue(
        hass,
        DOMAIN,
        provider_removed_issue_id(entry.entry_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_PROVIDER_REMOVED,
        translation_placeholders={
            "entry": entry.title,
            "provider": provider,
            "integration": integration,
        },
    )
    raise ConfigEntryError(
        translation_domain=DOMAIN,
        translation_key="provider_removed",
        translation_placeholders={"provider": provider, "integration": integration},
    )


async def async_setup_entry(hass: HomeAssistant, entry: SvitloYeahConfigEntry) -> bool:
    """Set up a new entry."""
    # The id, not the entry: the title of an entry can be the address of a person
    LOGGER.debug("Setup entry: %s", entry.entry_id)
    provider_type = entry.data.get(CONF_PROVIDER_TYPE)

    if provider := REMOVED_PROVIDERS.get(provider_type):
        # No other provider gives this schedule, so the user deletes the entry
        await _async_stop_removed_provider(hass, entry, provider)

    if provider_type == PROVIDER_TYPE_DTEK_JSON:
        coordinator = DtekCoordinatorJson(hass, entry)
    elif provider_type == PROVIDER_TYPE_YASNO:
        coordinator = YasnoCoordinator(hass, entry)
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
    """Unload a config entry."""
    LOGGER.debug("Unload entry: %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # The next setup asks the source again or reads the kept state of the
        # check of the address, and creates the issue if needed.
        ir.async_delete_issue(hass, DOMAIN, group_not_listed_issue_id(entry.entry_id))
        ir.async_delete_issue(hass, DOMAIN, address_not_found_issue_id(entry.entry_id))
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: SvitloYeahConfigEntry) -> None:
    """
    Delete the last data that the entry kept for a restart.

    The notification about a new group of the entry goes too. An unload keeps it,
    because the new group itself reloads the entry. The repair issue about a
    removed provider goes too, because it asks the user to delete the entry.
    """
    await Store(hass, STORE_VERSION, store_key(entry.entry_id)).async_remove()
    persistent_notification.async_dismiss(
        hass, group_changed_notification_id(entry.entry_id)
    )
    ir.async_delete_issue(hass, DOMAIN, provider_removed_issue_id(entry.entry_id))
