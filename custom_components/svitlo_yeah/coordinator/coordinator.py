"""Base coordinator for Svitlo Yeah integration."""

import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEvent
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from collections.abc import Sequence

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from ..const import (
    DOMAIN,
    EVENT_DATA_CHANGED,
    ISSUE_GROUP_NOT_LISTED,
    NAME,
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
    from ..api.e_svitlo import ESvitloClient
    from ..api.yasno import YasnoApi
    from ..models.providers import BaseProvider

LOGGER = logging.getLogger(__name__)

TIMEFRAME_TO_CHECK = datetime.timedelta(hours=24)

# The store keeps the last data of an entry across a restart (AGENTS.md, «Old
# states until new data»)
STORE_VERSION = 1


def group_not_listed_issue_id(entry_id: str) -> str:
    """Return the id of the repair issue about a group that the source lacks."""
    return f"{ISSUE_GROUP_NOT_LISTED}_{entry_id}"


def store_key(entry_id: str) -> str:
    """Return the key of the store that keeps the last data of an entry."""
    return f"{DOMAIN}.{entry_id}"


# A config entry of this integration, with its coordinator in runtime_data
type SvitloYeahConfigEntry = ConfigEntry[IntegrationCoordinator]


class IntegrationCoordinator(DataUpdateCoordinator[None]):
    """
    Base class to manage fetching outages data.

    The coordinator keeps no data of its own: the API client of each provider
    holds the schedule, so the data of the coordinator is None.
    """

    config_entry: SvitloYeahConfigEntry
    api: DtekAPIBase | YasnoApi | ESvitloClient
    region: YasnoRegion
    provider: BaseProvider

    def __init__(
        self, hass: HomeAssistant, config_entry: SvitloYeahConfigEntry
    ) -> None:
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
        # Whether the source lists the configured group, from the last data
        # that could tell. None until such data arrives.
        self.group_listed: bool | None = None
        # Whether the last fetch got no answer from the source. The entities
        # keep the last data then, so the refresh button and one log line of
        # _set_last_fetch_failed report it.
        self.last_fetch_failed = False
        # Whether the server refused the login; only E-Svitlo has a login
        self.login_rejected = False
        self._store: Store[dict] | None = None
        self._stored: dict | None = None

    async def _async_setup(self) -> None:
        """
        Start with the data that the last run kept, until the source answers.

        Thus after a restart the entities show the old states, also while the
        source does not answer.
        """
        self._store = Store(
            self.hass, STORE_VERSION, store_key(self.config_entry.entry_id)
        )
        stored = await self._store.async_load()
        if not stored:
            return
        self._stored = stored
        self._restore_source_data(stored["source"])
        if changed := stored.get("outage_data_last_changed"):
            self.outage_data_last_changed = dt_utils.parse_datetime(changed)
        # After a Reconfigure, the kept answer is about another group
        if stored.get("group") == self.group:
            await self.async_fetch_translations()  # the repair issue names the provider
            await self._async_update_group_listed(stored.get("group_listed"))

    def _source_data(self) -> dict | None:
        """Return the data of the source to keep across a restart, or None."""
        raise NotImplementedError

    def _restore_source_data(self, source: dict) -> None:
        """Give the kept data of the source back to the API client."""
        raise NotImplementedError

    async def _async_store_last_data(self) -> None:
        """Keep the last data of the source, when it changed after the last save."""
        if self._store is None or (source := self._source_data()) is None:
            return
        data = {
            "source": source,
            "group": self.group,
            "group_listed": self.group_listed,
            "outage_data_last_changed": (
                self.outage_data_last_changed.isoformat()
                if self.outage_data_last_changed
                else None
            ),
        }
        if data != self._stored:
            await self._store.async_save(data)
            self._stored = data

    def _set_last_fetch_failed(self, failed: bool) -> None:
        """
        Keep whether the last fetch got no answer, and log each change once.

        The entities keep the last data meanwhile, so these two info lines
        tell when the source stopped answering and when it answered again.
        """
        if failed == self.last_fetch_failed:
            return
        # An E-Svitlo entry has no provider_id, and its address is personal data
        source = getattr(self, "provider_id", None) or self.provider.region_name
        if failed:
            LOGGER.info(
                "The source of provider %s does not answer for group %s, "
                "so the entities keep the last schedule",
                source,
                self.group,
            )
        else:
            LOGGER.info(
                "The source of provider %s answers again for group %s",
                source,
                self.group,
            )
        self.last_fetch_failed = failed

    async def _async_update_group_listed(self, listed: bool | None) -> None:
        """
        Keep the last known answer whether the source lists the group.

        None means that the data says nothing about the group, so the last
        known answer stays. A change is logged once: a warning when the group
        disappears from the source, and an info when it comes back. While the
        group is missing, a repair issue tells the user about it.
        """
        if listed is None or listed == self.group_listed:
            return

        provider = getattr(self, "provider_id", None)
        issue_id = group_not_listed_issue_id(self.config_entry.entry_id)
        if listed is False:
            LOGGER.warning(
                "The source of provider %s has no schedule for group %s, "
                "so the integration shows no outages for this group",
                provider,
                self.group,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_GROUP_NOT_LISTED,
                translation_placeholders={
                    "group": str(self.group),
                    "provider": " ".join(
                        filter(None, (self.region_name, self.provider_name))
                    ),
                    # The way to Reconfigure goes through the list of integrations
                    "integration": await self._async_integration_title(),
                },
            )
        elif self.group_listed is False:
            LOGGER.info(
                "The source of provider %s lists group %s again", provider, self.group
            )
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self.group_listed = listed

    async def _async_integration_title(self) -> str:
        """Return the integration name that the list of integrations shows."""
        titles = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "title",
            [DOMAIN],
        )
        return titles.get(f"component.{DOMAIN}.title", NAME)

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

    def _get_first_future_start(
        self,
        events: Sequence[PlannedOutageEvent | CalendarEvent],
    ) -> datetime.date | datetime.datetime | None:
        """Get the start time of the first future event."""
        now = dt_utils.as_local(dt_utils.now())
        now_date = now.date()
        for event in sorted(events, key=lambda _: _.start):
            comparison_time = now_date if event.all_day else now
            if event.start > comparison_time:
                return event.start
        return None

    def _get_earliest_start_time(
        self,
        candidates: list[datetime.date | datetime.datetime | None],
    ) -> datetime.date | datetime.datetime | None:
        """Get the earliest start time from candidates, ignoring None values."""
        valid_candidates = [c for c in candidates if c is not None]
        return min(valid_candidates) if valid_candidates else None

    def _get_next_event_of_type(
        self, state_type: ConnectivityState | None = None
    ) -> CalendarEvent | None:
        """Get the next event of a specific type."""
        now = dt_utils.as_local(dt_utils.now())
        events = self.get_events_between(now, now + TIMEFRAME_TO_CHECK)

        # Filter by state type if specified
        if state_type is not None:
            events = [_ for _ in events if self._event_to_state(_) == state_type]

        # Find first future event
        start_time = self._get_first_future_start(events)
        if start_time is None:
            return None

        # Return the event with that start time
        for event in events:
            if event.start == start_time:
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
    def next_scheduled_outage(self) -> datetime.date | datetime.datetime | None:
        """Get the next scheduled or planned outage time, whichever is nearest."""
        now = dt_utils.as_local(dt_utils.now())

        # Get next scheduled outage using helper
        scheduled_events = self.get_scheduled_events_between(
            now, now + TIMEFRAME_TO_CHECK
        )
        next_scheduled = self._get_first_future_start(scheduled_events)

        # Get next planned outage
        next_planned = self.next_planned_outage

        # Return the earliest one using helper
        return self._get_earliest_start_time([next_scheduled, next_planned])

    @property
    def current_state(self) -> str | None:
        """
        Get the current state.

        None (unknown) while the source lists other groups but not this one:
        without a schedule, "normal" would claim that the power is on.

        Only data that lists groups tells that the group is missing, and for
        DTEK only fresh data does. Without such data, for example for a new
        entry while the DTEK source is stale, there are no events, and the
        state is "normal".
        """
        if self.group_listed is False:
            return None
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
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get scheduled outage events."""
        return []

    def _get_calendar_event(
        self, event: PlannedOutageEvent | None
    ) -> CalendarEvent | None:
        """Transform a regular event into a CalendarEvent."""
        if not event:
            return None

        summary: str = self.event_name_map.get(event.event_type, "")
        if not summary:
            LOGGER.warning(
                "Couldn't get %s from %s. Please report this.",
                event.event_type,
                self.event_name_map,
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

        # Use scheduled outage translation for scheduled events
        summary: str = (
            f"{self.translations.get(TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE, '')}"
            f"{self._group_str}"
        )
        summary = summary.strip()

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
        """
        Initialize outage tracking with current events.

        The time of the last change stays as it is: None, or the time that the
        store kept from the last run.
        """
        # Sort events for comparison. isoformat due to datetime and date objects
        sorted_current = sorted(
            current_events,
            key=lambda e: (e.start.isoformat(), e.end.isoformat(), e.event_type.value),
        )
        self._previous_outage_events = sorted_current

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
            return False

        # Compare with previous events
        if sorted_current != self._previous_outage_events:
            self._previous_outage_events = sorted_current
            self.outage_data_last_changed = dt_utils.now()
            LOGGER.debug("Outage data changed at %s", self.outage_data_last_changed)
            self.fire_event()
            return True

        return False

    @property
    def _group_str(self) -> str:
        """
        Postfix for CalendarEvent summaries.

        e.g. Scheduled Outage 3.1
        """
        return f" {self.group}"
