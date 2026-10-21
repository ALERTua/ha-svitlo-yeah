"""Sensor platform for Svitlo Yeah integration."""

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, override

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import EntityCategory, Platform
from homeassistant.helpers import entity_registry as er

from .const import CONF_PROVIDER_TYPE, DOMAIN, PROVIDER_TYPE_YASNO
from .entity import IntegrationEntity
from .models import ConnectivityState, YasnoAddress

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator.coordinator import IntegrationCoordinator, SvitloYeahConfigEntry

LOGGER = logging.getLogger(__name__)

# The coordinator fetches the data for all entities, which only read it
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IntegrationSensorDescription(SensorEntityDescription):
    """Yasno Outages entity description."""

    val_func: Callable[[IntegrationCoordinator], Any]


SENSORS: tuple[IntegrationSensorDescription, ...] = (
    IntegrationSensorDescription(
        key="electricity",
        translation_key="electricity",
        device_class=SensorDeviceClass.ENUM,
        options=[str(_.value) for _ in ConnectivityState],
        val_func=lambda coordinator: coordinator.current_state,
    ),
    IntegrationSensorDescription(
        key="schedule_updated_on",
        translation_key="schedule_updated_on",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.schedule_updated_on,
    ),
    IntegrationSensorDescription(
        key="schedule_data_changed",
        translation_key="schedule_data_changed",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.outage_data_last_changed,
    ),
    IntegrationSensorDescription(
        key="next_planned_outage",
        translation_key="next_planned_outage",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_planned_outage,
    ),
    IntegrationSensorDescription(
        key="next_scheduled_outage",
        translation_key="next_scheduled_outage",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_scheduled_outage,
    ),
    IntegrationSensorDescription(
        key="next_connectivity",
        translation_key="next_connectivity",
        device_class=SensorDeviceClass.TIMESTAMP,
        val_func=lambda coordinator: coordinator.next_connectivity,
    ),
)

# The group of the entry. A Yasno entry can get a new group from the check of its
# address, so only a Yasno entry has this sensor. The other providers keep the group
# that the user selected, which the device name shows. The sensor is enabled by
# default only on an entry with an address (see async_setup_entry).
GROUP_SENSOR = IntegrationSensorDescription(
    key="group",
    translation_key="group",
    entity_category=EntityCategory.DIAGNOSTIC,
    val_func=lambda coordinator: coordinator.group,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SvitloYeahConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    LOGGER.debug("Setup new sensor: %s", config_entry.entry_id)
    coordinator = config_entry.runtime_data
    descriptions = SENSORS
    if config_entry.data.get(CONF_PROVIDER_TYPE) == PROVIDER_TYPE_YASNO:
        # Only an address can give the entry a new group, so a group entry has
        # nothing to watch. Home Assistant reads this flag only when the registry gets
        # the entity for the first time. A sensor that an earlier version enabled on a
        # group entry stays enabled, and a Reconfigure back to a group keeps it too.
        has_address = YasnoAddress.from_entry_data(config_entry.data) is not None
        if has_address:
            _enable_group_sensor(hass, config_entry)
        descriptions = (
            *SENSORS,
            replace(GROUP_SENSOR, entity_registry_enabled_default=has_address),
        )
    async_add_entities(
        IntegrationSensor(coordinator, description) for description in descriptions
    )


def _enable_group_sensor(
    hass: HomeAssistant, config_entry: SvitloYeahConfigEntry
) -> None:
    """
    Enable the group sensor that the integration disabled on a group entry.

    A Reconfigure can give a group entry an address, and the registry already has the
    sensor as disabled. Home Assistant reloads the entry 30 seconds after an entity
    gets enabled, so the entry reloads once more: the integration accepts this cost.
    A sensor that the user disabled stays disabled.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{config_entry.entry_id}_{GROUP_SENSOR.key}"
    )
    entity = registry.async_get(entity_id) if entity_id else None
    if entity is None or entity.disabled_by is not er.RegistryEntryDisabler.INTEGRATION:
        return
    # The entity id has the address, so the log names the entry only
    LOGGER.debug("Enable the group sensor of entry %s", config_entry.entry_id)
    registry.async_update_entity(entity.entity_id, disabled_by=None)


class IntegrationSensor(IntegrationEntity, SensorEntity):
    """Implementation of sensor entity."""

    entity_description: IntegrationSensorDescription

    def __init__(
        self,
        coordinator: IntegrationCoordinator,
        entity_description: IntegrationSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description

        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        )

    @property
    @override
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
        if self.entity_description.key != "electricity":
            return attrs

        return {
            **attrs,
            "event_type": current_event.description if current_event else None,
            "event_start": current_event.start if current_event else None,
            "event_end": current_event.end if current_event else None,
            "supported_states": self.options,
            "current_state": self.state,
        }
