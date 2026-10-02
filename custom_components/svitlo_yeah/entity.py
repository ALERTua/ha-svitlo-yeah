"""Svitlo Yeah entity."""

import datetime
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_utils

from .const import (
    CONF_PROVIDER_TYPE,
    DEVICE_MANUFACTURER,
    DOMAIN,
    PROVIDER_TO_DEVICE_NAME_MAP,
    UPDATE_INTERVAL,
)
from .coordinator.coordinator import IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent

LOGGER = logging.getLogger(__name__)


class IntegrationEntity(CoordinatorEntity[IntegrationCoordinator]):
    """Common logic for Svitlo Yeah entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IntegrationCoordinator) -> None:
        """Initialize the integration entity."""
        super().__init__(coordinator)
        self._unsubscribe_boundary = None
        self._event: CalendarEvent | None = None

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity."""
        provider_type = self.coordinator.config_entry.data[CONF_PROVIDER_TYPE]
        translation_key = PROVIDER_TO_DEVICE_NAME_MAP[provider_type]

        # provider is optional
        if not all((self.coordinator.provider_name, self.coordinator.group)):
            LOGGER.debug(
                "Device info without a provider or a group: provider type %s, "
                "translation key %s, region %s, provider %s, group %s",
                provider_type,
                translation_key,
                self.coordinator.region_name,
                self.coordinator.provider_name,
                self.coordinator.group,
            )

        return DeviceInfo(
            translation_key=translation_key,
            translation_placeholders={
                "region_name": self.coordinator.region_name,
                "provider_name": self.coordinator.provider_name,
                "group": str(self.coordinator.group),
            },
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            manufacturer=DEVICE_MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    @override
    async def async_added_to_hass(self) -> None:
        """When entity is added, schedule first boundary update."""
        await super().async_added_to_hass()
        self._update_active_state()
        self._schedule_next_boundary()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Cancel the scheduled boundary callback when the entity is removed."""
        if self._unsubscribe_boundary:
            self._unsubscribe_boundary()
            self._unsubscribe_boundary = None
        await super().async_will_remove_from_hass()

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Write the new state, and plan the next boundary from the new data."""
        self._event = self.coordinator.get_current_event()
        self._schedule_next_boundary()
        super()._handle_coordinator_update()

    def _update_active_state(self) -> None:
        """Recalculate active state from events."""
        if (event := self.coordinator.get_current_event()) != self._event:
            self._event = event
            self.async_write_ha_state()

    def _schedule_next_boundary(self) -> None:
        """Schedule callback exactly at next event boundary."""
        # Cancel previous callback, if any
        if self._unsubscribe_boundary:
            self._unsubscribe_boundary()
            self._unsubscribe_boundary = None

        events = [
            self.coordinator.get_current_event(),
            self.coordinator.next_event,
        ]
        boundaries = []
        for event in events:
            if not event or event.all_day:
                continue

            boundaries.append(event.start_datetime_local)
            boundaries.append(event.end_datetime_local)

        boundaries.sort()
        next_boundary = None
        now = dt_utils.now()
        for boundary in boundaries:
            if boundary - dt_utils.now() <= datetime.timedelta(seconds=1):
                continue

            next_boundary = boundary
            break

        next_boundary = next_boundary or now + datetime.timedelta(
            minutes=UPDATE_INTERVAL
        )
        # noinspection PyTypeChecker
        self._unsubscribe_boundary = async_track_point_in_time(
            self.hass, self._handle_boundary, next_boundary
        )

    async def _handle_boundary(self, *_args: Any) -> None:
        """Run at exact event start/end."""
        self._update_active_state()
        self._schedule_next_boundary()
