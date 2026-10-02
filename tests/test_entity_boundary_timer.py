"""Tests for the boundary timer of the entities."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.svitlo_yeah.calendar import PlannedOutagesCalendar
from custom_components.svitlo_yeah.const import DOMAIN, YASNO_REGIONS_ENDPOINT
from custom_components.svitlo_yeah.models import ConnectivityState
from custom_components.svitlo_yeah.sensor import SENSORS, IntegrationSensor
from tests.helpers import YASNO_KYIV, YASNO_KYIV_1_1, YASNO_PLANNED_URL, kyiv_midnight

ELECTRICITY = next(s for s in SENSORS if s.key == "electricity")


def _yasno_today(slots: list) -> dict:
    """Build a Yasno answer for group 1.1 with these slots today."""
    today = kyiv_midnight().isoformat()
    day = {"slots": slots, "date": today, "status": "ScheduleApplies"}
    return {"1.1": {"today": day, "updatedOn": today}}


def _serve_yasno(aioclient_mock, slots: list) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    aioclient_mock.get(YASNO_PLANNED_URL, json=_yasno_today(slots))


@pytest.mark.usefixtures("enable_custom_integrations", "empty_yasno_region_cache")
async def test_outage_that_an_update_brings_ends_on_time(hass, aioclient_mock, freezer):
    """An outage that has begun when an update brings it ends at its end, not later."""
    freezer.move_to(kyiv_midnight() + timedelta(hours=9))
    _serve_yasno(aioclient_mock, [])
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    electricity = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_electricity"
    )

    # At 09:01 the answer brings an outage 09:00-09:10; the next poll is at 09:16
    freezer.move_to(kyiv_midnight() + timedelta(hours=9, minutes=1))
    _serve_yasno(aioclient_mock, [{"start": 540, "end": 550, "type": "Definite"}])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(electricity).state == ConnectivityState.STATE_PLANNED_OUTAGE

    freezer.move_to(kyiv_midnight() + timedelta(hours=9, minutes=10, seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(electricity).state == ConnectivityState.STATE_NORMAL
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


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


async def test_boundary_writes_the_new_state_and_plans_the_next_one():
    """At the start of an outage, the entity writes its new state and plans the end."""
    coordinator = MagicMock()
    coordinator.config_entry.entry_id = "test_entry"
    coordinator.next_event = None
    coordinator.get_current_event.return_value = None
    entity = IntegrationSensor(coordinator, ELECTRICITY)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    now = dt_utils.now()
    outage = CalendarEvent(
        summary="Planned outage",
        start=now - timedelta(seconds=1),
        end=now + timedelta(hours=1),
    )
    timers = []

    def track(_hass, action, when):
        timers.append((when, action))
        return MagicMock()

    with patch("custom_components.svitlo_yeah.entity.async_track_point_in_time", track):
        coordinator.get_current_event.return_value = outage  # the outage has begun
        await entity._handle_boundary(now)

    entity.async_write_ha_state.assert_called_once()
    assert timers == [(outage.end_datetime_local, entity._handle_boundary)]
