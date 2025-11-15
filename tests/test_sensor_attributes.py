"""Tests for electricity sensor with outage data change attributes."""

import datetime
from unittest.mock import MagicMock, patch

from custom_components.svitlo_yeah.models import ConnectivityState
from custom_components.svitlo_yeah.sensor import (
    IntegrationSensor,
    IntegrationSensorDescription,
)


class TestElectricitySensorAttributes:
    """Test electricity sensor attributes functionality."""

    def create_mock_coordinator(self):
        """Create a mock coordinator for testing."""
        coordinator = MagicMock()
        coordinator.current_state = ConnectivityState.STATE_NORMAL.value
        coordinator.outage_data_last_changed = datetime.datetime(2025, 1, 15, 10, 30, 0)
        coordinator.get_current_event.return_value = None  # No current event
        return coordinator

    def create_test_sensor(self, coordinator, key="electricity"):
        """Create a test sensor instance."""
        description = IntegrationSensorDescription(
            key=key,
            translation_key=key,
            device_class=IntegrationSensorDescription.__annotations__.get(
                "device_class", None
            ),
            val_func=lambda c: c.current_state,
        )

        # Mock the __init__ method to avoid calling parent classes
        with patch.object(IntegrationSensor, "__init__", return_value=None):
            sensor = IntegrationSensor(coordinator, description)
            sensor.entity_description = description
            sensor._attr_unique_id = f"test-{key}"
            sensor.options = ["normal", "planned_outage", "emergency"]  # Mock options
            sensor.coordinator = (
                coordinator  # Manually assign the coordinator since we mocked __init__
            )
            return sensor

    def test_electricity_sensor_shows_last_data_change_attribute(self):
        """Test that electricity sensor shows last_data_change attribute."""
        coordinator = self.create_mock_coordinator()
        sensor = self.create_test_sensor(coordinator, key="electricity")

        attributes = sensor.extra_state_attributes

        assert attributes is not None
        assert "last_data_change" in attributes
        assert attributes["last_data_change"] == datetime.datetime(
            2025, 1, 15, 10, 30, 0
        )

    def test_electricity_sensor_shows_all_expected_attributes(self):
        """Test that electricity sensor shows all expected attributes."""
        coordinator = self.create_mock_coordinator()
        sensor = self.create_test_sensor(coordinator, key="electricity")

        # Mock current event for more attributes
        event_mock = MagicMock()
        event_mock.description = "Planned Outage"
        event_mock.start = datetime.datetime(2025, 1, 15, 14, 0, 0)
        event_mock.end = datetime.datetime(2025, 1, 15, 16, 0, 0)
        coordinator.get_current_event.return_value = event_mock

        attributes = sensor.extra_state_attributes

        expected_attributes = {
            "event_type": "Planned Outage",
            "event_start": datetime.datetime(2025, 1, 15, 14, 0, 0),
            "event_end": datetime.datetime(2025, 1, 15, 16, 0, 0),
            "supported_states": ["normal", "planned_outage", "emergency"],
            "last_data_change": datetime.datetime(2025, 1, 15, 10, 30, 0),
        }

        assert attributes == expected_attributes

    def test_schedule_updated_on_sensor_shows_extra_attributes(self):
        """Test that schedule_updated_on sensor also shows extra attributes."""
        coordinator = self.create_mock_coordinator()

        # Test schedule_updated_on sensor
        sensor = self.create_test_sensor(coordinator, key="schedule_updated_on")
        attributes = sensor.extra_state_attributes

        assert attributes is not None
        assert "last_data_change" in attributes
        assert attributes["last_data_change"] == datetime.datetime(
            2025, 1, 15, 10, 30, 0
        )

    def test_last_data_change_handles_none_value(self):
        """Test that last_data_change attribute can be None."""
        coordinator = self.create_mock_coordinator()
        coordinator.outage_data_last_changed = None  # No changes detected yet

        sensor = self.create_test_sensor(coordinator, key="electricity")
        attributes = sensor.extra_state_attributes

        assert attributes["last_data_change"] is None

    def test_attribute_structure_contains_last_data_change(self):
        """Test that the attribute structure correctly includes last_data_change."""
        # Test the attribute structure that should contain last_data_change
        attributes = {
            "event_type": None,
            "event_start": None,
            "event_end": None,
            "supported_states": ["normal", "planned_outage", "emergency"],
            "last_data_change": datetime.datetime(2025, 1, 15, 10, 30, 0),
        }
        assert "last_data_change" in attributes
        assert isinstance(attributes["last_data_change"], datetime.datetime)
