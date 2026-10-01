"""Tests for coordinator functionality."""

# Test for coordinator.check_outage_data_changed implemented.

import inspect
from datetime import timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.const import (
    EVENT_DATA_CHANGED,
    TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE,
)
from custom_components.svitlo_yeah.coordinator.coordinator import IntegrationCoordinator
from custom_components.svitlo_yeah.coordinator.dtek.base import DtekCoordinatorBase
from custom_components.svitlo_yeah.coordinator.dtek.json import DtekCoordinatorJson
from custom_components.svitlo_yeah.coordinator.e_svitlo import ESvitloCoordinator
from custom_components.svitlo_yeah.coordinator.yasno import YasnoCoordinator
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEvent,
    PlannedOutageEventType,
)


@pytest.fixture(name="coordinator")
def _coordinator():
    """Create a mock coordinator for testing base functionality."""
    # Mock the required dependencies
    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.runtime_data = MagicMock()

    # Create coordinator instance with mocked API
    coordinator = IntegrationCoordinator(hass, config_entry)

    # Mock the API to return events
    coordinator.api = MagicMock()
    coordinator.api.get_events = MagicMock(return_value=[])
    coordinator.api.get_event_at = MagicMock()
    coordinator.api.get_current_event = MagicMock()
    coordinator.api.get_updated_on = MagicMock(return_value=None)
    coordinator.api.get_scheduled_events = MagicMock(return_value=[])

    # Add the scheduled events method to the coordinator
    def mock_get_scheduled_events_between(start_date, end_date):
        scheduled_events = coordinator.api.get_scheduled_events(start_date, end_date)
        return [
            coordinator._get_scheduled_calendar_event(event)
            for event in scheduled_events
        ]

    coordinator.get_scheduled_events_between = MagicMock(
        side_effect=mock_get_scheduled_events_between
    )

    return coordinator


class TestCoordinatorGetNextEventOfType:
    """Test _get_next_event_of_type method."""

    def test_get_next_event_with_all_day_event_future(self, coordinator, tomorrow):
        """Test getting next event with a future all-day event."""
        # Use current time to create an all-day event for tomorrow
        tomorrow_date = tomorrow.date()

        # Create an all-day CalendarEvent
        event = CalendarEvent(
            summary="Emergency Shutdown",
            start=tomorrow_date,
            end=tomorrow_date + timedelta(days=1),
            description="Emergency",
            uid="emergency",
        )

        # Mock the get_events_between method to return this event
        coordinator.get_events_between = MagicMock(return_value=[event])

        result = coordinator._get_next_event_of_type(None)
        assert result == event

    def test_get_next_event_with_all_day_event_past(self, coordinator, today):
        """Test getting next event skips past all-day events."""
        # Use current time to create an all-day event for yesterday
        yesterday = today - timedelta(days=1)
        yesterday_date = yesterday.date()

        # Create an all-day CalendarEvent for yesterday
        event = CalendarEvent(
            summary="Past Emergency",
            start=yesterday_date,
            end=yesterday_date + timedelta(days=1),
            description="Past Emergency",
            uid="past_emergency",
        )

        # Mock the get_events_between method to return this event
        coordinator.get_events_between = MagicMock(return_value=[event])

        result = coordinator._get_next_event_of_type(None)
        assert result is None

    def test_get_next_event_with_datetime_event_future(self, coordinator):
        """Test getting next event with a future datetime event."""
        now = dt_utils.now()
        future_time = now + timedelta(hours=1)

        # Create a datetime CalendarEvent
        event = CalendarEvent(
            summary="Definite Outage",
            start=future_time,
            end=future_time + timedelta(hours=2),
            description="Definite",
            uid="definite",
        )

        # Mock the get_events_between method to return this event
        coordinator.get_events_between = MagicMock(return_value=[event])

        result = coordinator._get_next_event_of_type(None)
        assert result == event

    def test_get_next_event_with_datetime_event_past(self, coordinator):
        """Test getting next event skips past datetime events."""
        now = dt_utils.now()
        past_time = now - timedelta(hours=1)

        # Create a datetime CalendarEvent for past
        event = CalendarEvent(
            summary="Past Outage",
            start=past_time,
            end=past_time + timedelta(hours=2),
            description="Past",
            uid="past",
        )

        # Mock the get_events_between method to return this event
        coordinator.get_events_between = MagicMock(return_value=[event])

        result = coordinator._get_next_event_of_type(None)
        assert result is None

    def test_get_next_event_filtered_by_type(self, coordinator, tomorrow):
        """Test filtering events by type."""
        tomorrow_date = tomorrow.date()

        # Create events: one outage, one emergency
        outage_event = CalendarEvent(
            summary="Planned Outage",
            start=tomorrow_date,
            end=tomorrow_date + timedelta(days=1),
            description="Outage",
            uid="outage",
        )
        emergency_event = CalendarEvent(
            summary="Emergency",
            start=tomorrow_date,
            end=tomorrow_date + timedelta(days=1),
            description="Emergency",
            uid="emergency",
        )

        # Mock the API
        coordinator.get_events_between = MagicMock(
            return_value=[outage_event, emergency_event]
        )

        # Mock _event_to_state
        coordinator._event_to_state = MagicMock()
        coordinator._event_to_state.side_effect = lambda e: (
            ConnectivityState.STATE_PLANNED_OUTAGE
            if "Outage" in e.summary
            else ConnectivityState.STATE_EMERGENCY
        )

        # Test filtering for outage events
        result = coordinator._get_next_event_of_type(
            ConnectivityState.STATE_PLANNED_OUTAGE
        )
        assert result == outage_event

        # Test filtering for all types
        result = coordinator._get_next_event_of_type(None)
        assert result == outage_event  # First one sorted by start

    def test_get_next_event_no_events(self, coordinator):
        """Test getting next event when no events exist."""
        coordinator.get_events_between = MagicMock(return_value=[])

        result = coordinator._get_next_event_of_type(None)
        assert result is None


