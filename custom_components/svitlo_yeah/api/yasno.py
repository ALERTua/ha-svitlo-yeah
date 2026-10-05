"""Yasno API client for Svitlo Yeah integration."""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.core import HomeAssistant

from custom_components.svitlo_yeah.const import (
    BLOCK_KEY_STATUS,
    HOURS_IN_DAY,
    MINUTES_IN_DAY,
    TZ_UA,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoPlannedOutageDayStatus,
    YasnoRegion,
)

from .common_tools import (
    REQUEST_ERRORS,
    _merge_adjacent_events,
    parse_timestamp,
    start_moment,
)

LOGGER = logging.getLogger(__name__)


def _minutes_to_time(minutes: int, dt: datetime) -> datetime:
    """Convert minutes from start of day to datetime."""
    hours = minutes // 60
    mins = minutes % 60

    # Handle end of day (24:00) as 00:00 of the next day
    if hours == HOURS_IN_DAY:
        dt = dt + timedelta(days=1)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    return dt.replace(hour=hours, minute=mins, second=0, microsecond=0)


def _parse_day_schedule(day_data: dict, dt: datetime) -> list[PlannedOutageEvent]:
    """
    Parse schedule for a single day.

    {
      "3.1": {
        "today": {
          "slots": [
            {
              "start": 0,
              "end": 960,
              "type": "NotPlanned"
            },
            {
              "start": 960,
              "end": 1200,
              "type": "Definite"
            },
            {
              "start": 1200,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-27T00:00:00+02:00",
          "status": "ScheduleApplies"
        },
        "tomorrow": {
          "slots": [
            {
              "start": 0,
              "end": 900,
              "type": "NotPlanned"
            },
            {
              "start": 900,
              "end": 1080,
              "type": "Definite"
            },
            {
              "start": 1080,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-28T00:00:00+02:00",
          "status": "WaitingForSchedule"
        },
        "updatedOn": "2025-10-27T13:42:41+00:00"
      },
    }
    """
    events = []
    slots = day_data.get("slots", [])

    for slot in slots:
        start_minutes = slot["start"]
        end_minutes = slot["end"]
        slot_type = slot["type"]

        # parse only outages, and a slot without a duration is no outage
        if (
            slot_type != PlannedOutageEventType.DEFINITE.value
            or start_minutes == end_minutes
        ):
            continue

        event_start = _minutes_to_time(start_minutes, dt)
        event_end = _minutes_to_time(end_minutes, dt)

        events.append(
            PlannedOutageEvent(
                start=event_start,
                end=event_end,
                event_type=PlannedOutageEventType(slot_type),
            ),
        )

    return events


def _is_day(day: dict) -> bool:
    """Return whether a day of a group has the shape that the parsers read."""
    slots = day.get("slots", [])
    return (
        isinstance(day.get("date"), str | None)
        and isinstance(slots, list)
        and all(
            isinstance(slot, dict)
            # The minutes are whole numbers; a bool would pass isinstance(_, int)
            and all(
                type(slot.get(key)) is int and 0 <= slot[key] <= MINUTES_IN_DAY
                for key in ("start", "end")
            )
            # HA refuses a calendar event that ends before it starts
            and slot["start"] <= slot["end"]
            and isinstance(slot.get("type"), str)
            for slot in slots
        )
    )


def is_planned_outages(answer: object) -> bool:
    """Return whether planned outages have the shape that the parsers read."""
    return isinstance(answer, dict) and all(
        isinstance(group, dict)
        # The parsers skip a value that is not a day, for example updatedOn
        and all(_is_day(day) for day in group.values() if isinstance(day, dict))
        for group in answer.values()
    )


def _in_range(
    events: list[PlannedOutageEvent], start_date: datetime, end_date: datetime
) -> list[PlannedOutageEvent]:
    """Sort and merge the events, and keep those in the range and each all-day one."""
    events = _merge_adjacent_events(sorted(events, key=start_moment))
    return [
        _
        for _ in events
        if _.all_day or not (_.end <= start_date or _.start >= end_date)
    ]


