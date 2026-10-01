"""Button platform for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .entity import IntegrationEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator.coordinator import IntegrationCoordinator, SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

REFRESH_BUTTON = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    icon="mdi:refresh",
    entity_category=EntityCategory.CONFIG,
)


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SvitloYeahConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button platform."""
    LOGGER.debug("Setup new button: %s", config_entry)
    coordinator = config_entry.runtime_data
    async_add_entities([IntegrationRefreshButton(coordinator, REFRESH_BUTTON)])


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

    async def async_press(self) -> None:
        """
        Force an immediate data refresh, ignoring the update interval.

        When the source does not answer, the press fails with an error. The
        entities stay available with the last data (AGENTS.md, «Old states
        until new data»), so the press must not touch last_update_success.
        """
        LOGGER.debug("Manual refresh requested for %s", self.coordinator.group)
        await self.coordinator.async_refresh()
        if self.coordinator.login_rejected:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="login_rejected",
            )
        if self.coordinator.last_fetch_failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
            )