class TestCheckOutageDataChanged:
    """Test check_outage_data_changed method."""

    @pytest.fixture(autouse=True)
    def setup_coordinator(self, coordinator):
        """Set up coordinator with required attributes."""
        coordinator.region = MagicMock()
        coordinator.provider = MagicMock()
        coordinator.group = "test_group"

    def test_first_call_initializes_tracking(self, coordinator):
        """Test that first call initializes outage data tracking and returns False."""
        now = dt_utils.now()
        events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                all_day=False,
            )
        ]

        result = coordinator.check_outage_data_changed(events)

        assert result is False
        assert (
            coordinator._previous_outage_events == events
        )  # Should be sorted, but same
        assert coordinator.outage_data_last_changed is None  # Not set on initialization
        coordinator.hass.bus.async_fire.assert_not_called()

    def test_same_data_returns_false(self, coordinator):
        """Test that calling with same data returns False and no event fired."""
        now = dt_utils.now()
        events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                all_day=False,
            )
        ]

        # First call
        coordinator.check_outage_data_changed(events)

        # Second call with same data
        result = coordinator.check_outage_data_changed(events)

        assert result is False
        assert coordinator._previous_outage_events == events
        coordinator.hass.bus.async_fire.assert_not_called()

    def test_changed_data_returns_true_and_fires_event(self, coordinator):
        """Test that calling with changed data returns True and fires event."""
        now = dt_utils.now()
        original_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                all_day=False,
            )
        ]
        new_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.EMERGENCY,
                start=now + timedelta(hours=3),
                end=now + timedelta(hours=4),
                all_day=False,
            )
        ]

        # First call
        coordinator.check_outage_data_changed(original_events)

        # Clear the mock to check new calls
        coordinator.hass.bus.async_fire.reset_mock()

        # Second call with different data
        result = coordinator.check_outage_data_changed(new_events)

        assert result is True
        assert coordinator._previous_outage_events == new_events
        assert coordinator.outage_data_last_changed is not None

        # Check event was fired with correct data
        coordinator.hass.bus.async_fire.assert_called_once()
        call_args = coordinator.hass.bus.async_fire.call_args
        event_name = call_args.args[0]
        event_data = call_args.args[1]
        assert event_name == EVENT_DATA_CHANGED
        assert event_data["provider_name"] == getattr(
            coordinator.provider, "name", None
        )
        assert event_data["provider_id"] == getattr(coordinator.provider, "id", None)
        assert event_data["region_name"] == coordinator.provider.region_name
        assert event_data["region_id"] == getattr(
            coordinator.provider, "region_id", None
        )
        assert event_data["group"] == coordinator.group
        assert event_data["last_data_change"] == coordinator.outage_data_last_changed
        assert event_data["config_entry_id"] == coordinator.config_entry.entry_id

    def test_sorting_of_events(self, coordinator):
        """Test that events are sorted before comparison."""
        now = dt_utils.now()
        # Create events out of order
        events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=4),
                end=now + timedelta(hours=5),
                all_day=False,
            ),
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                all_day=False,
            ),
        ]

        # First call
        coordinator.check_outage_data_changed(events)

        # Sorted events
        sorted_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=2),
                all_day=False,
            ),
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=now + timedelta(hours=4),
                end=now + timedelta(hours=5),
                all_day=False,
            ),
        ]

        # Call with same events in different order
        result = coordinator.check_outage_data_changed(events)

        # Should be False because they get sorted and are the same
        assert result is False
        assert coordinator._previous_outage_events == sorted_events


