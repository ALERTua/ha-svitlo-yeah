"""Tests for an SOE entry: its device, its states and its repair issue."""

from datetime import datetime

import pytest
from aiohttp import ClientError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import DOMAIN, SOE_SCHEDULE_URL, TZ_UA
from custom_components.svitlo_yeah.coordinator.coordinator import (
    STORE_VERSION,
    group_not_listed_issue_id,
    store_key,
)
from custom_components.svitlo_yeah.coordinator.soe import SoeCoordinator
from tests.helpers import SOE_SUMY_4_1, soe_group

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

UPDATE = "11.10.2026 18:48"
# 11:00 in Kyiv on 11 October 2026
MORNING = datetime(2026, 10, 11, 11, 0, tzinfo=TZ_UA)


def _answer(periods_of_4_1: list[tuple[str, str]] | None) -> dict:
    """Build an answer; None leaves sub-queue 4.1 out of it."""
    groups = [soe_group("4.2", [("12:00", "14:00")], UPDATE)]
    if periods_of_4_1 is not None:
        groups.insert(0, soe_group("4.1", periods_of_4_1, UPDATE))
    return {"data": groups}


async def _set_up(hass, aioclient_mock, answer: dict) -> MockConfigEntry:
    aioclient_mock.get(SOE_SCHEDULE_URL, json=answer)
    entry = MockConfigEntry(domain=DOMAIN, data=SOE_SUMY_4_1, entry_id="soe_entry")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _refresh(hass, aioclient_mock, entry, answer: dict) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(SOE_SCHEDULE_URL, json=answer)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _electricity(hass, entry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_electricity"
    )
    assert entity_id is not None
    return hass.states.get(entity_id).state


@pytest.fixture(autouse=True)
def _morning(freezer):
    freezer.move_to(MORNING)


async def test_entry_gets_the_soe_coordinator_and_device(hass, aioclient_mock):
    """The device is «Sumy SOE 4.1», and its entity ids carry this name."""
    entry = await _set_up(hass, aioclient_mock, _answer([("10:30", "12:00")]))

    assert isinstance(entry.runtime_data, SoeCoordinator)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [d.name for d in devices] == ["Sumy SOE 4.1"]
    entity_ids = [
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]
    assert "sensor.sumy_soe_4_1_electricity" in entity_ids


@pytest.mark.parametrize(
    ("periods", "state"),
    [
        ([("10:30", "12:00")], "planned_outage"),
        ([("12:00", "14:00")], "normal"),
        ([], "normal"),
    ],
    ids=["in_an_outage", "outage_later", "no_outages"],
)
async def test_electricity_follows_the_sub_queue(hass, aioclient_mock, periods, state):
    """An empty list of the sub-queue means no outages, so the power is on."""
    entry = await _set_up(hass, aioclient_mock, _answer(periods))

    assert _electricity(hass, entry) == state
    assert entry.runtime_data.group_listed is True


async def test_missing_sub_queue_gives_unknown_and_an_issue(hass, aioclient_mock):
    """The site lists other sub-queues only: the state is unknown, Repairs warns."""
    entry = await _set_up(hass, aioclient_mock, _answer(None))

    assert _electricity(hass, entry) == "unknown"
    issue_id = group_not_listed_issue_id(entry.entry_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["provider"] == "Sumy SOE"

    await _refresh(hass, aioclient_mock, entry, _answer([]))

    assert _electricity(hass, entry) == "normal"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_schedule_updated_on_comes_from_the_sub_queue(hass, aioclient_mock):
    """The update time is the one that the site gives for the sub-queue."""
    entry = await _set_up(hass, aioclient_mock, _answer([]))

    assert entry.runtime_data.schedule_updated_on == datetime(
        2026, 10, 11, 18, 48, tzinfo=TZ_UA
    )


async def test_calendar_event_names_the_sub_queue(hass, aioclient_mock):
    """The outage in the calendar is a planned outage of the sub-queue."""
    entry = await _set_up(hass, aioclient_mock, _answer([("10:30", "12:00")]))

    event = entry.runtime_data.get_current_event()

    assert event is not None
    assert event.summary == "Planned Outage 4.1"
    assert event.end == datetime(2026, 10, 11, 12, 0, tzinfo=TZ_UA)


async def test_answer_goes_into_the_store_with_its_day(
    hass, aioclient_mock, hass_storage
):
    """The store keeps the answer and the day in Kyiv that it gives."""
    answer = _answer([("10:30", "12:00")])
    entry = await _set_up(hass, aioclient_mock, answer)

    kept = hass_storage[store_key(entry.entry_id)]["data"]

    assert kept["source"] == {"answer": answer, "day": "2026-10-11"}
    assert (kept["group"], kept["group_listed"]) == ("4.1", True)


def _kept(answer: dict, day: str) -> dict:
    return {
        "version": STORE_VERSION,
        "minor_version": 1,
        "key": store_key("soe_entry"),
        "data": {
            "source": {"answer": answer, "day": day},
            "group": "4.1",
            "group_listed": True,
            "outage_data_last_changed": None,
        },
    }


@pytest.mark.parametrize(
    ("day", "state"),
    [("2026-10-11", "planned_outage"), ("2026-10-10", "normal")],
    ids=["kept_today", "kept_yesterday"],
)
async def test_restart_without_an_answer_shows_the_kept_schedule(
    hass, aioclient_mock, hass_storage, day, state
):
    """The kept outages stay on their own day, also after a restart."""
    hass_storage[store_key("soe_entry")] = _kept(_answer([("10:30", "12:00")]), day)
    aioclient_mock.get(SOE_SCHEDULE_URL, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=SOE_SUMY_4_1, entry_id="soe_entry")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.last_fetch_failed is True
    assert _electricity(hass, entry) == state


async def test_entry_without_a_group_does_not_load(hass, aioclient_mock):
    """The config flow always writes the group, so an entry without it is broken."""
    aioclient_mock.get(SOE_SCHEDULE_URL, json=_answer([]))
    data = {k: v for k, v in SOE_SUMY_4_1.items() if k != "group"}
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
