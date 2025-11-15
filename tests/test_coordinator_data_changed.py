"""Tests for outage data change tracking in coordinators."""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from custom_components.svitlo_yeah.coordinator.coordinator import IntegrationCoordinator
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator instance."""
    hass = MagicMock()
    config_entry = MagicMock()
    with patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ):
        coordinator = IntegrationCoordinator(hass, config_entry)
        # Initialize the coordinator attributes
        coordinator.hass = hass  # Assign hass to the coordinator
        coordinator.config_entry = (
            config_entry  # Assign config_entry to the coordinator
        )
        # Add group attribute for tests
        coordinator.group = "A"
        coordinator.region = "test_region"
        coordinator.provider = "test_provider"
        coordinator.translations = {}
        coordinator._previous_outage_events = None
        coordinator.outage_data_last_changed = None
        coordinator.api = MagicMock()
        return coordinator


class TestOutageDataChangeTracking:
    """Test outage data change tracking functionality."""

    def create_test_events(
        self, base_datetime: datetime.datetime
    ) -> list[PlannedOutageEvent]:
        """Create a set of test outage events."""
        return [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=2),
                end=base_datetime + datetime.timedelta(hours=4),
            ),
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=6),
                end=base_datetime + datetime.timedelta(hours=8),
            ),
        ]

    def test_no_change_detected_does_not_update_timestamp(self, mock_coordinator):
        """Test that when events don't change, timestamp is not updated."""
        initial_timestamp = datetime.datetime(2025, 1, 15, 10, 30, 0)
        # Don't call initialize_outage_data_tracking since we want to test the other path
        # where _previous_outage_events is already set
        mock_coordinator._previous_outage_events = self.create_test_events(
            datetime.datetime(2025, 1, 15, 0, 0, 0)
        )
        mock_coordinator.outage_data_last_changed = initial_timestamp

        # Same events
        events = self.create_test_events(datetime.datetime(2025, 1, 15, 0, 0, 0))

        # Check for changes (should return False)
        changed = mock_coordinator.check_outage_data_changed(events)

        assert not changed
        assert mock_coordinator.outage_data_last_changed == initial_timestamp

    @freeze_time("2025-01-15T12:30:00")
    def test_change_detected_updates_timestamp(self, mock_coordinator):
        """Test that when events change, timestamp is updated to current time."""
        # Initialize with original events
        original_events = self.create_test_events(
            datetime.datetime(2025, 1, 15, 0, 0, 0)
        )
        mock_coordinator.initialize_outage_data_tracking(original_events)

        # Different events (one less outage)
        modified_events = original_events[:-1]  # Remove last event

        # Check for changes (should return True)
        with patch.object(mock_coordinator.hass.bus, "async_fire") as mock_fire:
            changed = mock_coordinator.check_outage_data_changed(modified_events)

        assert changed
        # When using freeze_time, dt_utils.now() returns timezone-aware datetime
        expected_time = datetime.datetime(2025, 1, 15, 12, 30, 0, tzinfo=datetime.UTC)
        assert mock_coordinator.outage_data_last_changed == expected_time
        # Verify event was fired
        mock_fire.assert_called_once()

    def test_events_are_sorted_for_consistent_comparison(self, mock_coordinator):
        """Test that events are sorted before comparison for consistent results."""
        # Create events in reverse order
        base_datetime = datetime.datetime(2025, 1, 15, 0, 0, 0)
        events_unsorted = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=6),
                end=base_datetime + datetime.timedelta(hours=8),
            ),
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=2),
                end=base_datetime + datetime.timedelta(hours=4),
            ),
        ]

        # Initialize and check - should sort internally
        mock_coordinator.initialize_outage_data_tracking(events_unsorted)

        # Create same events but in different order
        events_different_order = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=2),
                end=base_datetime + datetime.timedelta(hours=4),
            ),
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=base_datetime + datetime.timedelta(hours=6),
                end=base_datetime + datetime.timedelta(hours=8),
            ),
        ]

        # Check for changes - should not detect change due to sorting
        changed = mock_coordinator.check_outage_data_changed(events_different_order)

        assert not changed  # Same events, just different order

    def test_time_change_only_does_not_count_as_content_change(self, mock_coordinator):
        """Test that when event times change, it's detected as a change."""
        # Initialize with original events
        original_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=datetime.datetime(2025, 1, 15, 10, 0, 0),
                end=datetime.datetime(2025, 1, 15, 12, 0, 0),
            )
        ]
        mock_coordinator.initialize_outage_data_tracking(original_events)

        # Same event but different time (should be detected as change)
        modified_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=datetime.datetime(2025, 1, 15, 11, 0, 0),  # Time changed
                end=datetime.datetime(2025, 1, 15, 13, 0, 0),
            )
        ]

        with patch.object(mock_coordinator.hass.bus, "async_fire") as mock_fire:
            changed = mock_coordinator.check_outage_data_changed(modified_events)

        assert changed  # Time change should be detected
        # Verify event was fired
        mock_fire.assert_called_once()

    def test_emergency_vs_planned_events_are_differently_detected(
        self, mock_coordinator
    ):
        """Test that emergency vs planned outage events are different."""
        # Initialize with planned outage
        planned_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.DEFINITE,
                start=datetime.datetime(2025, 1, 15, 10, 0, 0),
                end=datetime.datetime(2025, 1, 15, 12, 0, 0),
            )
        ]
        mock_coordinator.initialize_outage_data_tracking(planned_events)

        # Change to emergency outage
        emergency_events = [
            PlannedOutageEvent(
                event_type=PlannedOutageEventType.EMERGENCY,
                start=datetime.datetime(2025, 1, 15, 10, 0, 0),
                end=datetime.datetime(2025, 1, 15, 12, 0, 0),
            )
        ]

        with patch.object(mock_coordinator.hass.bus, "async_fire") as mock_fire:
            changed = mock_coordinator.check_outage_data_changed(emergency_events)

        assert changed  # Different event types should be detected
        # Verify event was fired
        mock_fire.assert_called_once()
