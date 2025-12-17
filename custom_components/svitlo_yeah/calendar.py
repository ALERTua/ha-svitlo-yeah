"""Calendar platform for Svitlo Yeah integration."""

import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator.coordinator import IntegrationCoordinator
from .entity import IntegrationEntity

LOGGER = logging.getLogger(__name__)


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Svitlo Yeah calendar platform."""
    LOGGER.debug("Setup new calendar entry: %s", config_entry)
    coordinator: IntegrationCoordinator = config_entry.runtime_data
    entities = [
        PlannedOutagesCalendar(coordinator),
        ScheduledOutagesCalendar(coordinator),
    ]
    async_add_entities(entities)


class PlannedOutagesCalendar(IntegrationEntity, CalendarEntity):
    """Implementation of the Planned Outages Calendar entity."""

    def __init__(
        self,
        coordinator: IntegrationCoordinator,
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)

        self.entity_id = (
            "calendar."
            f"_{coordinator.region_name}"
            f"_{coordinator.provider_name}"
            f"_{coordinator.group}"
            "_planned_outages"
        )
        self.entity_description = EntityDescription(
            key="calendar",
            name="Calendar",
            translation_key="calendar",
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{self.entity_description.key}"
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return current or next event."""
        return self.coordinator.get_current_event()

    async def async_get_events(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        return self.coordinator.get_events_between(start_date, end_date)


class ScheduledOutagesCalendar(IntegrationEntity, CalendarEntity):
    """Implementation of the Scheduled Outages Calendar entity."""

    def __init__(
        self,
        coordinator: IntegrationCoordinator,
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)

        self.entity_id = (
            "calendar."
            f"_{coordinator.region_name}"
            f"_{coordinator.provider_name}"
            f"_{coordinator.group}"
            "_scheduled_outages"
        )
        self.entity_description = EntityDescription(
            key="scheduled_calendar",
            name="Scheduled Calendar",
            translation_key="scheduled_calendar",
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{self.entity_description.key}"
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return current or next event."""
        # For scheduled outages, we don't show current events initially
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        return self.coordinator.get_scheduled_events_between(start_date, end_date)
