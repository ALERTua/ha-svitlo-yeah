"""Yasno API client for Svitlo Yeah integration."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta

import aiohttp
from homeassistant.util import dt as dt_utils

from ..const import (
    BLOCK_KEY_STATUS,
    DEBUG,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from ..models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoPlannedOutageDayStatus,
    YasnoRegion,
)
from .common_tools import _merge_adjacent_events, parse_timestamp

LOGGER = logging.getLogger(__name__)


def _minutes_to_time(minutes: int, dt: datetime) -> datetime:
    """Convert minutes from start of day to datetime."""
    hours = minutes // 60
    mins = minutes % 60

    # Handle end of day (24:00) as 00:00 of the next day
    if hours == 24:  # noqa: PLR2004
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

        # parse only outages
        if slot_type not in [PlannedOutageEventType.DEFINITE.value]:
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


# noinspection PyUnusedLocal
def _debug_data() -> dict:
    # emergency shutdowns
    now = datetime.now(UTC)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    output = {
        "3.1": {
            "today": {
                "slots": [],
                "date": today_midnight.isoformat(timespec="seconds"),
                "status": "EmergencyShutdowns",
            },
            "tomorrow": {
                "slots": [],
                "date": (today_midnight + timedelta(days=1)).isoformat(
                    timespec="seconds"
                ),
                "status": "EmergencyShutdowns",
            },
            "updatedOn": now.isoformat(timespec="seconds"),
        }
    }
    # over midnight events
    output = {
        "3.1": {
            "today": {
                "slots": [
                    {"start": 0, "end": 960, "type": "NotPlanned"},
                    {"start": 960, "end": 1200, "type": "Definite"},
                    {"start": 1200, "end": 1350, "type": "NotPlanned"},
                    {"start": 1350, "end": 1440, "type": "Definite"},
                ],
                "date": now.isoformat(timespec="seconds"),
                "status": "ScheduleApplies",
            },
            "tomorrow": {
                "slots": [
                    {"start": 0, "end": 270, "type": "Definite"},
                ],
                "date": (now + timedelta(days=1)).isoformat(timespec="seconds"),
                "status": "ScheduleApplies",
            },
            "updatedOn": now.isoformat(timespec="seconds"),
        }
    }
    # manual outage data
    minutes = 14 * 60 + 8
    output = {
        "3.1": {
            "today": {
                "slots": [
                    {"start": 0, "end": minutes, "type": "NotPlanned"},
                    {"start": minutes, "end": minutes + 1, "type": "Definite"},
                ],
                "date": now.isoformat(timespec="seconds"),
                "status": "ScheduleApplies",
            },
            "tomorrow": {
                "slots": [],
                "date": (now + timedelta(days=1)).isoformat(timespec="seconds"),
                "status": "WaitingForSchedule",
            },
            "updatedOn": now.isoformat(timespec="seconds"),
        }
    }
    return output  # noqa: RET504


class YasnoApi:
    """Class to interact with Yasno API."""

    _regions: list[YasnoRegion] | None = None

    def __init__(
        self,
        region_id: int | None = None,
        provider_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the Yasno API."""
        self.region_id: int | None = region_id
        self.provider_id: int | None = provider_id
        self.group: str | None = group
        self.planned_outage_data: dict | None = None

    async def _get_route_data(
        self,
        session: aiohttp.ClientSession,
        url: str,
        timeout_secs: int = 60,
    ) -> list[dict] | None:
        """Fetch data from the given URL."""
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
            ) as response:
                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError:
            LOGGER.exception("Error fetching data from %s", url)
            return None

    async def fetch_yasno_regions(self) -> None:
        """Fetch regions and providers data."""
        if YasnoApi._regions:
            return

        async with aiohttp.ClientSession() as session:
            result = await self._get_route_data(session, YASNO_REGIONS_ENDPOINT)

        if result:
            YasnoApi._regions = [YasnoRegion.from_dict(_) for _ in result]

        LOGGER.debug("Fetched yasno regions data: %s", YasnoApi._regions)

    async def fetch_planned_outage_data(self) -> None:
        """Fetch outage data for the configured region and provider."""
        if not self.region_id or not self.provider_id:
            LOGGER.error(
                "Region ID %s and Provider ID %s must be set before fetching outages",
                self.region_id,
                self.provider_id,
            )
            return

        url = YASNO_PLANNED_OUTAGES_ENDPOINT.format(
            region_id=self.region_id,
            dso_id=self.provider_id,
        )
        LOGGER.debug("Fetching Yasno planned outage data: %s", url)
        async with aiohttp.ClientSession() as session:
            self.planned_outage_data = await self._get_route_data(session, url)

        if DEBUG:
            self.planned_outage_data = _debug_data()

    @property
    def regions(self) -> list[YasnoRegion] | None:
        """Return the list of regions."""
        return YasnoApi._regions

    def get_region_by_id(self, region_id: int) -> YasnoRegion | None:
        """Get region data by name."""
        if not self.regions:
            LOGGER.debug(
                f"Yasno API get_region_by_id {region_id}"
                f" while regions are not yet fetched"
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
        for event in all_events:
            if event.all_day and event.start == at.date():
                return event
            if not event.all_day and event.start <= at < event.end:
                return event

        return None

    def get_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("Cannot get_events: no group_data yet")
            return []

        if DEBUG:
            LOGGER.debug(
                "get_events for %s from %s to %s:\n%s",
                self.group,
                start_date,
                end_date,
                group_data,
            )

        events = []
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

            day_dt = dt_utils.as_local(day_dt)

            status = day_data.get(BLOCK_KEY_STATUS)
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

        events.sort(
            key=lambda e: (
                datetime.combine(e.start, time.min)
                if isinstance(e.start, date)
                else e.start
            )
        )

        # Merge adjacent events of the same type
        events = _merge_adjacent_events(events)

        return [
            _
            for _ in events
            if _.all_day or not (_.end <= start_date or _.start >= end_date)
        ]

    def get_scheduled_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get scheduled events (includes WaitingForSchedule status)."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("Cannot get_scheduled_events: no group_data yet")
            return []

        if DEBUG:
            LOGGER.debug(
                "get_scheduled_events for %s from %s to %s:\n%s",
                self.group,
                start_date,
                end_date,
                group_data,
            )

        events = []
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

            day_dt = dt_utils.as_local(day_dt)

            # parse only STATUS_WAITING_FOR_SCHEDULE statuses
            status = day_data.get(BLOCK_KEY_STATUS)
            if status == YasnoPlannedOutageDayStatus.STATUS_WAITING_FOR_SCHEDULE.value:
                events.extend(_parse_day_schedule(day_data, day_dt))

        events.sort(
            key=lambda e: (
                datetime.combine(e.start, time.min)
                if isinstance(e.start, date)
                else e.start
            )
        )

        # Merge adjacent events of the same type
        events = _merge_adjacent_events(events)

        return [
            _
            for _ in events
            if _.all_day or not (_.end <= start_date or _.start >= end_date)
        ]

    async def fetch_data(self) -> None:
        """Fetch all required data."""
        await self.fetch_yasno_regions()
        await self.fetch_planned_outage_data()


async def _main() -> None:
    """Test the API functionality."""
    _api = YasnoApi()
    await _api.fetch_yasno_regions()
    _regions = _api.regions
    _api.region_id = _regions[0].id
    _api.provider_id = _regions[0].dsos[0].id
    await _api.fetch_planned_outage_data()
    _groups = _api.get_yasno_groups()
    _api.group = _groups[0]


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