class TestCoordinatorScheduledEvents:
    """Test scheduled events functionality."""

    def test_get_scheduled_events_between_with_events(self, coordinator):
        """Test getting scheduled events between dates."""
        # Mock the API to return scheduled events
        scheduled_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=dt_utils.now() + timedelta(hours=1),
                end=dt_utils.now() + timedelta(hours=2),
                all_day=False,
            )
        ]
        coordinator.api.get_scheduled_events = MagicMock(return_value=scheduled_events)
        coordinator.group = "1.1"  # Set group for _group_str

        start_date = dt_utils.now()
        end_date = start_date + timedelta(days=1)

        # Mock translations
        coordinator.translations = {
            "component.svitlo_yeah.common.event_name_scheduled_outage": "Scheduled Outage"
        }

        events = coordinator.get_scheduled_events_between(start_date, end_date)

        assert len(events) == 1
        assert events[0].summary == f"Scheduled Outage {coordinator.group}"
        assert events[0].rrule is None  # Base coordinator uses default None
        coordinator.api.get_scheduled_events.assert_called_once_with(
            start_date, end_date
        )

    def test_get_scheduled_events_between_no_events(self, coordinator):
        """Test getting scheduled events when none exist."""
        coordinator.api.get_scheduled_events = MagicMock(return_value=[])

        start_date = dt_utils.now()
        end_date = start_date + timedelta(days=1)

        events = coordinator.get_scheduled_events_between(start_date, end_date)

        assert events == []

    def test_get_calendar_event_methods(self, coordinator):
        """Test both _get_calendar_event and _get_scheduled_calendar_event methods."""
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.DEFINITE,
            start=dt_utils.now() + timedelta(hours=1),
            end=dt_utils.now() + timedelta(hours=2),
            all_day=False,
        )
        coordinator.group = "1.1"  # Set group for _group_str
        names = {PlannedOutageEventType.DEFINITE: f"Planned Outage {coordinator.group}"}
        coordinator.translations = {
            "component.svitlo_yeah.common.event_name_scheduled_outage": "Scheduled Outage"
        }

        # Test regular calendar event; only this block replaces the names
        with patch.object(
            IntegrationCoordinator,
            "event_name_map",
            new_callable=PropertyMock,
            return_value=names,
        ):
            calendar_event = coordinator._get_calendar_event(event)
        assert calendar_event.summary == f"Planned Outage {coordinator.group}"
        assert calendar_event.rrule is None

        # Test scheduled calendar event with default rrule (None)
        scheduled_event = coordinator._get_scheduled_calendar_event(event)
        assert scheduled_event.summary == f"Scheduled Outage {coordinator.group}"
        assert scheduled_event.description == "Scheduled"
        assert scheduled_event.uid == "Scheduled"
        assert scheduled_event.rrule is None

        # Test scheduled calendar event with custom rrule
        custom_rrule_event = coordinator._get_scheduled_calendar_event(
            event, rrule="FREQ=DAILY"
        )
        assert custom_rrule_event.summary == f"Scheduled Outage {coordinator.group}"
        assert custom_rrule_event.rrule == "FREQ=DAILY"

        # Test scheduled calendar event with no rrule
        no_rrule_event = coordinator._get_scheduled_calendar_event(event, rrule=None)
        assert no_rrule_event.summary == f"Scheduled Outage {coordinator.group}"
        assert no_rrule_event.rrule is None

        # The other tests get the class as it is
        assert isinstance(
            inspect.getattr_static(IntegrationCoordinator, "event_name_map"), property
        )

    def test_get_calendar_event_none_event(self, coordinator):
        """Test _get_calendar_event with None event."""
        result = coordinator._get_calendar_event(None)
        assert result is None


