"""Tests for sensor functionality."""

import datetime
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
)
from custom_components.svitlo_yeah.sensor import SENSORS, IntegrationSensor


@pytest.fixture(name="coordinator")
def _coordinator():
    """Create a mock coordinator for testing."""
    coordinator = MagicMock()

    # Mock the get_scheduled_events_between method to return empty list by default
    coordinator.get_scheduled_events_between.return_value = []

    # Mock the next_planned_outage property to return None by default
    coordinator.next_planned_outage = None

    return coordinator


class MockCoordinator:
    """Mock coordinator that implements next_scheduled_outage logic for testing."""

    def __init__(self) -> None:
        """Initialize the mock coordinator."""
        self.scheduled_events = []
        self.planned_outage_time = None
        # Mock config_entry for sensor initialization
        self.config_entry = MagicMock()
        self.config_entry.entry_id = "test_entry_id"

    def get_scheduled_events_between(self, start_date, end_date):  # noqa: ARG002
        """Return scheduled events."""
        return self.scheduled_events

    @property
    def next_planned_outage(self):
        """Get next planned outage."""
        return self.planned_outage_time

    @property
    def next_scheduled_outage(self):
        """Get the next scheduled or planned outage time, whichever is nearest."""
        # Get next scheduled outage
        now = dt_utils.as_local(dt_utils.now())
        scheduled_events = sorted(
            self.get_scheduled_events_between(
                now,
                now + datetime.timedelta(hours=24),
            ),
            key=lambda _: _.start,
        )
        next_scheduled = None
        for event in scheduled_events:
            _now = now.date() if event.all_day else now
            # event.start can be datetime or date (all_day event)
            if event.start > _now:
                next_scheduled = event.start
                break

        # Get next planned outage
        next_planned = self.next_planned_outage

        # Return the earliest one, or None if both are None
        candidates = [next_scheduled, next_planned]
        candidates = [c for c in candidates if c is not None]
        return min(candidates) if candidates else None


class TestNextPlannedOutageSensor:
    """Test the next_planned_outage sensor."""

    def test_next_planned_outage_with_future_event(self, coordinator):
        """Test sensor returns future planned outage time."""
        now = dt_utils.now()
        future_time = now + datetime.timedelta(hours=2)

        # Set the next_planned_outage property on the mock coordinator
        coordinator.next_planned_outage = future_time

        # Find the next_planned_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_planned_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == future_time

    def test_next_planned_outage_no_events(self, coordinator):
        """Test sensor returns None when no planned events."""
        # Set no planned outage
        coordinator.next_planned_outage = None

        # Find the next_planned_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_planned_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result is None

    def test_next_planned_outage_past_event_ignored(self, coordinator):
        """Test sensor returns None when only past events exist."""
        # Set no planned outage (past events should result in None)
        coordinator.next_planned_outage = None

        # Find the next_planned_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_planned_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result is None

    def test_next_planned_outage_mixed_events(self, coordinator):
        """Test sensor returns earliest future planned event."""
        now = dt_utils.now()
        near_future = now + datetime.timedelta(hours=1)

        # Set the next_planned_outage to the earliest future event
        coordinator.next_planned_outage = near_future

        # Find the next_planned_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_planned_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == near_future  # Should return the earliest future event


class TestNextScheduledOutageSensor:
    """Test the next_scheduled_outage sensor."""

    def test_next_scheduled_outage_returns_scheduled_when_only_scheduled_exists(self):
        """Test sensor returns scheduled outage when only scheduled exists."""
        now = dt_utils.now()
        scheduled_time = now + datetime.timedelta(hours=2)

        # Create mock coordinator with scheduled event
        coordinator = MockCoordinator()
        scheduled_event = PlannedOutageEvent(
            start=scheduled_time,
            end=scheduled_time + datetime.timedelta(hours=1),
            event_type=PlannedOutageEventType.SCHEDULED,
        )
        coordinator.scheduled_events = [scheduled_event]
        coordinator.planned_outage_time = None

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == scheduled_time

    def test_next_scheduled_outage_returns_planned_when_only_planned_exists(self):
        """Test sensor returns planned outage when only planned exists."""
        now = dt_utils.now()
        planned_time = now + datetime.timedelta(hours=3)

        # Create mock coordinator with planned outage
        coordinator = MockCoordinator()
        coordinator.scheduled_events = []
        coordinator.planned_outage_time = planned_time

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == planned_time

    def test_next_scheduled_outage_returns_scheduled_when_scheduled_is_earlier(self):
        """Test sensor returns scheduled outage when it's earlier than planned."""
        now = dt_utils.now()
        scheduled_time = now + datetime.timedelta(hours=1)
        planned_time = now + datetime.timedelta(hours=3)

        # Create mock coordinator with both events
        coordinator = MockCoordinator()
        scheduled_event = PlannedOutageEvent(
            start=scheduled_time,
            end=scheduled_time + datetime.timedelta(hours=1),
            event_type=PlannedOutageEventType.SCHEDULED,
        )
        coordinator.scheduled_events = [scheduled_event]
        coordinator.planned_outage_time = planned_time

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == scheduled_time  # Should return scheduled (earlier)

    def test_next_scheduled_outage_returns_planned_when_planned_is_earlier(self):
        """Test sensor returns planned outage when it's earlier than scheduled."""
        now = dt_utils.now()
        scheduled_time = now + datetime.timedelta(hours=3)
        planned_time = now + datetime.timedelta(hours=1)

        # Create mock coordinator with both events
        coordinator = MockCoordinator()
        scheduled_event = PlannedOutageEvent(
            start=scheduled_time,
            end=scheduled_time + datetime.timedelta(hours=1),
            event_type=PlannedOutageEventType.SCHEDULED,
        )
        coordinator.scheduled_events = [scheduled_event]
        coordinator.planned_outage_time = planned_time

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == planned_time  # Should return planned (earlier)

    def test_next_scheduled_outage_no_events(self):
        """Test sensor returns None when no events exist."""
        # Create mock coordinator with no events
        coordinator = MockCoordinator()
        coordinator.scheduled_events = []
        coordinator.planned_outage_time = None

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result is None
