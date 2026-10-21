"""Button platform for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING, override

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .api.yasno import AddressResult
from .const import DOMAIN
from .coordinator.yasno import YasnoCoordinator
from .entity import IntegrationEntity, registry_entity_id
from .models import YasnoAddress

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator.coordinator import IntegrationCoordinator, SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

# Each press asks the source, so the presses of an entry run one at a time
PARALLEL_UPDATES = 1

REFRESH_BUTTON = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    entity_category=EntityCategory.CONFIG,
)
# Only a Yasno entry with an address has this button
CHECK_GROUP_BUTTON = ButtonEntityDescription(
    key="check_group",
    translation_key="check_group",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SvitloYeahConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    LOGGER.debug("Setup new button: %s", config_entry.entry_id)
    coordinator = config_entry.runtime_data
    entities: list[ButtonEntity] = [
        IntegrationRefreshButton(coordinator, REFRESH_BUTTON)
    ]
    if YasnoAddress.from_entry_data(config_entry.data) is None:
        # A Reconfigure can take the address away, and the button of the address
        # stays in the registry. Home Assistant would show it as unavailable.
        registry = er.async_get(hass)
        if entity_id := registry_entity_id(
            registry, Platform.BUTTON, config_entry.entry_id, CHECK_GROUP_BUTTON.key
        ):
            # The entity id has the address, so the log names the entry only
            LOGGER.debug("Remove the group button of entry %s", config_entry.entry_id)
            registry.async_remove(entity_id)
    elif isinstance(coordinator, YasnoCoordinator):
        entities.append(IntegrationCheckGroupButton(coordinator, CHECK_GROUP_BUTTON))
    async_add_entities(entities)


class IntegrationRefreshButton(IntegrationEntity, ButtonEntity):
    """Button that forces a coordinator refresh regardless of the timer."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: IntegrationCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        )

    @override
    async def async_press(self) -> None:
        """
        Force an immediate data refresh, ignoring the update interval.

        Fail when the source does not answer. Never touch last_update_success,
        because the entities keep the last data.
        """
        LOGGER.debug("Manual refresh requested for %s", self.coordinator.group)
        await self.coordinator.async_refresh()
        if self.coordinator.last_fetch_failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
            )


class IntegrationCheckGroupButton(IntegrationEntity, ButtonEntity):
    """Button that asks Yasno for the group of the address of the entry at once."""

    entity_description: ButtonEntityDescription
    coordinator: YasnoCoordinator

    def __init__(
        self,
        coordinator: YasnoCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        )

    @override
    async def async_press(self) -> None:
        """
        Check the group of the address at once, and switch to a new group at once.

        Fail when Yasno gives no sure answer, does not find the address, or gives a
        group without a schedule. The entry and its entities stay as they are then.
        """
        # The id, not the address: the log never has the address
        LOGGER.debug(
            "Manual check of the group requested for entry %s",
            self.coordinator.config_entry.entry_id,
        )
        await self.coordinator.async_check_address_now()
        result = self.coordinator.address_check_result
        if result is AddressResult.NOT_FOUND:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="address_not_found",
            )
        if result is not AddressResult.FOUND:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="check_group_failed",
            )
        # The schedule of a group that the planned outages lack would be empty
        if (group := self.coordinator.address_check_group_not_listed) is not None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="check_group_not_listed",
                translation_placeholders={"group": group},
            )