class TestCoordinatorEventToState:
    """Test _event_to_state method for all coordinators."""

    @pytest.mark.parametrize(
        "coordinator_class",
        [
            DtekCoordinatorBase,
            DtekCoordinatorJson,
            YasnoCoordinator,
            ESvitloCoordinator,
        ],
        ids=[
            "DtekCoordinatorBase",
            "DtekCoordinatorJson",
            "YasnoCoordinator",
            "ESvitloCoordinator",
        ],
    )
    def test_event_to_state_none_event_returns_normal(self, coordinator_class):
        """Without a current event, each coordinator says that the power is on."""
        # _event_to_state reads no state of the coordinator, so the test skips
        # __init__ and its Home Assistant dependencies.
        coordinator = object.__new__(coordinator_class)

        result = coordinator._event_to_state(None)
        assert result == ConnectivityState.STATE_NORMAL, (
            f"{coordinator_class.__name__}._event_to_state(None) should return STATE_NORMAL"
        )

    @pytest.mark.parametrize(
        ("coordinator_class", "uid", "state"),
        [
            (
                DtekCoordinatorJson,
                PlannedOutageEventType.DEFINITE.value,
                ConnectivityState.STATE_PLANNED_OUTAGE,
            ),
            # DTEK sources publish no emergency outages
            (
                DtekCoordinatorJson,
                PlannedOutageEventType.EMERGENCY.value,
                ConnectivityState.STATE_NORMAL,
            ),
            (
                YasnoCoordinator,
                PlannedOutageEventType.EMERGENCY.value,
                ConnectivityState.STATE_EMERGENCY,
            ),
            (YasnoCoordinator, "unknown", ConnectivityState.STATE_NORMAL),
            (
                ESvitloCoordinator,
                PlannedOutageEventType.EMERGENCY.value,
                ConnectivityState.STATE_EMERGENCY,
            ),
            (ESvitloCoordinator, "unknown", ConnectivityState.STATE_NORMAL),
        ],
        ids=[
            "dtek_definite",
            "dtek_emergency",
            "yasno_emergency",
            "yasno_unknown",
            "e_svitlo_emergency",
            "e_svitlo_unknown",
        ],
    )
    def test_event_to_state_maps_each_event_type(self, coordinator_class, uid, state):
        """Each coordinator turns the type of the current event into a state."""
        coordinator = object.__new__(coordinator_class)
        now = dt_utils.now()
        event = CalendarEvent(
            start=now, end=now + timedelta(hours=1), summary="", uid=uid
        )

        assert coordinator._event_to_state(event) == state


class TestESvitloEventNames:
    """E-Svitlo names its events without the group."""

    def test_scheduled_event_name_has_no_group(self):
        """The group of E-Svitlo comes from the account, so the name does not repeat it."""
        coordinator = object.__new__(ESvitloCoordinator)
        coordinator.group = "4.1"
        coordinator.translations = {
            TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE: "Графікове відключення"
        }
        now = dt_utils.now()
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.DEFINITE,
            start=now,
            end=now + timedelta(hours=1),
        )

        result = coordinator._get_scheduled_calendar_event(event)

        assert result.summary == "Графікове відключення"

    def test_event_without_a_name_gets_the_name_of_its_type(self, caplog):
        """Without a translated name, the event is named after its type, with a warning."""
        coordinator = object.__new__(ESvitloCoordinator)
        coordinator.translations = {}
        now = dt_utils.now()
        event = PlannedOutageEvent(
            event_type=PlannedOutageEventType.EMERGENCY,
            start=now,
            end=now + timedelta(hours=1),
        )

        result = coordinator._get_calendar_event(event)

        assert result.summary == PlannedOutageEventType.EMERGENCY.value
        assert "Couldn't get" in caplog.text

    def test_no_scheduled_event_gives_no_calendar_event(self):
        """Without a scheduled event, there is no calendar event."""
        coordinator = object.__new__(ESvitloCoordinator)

        assert coordinator._get_scheduled_calendar_event(None) is None
