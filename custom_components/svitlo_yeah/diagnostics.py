"""Diagnostics of a Svitlo Yeah entry, for a bug report."""

import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_utils

from .const import CONF_ACCOUNT_ID, CONF_ADDRESS_STR

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.core import HomeAssistant

    from .coordinator.coordinator import SvitloYeahConfigEntry

# The E-Svitlo login, the personal account and its address identify a person
TO_REDACT = {"username", "password", CONF_ACCOUNT_ID, CONF_ADDRESS_STR}
LOOK_AHEAD = datetime.timedelta(hours=24)


def _iso(value: datetime.datetime | datetime.date | None) -> str | None:
    return value.isoformat() if value else None


def _event(event: CalendarEvent) -> dict[str, Any]:
    return {
        "summary": event.summary,
        "start": _iso(event.start),
        "end": _iso(event.end),
        "uid": event.uid,
    }


# noinspection PyUnusedLocal
async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001  # Home Assistant calls each platform with it
    entry: SvitloYeahConfigEntry,
) -> dict[str, Any]:
    """
    Return the entry settings without personal data, and what the coordinator knows.

    The name of an E-Svitlo provider is the address, so the provider name is not here.
    """
    coordinator = entry.runtime_data
    now = dt_utils.now()
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "group": coordinator.group,
            "group_listed": coordinator.group_listed,
            "current_state": coordinator.current_state,
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                repr(coordinator.last_exception) if coordinator.last_exception else None
            ),
            "last_fetch_failed": coordinator.last_fetch_failed,
            "login_rejected": coordinator.login_rejected,
            "schedule_updated_on": _iso(coordinator.schedule_updated_on),
            "outage_data_last_changed": _iso(coordinator.outage_data_last_changed),
        },
        "events": [
            _event(e) for e in coordinator.get_events_between(now, now + LOOK_AHEAD)
        ],
        "scheduled_events": [
            _event(e)
            for e in coordinator.get_scheduled_events_between(now, now + LOOK_AHEAD)
        ],
    }
