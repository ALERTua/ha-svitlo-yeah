"""Common tools for API clients."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_utils

from ..models import PlannedOutageEvent

LOGGER = logging.getLogger(__name__)


def parse_timestamp(timestamp_str: str) -> datetime.datetime | None:
    """
    Parse a timestamp string into a datetime object.

    Supports multiple formats:
    - Unix timestamp (integer/float): "1733520000"
    - ISO 8601 with timezone: "2025-12-07T11:10:49.815+02:00"
    - ISO 8601 UTC: "2025-12-07T11:10:49.815Z"
    - DD.MM.YYYY HH:MM (treated as UTC): "07.12.2025 00:01"
    - HH:MM DD.MM.YYYY (treated as UTC): "00:01 07.12.2025"

    Returns the parsed datetime in local timezone, or None if parsing fails.
    """
    if not timestamp_str:
        return None

    # Try parsing as Unix timestamp
    try:
        utc_dt = dt_utils.utc_from_timestamp(float(timestamp_str))
        return dt_utils.as_local(utc_dt)
    except (ValueError, TypeError, OverflowError):
        pass

    # Try parsing with Home Assistant's datetime parser (handles ISO 8601)
    try:
        dt = dt_utils.parse_datetime(timestamp_str)
        if dt:
            return dt_utils.as_local(dt)
    except (ValueError, TypeError):
        pass

    # Try parsing custom DD.MM.YYYY formats (treat as UTC)
    date_formats = [
        "%d.%m.%Y %H:%M",  # DD.MM.YYYY HH:MM
        "%H:%M %d.%m.%Y",  # HH:MM DD.MM.YYYY
    ]

    for fmt in date_formats:
        try:
            naive_dt = datetime.datetime.strptime(timestamp_str, fmt)  # noqa: DTZ007
            utc_dt = naive_dt.replace(tzinfo=datetime.UTC)
            return dt_utils.as_local(utc_dt)
        except (ValueError, TypeError):
            continue

    LOGGER.debug("Failed to parse timestamp: %s", timestamp_str)
    return None


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
            if current.end + datetime.timedelta(seconds=1) >= next_event.start:
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
