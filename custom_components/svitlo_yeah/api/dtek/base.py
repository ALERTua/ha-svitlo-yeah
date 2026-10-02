"""Base class for DTEK API implementations."""

import datetime
import logging
from enum import Enum

from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.common_tools import (
    _merge_adjacent_events,
    parse_timestamp,
)
from custom_components.svitlo_yeah.const import HOURS_IN_DAY, LAST_HOUR, LAST_MINUTE
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
)

LOGGER = logging.getLogger(__name__)


class FetchResult(Enum):
    """Outcome of a DTEK data fetch attempt."""

    FRESH = "fresh"  # a source returned data within the freshness window
    STALE = "stale"  # sources responded, but all data is older than allowed
    UNAVAILABLE = "unavailable"  # no source could be fetched/parsed at all


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

    hours_range = range(HOURS_IN_DAY)
    zero_based = "0" in group_hours  # 0-23 or 1-24 hour format

    def get_key(hour: int) -> str:
        """Return the key of the hour that starts at hour:00."""
        return str(hour if zero_based else hour + 1)

    def safe_time(hour: int, minute: int = 0) -> datetime.time:
        """Create datetime.time handling hour 24 as midnight (0:00)."""
        if hour >= HOURS_IN_DAY:
            return datetime.time(0, minute)
        return datetime.time(hour, minute)

    for hour in hours_range:
        key = get_key(hour)
        status = group_hours.get(key, "yes")

        prev_key = get_key(hour - 1) if hour > 0 else None
        next_key = get_key(hour + 1) if hour < LAST_HOUR else None

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


def _ranges_to_events(
    day: datetime.datetime,
    time_ranges: list[tuple[datetime.time, datetime.time]],
) -> list[PlannedOutageEvent]:
    """
    Turn the outage time ranges of one local day into events.

    ``day`` is any moment of that day. A range that ends at 23:59 or at 0:00
    ends at the midnight after the day.
    """
    next_midnight = (day + datetime.timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    events = []
    for start_time, end_time in time_ranges:
        event_start = day.replace(
            hour=start_time.hour,
            minute=start_time.minute,
            second=0,
            microsecond=0,
        )
        if (end_time.hour == LAST_HOUR and end_time.minute == LAST_MINUTE) or (
            end_time.hour == 0 and end_time.minute == 0
        ):
            event_end = next_midnight
        else:
            event_end = day.replace(
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
    return events


class DtekAPIBase:
    """Base class for DTEK API implementations."""

    def __init__(self, group: str | None = None) -> None:
        """Initialize the DTEK API base."""
        self.group = group
        self.data = None

    async def fetch_data(self, *, allow_stale_data: bool = False) -> FetchResult:
        """Fetch outage data. To be implemented by subclasses."""
        raise NotImplementedError

    def _preset_section(self, key: str) -> dict:
        """
        Get one section of the weekly preset schedule, for example ``data``.

        An empty dict stands for a missing preset schedule and for a section
        that is not a dict, such as ``"data": []``.
        """
        preset_data = getattr(self, "preset_data", None)
        section = preset_data.get(key) if isinstance(preset_data, dict) else None
        return section if isinstance(section, dict) else {}

    def get_dtek_region_groups(self) -> list[str]:
        """
        Get the list of available groups (with GPV prefix stripped).

        The groups come from the first day of the fact schedule:
        {
        'data': {
            '1761688800': {
                'GPV1.1': {

        When the fact schedule has no groups (e.g. ``"data": []`` while no
        outages are published), the groups come from the weekly preset schedule:
        {
        'data': {
            'GPV1.1': {
                '1': {
        """
        fact_days = (self.data or {}).get("data")
        if isinstance(fact_days, dict):
            first_timestamp = next(iter(fact_days.values()), {})
            if first_timestamp:
                return [key.replace("GPV", "") for key in first_timestamp]

        return [key.replace("GPV", "") for key in self._preset_section("data")]

    def get_dtek_region_group_labels(self) -> dict[str, str]:
        """
        Get labels for the groups whose name in the source does not show the group.

        The weekly preset schedule names each group in ``sch_names``, for example
        ``"GPV1001.1": "ЦЕК 1.1"``. Such a name gets a label with the group in
        parentheses: ``"ЦЕК 1.1 (1001.1)"``. A name that already shows the group,
        such as ``"Черга 1.1"``, gets no label.
        """
        labels = {}
        for key, name in self._preset_section("sch_names").items():
            group = key.replace("GPV", "")
            if isinstance(name, str) and group not in name.split():
                labels[group] = f"{name} ({group})"
        return labels

    def is_group_listed(self) -> bool | None:
        """
        Tell whether the source has a schedule for the configured group.

        True: the group is in a day of the fact schedule or in the preset
        schedule. False: the source lists other groups only.
        None: there is no data, no configured group, or no listed group at all,
        so the source says nothing about the group.
        """
        if not self.group:
            return None

        listed: set[str] = set()
        fact_days = (self.data or {}).get("data")
        if isinstance(fact_days, dict):
            for day in fact_days.values():
                if isinstance(day, dict):
                    listed.update(day)
        listed.update(self._preset_section("data"))

        if not listed:
            return None
        return f"GPV{self.group}" in listed

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
        if (
            not self.data
            or not isinstance(self.data.get("data"), dict)
            or not self.group
        ):
            return []

        events = []
        group_key = f"GPV{self.group}"
        for timestamp_str, day_data in self.data["data"].items():
            if group_key not in day_data:
                continue

            day_dt = dt_utils.utc_from_timestamp(int(timestamp_str))
            day_dt = dt_utils.as_local(day_dt)

            group_hours = day_data[group_key]
            events.extend(_ranges_to_events(day_dt, _parse_group_hours(group_hours)))

        events.sort(key=lambda e: e.start)
        events = _merge_adjacent_events(events)
        return [e for e in events if not (e.end <= start_date or e.start >= end_date)]

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
        preset_groups = self._preset_section("data")
        if not preset_groups or not self.group:
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
                day_data = preset_groups.get(group_key, {}).get(str(day_num), {})
                if not day_data:
                    continue

                events.extend(
                    _ranges_to_events(day_start, _parse_group_hours(day_data))
                )

        events.sort(key=lambda e: e.start)
        events = _merge_adjacent_events(events)
        return [e for e in events if not (e.end <= start_date or e.start >= end_date)]
