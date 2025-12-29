"""Base coordinator for Svitlo Yeah integration."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEvent
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from ..const import (
    DEBUG,
    DOMAIN,
    EVENT_DATA_CHANGED,
    TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE,
    UPDATE_INTERVAL,
)
from ..models import (
    ConnectivityState,
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoRegion,
)

if TYPE_CHECKING:
    from ..api.dtek.base import DtekAPIBase
    from ..api.yasno import YasnoApi
    from ..models.providers import BaseProvider

LOGGER = logging.getLogger(__name__)

TIMEFRAME_TO_CHECK = datetime.timedelta(hours=24)


class IntegrationCoordinator(DataUpdateCoordinator):
    """Base class to manage fetching outages data."""

    config_entry: ConfigEntry
    api: DtekAPIBase | YasnoApi
    region: YasnoRegion
    provider: BaseProvider

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(minutes=UPDATE_INTERVAL),
            config_entry=config_entry,
        )
        self.translations = {}
        self._previous_outage_events: list[PlannedOutageEvent] | None = None
        self.outage_data_last_changed: datetime.datetime | None = None
        self.group: str | None = None

    async def async_fetch_translations(self) -> None:
        """Fetch translations."""
        self.translations = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "common",
            [DOMAIN],
        )

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        raise NotImplementedError

    def _get_next_event_of_type(
        self, state_type: ConnectivityState | None = None
    ) -> CalendarEvent | None:
        """Get the next event of a specific type."""
        now = dt_utils.as_local(dt_utils.now())
        # Sort events to handle multi-day spanning events correctly
        next_events = sorted(
            self.get_events_between(
                now,
                now + TIMEFRAME_TO_CHECK,
            ),
            key=lambda _: _.start,
        )
        for event in next_events:
            _now = now.date() if event.all_day else now
            # event.start can be datetime or date (all_day event)
            if event.start > _now and (
                state_type is None or self._event_to_state(event) == state_type
            ):
                return event
        return None

    @property
    def next_planned_outage(self) -> datetime.date | datetime.datetime | None:
        """Get the next planned outage time."""
        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        return event.start if event else None

    @property
    def next_event(self) -> CalendarEvent | None:
        """Get the next event of any type."""
        return self._get_next_event_of_type(None)

    @property
    def next_connectivity(self) -> datetime.date | datetime.datetime | None:
        """Get next connectivity time."""
        current_event = self.get_current_event()
        current_state = self._event_to_state(current_event)

        # If currently in outage state, return when it ends
        if current_state == ConnectivityState.STATE_PLANNED_OUTAGE:
            return current_event.end if current_event else None

        # Otherwise, return the end of the next outage
        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        return event.end if event else None

    @property
    def current_state(self) -> str:
        """Get the current state."""
        event = self.get_current_event()
        return self._event_to_state(event)

    @property
    def schedule_updated_on(self) -> datetime.datetime | None:
        """Get the schedule last updated timestamp."""
        return self.api.get_updated_on()

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        raise NotImplementedError

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        raise NotImplementedError

    def get_current_event(self) -> CalendarEvent | None:
        """Get the event at the present time."""
        return self.get_event_at(dt_utils.now())

    def get_event_at(self, at: datetime.datetime) -> CalendarEvent | None:
        """Get the event at a given time."""
        event = self.api.get_current_event(at)
        return self._get_calendar_event(event)

    def get_events_between(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get all events."""
        events = self.api.get_events(start_date, end_date)
        output = [self._get_calendar_event(_) for _ in events]
        return [_ for _ in output if _]

    def get_scheduled_events_between(
        self,
        start_date: datetime.datetime,  # noqa: ARG002
        end_date: datetime.datetime,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """Get scheduled outage events."""
        return []

    def _get_calendar_event(
        self, event: PlannedOutageEvent | None
    ) -> CalendarEvent | None:
        """Transform a regular event into a CalendarEvent."""
        if not event:
            return None

        if DEBUG:
            LOGGER.debug(
                "Getting event name for %s from %s",
                event.event_type,
                self.event_name_map,
            )

        summary: str = self.event_name_map.get(event.event_type, "")
        if not summary:
            LOGGER.warning(
                f"Couldn't get {event.event_type} from {self.event_name_map}."
                f" Please report this."
            )

        if DEBUG:
            summary += (
                f" {event.start.date().day}.{event.start.date().month}"
                f"@{event.start.time()}"
                f"-{event.end.date().day}.{event.end.date().month}"
                f"@{event.end.time()}"
            )

        # noinspection PyTypeChecker
        return CalendarEvent(
            summary=summary,
            start=event.start,
            end=event.end,
            description=event.event_type.value,
            uid=event.event_type.value,
        )

    def _get_scheduled_calendar_event(
        self, event: PlannedOutageEvent | None, *, rrule: str | None = None
    ) -> CalendarEvent | None:
        """Transform a scheduled event into a CalendarEvent."""
        if not event:
            return None

        if DEBUG:
            LOGGER.debug(
                "Getting scheduled event name for %s",
                event.event_type,
            )

        # Use scheduled outage translation for scheduled events
        summary: str = self.translations.get(TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE, "")

        if DEBUG:
            summary += (
                f" {event.start.date().day}.{event.start.date().month}"
                f"@{event.start.time()}"
                f"-{event.end.date().day}.{event.end.date().month}"
                f"@{event.end.time()}"
            )

        # noinspection PyTypeChecker
        return CalendarEvent(
            summary=summary,
            start=event.start,
            end=event.end,
            description=PlannedOutageEventType.SCHEDULED.value,
            uid=PlannedOutageEventType.SCHEDULED.value,
            rrule=rrule,  # Configurable recurrence rule
        )

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        raise NotImplementedError

    def initialize_outage_data_tracking(
        self, current_events: list[PlannedOutageEvent]
    ) -> None:
        """Initialize outage tracking with current events and update timestamp."""
        # Sort events for comparison. isoformat due to datetime and date objects
        sorted_current = sorted(
            current_events,
            key=lambda e: (e.start.isoformat(), e.end.isoformat(), e.event_type.value),
        )
        self._previous_outage_events = sorted_current
        # Initialize with the API's last update timestamp
        self.outage_data_last_changed = None

    def fire_event(self) -> None:
        """Fire event for data change."""
        event_data = {
            "region_name": self.provider.region_name,
            "region_id": getattr(self.provider, "region_id", None),
            "provider_id": getattr(self.provider, "id", None),
            "provider_name": getattr(self.provider, "name", None),
            "group": self.group,
            "last_data_change": self.outage_data_last_changed,
            "config_entry_id": self.config_entry.entry_id,
        }

        self.hass.bus.async_fire(EVENT_DATA_CHANGED, event_data)
        LOGGER.debug("Fired %s event for %s", EVENT_DATA_CHANGED, self.group)

    def check_outage_data_changed(
        self, current_events: list[PlannedOutageEvent]
    ) -> bool:
        """Check if outage data has changed and update last changed timestamp."""
        # Sort events for comparison. isoformat due to datetime and date objects
        sorted_current = sorted(
            current_events,
            key=lambda e: (e.start.isoformat(), e.end.isoformat(), e.event_type.value),
        )

        if self._previous_outage_events is None:
            # First run - initialize tracking
            self.initialize_outage_data_tracking(sorted_current)
            """
            # EVENT DEBUG. DO NOT COMMIT UNCOMMENTED
            self.fire_event()
            """
            return False

        # Compare with previous events
        if sorted_current != self._previous_outage_events:
            self._previous_outage_events = sorted_current
            self.outage_data_last_changed = dt_utils.now()
            LOGGER.debug("Outage data changed at %s", self.outage_data_last_changed)
            self.fire_event()
            return True

        return False
