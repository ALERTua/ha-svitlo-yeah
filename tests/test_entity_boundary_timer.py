"""Tests for the boundary timer of the entities."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.calendar import PlannedOutagesCalendar
from custom_components.svitlo_yeah.sensor import SENSORS, IntegrationSensor

ELECTRICITY = next(s for s in SENSORS if s.key == "electricity")


@pytest.mark.asyncio
async def test_boundary_timer_cancelled_on_remove():
    """The scheduled boundary callback must be cancelled when the entity is removed."""
    entity = object.__new__(PlannedOutagesCalendar)
    unsubscribe = MagicMock()
    entity._unsubscribe_boundary = unsubscribe

    await entity.async_will_remove_from_hass()

    unsubscribe.assert_called_once()
    assert entity._unsubscribe_boundary is None


async def test_coordinator_update_plans_the_next_boundary():
    """New data with a nearer outage moves the timer to the start of that outage."""
    coordinator = MagicMock()
    coordinator.config_entry.entry_id = "test_entry"
    coordinator.get_current_event.return_value = None
    coordinator.next_event = None
    entity = IntegrationSensor(coordinator, ELECTRICITY)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    timers = []

    def track(_hass, _action, when):
        timers.append((when, MagicMock()))
        return timers[-1][1]

    async def added_to_hass(_self):
        """Skip the listener of the coordinator, which needs a real hass."""

    with (
        patch("custom_components.svitlo_yeah.entity.async_track_point_in_time", track),
        patch.object(CoordinatorEntity, "async_added_to_hass", added_to_hass),
    ):
        await entity.async_added_to_hass()
        first_unsubscribe = timers[-1][1]

        outage_start = dt_utils.now() + timedelta(minutes=5)
        coordinator.next_event = CalendarEvent(
            summary="Planned outage",
            start=outage_start,
            end=outage_start + timedelta(hours=1),
        )
        entity._handle_coordinator_update()

    first_unsubscribe.assert_called_once()
    assert timers[-1][0] == outage_start
    entity.async_write_ha_state.assert_called()
