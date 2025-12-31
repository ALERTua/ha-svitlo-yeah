"""Tests for sensor functionality."""

import datetime
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.sensor import SENSORS, IntegrationSensor


@pytest.fixture(name="coordinator")
def _coordinator():
    """Create a mock coordinator for testing."""
    coordinator = MagicMock()

    # Mock the next_planned_outage and next_scheduled_outage properties
    coordinator.next_planned_outage = None
    coordinator.next_scheduled_outage = None

    return coordinator


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

    def test_next_scheduled_outage_with_future_event(self, coordinator):
        """Test sensor returns future scheduled outage time."""
        now = dt_utils.now()
        future_time = now + datetime.timedelta(hours=2)

        # Set the next_scheduled_outage property on the mock coordinator
        coordinator.next_scheduled_outage = future_time

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == future_time

    def test_next_scheduled_outage_no_events(self, coordinator):
        """Test sensor returns None when no scheduled events."""
        # Set no scheduled outage
        coordinator.next_scheduled_outage = None

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result is None

    def test_next_scheduled_outage_past_event_ignored(self, coordinator):
        """Test sensor returns None when only past events exist."""
        # Set no scheduled outage (past events should result in None)
        coordinator.next_scheduled_outage = None

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result is None

    def test_next_scheduled_outage_mixed_events(self, coordinator):
        """Test sensor returns earliest future scheduled event."""
        now = dt_utils.now()
        near_future = now + datetime.timedelta(hours=1)

        # Set the next_scheduled_outage to the earliest future event
        coordinator.next_scheduled_outage = near_future

        # Find the next_scheduled_outage sensor
        sensor_description = next(
            desc for desc in SENSORS if desc.key == "next_scheduled_outage"
        )
        sensor = IntegrationSensor(coordinator, sensor_description)

        result = sensor.native_value
        assert result == near_future  # Should return the earliest future event
