"""Tests for coordinator functionality."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.coordinator.coordinator import IntegrationCoordinator
from custom_components.svitlo_yeah.models import ConnectivityState


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
