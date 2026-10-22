"""Calendar platform for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING, override

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityDescription,
    CalendarEvent,
)
from homeassistant.util import slugify

from .entity import IntegrationEntity
from .models import YasnoAddress

if TYPE_CHECKING:
    import datetime as dt

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator.coordinator import IntegrationCoordinator, SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

# The coordinator fetches the data for all entities, which only read it
PARALLEL_UPDATES = 0


def _calendar_entity_id(coordinator: IntegrationCoordinator, kind: str) -> str:
    """
    Return the entity id of a new calendar: the address, or region, provider and group.

    The group of an address can change, so its calendar has the address in its id,
    as its other entities do. A calendar in the registry keeps its id.
    """
    if address := YasnoAddress.from_entry_data(coordinator.config_entry.data):
        base = address.text
    else:
        base = "".join(
            (
                f"{coordinator.region_name}" if coordinator.region_name else "",
                f"_{coordinator.provider_name}" if coordinator.provider_name else "",
                f"_{coordinator.group}",
            )
        ).strip("_")
    return f"calendar.{slugify(f'{base}_{kind}')}"


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  # Home Assistant calls each platform with it
    config_entry: SvitloYeahConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Svitlo Yeah calendar platform."""
    LOGGER.debug("Setup new calendar entry: %s", config_entry.entry_id)
    coordinator = config_entry.runtime_data
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

        self.entity_id = _calendar_entity_id(coordinator, "planned_outages")
        self.entity_description = CalendarEntityDescription(
            key="calendar",
            name="Calendar",
            translation_key="calendar",
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{self.entity_description.key}"
        )

    @property
    @override
    def event(self) -> CalendarEvent | None:
        """Return current or next event."""
        return self.coordinator.get_current_event()

    @override
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: dt.datetime,
        end_date: dt.datetime,
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

        self.entity_id = _calendar_entity_id(coordinator, "scheduled_outages")
        self.entity_description = CalendarEntityDescription(
            key="scheduled_calendar",
            name="Scheduled Calendar",
            translation_key="scheduled_calendar",
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-{self.entity_description.key}"
        )

    @property
    @override
    def event(self) -> CalendarEvent | None:
        """Return current or next event."""
        # For scheduled outages, we don't show current events initially
        return None

    @override
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: dt.datetime,
        end_date: dt.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        return self.coordinator.get_scheduled_events_between(start_date, end_date)
