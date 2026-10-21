"""Tests for calendar functionality."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.calendar import (
    PlannedOutagesCalendar,
    ScheduledOutagesCalendar,
    async_setup_entry,
)
from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_STREET,
)


@pytest.fixture(name="coordinator")
def _coordinator():
    """Create a mock coordinator for testing."""
    coordinator = MagicMock()
    coordinator.region_name = "kyiv"
    coordinator.provider_name = "dtek"
    coordinator.group = "1_1"
    coordinator.config_entry.entry_id = "test_entry"
    # An entry with a group and no address, as the entries of the tests here
    coordinator.config_entry.data = {"group": "1_1"}
    coordinator.get_events_between = MagicMock(return_value=[])
    coordinator.get_scheduled_events_between = MagicMock(return_value=[])
    coordinator.get_current_event = MagicMock(return_value=None)
    return coordinator


class TestPlannedOutagesCalendar:
    """Test PlannedOutagesCalendar entity."""

    def test_calendar_initialization(self, coordinator):
        """Test calendar entity initialization."""
        calendar = PlannedOutagesCalendar(coordinator)

        assert calendar.coordinator == coordinator
        expected_entity_id = "calendar.kyiv_dtek_1_1_planned_outages"
        assert calendar.entity_id == expected_entity_id
        assert calendar.entity_description.name == "Calendar"
        assert calendar.entity_description.translation_key == "calendar"
        expected_unique_id = "test_entry-calendar"
        assert calendar._attr_unique_id == expected_unique_id

    def test_calendar_event_property(self, coordinator):
        """Test calendar event property returns None."""
        calendar = PlannedOutagesCalendar(coordinator)
        assert calendar.event is None

    @pytest.mark.asyncio
    async def test_async_get_events(self, coordinator):
        """Test async_get_events method."""
        calendar = PlannedOutagesCalendar(coordinator)

        start_date = dt_utils.now()
        end_date = start_date + timedelta(days=1)

        events = [
            CalendarEvent(
                summary="Planned Outage",
                start=start_date + timedelta(hours=1),
                end=start_date + timedelta(hours=2),
                description="Test outage",
                uid="test",
            )
        ]
        coordinator.get_events_between.return_value = events

        hass = MagicMock()
        result = await calendar.async_get_events(hass, start_date, end_date)

        assert result == events
        coordinator.get_events_between.assert_called_once_with(start_date, end_date)


class TestScheduledOutagesCalendar:
    """Test ScheduledOutagesCalendar entity."""

    def test_calendar_initialization(self, coordinator):
        """Test scheduled calendar entity initialization."""
        calendar = ScheduledOutagesCalendar(coordinator)

        assert calendar.coordinator == coordinator
        expected_entity_id = "calendar.kyiv_dtek_1_1_scheduled_outages"
        assert calendar.entity_id == expected_entity_id
        assert calendar.entity_description.name == "Scheduled Calendar"
        assert calendar.entity_description.translation_key == "scheduled_calendar"
        expected_unique_id = "test_entry-scheduled_calendar"
        assert calendar._attr_unique_id == expected_unique_id

    def test_calendar_event_property(self, coordinator):
        """Test scheduled calendar event property returns None."""
        calendar = ScheduledOutagesCalendar(coordinator)
        assert calendar.event is None

    @pytest.mark.asyncio
    async def test_async_get_events(self, coordinator):
        """Test scheduled calendar async_get_events method."""
        calendar = ScheduledOutagesCalendar(coordinator)

        start_date = dt_utils.now()
        end_date = start_date + timedelta(days=1)

        events = [
            CalendarEvent(
                summary="Scheduled Outage",
                start=start_date + timedelta(hours=1),
                end=start_date + timedelta(hours=2),
                description="Test scheduled outage",
                uid="scheduled_test",
                rrule="FREQ=WEEKLY",
            )
        ]
        coordinator.get_scheduled_events_between.return_value = events

        hass = MagicMock()
        result = await calendar.async_get_events(hass, start_date, end_date)

        assert result == events
        coordinator.get_scheduled_events_between.assert_called_once_with(
            start_date, end_date
        )


class TestCalendarEntityIdOfAnAddress:
    """The entity ids of both calendars of an address entry come from the address."""

    # The data of the entry, and the base of the ids that its address gives. The names
    # have no group: the group of an address can change, and its ids stay.
    @pytest.mark.parametrize(
        ("address", "base"),
        [
            pytest.param(
                {CONF_STREET: "вул. Сверстюка Євгена", CONF_HOUSE: "1"},
                "vul_sverstiuka_evgena_1",
                id="without_a_city",
            ),
            pytest.param(
                {
                    CONF_CITY: "м. Дніпро",
                    CONF_STREET: "вул. Грушевського Михайла",
                    CONF_HOUSE: "1",
                },
                "m_dnipro_vul_grushevskogo_mikhaila_1",
                id="with_a_city",
            ),
        ],
    )
    def test_ids_come_from_the_address(self, coordinator, address, base):
        """The region, the provider and the group of the entry are not in the ids."""
        coordinator.config_entry.data = {CONF_GROUP: "53_1", **address}

        planned = PlannedOutagesCalendar(coordinator)
        scheduled = ScheduledOutagesCalendar(coordinator)

        assert planned.entity_id == f"calendar.{base}_planned_outages"
        assert scheduled.entity_id == f"calendar.{base}_scheduled_outages"
        # The unique ids still come from the entry, so the registry keeps the entities
        assert planned._attr_unique_id == "test_entry-calendar"
        assert scheduled._attr_unique_id == "test_entry-scheduled_calendar"

    def test_street_without_a_house_is_not_an_address(self, coordinator):
        """An entry needs the street and the house: else the ids come from the group."""
        coordinator.config_entry.data = {
            CONF_GROUP: "1_1",
            CONF_STREET: "вул. Сверстюка Євгена",
        }

        planned = PlannedOutagesCalendar(coordinator)

        assert planned.entity_id == "calendar.kyiv_dtek_1_1_planned_outages"


class TestCalendarSetup:
    """Test calendar setup functionality."""

    @pytest.mark.asyncio
    async def test_async_setup_entry(self, coordinator):
        """Test async_setup_entry creates both calendar entities."""
        config_entry = MagicMock()
        config_entry.runtime_data = coordinator

        hass = MagicMock()
        async_add_entities = MagicMock()

        await async_setup_entry(hass, config_entry, async_add_entities)

        # Verify that async_add_entities was called once with two entities
        assert async_add_entities.call_count == 1
        entities = async_add_entities.call_args[0][0]

        assert len(entities) == 2
        assert isinstance(entities[0], PlannedOutagesCalendar)
        assert isinstance(entities[1], ScheduledOutagesCalendar)

        # Verify both entities have the same coordinator
        assert entities[0].coordinator == coordinator
        assert entities[1].coordinator == coordinator