class YasnoApi:
    """Class to interact with Yasno API."""

    _regions: list[YasnoRegion] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        region_id: int | None = None,
        provider_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the Yasno API."""
        self.hass = hass
        self.session: aiohttp.ClientSession = async_get_clientsession(hass)
        self.region_id: int | None = region_id
        self.provider_id: int | None = provider_id
        self.group: str | None = group
        self.planned_outage_data: dict | None = None

    async def _get_route_data(
        self,
        url: str,
        timeout_secs: int = 60,
    ) -> Any:
        """Fetch the JSON of the URL: a list or a dict, or None after a failure."""
        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
            ) as response:
                response.raise_for_status()
                return await response.json()

        except REQUEST_ERRORS:
            # The coordinator logs once when Yasno stops answering
            LOGGER.debug("Error fetching data from %s", url, exc_info=True)
            return None

    async def fetch_yasno_regions(self) -> None:
        """Fetch regions and providers data."""
        if YasnoApi._regions:
            return

        result = await self._get_route_data(YASNO_REGIONS_ENDPOINT)

        if result:
            YasnoApi._regions = [YasnoRegion.from_dict(_) for _ in result]

        LOGGER.debug("Fetched yasno regions data: %s", YasnoApi._regions)

    async def fetch_planned_outage_data(self) -> bool:
        """Fetch the planned outages of the region, and tell whether Yasno answered."""
        if not self.region_id or not self.provider_id:
            LOGGER.error(
                "Region ID %s and Provider ID %s must be set before fetching outages",
                self.region_id,
                self.provider_id,
            )
            return False

        url = YASNO_PLANNED_OUTAGES_ENDPOINT.format(
            region_id=self.region_id,
            dso_id=self.provider_id,
        )
        LOGGER.debug("Fetching Yasno planned outage data: %s", url)
        output = await self._get_route_data(url)
        if output is None or not is_planned_outages(output):
            # A failed request or an answer of another shape says nothing new,
            # so the last planned outages stay
            LOGGER.debug("Keeping the last Yasno planned outage data")
            return False
        LOGGER.debug("Filling Yasno planned outage data with: %s", output)
        self.planned_outage_data = output

        return True

    @property
    def regions(self) -> list[YasnoRegion] | None:
        """Return the list of regions."""
        return YasnoApi._regions

    def get_region_by_id(self, region_id: int) -> YasnoRegion | None:
        """Get region data by name."""
        if not self.regions:
            LOGGER.debug(
                "Yasno API get_region_by_id %s while regions are not yet fetched",
                region_id,
            )
            return None

        LOGGER.debug("Getting region by id: %s among %s", region_id, self.regions)
        return next((_ for _ in self.regions if _.id == region_id), None)

    def get_yasno_groups(self) -> list[str]:
        """Get groups from planned outage data."""
        if not self.planned_outage_data:
            LOGGER.debug("Cannot get yasno groups: no planned outage data yet")
            return []

        return list(self.planned_outage_data.keys())

    def is_group_listed(self) -> bool | None:
        """
        Tell whether the planned outage data has the configured group.

        None: there is no data or no configured group, so the source says
        nothing about the group.
        """
        if (
            not self.group
            or not isinstance(self.planned_outage_data, dict)
            or not self.planned_outage_data
        ):
            return None
        return self.group in self.planned_outage_data

    def _get_group_data(self) -> dict | None:
        """
        Get data for the configured group.

        {
          'today': {
            'slots': [
              {
                'start': 0,
                'end': 1140,
                'type': 'NotPlanned'
              },
              {
                'start': 1140,
                'end': 1320,
                'type': 'Definite'
              },
              {
                'start': 1320,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-28T00:00:00+02:00',
            'status': 'ScheduleApplies'
          },
          'tomorrow': {
            'slots': [
              {
                'start': 0,
                'end': 960,
                'type': 'NotPlanned'
              },
              {
                'start': 960,
                'end': 1200,
                'type': 'Definite'
              },
              {
                'start': 1200,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-29T00:00:00+02:00',
            'status': 'WaitingForSchedule'
          },
          'updatedOn': '2025-10-28T10:23:56+00:00'
        }
        """
        if not self.planned_outage_data or self.group not in self.planned_outage_data:
            LOGGER.debug("No planned outage data for group %s", self.group)
            return None

        # noinspection PyTypeChecker
        return self.planned_outage_data[self.group]

    def get_updated_on(self) -> datetime | None:
        """Get the updated on timestamp for the configured group."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("Cannot get_updated_on: no group_data data yet")
            return None

        if "updatedOn" not in group_data:
            LOGGER.debug(
                "Cannot get_updated_on: updatedOn not in group_data %s", group_data
            )
            return None

        return parse_timestamp(group_data["updatedOn"])

    def get_current_event(self, at: datetime) -> PlannedOutageEvent | None:
        """Get the current event."""
        all_events = self.get_events(at, at + timedelta(days=1))
        # The date of an all-day event is a day in Kyiv
        day = at.astimezone(TZ_UA).date()
        for event in all_events:
            if event.all_day and event.start == day:
                return event
            if not event.all_day and event.start <= at < event.end:
                return event

        return None

    def _days(self) -> Iterator[tuple[str | None, dict, datetime]]:
        """Yield the status, the data and the moment of each day of the group."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("No days: no group_data yet")
            return

        for key, day_data in group_data.items():
            # parse only "today" and "tomorrow"
            if key == "updatedOn" or not isinstance(day_data, dict):
                continue

            date_str = day_data.get("date")
            if not date_str:
                continue

            day_dt = dt_utils.parse_datetime(date_str)
            if not day_dt:
                continue

            # The slots are minutes of the day in Kyiv, whatever the time zone of HA
            yield day_data.get(BLOCK_KEY_STATUS), day_data, day_dt.astimezone(TZ_UA)

    def get_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        events: list[PlannedOutageEvent] = []
        for status, day_data, day_dt in self._days():
            if status == YasnoPlannedOutageDayStatus.STATUS_SCHEDULE_APPLIES.value:
                events.extend(_parse_day_schedule(day_data, day_dt))
            elif status == YasnoPlannedOutageDayStatus.STATUS_EMERGENCY_SHUTDOWNS.value:
                """
                {
                    "3.1": {
                        "today": {
                            "slots": [],
                            "date": "2025-10-27T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "tomorrow": {
                            "slots": [],
                            "date": "2025-10-28T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "updatedOn": "2025-10-27T07:04:31+00:00"
                    }
                }
                """
                events.append(
                    PlannedOutageEvent(
                        start=day_dt.date(),
                        end=day_dt.date() + timedelta(days=1),
                        all_day=True,
                        event_type=PlannedOutageEventType.EMERGENCY,
                    )
                )
        return _in_range(events, start_date, end_date)

    def get_scheduled_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get scheduled events (includes WaitingForSchedule status)."""
        events = [
            event
            for status, day_data, day_dt in self._days()
            if status == YasnoPlannedOutageDayStatus.STATUS_WAITING_FOR_SCHEDULE.value
            for event in _parse_day_schedule(day_data, day_dt)
        ]
        return _in_range(events, start_date, end_date)

    async def fetch_data(self) -> bool:
        """
        Fetch all required data, and tell whether Yasno gave the planned outages.

        The regions only name the device, so their request does not count.
        """
        await self.fetch_yasno_regions()
        return await self.fetch_planned_outage_data()
