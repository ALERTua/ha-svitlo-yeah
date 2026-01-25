"""Base class for DTEK API implementations."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_utils

from ...const import DEBUG
from ...models import PlannedOutageEvent, PlannedOutageEventType
from ..common_tools import _merge_adjacent_events, parse_timestamp

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

    hours_range = range(24)
    get_key = lambda h: str(h + 1)  # noqa: E731
    if "0" in group_hours:  # 0-23 or 1-24 hour format
        get_key = str

    def safe_time(hour: int, minute: int = 0) -> datetime.time:
        """Create datetime.time handling hour 24 as midnight (0:00)."""
        if hour >= 24:  # noqa: PLR2004
            return datetime.time(0, minute)
        return datetime.time(hour, minute)

    for hour in hours_range:
        key = get_key(hour)
        status = group_hours.get(key, "yes")

        prev_key = get_key(hour - 1) if hour > 0 else None
        next_key = get_key(hour + 1) if hour < 23 else None  # noqa: PLR2004

        prev_status = group_hours.get(prev_key, "yes") if prev_key else "yes"
        next_status = group_hours.get(next_key, "yes") if next_key else "yes"

        if status == "yes":
            if outage_start is not None:
                ranges.append((outage_start, safe_time(hour)))
                outage_start = None
        elif status in ("second", "msecond"):
            if prev_status == "yes" or (
                prev_status in ("first", "mfirst") and outage_start is None
            ):
                # Start new outage at 30 minutes
                outage_start = safe_time(hour, 30)
            elif outage_start is None:
                # Continue from previous outage, start at beginning of hour
                outage_start = safe_time(hour)
        elif status in ("first", "mfirst"):
            if outage_start is None:
                outage_start = safe_time(hour)
            if next_status == "yes" or (next_status in ("second", "msecond")):
                # End outage at 30 minutes
                ranges.append((outage_start, safe_time(hour, 30)))
                outage_start = None
        elif status in ("no", "maybe") and outage_start is None:
            outage_start = safe_time(hour)

    # Close any remaining outage at end of day
    if outage_start is not None:
        ranges.append((outage_start, datetime.time(23, 59, 59)))

    return ranges


def _merge_ranges(
    ranges: list[tuple[datetime.time, datetime.time]],
) -> list[tuple[datetime.time, datetime.time]]:
    """
    Merge adjacent or overlapping time ranges.

    Args:
        ranges: List of time ranges to merge

    Returns:
        List of merged time ranges

    """
    if not ranges:
        return []

    # Sort ranges by start time
    sorted_ranges = sorted(ranges, key=lambda x: x[0])

    merged = []
    current_start, current_end = sorted_ranges[0]

    for start, end in sorted_ranges[1:]:
        # Check if ranges are adjacent or overlapping
        # For time ranges, we consider them adjacent if start <= current_end
        if start <= current_end:
            # Ranges overlap or are adjacent, merge them
            # If end is 59:59, use the next hour boundary
            if end.minute == 59 and end.second == 59:  # noqa: PLR2004
                if end.hour < 23:  # noqa: PLR2004
                    current_end = datetime.time(end.hour + 1)
                else:
                    current_end = datetime.time(23, 59, 59)
            else:
                current_end = max(current_end, end)
        else:
            # No overlap, add current range and start a new one
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    # Add the last range
    merged.append((current_start, current_end))

    return merged


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
                if (end_time.hour == 23 and end_time.minute == 59) or (  # noqa: PLR2004
                    end_time.hour == 0 and end_time.minute == 0
                ):
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

        update_str = self.data["update"]
        return parse_timestamp(update_str)

    def get_scheduled_events(
        self, start_date: datetime.datetime, end_date: datetime.datetime
    ) -> list[PlannedOutageEvent]:
        """Get scheduled events within the date range from preset data."""
        # Access preset_data from the API instance (stored in subclasses)
        preset_data = getattr(self, "preset_data", None)
        if not preset_data or "data" not in preset_data or not self.group:
            return []

        events = []
        group_key = f"GPV{self.group}"

        # Generate events for the current week - they will be made recurring with rrule
        weeks_to_generate = 1
        base_date = dt_utils.now().date()

        for week_offset in range(weeks_to_generate):
            for day_num in range(1, 8):  # Days 1-7 (Monday-Sunday)
                # Calculate the actual date for this day of the week
                days_ahead = (day_num - 1) - base_date.weekday() + (week_offset * 7)
                if days_ahead < 0:
                    days_ahead += 7  # Next occurrence of this weekday
                target_date = base_date + datetime.timedelta(days=days_ahead)

                # Check if this date is within our range
                day_start = dt_utils.as_local(
                    datetime.datetime.combine(target_date, datetime.time.min)
                )
                day_end = day_start + datetime.timedelta(days=1)

                if day_end <= start_date or day_start >= end_date:
                    continue

                # Get the preset data for this day
                day_data = preset_data["data"].get(group_key, {}).get(str(day_num), {})
                if not day_data:
                    continue

                time_ranges = _parse_group_hours(day_data)

                for start_time, end_time in time_ranges:
                    event_start = day_start.replace(
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=0,
                        microsecond=0,
                    )

                    if (end_time.hour == 23 and end_time.minute == 59) or (  # noqa: PLR2004
                        end_time.hour == 0 and end_time.minute == 0
                    ):
                        event_end = day_end
                    else:
                        event_end = day_start.replace(
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
            LOGGER.debug("%s: get_scheduled_events: %s", self, output)
        return output


def _debug_data() -> dict:
    now = dt_utils.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # till_midnight
    output = {
        "data": {
            midnight.timestamp(): {
                "GPV1.2": {
                    "1": "yes",
                    "2": "yes",
                    "3": "yes",
                    "4": "yes",
                    "5": "yes",
                    "6": "yes",
                    "7": "yes",
                    "8": "yes",
                    "9": "yes",
                    "10": "msecond",
                    "11": "no",
                    "12": "msecond",
                    "13": "yes",
                    "14": "yes",
                    "15": "yes",
                    "16": "yes",
                    "17": "yes",
                    "18": "yes",
                    "19": "yes",
                    "20": "mfirst",
                    "21": "no",
                    "22": "no",
                    "23": "no",
                    "24": "mfirst",
                },
            },
        },
        "update": midnight.strftime("%d.%m.%Y %H:%M"),
        "today": midnight.timestamp(),
    }
    return output  # noqa: RET504
