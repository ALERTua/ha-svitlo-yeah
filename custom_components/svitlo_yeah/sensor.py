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


SENSORS: tuple[IntegrationSensorDescription, ...] = (
    IntegrationSensorDescription(
        key="electricity",
        translation_key="electricity",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.ENUM,
        options=[str(_.value) for _ in ConnectivityState],
        val_func=lambda coordinator: coordinator.current_state,
    ),
    IntegrationSensorDescription(
        key="schedule_updated_on",
        translation_key="schedule_updated_on",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.schedule_updated_on,
    ),
    IntegrationSensorDescription(
        key="schedule_data_changed",
        translation_key="schedule_data_changed",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.outage_data_last_changed,
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
)


# noinspection PyUnusedLocal
async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    LOGGER.debug("Setup new sensor: %s", config_entry)
    coordinator: YasnoCoordinator = config_entry.runtime_data
    async_add_entities(
        IntegrationSensor(coordinator, description) for description in SENSORS
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
            f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        )

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.entity_description.val_func(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes for the electricity sensor."""
        # Show extra attributes only for these sensors
        if self.entity_description.key not in ["electricity", "schedule_updated_on"]:
            return None

        current_event = self.coordinator.get_current_event()
        attrs = {
            # timestamp when outage data actually changed
            "last_data_change": self.coordinator.outage_data_last_changed,
        }
        if self.entity_description.key not in ["electricity"]:
            return attrs

        return {
            **attrs,
            "event_type": current_event.description if current_event else None,
            "event_start": current_event.start if current_event else None,
            "event_end": current_event.end if current_event else None,
            "supported_states": self.options,
            "current_state": self.state,
        }
