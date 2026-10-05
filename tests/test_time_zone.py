"""The days and hours of a source are in Kyiv, whatever the time zone of HA."""

from datetime import datetime, timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.svitlo_yeah.const import (
    DOMAIN,
    EVENT_DATA_CHANGED,
    TZ_UA,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    KYIV_REGION_URLS,
    YASNO_KYIV,
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

# New York is behind Kyiv, and Tokyo is ahead of it
TIME_ZONES = ["Europe/Kyiv", "UTC", "Europe/Berlin", "America/New_York", "Asia/Tokyo"]
MONDAY = datetime(2026, 10, 5, tzinfo=TZ_UA)
TUESDAY = MONDAY + timedelta(days=1)
# 01:30 in Kyiv is still Sunday in UTC and in New York
NIGHT = MONDAY + timedelta(hours=1, minutes=30)
# 06:00 in Kyiv is still Sunday in New York
NOW = MONDAY + timedelta(hours=6)
# 22:00 in Kyiv is already Tuesday in Tokyo
LATE = MONDAY + timedelta(hours=22)


def _in_kyiv(events) -> list[tuple[str, str]]:
    """Return the start and the end of each event, as the clock in Kyiv shows them."""
    return [
        (
            event.start.astimezone(TZ_UA).strftime("%d.%m %H:%M"),
            event.end.astimezone(TZ_UA).strftime("%d.%m %H:%M"),
        )
        for event in events
    ]


def _yasno_day(day: datetime, status: str) -> dict:
    """Build a Yasno answer for group 1.1 with one day without slots."""
    return {
        "1.1": {
            "today": {"slots": [], "date": day.isoformat(), "status": status},
            "updatedOn": day.isoformat(),
        }
    }


def _serve_yasno(aioclient_mock, answer: dict) -> None:
    """Serve the Yasno regions and this answer of the planned outages."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    aioclient_mock.get(YASNO_PLANNED_URL, json=answer)


async def _set_up(hass, data: dict) -> MockConfigEntry:
    """Set up an entry with this data."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that no timer of it outlives the test."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _events(hass, data: dict, now: datetime = NOW) -> tuple[list, list]:
    """Set up the entry, and return its planned and scheduled events of three days."""
    entry = await _set_up(hass, data)
    coordinator = entry.runtime_data
    start, end = now - timedelta(days=1), now + timedelta(days=2)
    planned = coordinator.get_events_between(start, end)
    scheduled = coordinator.get_scheduled_events_between(start, end)
    await _unload(hass, entry)
    return planned, scheduled


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_dtek_hours_are_hours_in_kyiv(hass, aioclient_mock, freezer, time_zone):
    """Hour 11 of the fact is 10:00-11:00 in Kyiv; hour 15 of Monday is 14:00-15:00."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(NOW)
    fact = {
        "data": {str(int(MONDAY.timestamp())): {"GPV1.1": {"11": "no"}}},
        "update": "05.10.2026 05:00",
        "today": int(MONDAY.timestamp()),
    }
    preset = {"data": {"GPV1.1": {"1": {"15": "no"}}}}
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": preset})

    planned, scheduled = await _events(hass, DTEK_KYIV_REGION_1_1)

    assert _in_kyiv(planned) == [("05.10 10:00", "05.10 11:00")]
    assert _in_kyiv(scheduled) == [("05.10 14:00", "05.10 15:00")]


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_dtek_preset_weekday_is_the_day_in_kyiv(
    hass, aioclient_mock, freezer, time_zone
):
    """At 22:00 on Monday in Kyiv, hour 24 of the Monday preset is still ahead."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(LATE)
    fact = {
        "data": {str(int(MONDAY.timestamp())): {"GPV1.1": {"1": "yes"}}},
        "update": "05.10.2026 21:00",
        "today": int(MONDAY.timestamp()),
    }
    preset = {"data": {"GPV1.1": {"1": {"24": "no"}}}}
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": preset})

    _, scheduled = await _events(hass, DTEK_KYIV_REGION_1_1, now=LATE)

    assert _in_kyiv(scheduled) == [("05.10 23:00", "06.10 00:00")]


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_yasno_minutes_are_minutes_in_kyiv(
    hass, aioclient_mock, freezer, time_zone
):
    """Minute 600 of today is 10:00 in Kyiv, and minute 900 of tomorrow is 15:00."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(NOW)
    answer = {
        "1.1": {
            "today": {
                "slots": [{"start": 600, "end": 660, "type": "Definite"}],
                "date": MONDAY.isoformat(),
                "status": "ScheduleApplies",
            },
            "tomorrow": {
                "slots": [{"start": 900, "end": 960, "type": "Definite"}],
                "date": TUESDAY.isoformat(),
                "status": "WaitingForSchedule",
            },
            "updatedOn": NOW.isoformat(),
        }
    }
    _serve_yasno(aioclient_mock, answer)

    planned, scheduled = await _events(hass, YASNO_KYIV_1_1)

    assert _in_kyiv(planned) == [("05.10 10:00", "05.10 11:00")]
    assert _in_kyiv(scheduled) == [("06.10 15:00", "06.10 16:00")]


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_yasno_emergency_day_is_the_day_in_kyiv(
    hass, aioclient_mock, freezer, time_zone
):
    """An emergency day of Yasno is an all-day event of that date in Kyiv."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(NOW)
    _serve_yasno(aioclient_mock, _yasno_day(MONDAY, "EmergencyShutdowns"))

    planned, _ = await _events(hass, YASNO_KYIV_1_1)

    assert [(e.start, e.end) for e in planned] == [(MONDAY.date(), TUESDAY.date())]


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_yasno_emergency_day_starts_at_the_kyiv_midnight(
    hass, aioclient_mock, freezer, time_zone
):
    """At 01:30 and 06:00 in Kyiv, the emergency of Monday is the current event."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(NIGHT)
    _serve_yasno(aioclient_mock, _yasno_day(MONDAY, "EmergencyShutdowns"))

    entry = await _set_up(hass, YASNO_KYIV_1_1)

    assert entry.runtime_data.current_state == ConnectivityState.STATE_EMERGENCY
    assert entry.runtime_data.next_event is None
    freezer.move_to(NOW)
    assert entry.runtime_data.current_state == ConnectivityState.STATE_EMERGENCY
    await _unload(hass, entry)


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_yasno_emergency_today_and_an_outage_tomorrow(
    hass, aioclient_mock, freezer, time_zone
):
    """An all-day emergency next to a timed outage adds each entity of the entry."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(LATE)
    answer = _yasno_day(MONDAY, "EmergencyShutdowns")
    answer["1.1"]["tomorrow"] = {
        "slots": [{"start": 60, "end": 180, "type": "Definite"}],
        "date": TUESDAY.isoformat(),
        "status": "ScheduleApplies",
    }
    _serve_yasno(aioclient_mock, answer)

    entry = await _set_up(hass, YASNO_KYIV_1_1)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 9
    assert [e.entity_id for e in entities if hass.states.get(e.entity_id) is None] == []
    assert entry.runtime_data.current_state == ConnectivityState.STATE_EMERGENCY
    assert entry.runtime_data.next_event.start == TUESDAY + timedelta(hours=1)
    await _unload(hass, entry)


@pytest.mark.parametrize("time_zone", TIME_ZONES)
async def test_yasno_emergency_day_that_ended_is_no_change(
    hass, aioclient_mock, freezer, time_zone
):
    """At 01:30 on Tuesday in Kyiv, a Monday without the emergency is no change."""
    await hass.config.async_set_time_zone(time_zone)
    freezer.move_to(NOW)
    _serve_yasno(aioclient_mock, _yasno_day(MONDAY, "EmergencyShutdowns"))
    entry = await _set_up(hass, YASNO_KYIV_1_1)
    changes = async_capture_events(hass, EVENT_DATA_CHANGED)

    freezer.move_to(NIGHT + timedelta(days=1))
    _serve_yasno(aioclient_mock, _yasno_day(TUESDAY, "ScheduleApplies"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert changes == []
    assert entry.runtime_data.current_state == ConnectivityState.STATE_NORMAL
    await _unload(hass, entry)
