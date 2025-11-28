"""Base class for DTEK API implementations."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_utils

from ...const import DEBUG
from ...models import PlannedOutageEvent, PlannedOutageEventType
from ..common_tools import _merge_adjacent_events

LOGGER = logging.getLogger(__name__)


def _parse_group_hours(
    group_hours: dict[str, str],
) -> list[tuple[datetime.time, datetime.time]]:
    """
    Parse group hours data into a list of outage time ranges.

    'GPV1.1': {
    '1': 'yes',
    ...
    '12': 'yes',
    '13': 'second',
    '14': 'no',
    '15': 'no',
    '16': 'no',
    '17': 'first',
    '18': 'yes',
    ...
    '24': 'yes',
    },
    Supports two hour formats:
    - Hours starting from '1' (corresponding to 0:00) up to '24'
    - Hours starting from '0' (00:00) up to '23'
    """
    ranges = []
    outage_start = None

    # Check if '0' key is present to determine hour format
    # If '0' exists, hours are 0-23 (keys '0' to '23')
    # If no '0', hours are 1-24 (keys '1' to '24')
    if "0" in group_hours:
        # Parse 24-hour format starting from 0
        start_n, end_n = 0, 24
    else:
        # Parse 24-hour format starting from 1
        start_n, end_n = 1, 25

    for n in range(start_n, end_n):
        # Calculate actual hour (0-23) from n
        if "0" in group_hours:
            hour = n  # '0' key -> hour 0, '1' key -> hour 1, etc.
            key = str(n)
        else:
            hour = n - 1  # '1' key -> hour 0, '2' key -> hour 1, etc.
            key = str(n)

        # Get status for this hour slot
        status = group_hours.get(key, "yes")

        if status == "yes":
            # Power is on - close any open outage period
            if outage_start is not None:
                ranges.append((outage_start, datetime.time(hour, 0)))
                outage_start = None
        else:  # "first", "no", or "second" - all indicate outages
            # Power is out - start or continue outage period
            if outage_start is None:  # Start new outage at appropriate time
                outage_start = (
                    datetime.time(hour, 30)  # Start at half-hour if "second"
                    if status == "second"
                    else datetime.time(hour, 0)  # Otherwise start at top of hour
                )
            if (
                status == "first"
            ):  # If "first", close at hour:30 (next slot will be "yes")
                ranges.append((outage_start, datetime.time(hour, 30)))
                outage_start = None

    # Close any remaining open outage period at end of day
    if outage_start is not None:
        ranges.append((outage_start, datetime.time(23, 59, 59)))

    return ranges


class DtekAPIBase:
    """Base class for DTEK API implementations."""

    def __init__(self, group: str | None = None) -> None:
        """Initialize the DTEK API base."""
        self.group = group
        self.data = None

    async def fetch_data(self) -> None:
        """Fetch outage data. To be implemented by subclasses."""
        raise NotImplementedError

    def get_dtek_region_groups(self) -> list[str]:
        """
        Get the list of available groups (with GPV prefix stripped).

        {
        'data': {
            '1761688800': {
                'GPV1.1': {
        """
        if not self.data or "data" not in self.data:
            return []

        first_timestamp = next(iter(self.data["data"].values()), {})
        return [key.replace("GPV", "") for key in first_timestamp]

    def get_current_event(self, at: datetime.datetime) -> PlannedOutageEvent | None:
        """Get the current event at a specific time."""
        events = self.get_events(at, at + datetime.timedelta(days=1))
        for event in events:
            if event.start <= at < event.end:
                return event
        return None

    def get_events(
        self, start_date: datetime.datetime, end_date: datetime.datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        if not self.data or "data" not in self.data or not self.group:
            return []

        events = []
        group_key = f"GPV{self.group}"
        for timestamp_str, day_data in self.data["data"].items():
            if group_key not in day_data:
                continue

            day_dt = dt_utils.utc_from_timestamp(int(timestamp_str))
            day_dt = dt_utils.as_local(day_dt)

            group_hours = day_data[group_key]
            time_ranges = _parse_group_hours(group_hours)

            for start_time, end_time in time_ranges:
                event_start = day_dt.replace(
                    hour=start_time.hour,
                    minute=start_time.minute,
                    second=0,
                    microsecond=0,
                )
                if end_time.hour == 23 and end_time.minute == 59:  # noqa: PLR2004
                    event_end = (day_dt + datetime.timedelta(days=1)).replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                else:
                    event_end = day_dt.replace(
                        hour=end_time.hour,
                        minute=end_time.minute,
                        second=end_time.second,
                        microsecond=0,
                    )

                events.append(
                    PlannedOutageEvent(
                        start=event_start,
                        end=event_end,
                        event_type=PlannedOutageEventType.DEFINITE,
                    )
                )

        events.sort(key=lambda e: e.start)
        events = _merge_adjacent_events(events)
        output = [e for e in events if not (e.end <= start_date or e.start >= end_date)]
        if DEBUG:
            LOGGER.debug("%s: get_events: %s", self, output)
        return output

    def get_updated_on(self) -> datetime.datetime | None:
        """Get the updated on timestamp."""
        if not self.data or "update" not in self.data:
            return None

        try:
            update_str = self.data["update"]
            naive_dt = datetime.datetime.strptime(  # noqa: DTZ007
                update_str, "%d.%m.%Y %H:%M"
            )
            aware_dt = dt_utils.as_local(naive_dt)
        except (ValueError, TypeError):
            LOGGER.debug("Failed to parse update timestamp: %s", self.data["update"])
            return None

        return aware_dt


def _debug_data() -> dict:
    now = dt_utils.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # till_midnight
    output = {
        "data": {
            midnight.timestamp(): {
                "GPV1.1": {
                    "1": "yes",
                    "2": "yes",
                    "3": "yes",
                    "4": "yes",
                    "5": "yes",
                    "6": "yes",
                    "7": "yes",
                    "8": "yes",
                    "9": "yes",
                    "10": "yes",
                    "11": "yes",
                    "12": "yes",
                    "13": "second",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "first",
                    "18": "yes",
                    "19": "yes",
                    "20": "yes",
                    "21": "yes",
                    "22": "second",
                    "23": "no",
                    "24": "no",
                },
            },
        },
        "update": midnight.strftime("%d.%m.%Y %H:%M"),
        "today": midnight.timestamp(),
    }
    return output  # noqa: RET504
