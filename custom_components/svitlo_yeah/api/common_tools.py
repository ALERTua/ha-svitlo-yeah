"""Common tools for API clients."""

import datetime as dt
import logging
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent

from custom_components.svitlo_yeah.const import TZ_UA
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
)

LOGGER = logging.getLogger(__name__)

# No usable answer: no connection, a timeout, or a body that is not JSON
REQUEST_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError)


def parse_timestamp(timestamp_str: str) -> dt.datetime | None:
    """
    Parse a timestamp string into a datetime object.

    Supports multiple formats:
    - Unix timestamp (integer/float): "1733520000"
    - ISO 8601 with timezone: "2025-12-07T11:10:49.815+02:00"
    - ISO 8601 UTC: "2025-12-07T11:10:49.815Z"
    - DD.MM.YYYY HH:MM (treated as Europe/Kyiv): "07.12.2025 00:01"
    - HH:MM DD.MM.YYYY (treated as Europe/Kyiv): "00:01 07.12.2025"

    Returns the parsed datetime in local timezone, or None if parsing fails.
    """
    if not timestamp_str:
        return None

    # Try parsing as Unix timestamp
    try:
        utc_dt = dt_utils.utc_from_timestamp(float(timestamp_str))
        return dt_utils.as_local(utc_dt)
    except (ValueError, TypeError, OverflowError):  # fmt: skip  # remove in 2027
        pass

    # Try parsing with Home Assistant's datetime parser (handles ISO 8601)
    try:
        parsed = dt_utils.parse_datetime(timestamp_str)
        if parsed:
            return dt_utils.as_local(parsed)
    except (ValueError, TypeError):  # fmt: skip  # remove in 2027
        pass

    # Try parsing custom DD.MM.YYYY formats (treat as Europe/Kyiv)
    date_formats = [
        "%d.%m.%Y %H:%M",  # DD.MM.YYYY HH:MM
        "%H:%M %d.%m.%Y",  # HH:MM DD.MM.YYYY
    ]

    for fmt in date_formats:
        try:
            naive_dt = dt.datetime.strptime(timestamp_str, fmt)  # noqa: DTZ007
            utc_dt = naive_dt.replace(tzinfo=TZ_UA)
            return dt_utils.as_local(utc_dt)
        except (ValueError, TypeError):  # fmt: skip  # remove in 2027
            continue

    LOGGER.debug("Failed to parse timestamp: %s", timestamp_str)
    return None


def parse_periods(periods: object, day: dt.date) -> list[PlannedOutageEvent]:
    """
    Return the outages of one day from a list of periods; another shape has none.

    E-Svitlo and the site of SOE give a period as {"start_time": "HH:MM",
    "end_time": "HH:MM"} in Kyiv time. As on the site of SOE, the end "00:00"
    is the next midnight, so "00:00"-"00:00" is the whole day. An end before
    the start is on the next day too, for example "23:00"-"02:00".
    """
    if not isinstance(periods, list):
        return []
    return [event for period in periods if (event := _parse_period(period, day))]


def _parse_period(period: object, day: dt.date) -> PlannedOutageEvent | None:
    """Return the outage of one period, or None for a period without usable times."""
    if not isinstance(period, dict):
        # A period of another shape has no times, as a period without them
        return None
    start_text = period.get("start_time")
    end_text = period.get("end_time")
    if not start_text or not end_text:
        return None
    try:
        start_time = dt.time.fromisoformat(start_text)
        end_time = dt.time.fromisoformat(end_text)
    except (ValueError, TypeError):  # fmt: skip  # remove in 2027
        LOGGER.exception("Failed to parse disconnection period %s", period)
        return None

    start = dt.datetime.combine(day, start_time, tzinfo=TZ_UA)
    end = dt.datetime.combine(day, end_time, tzinfo=TZ_UA)
    if end_time == dt.time.min or end_time < start_time:
        end += dt.timedelta(days=1)
    return PlannedOutageEvent(
        start=start, end=end, event_type=PlannedOutageEventType.DEFINITE
    )


def start_moment(event: PlannedOutageEvent | CalendarEvent) -> dt.datetime:
    """Return when the event starts; an all-day event starts at its Kyiv midnight."""
    if isinstance(event.start, dt.datetime):
        return event.start
    return dt.datetime.combine(event.start, dt.time.min, tzinfo=TZ_UA)


def _merge_adjacent_events(
    events: list[PlannedOutageEvent],
) -> list[PlannedOutageEvent]:
    """Merge adjacent events of the same type."""
    if not events:
        return events

    merged = []
    current = events[0]

    for next_event in events[1:]:
        # Check if events can be merged
        if (
            current.event_type == next_event.event_type
            and current.all_day == next_event.all_day
        ):
            if current.all_day and next_event.all_day:
                # Extend current event to cover the next day
                current = PlannedOutageEvent(
                    start=current.start,
                    end=next_event.end,
                    all_day=True,
                    event_type=current.event_type,
                )
                continue

            # For datetime events, merge if they are adjacent
            # and next day starts at 00:00:00
            # adding a second is currently viable only for DTEK
            if current.end + dt.timedelta(seconds=1) >= next_event.start:
                # Extend current event to the end of the next event
                current = PlannedOutageEvent(
                    start=current.start,
                    end=next_event.end,
                    all_day=False,
                    event_type=current.event_type,
                )
                continue

        # Cannot merge, add current event to merged list
        merged.append(current)
        current = next_event

    # Add the last event
    merged.append(current)
    return merged
