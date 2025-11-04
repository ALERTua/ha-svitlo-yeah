"""Sensor platform for Svitlo Yeah integration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator.yasno import YasnoCoordinator
from .entity import IntegrationEntity
from .models import ConnectivityState

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class IntegrationSensorDescription(SensorEntityDescription):
    """Yasno Outages entity description."""

    val_func: Callable[[YasnoCoordinator], Any]


SENSOR_TYPES: tuple[IntegrationSensorDescription, ...] = (
    IntegrationSensorDescription(
        key="electricity",
        translation_key="electricity",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.ENUM,
        options=[str(_.value) for _ in ConnectivityState],
        val_func=lambda coordinator: coordinator.current_state,
    ),
    IntegrationSensorDescription(
        key="current_day_status",
        translation_key="current_day_status",
        icon="mdi:calendar-today",
        device_class=SensorDeviceClass.ENUM,
        options=["ScheduleApplies", "EmergencyShutdowns"],
        val_func=lambda coordinator: coordinator.current_day_status,
    ),
    IntegrationSensorDescription(
        key="next_outage_type",
        translation_key="next_outage_type",
        icon="mdi:alert-circle",
        device_class=SensorDeviceClass.ENUM,
        options=["Definite", "Emergency", "NotPlanned"],
        val_func=lambda coordinator: coordinator.next_outage_type,
    ),
    # Schedule and timing sensors
    IntegrationSensorDescription(
        key="schedule_updated_on",
        translation_key="schedule_updated_on",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.schedule_updated_on,
    ),
    IntegrationSensorDescription(
        key="next_planned_outage",
        translation_key="next_planned_outage",
        icon="mdi:calendar-remove",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_planned_outage,
    ),
    IntegrationSensorDescription(
        key="next_connectivity",
        translation_key="next_connectivity",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_connectivity,
    ),
    IntegrationSensorDescription(
        key="next_planned_reconnection",
        translation_key="next_planned_reconnection",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_planned_reconnection,
    ),
    # Time detail sensors
    IntegrationSensorDescription(
        key="next_planned_outage_start_time",
        translation_key="next_planned_outage_start_time",
        icon="mdi:clock-start",
        val_func=lambda coordinator: coordinator.next_planned_outage_start_time,
    ),
    IntegrationSensorDescription(
        key="next_planned_outage_end_time",
        translation_key="next_planned_outage_end_time",
        icon="mdi:clock-end",
        val_func=lambda coordinator: coordinator.next_planned_outage_end_time,
    ),
    # Duration and countdown sensors
    IntegrationSensorDescription(
        key="next_planned_outage_duration",
        translation_key="next_planned_outage_duration",
        icon="mdi:timer",
        native_unit_of_measurement="min",
        val_func=lambda coordinator: coordinator.next_planned_outage_duration,
    ),
    IntegrationSensorDescription(
        key="time_until_connectivity",
        translation_key="time_until_connectivity",
        icon="mdi:clock-outline",
        val_func=lambda coordinator: coordinator.time_until_connectivity,
    ),
    IntegrationSensorDescription(
        key="time_until_outage",
        translation_key="time_until_outage",
        icon="mdi:clock-alert-outline",
        val_func=lambda coordinator: coordinator.time_until_outage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    LOGGER.debug("Setup new sensor: %s", config_entry)
    coordinator: YasnoCoordinator = config_entry.runtime_data
    async_add_entities(
        IntegrationSensor(coordinator, description) for description in SENSOR_TYPES
    )


class IntegrationSensor(IntegrationEntity, SensorEntity):
    """Implementation of sensor entity."""

    entity_description: IntegrationSensorDescription

    def __init__(
        self,
        coordinator: YasnoCoordinator,
        entity_description: IntegrationSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-"
            f"{coordinator.group}-"
            f"{self.entity_description.key}"
        )

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.entity_description.val_func(self.coordinator)

    @property
    def icon(self) -> str | None:
        """Return the icon of the sensor."""
        # Dynamic icons for electricity sensor
        if self.entity_description.key == "electricity":
            state = self.native_value
            if state == ConnectivityState.STATE_NORMAL.value:
                return "mdi:transmission-tower"
            if state == ConnectivityState.STATE_PLANNED_OUTAGE.value:
                return "mdi:transmission-tower-off"
            if state == ConnectivityState.STATE_EMERGENCY.value:
                return "mdi:alert-octagon"

        return self.entity_description.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes for the electricity sensor."""
        if self.entity_description.key != "electricity":
            return None

        # Get the current event to provide additional context
        current_event = self.coordinator.get_current_event()
        return {
            "event_type": current_event.description if current_event else None,
            "event_start": current_event.start if current_event else None,
            "event_end": current_event.end if current_event else None,
            "supported_states": self.options,
        }
