"""Common tools for API clients."""

from __future__ import annotations

import datetime

from ..models import PlannedOutageEvent


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
