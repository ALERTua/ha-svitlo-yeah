"""
The weekly check of the group of the address of a Yasno entry.

The entries have the address in their data, as the config flow writes it. The
address requests of Yasno answer with the measured chain of Київ: the street
«вул. Сверстюка Євгена» (id 1647), the house 6 with its Cyrillic letter (id 41362),
the group 53.1.
"""

import asyncio
import json
import logging
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from aiohttp import ClientError
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_get_persistent_notifications,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.svitlo_yeah.api.yasno import AddressResult, YasnoApi
from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_PROVIDER,
    CONF_REGION,
    CONF_STREET,
    DOMAIN,
    EVENT_GROUP_CHANGED,
    TRANSLATION_KEY_GROUP_CHANGED_MESSAGE,
    TRANSLATION_KEY_GROUP_CHANGED_TITLE,
    TZ_UA,
    YASNO_ADDRESSES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.coordinator.coordinator import (
    STORE_VERSION,
    store_key,
)
from custom_components.svitlo_yeah.coordinator.yasno import (
    GROUP_CHANGED_MESSAGE,
    GROUP_CHANGED_TITLE,
    AddressCheck,
    YasnoCoordinator,
    address_not_found_issue_id,
    group_changed_notification_id,
)
from custom_components.svitlo_yeah.models import YasnoAddress
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    YASNO_KYIV,
    YASNO_KYIV_1_1,
    YASNO_KYIV_ADDRESS_1_1,
    YASNO_KYIV_HOUSE,
    YASNO_KYIV_STREET,
    YASNO_PLANNED_URL,
    dtek_answers,
    fact_with_an_outage_today,
    kyiv_midnight,
    yasno_outage_all_day_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

LOGGER_NAME = "custom_components.svitlo_yeah"
YASNO_LOGGER = "custom_components.svitlo_yeah.coordinator.yasno"
TRANSLATIONS = Path(__file__).parent.parent / (
    "custom_components/svitlo_yeah/translations"
)
# The title of an address entry is its address
ADDRESS_TEXT = f"{YASNO_KYIV_STREET}, {YASNO_KYIV_HOUSE}"
ADDRESS = YasnoAddress(street=YASNO_KYIV_STREET, house=YASNO_KYIV_HOUSE)
KYIV_PAGE = "https://static.yasno.ua/kyiv/outages"
# The name of the integration in the list of integrations, as the group_not_listed
# issue names it (its tests expect the same text)
INTEGRATION = "Svitlo Yeah!"
WEEK = timedelta(days=7)
HOUR = timedelta(hours=1)

# The measured chain of the address of the entry, and the group answers of Yasno
STREETS = {"json": [{"id": 1647, "value": YASNO_KYIV_STREET}]}
HOUSES = {"json": [{"id": 41362, "value": YASNO_KYIV_HOUSE}]}
GROUP_53_1 = {"json": {"group": 53, "subgroup": 1}}
GROUP_2_1 = {"json": {"group": 2, "subgroup": 1}}
GROUP_1_1 = {"json": {"group": 1, "subgroup": 1}}
# A group that the planned outages of the tests do not list
GROUP_60_1 = {"json": {"group": 60, "subgroup": 1}}
# Yasno finds no such street: a list without the name, shorter than the cap
NO_STREET = {"json": []}
SERVER_ERROR = {"status": 500}


@pytest.fixture(autouse=True, name="nine_o_clock")
def _nine_o_clock(freezer):
    """Start each test at 09:00 in Kyiv, so that a step of one hour stays in the day."""
    freezer.move_to(kyiv_midnight() + timedelta(hours=9))
    return freezer


def _planned() -> dict:
    """Build planned outages that list the groups 1.1, 2.1 and 53.1."""
    day = yasno_outage_all_day_today()["1.1"]
    return dict.fromkeys(("1.1", "2.1", "53.1"), day)


def _serve(
    mock,
    *,
    group: dict = GROUP_53_1,
    streets: dict = STREETS,
    schedule: bool = True,
) -> None:
    """Serve the schedule and the address requests, after the earlier replies."""
    mock.clear_requests()
    mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    if schedule:
        mock.get(YASNO_PLANNED_URL, json=_planned())
    else:
        mock.get(YASNO_PLANNED_URL, exc=ClientError())
    mock.get(YASNO_ADDRESSES_ENDPOINT + "streets", **streets)
    mock.get(YASNO_ADDRESSES_ENDPOINT + "houses", **HOUSES)
    mock.get(YASNO_ADDRESSES_ENDPOINT + "group", **group)


def _address_requests(mock) -> list[str]:
    """Return the address endpoint of each request that went out, in order."""
    paths = [
        url.path.rsplit("/", 1)[-1]
        for _, url, _, _ in mock.mock_calls
        if str(url).startswith(YASNO_ADDRESSES_ENDPOINT)
    ]
    return [_ for _ in paths if _ != "regions"]


def _check(
    next_check: datetime,
    *,
    pending: str | None = None,
    count: int = 0,
    house: str = YASNO_KYIV_HOUSE,
) -> dict:
    """Build the kept state of the check of the address of the entry."""
    return {
        "address": {CONF_STREET: YASNO_KYIV_STREET, CONF_HOUSE: house},
        "next_check": next_check.isoformat(),
        "pending_group": pending,
        "not_found_count": count,
    }


def _kept(check: dict | None, group: str = "1.1") -> dict:
    """Wrap the kept data of a Yasno entry in the envelope of the store."""
    source: dict = {"planned_outage_data": _planned(), "region": YASNO_KYIV}
    if check is not None:
        source["address_check"] = check
    return {
        "version": STORE_VERSION,
        "minor_version": 1,
        "key": "",
        "data": {
            "source": source,
            "group": group,
            "group_listed": True,
            "outage_data_last_changed": None,
        },
    }


def _kept_check(hass_storage, entry: MockConfigEntry) -> dict | None:
    """Return the state of the check that the store of the entry keeps."""
    return hass_storage[store_key(entry.entry_id)]["data"]["source"].get(
        "address_check"
    )


async def _start(
    hass,
    hass_storage,
    *,
    check: dict | None = None,
    data: dict = YASNO_KYIV_ADDRESS_1_1,
) -> tuple[MockConfigEntry, YasnoCoordinator]:
    """Add an address entry, with a kept state of its check or not, and set it up."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=ADDRESS_TEXT)
    entry.add_to_hass(hass)
    if check is not None:
        hass_storage[store_key(entry.entry_id)] = _kept(check, data[CONF_GROUP])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry, entry.runtime_data


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that no timer of it outlives the test."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _issue(hass, entry: MockConfigEntry) -> ir.IssueEntry | None:
    """Return the repair issue about the address of the entry, if it exists."""
    issue_id = address_not_found_issue_id(entry.entry_id)
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def _counting(hass, entry: MockConfigEntry, count: int | None) -> YasnoCoordinator:
    """Build a coordinator whose state counts Not found results, or has no state."""
    coordinator = YasnoCoordinator(hass, entry)
    if count is not None:
        coordinator._address_check = AddressCheck(
            ADDRESS, dt_utils.utcnow(), not_found_count=count
        )
    return coordinator


def _records(caplog, level: int) -> list[str]:
    """Return the messages of the integration at this level."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith(LOGGER_NAME) and r.levelno == level
    ]


class TestTheClock:
    """When a check is due."""

    async def test_first_refresh_and_first_poll_ask_no_address(
        self, hass, aioclient_mock, hass_storage
    ):
        """The first refresh does not check; the first poll only starts the clock."""
        _serve(aioclient_mock)

        entry, coordinator = await _start(hass, hass_storage)

        assert _address_requests(aioclient_mock) == []
        assert coordinator._address_check is None
        assert (
            "address_check"
            not in hass_storage[store_key(entry.entry_id)]["data"]["source"]
        )

        await coordinator.async_refresh()

        assert _address_requests(aioclient_mock) == []
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        assert coordinator.address_check_result is None
        await _unload(hass, entry)

    async def test_check_comes_after_a_week(
        self, hass, aioclient_mock, hass_storage, nine_o_clock
    ):
        """The clock that the first poll starts makes the check due after a week."""
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(hass, hass_storage)
        await coordinator.async_refresh()

        nine_o_clock.tick(WEEK - timedelta(minutes=1))
        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == []

        nine_o_clock.tick(timedelta(minutes=1))
        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        await _unload(hass, entry)

    @pytest.mark.parametrize(
        "start",
        [
            # The DST ends on 2026-11-01 in the US and on 2026-10-25 in Europe
            datetime(2026, 10, 28, 9, tzinfo=ZoneInfo("US/Pacific")),
            datetime(2026, 10, 21, 9, tzinfo=TZ_UA),
            # The DST starts on 2027-03-28 in Europe
            datetime(2027, 3, 25, 9, tzinfo=TZ_UA),
        ],
        ids=["us_autumn", "kyiv_autumn", "kyiv_spring"],
    )
    async def test_week_is_seven_times_24_hours_across_a_dst_change(
        self, hass, aioclient_mock, hass_storage, nine_o_clock, start
    ):
        """
        A DST change of the time zone of Home Assistant does not move the check.

        A local time plus seven days keeps the local hour, and the check then
        comes one hour early or late.
        """
        await hass.config.async_set_time_zone(str(start.tzinfo))
        nine_o_clock.move_to(start)
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(hass, hass_storage)
        await coordinator.async_refresh()

        check = coordinator._address_check
        assert check is not None
        assert check.next_check - dt_utils.utcnow() == timedelta(hours=7 * 24)

        nine_o_clock.tick(WEEK - timedelta(minutes=1))
        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == []

        nine_o_clock.tick(timedelta(minutes=1))
        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        await _unload(hass, entry)

    async def test_restart_does_not_check_before_the_time(
        self, hass, aioclient_mock, hass_storage
    ):
        """After a restart, the kept time of the next check stays."""
        _serve(aioclient_mock)
        next_check = dt_utils.utcnow() + timedelta(days=3)

        entry, coordinator = await _start(
            hass, hass_storage, check=_check(next_check, count=1)
        )
        await coordinator.async_refresh()

        assert _address_requests(aioclient_mock) == []
        assert _kept_check(hass_storage, entry) == _check(next_check, count=1)
        await _unload(hass, entry)

    async def test_due_check_waits_for_the_first_poll(
        self, hass, aioclient_mock, hass_storage
    ):
        """A check that came due while Home Assistant was off runs in the first poll."""
        _serve(aioclient_mock, group=GROUP_1_1)

        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() - timedelta(days=2))
        )
        assert _address_requests(aioclient_mock) == []

        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        await _unload(hass, entry)

    async def test_due_check_waits_while_the_schedule_fails(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        A poll whose schedule request fails runs no due check: Yasno is down.

        The check stays due, and the next poll with an answer runs it.
        """
        _serve(aioclient_mock, group=GROUP_1_1, schedule=False)
        due = dt_utils.utcnow() - timedelta(minutes=1)
        entry, coordinator = await _start(hass, hass_storage, check=_check(due))

        await coordinator.async_refresh()

        assert coordinator.last_fetch_failed is True
        assert _address_requests(aioclient_mock) == []
        assert _kept_check(hass_storage, entry) == _check(due)

        _serve(aioclient_mock, group=GROUP_1_1)
        await coordinator.async_refresh()

        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        await _unload(hass, entry)

    async def test_forced_check_runs_while_the_schedule_fails(
        self, hass, aioclient_mock, hass_storage
    ):
        """The button checks the address also when Yasno does not give the schedule."""
        _serve(aioclient_mock, group=GROUP_1_1, schedule=False)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        await coordinator.async_check_address_now()

        assert coordinator.last_fetch_failed is True
        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        assert coordinator.address_check_result is AddressResult.FOUND
        await _unload(hass, entry)

    async def test_kept_state_of_another_address_counts_as_no_state(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        After a Reconfigure of the address, the kept state starts the clock again.

        Its Not found results, and its repair issue, are about the old address.
        """
        _serve(aioclient_mock)
        past = dt_utils.utcnow() - timedelta(days=2)

        entry, coordinator = await _start(
            hass, hass_storage, check=_check(past, count=2, house="2")
        )
        assert _issue(hass, entry) is None
        await coordinator.async_refresh()

        assert _address_requests(aioclient_mock) == []
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        await _unload(hass, entry)


class TestFound:
    """A check that finds the group of the address."""

    async def test_same_group_waits_a_week(self, hass, aioclient_mock, hass_storage):
        """The group of the entry: the next check in a week, no pending group."""
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(
            hass,
            hass_storage,
            check=_check(dt_utils.utcnow(), pending="53.1", count=1),
        )

        await coordinator.async_refresh()

        assert coordinator.address_check_result is AddressResult.FOUND
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        assert entry.data[CONF_GROUP] == "1.1"
        await _unload(hass, entry)

    async def test_new_group_needs_a_second_check_an_hour_later(
        self, hass, aioclient_mock, hass_storage, nine_o_clock, caplog
    ):
        """
        The first check keeps the new group pending, and the second one switches.

        The entry gets the new group, and the update listener reloads it.
        """
        caplog.set_level(logging.INFO, logger=LOGGER_NAME)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow())
        )

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "1.1"
        assert entry.runtime_data is coordinator
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="53.1"
        )

        nine_o_clock.tick(HOUR)
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data == {**YASNO_KYIV_ADDRESS_1_1, CONF_GROUP: "53.1"}
        assert entry.title == ADDRESS_TEXT
        assert entry.state is ConfigEntryState.LOADED
        reloaded = entry.runtime_data
        assert reloaded is not coordinator
        assert (reloaded.group, reloaded.api.group) == ("53.1", "53.1")
        assert reloaded.group_listed is True
        kept = hass_storage[store_key(entry.entry_id)]["data"]
        assert (kept["group"], kept["group_listed"]) == ("53.1", True)
        assert kept["source"]["address_check"] == _check(dt_utils.utcnow() + WEEK)
        assert _records(caplog, logging.INFO) == [
            f"The Yasno group of entry {entry.entry_id} changed from 1.1 to 53.1"
        ]
        await _unload(hass, entry)

    async def test_third_group_replaces_the_pending_group(
        self, hass, aioclient_mock, hass_storage
    ):
        """A check that finds another new group keeps it pending instead."""
        _serve(aioclient_mock, group=GROUP_2_1)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "1.1"
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="2.1"
        )
        await _unload(hass, entry)

    @pytest.mark.parametrize("force", [False, True], ids=["poll", "force"])
    async def test_group_without_a_schedule_is_not_taken(
        self, hass, aioclient_mock, hass_storage, force
    ):
        """A group that the planned outages lack is no answer: retry in an hour."""
        _serve(aioclient_mock, group=GROUP_60_1)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="60.1")
        )

        if force:
            await coordinator.async_check_address_now()
        else:
            await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "1.1"
        assert entry.runtime_data is coordinator
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="60.1"
        )
        await _unload(hass, entry)

    @pytest.mark.parametrize("kept", [True, False], ids=["kept_state", "new_entry"])
    async def test_force_switches_at_once(
        self, hass, aioclient_mock, hass_storage, kept
    ):
        """The force skips the wait for the time and for the second check."""
        _serve(aioclient_mock)
        check = _check(dt_utils.utcnow() + timedelta(days=5)) if kept else None
        entry, coordinator = await _start(hass, hass_storage, check=check)

        await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        assert coordinator._force_address_check is False
        assert entry.data[CONF_GROUP] == "53.1"
        assert entry.runtime_data is not coordinator
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        await _unload(hass, entry)

    async def test_force_goes_back_after_a_check_without_a_switch(
        self, hass, aioclient_mock, hass_storage
    ):
        """After a forced check, the next poll waits for the time again."""
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        await coordinator.async_check_address_now()
        assert coordinator._force_address_check is False
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)

        aioclient_mock.mock_calls.clear()
        await coordinator.async_refresh()
        assert _address_requests(aioclient_mock) == []
        await _unload(hass, entry)

    async def test_force_does_not_outlive_a_poll_that_stops_before_the_check(
        self, hass, aioclient_mock, hass_storage
    ):
        """A poll that fails before the check leaves no force for the next poll."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        with patch.object(
            coordinator, "_async_use_answer", side_effect=RuntimeError("broken")
        ):
            await coordinator.async_check_address_now()
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert _address_requests(aioclient_mock) == []
        assert coordinator._force_address_check is False
        assert entry.data[CONF_GROUP] == "1.1"
        await _unload(hass, entry)

    async def test_press_during_a_running_poll_gives_one_check(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        A press while a poll waits for the schedule: that poll runs the check.

        The check takes the force, so the poll of the press runs no second check.
        The press still gets the result of the check of the running poll.
        """
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        asked, release = asyncio.Event(), asyncio.Event()

        async def wait_and_answer(method, url, _data):
            asked.set()
            await release.wait()
            return AiohttpClientMockResponse(method, url, json=_planned())

        # The first registered reply that matches answers, so this one goes first
        aioclient_mock._mocks.insert(
            0,
            AiohttpClientMockResponse(
                "get", URL(YASNO_PLANNED_URL), side_effect=wait_and_answer
            ),
        )

        poll = hass.async_create_task(coordinator.async_refresh())
        await _until_asked(asked, release)
        press = hass.async_create_task(coordinator.async_check_address_now())
        # The press sets the force, and then it waits for the lock of the poll
        await asyncio.sleep(0)
        release.set()
        await poll
        await press

        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        assert coordinator.address_check_result is AddressResult.FOUND
        assert coordinator._force_address_check is False
        await _unload(hass, entry)


def _wait_for(mock, path: str, reply: dict):
    """Make the request of the path wait; return the events of the ask and answer."""
    asked, release = asyncio.Event(), asyncio.Event()

    async def wait_and_answer(method, url, _data):
        asked.set()
        await release.wait()
        return AiohttpClientMockResponse(method, url, **reply)

    # The first registered reply that matches answers, so this one goes first
    mock._mocks.insert(
        0,
        AiohttpClientMockResponse(
            "get", URL(YASNO_ADDRESSES_ENDPOINT + path), side_effect=wait_and_answer
        ),
    )
    return asked, release


async def _until_asked(asked: asyncio.Event, release: asyncio.Event) -> None:
    """
    Let the poll run until it asks, or fail the test.

    The frozen clock stops each timeout of asyncio, so the wait counts the turns
    of the loop instead. A test that fails lets the poll go, so that it ends.
    """
    for _ in range(1000):
        if asked.is_set():
            return
        await asyncio.sleep(0)
    release.set()
    pytest.fail("The check did not ask Yasno")


class TestRaceGuard:
    """A check that ends after the entry changed writes no group."""

    async def test_another_address_while_yasno_answers(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        The entry gets another address while the check waits: nothing is written.

        The update listener is away, so that no reload stops the coordinator, and
        only the check of the address stops the write.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )
        kept = hass_storage[store_key(entry.entry_id)]["data"]
        asked, release = _wait_for(aioclient_mock, "group", GROUP_53_1)
        listeners = entry.update_listeners.copy()
        entry.update_listeners.clear()

        poll = hass.async_create_task(coordinator.async_refresh())
        await _until_asked(asked, release)
        other = {**YASNO_KYIV_ADDRESS_1_1, CONF_HOUSE: "2"}
        hass.config_entries.async_update_entry(entry, data=other)
        release.set()
        await poll
        await hass.async_block_till_done()

        assert coordinator.address_check_result is AddressResult.FOUND
        assert entry.data == other
        assert hass_storage[store_key(entry.entry_id)]["data"] == kept
        entry.update_listeners.extend(listeners)
        await _unload(hass, entry)

    async def test_another_address_while_the_store_saves(
        self, hass, aioclient_mock, hass_storage
    ):
        """The entry gets another address while the switch saves: no group goes in."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )
        listeners = entry.update_listeners.copy()
        entry.update_listeners.clear()
        other = {**YASNO_KYIV_ADDRESS_1_1, CONF_HOUSE: "2"}
        save = coordinator._store.async_save

        async def save_while_the_address_changes(data):
            hass.config_entries.async_update_entry(entry, data=other)
            await save(data)

        with patch.object(
            coordinator._store,
            "async_save",
            side_effect=save_while_the_address_changes,
        ):
            await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data == other
        entry.update_listeners.extend(listeners)
        await _unload(hass, entry)

    async def test_unload_while_the_switch_saves(
        self, hass, aioclient_mock, hass_storage
    ):
        """The entry unloads while the switch saves: no group goes in, and no notice."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )
        save = coordinator._store.async_save

        async def save_and_unload(data):
            await save(data)
            # Only the save of the switch keeps the new group
            if data.get("group") == "53.1":
                await hass.config_entries.async_unload(entry.entry_id)

        with patch.object(
            coordinator._store, "async_save", side_effect=save_and_unload
        ):
            await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.NOT_LOADED
        assert entry.data[CONF_GROUP] == "1.1"
        notifications = async_get_persistent_notifications(hass)
        assert group_changed_notification_id(entry.entry_id) not in notifications

    @pytest.mark.parametrize("action", ["unload", "remove"])
    async def test_entry_gone_while_yasno_answers(
        self, hass, aioclient_mock, hass_storage, caplog, action
    ):
        """A check that ends after an unload or a removal writes and keeps nothing."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )
        kept = hass_storage[store_key(entry.entry_id)]["data"]
        asked, release = _wait_for(aioclient_mock, "group", GROUP_53_1)

        poll = hass.async_create_task(coordinator.async_refresh())
        await _until_asked(asked, release)
        if action == "remove":
            assert await hass.config_entries.async_remove(entry.entry_id)
        else:
            assert await hass.config_entries.async_unload(entry.entry_id)
        release.set()
        await poll
        await hass.async_block_till_done()

        assert entry.data == YASNO_KYIV_ADDRESS_1_1
        if action == "remove":
            assert store_key(entry.entry_id) not in hass_storage
        else:
            assert hass_storage[store_key(entry.entry_id)]["data"] == kept
        assert [
            r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
        ] == []

    async def test_removal_while_the_poll_saves_leaves_no_store(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        The user removes the entry while the poll saves its data: no store stays.

        The entry has no state of the check yet, so the end of the poll would
        start the clock and save the store of the removed entry again.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(hass, hass_storage)
        save = coordinator._store.async_save
        saves = []

        async def save_and_remove(data):
            saves.append(data)
            await save(data)
            if len(saves) == 1:
                await hass.config_entries.async_remove(entry.entry_id)

        # A new time of the last change makes the poll save its data
        coordinator.outage_data_last_changed = dt_utils.utcnow()
        with patch.object(
            coordinator._store, "async_save", side_effect=save_and_remove
        ):
            await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert hass.config_entries.async_entries(DOMAIN) == []
        assert store_key(entry.entry_id) not in hass_storage
        assert len(saves) == 1


class TestNotFound:
    """A check that does not find the address."""

    async def test_twice_in_a_row_creates_the_issue(
        self, hass, aioclient_mock, hass_storage, nine_o_clock, caplog
    ):
        """
        Once: another try in an hour. Twice: a warning and the issue, for a week.

        The group of the entry stays, the pending group goes, and a third result
        warns no more.
        """
        caplog.set_level(logging.INFO, logger=LOGGER_NAME)
        _serve(aioclient_mock, streets=NO_STREET)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1")
        )

        await coordinator.async_refresh()

        assert coordinator.address_check_result is AddressResult.NOT_FOUND
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, count=1
        )
        assert _issue(hass, entry) is None
        assert _records(caplog, logging.WARNING) == []

        nine_o_clock.tick(HOUR)
        await coordinator.async_refresh()

        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + WEEK, count=2
        )
        issue = _issue(hass, entry)
        assert issue is not None
        assert (issue.severity, issue.is_fixable, issue.is_persistent) == (
            ir.IssueSeverity.WARNING,
            False,
            False,
        )
        assert issue.translation_key == "address_not_found"
        assert issue.translation_placeholders == {
            "entry": ADDRESS_TEXT,
            "group": "1.1",
            "url": KYIV_PAGE,
            "integration": INTEGRATION,
        }
        warning = (
            f"Yasno does not find the address of entry {entry.entry_id} any more, "
            "so the entry keeps group 1.1"
        )
        assert _records(caplog, logging.WARNING) == [warning]

        nine_o_clock.tick(WEEK)
        await coordinator.async_refresh()

        assert _kept_check(hass_storage, entry)["not_found_count"] == 3
        assert _issue(hass, entry) is not None
        assert len(_records(caplog, logging.WARNING)) == 1
        assert entry.data[CONF_GROUP] == "1.1"
        assert coordinator.group == "1.1"
        await _unload(hass, entry)

    async def test_found_of_a_new_group_ends_the_results_in_a_row(
        self, hass, aioclient_mock, hass_storage, nine_o_clock
    ):
        """
        Not found, then a Found of a new group, then Not found: no repair issue.

        Yasno found the address in the middle, so the two Not found results are
        not in a row.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), count=1)
        )

        await coordinator.async_refresh()

        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="53.1"
        )

        nine_o_clock.tick(HOUR)
        _serve(aioclient_mock, streets=NO_STREET)
        await coordinator.async_refresh()

        assert coordinator.address_check_result is AddressResult.NOT_FOUND
        assert _kept_check(hass_storage, entry)["not_found_count"] == 1
        assert _issue(hass, entry) is None
        await _unload(hass, entry)

    async def test_not_found_between_two_founds_of_a_new_group_stops_the_switch(
        self, hass, aioclient_mock, hass_storage, nine_o_clock
    ):
        """
        A new group, then Not found, then the new group again: no switch yet.

        Two checks with no Not found between them must find the new group.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow())
        )
        await coordinator.async_refresh()

        nine_o_clock.tick(HOUR)
        _serve(aioclient_mock, streets=NO_STREET)
        await coordinator.async_refresh()

        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, count=1
        )

        nine_o_clock.tick(HOUR)
        _serve(aioclient_mock)
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "1.1"
        assert entry.runtime_data is coordinator
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="53.1"
        )
        await _unload(hass, entry)

    async def test_issue_survives_a_restart_and_goes_after_a_found(
        self, hass, aioclient_mock, hass_storage
    ):
        """The setup restores the issue from the store; a later Found removes it."""
        _serve(aioclient_mock, group=GROUP_1_1)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), count=2)
        )

        issue = _issue(hass, entry)
        assert issue is not None
        assert issue.translation_placeholders["group"] == "1.1"

        await coordinator.async_refresh()

        assert _issue(hass, entry) is None
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        await _unload(hass, entry)

    async def test_unload_deletes_the_issue(self, hass, aioclient_mock, hass_storage):
        """The issue goes with the unload, as group_not_listed does."""
        _serve(aioclient_mock)
        entry, _ = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + WEEK, count=2)
        )
        assert _issue(hass, entry) is not None

        await _unload(hass, entry)

        assert _issue(hass, entry) is None

    @pytest.mark.parametrize(
        ("region", "url"),
        [
            (25, KYIV_PAGE),
            (3, "https://static.yasno.ua/dnipro/outages"),
            (7, KYIV_PAGE),
        ],
        ids=["kyiv", "dnipro", "other"],
    )
    async def test_issue_links_the_page_of_the_region(self, hass, region, url):
        """The issue links the Yasno page of the region, or the page of Київ."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={**YASNO_KYIV_ADDRESS_1_1, CONF_REGION: region, CONF_PROVIDER: 301},
            title=ADDRESS_TEXT,
        )
        entry.add_to_hass(hass)

        await _counting(hass, entry, 2)._async_create_address_issue()

        issue = _issue(hass, entry)
        assert issue is not None
        assert issue.translation_placeholders["url"] == url

    async def test_issue_names_the_integration_for_the_reconfigure(self, hass):
        """The text shows the way to Reconfigure, so it names the integration."""
        entry = MockConfigEntry(
            domain=DOMAIN, data=YASNO_KYIV_ADDRESS_1_1, title=ADDRESS_TEXT
        )
        entry.add_to_hass(hass)

        await _counting(hass, entry, 2)._async_create_address_issue()

        issue = _issue(hass, entry)
        assert issue is not None
        assert issue.translation_placeholders["integration"] == INTEGRATION

    @pytest.mark.parametrize(
        "count", [None, 0, 1], ids=["no_state", "no_results", "one_result"]
    )
    async def test_issue_needs_two_not_found_results(self, hass, count):
        """The issue shows only while the state counts two Not found results."""
        entry = MockConfigEntry(
            domain=DOMAIN, data=YASNO_KYIV_ADDRESS_1_1, title=ADDRESS_TEXT
        )
        entry.add_to_hass(hass)

        await _counting(hass, entry, count)._async_create_address_issue()

        assert _issue(hass, entry) is None

    @pytest.mark.parametrize("language", ["en", "uk"])
    def test_translation_uses_the_sent_placeholders(self, language):
        """The title names the entry, and the description the entry, group and page."""
        translations = json.loads(
            (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
        )
        issue = translations["issues"]["address_not_found"]

        assert _placeholders(issue["title"]) == {"entry"}
        assert _placeholders(issue["description"]) == {
            "entry",
            "group",
            "url",
            "integration",
        }


def _placeholders(text: str) -> set[str]:
    """Return the names of the placeholders in a translation text."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


async def _reconfigure_to_the_address(hass, entry: MockConfigEntry) -> dict:
    """Walk a Reconfigure of the entry through the address steps, to its own address."""
    flow = hass.config_entries.flow
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "address"})
    assert result["step_id"] == "address"
    # The form suggests the street of the entry, and the house form suggests its house
    street = {CONF_STREET: YASNO_KYIV_STREET}
    result = await flow.async_configure(result["flow_id"], street)
    assert result["step_id"] == "house"
    house = {CONF_HOUSE: YASNO_KYIV_HOUSE}
    return await flow.async_configure(result["flow_id"], house)


class TestAddressFound:
    """A Reconfigure that finds the address of a loaded entry starts its clock again."""

    async def test_address_of_the_entry_clears_the_not_found_results(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        The issue goes, the clock starts again, and the store keeps the new state.

        The pending group goes too: the Reconfigure brings the group of the address.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=2)
        )
        assert _issue(hass, entry) is not None

        await coordinator.async_address_found(ADDRESS)

        assert _issue(hass, entry) is None
        assert coordinator._address_check == AddressCheck(
            ADDRESS, dt_utils.utcnow() + WEEK
        )
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        await _unload(hass, entry)

    # An address that differs from the address of the entry in one name
    @pytest.mark.parametrize(
        "address",
        [
            YasnoAddress(street=YASNO_KYIV_STREET, house="2"),
            YasnoAddress(street="вул. Інша Тестова", house=YASNO_KYIV_HOUSE),
            YasnoAddress(
                street=YASNO_KYIV_STREET, house=YASNO_KYIV_HOUSE, city="м. Тестове"
            ),
        ],
        ids=["other_house", "other_street", "other_city"],
    )
    async def test_other_address_changes_nothing(
        self, hass, aioclient_mock, hass_storage, address
    ):
        """The kept state of the entry is not about another address: nothing changes."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass,
            hass_storage,
            check=_check(
                dt_utils.utcnow() + timedelta(days=3), pending="53.1", count=2
            ),
        )
        before = coordinator._address_check
        kept = _kept_check(hass_storage, entry)

        with patch.object(coordinator._store, "async_save") as save:
            await coordinator.async_address_found(address)

        assert coordinator._address_check == before
        assert _issue(hass, entry) is not None
        assert _kept_check(hass_storage, entry) == kept
        save.assert_not_called()
        await _unload(hass, entry)

    async def test_reconfigure_to_the_same_address_clears_the_issue_for_good(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        A Reconfigure to the address of the entry takes the repair issue away.

        The data stays the same, so the entry does not reload. The store keeps the
        new state, so a later reload does not bring the issue back.
        """
        data = {**YASNO_KYIV_ADDRESS_1_1, CONF_GROUP: "53.1"}
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), count=2), data=data
        )
        assert _issue(hass, entry) is not None

        result = await _reconfigure_to_the_address(hass, entry)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_unchanged"
        assert entry.data == data
        assert entry.runtime_data is coordinator
        assert _issue(hass, entry) is None
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data is not coordinator
        assert _issue(hass, entry) is None
        diagnostics = entry.runtime_data.address_check_diagnostics()
        assert diagnostics["not_found_count"] == 0
        await _unload(hass, entry)


async def _run_check(coordinator: YasnoCoordinator, *, force: bool) -> None:
    """Run the check of the address: a due poll, or the forced check of the button."""
    if force:
        await coordinator.async_check_address_now()
    else:
        await coordinator.async_refresh()


class TestFoundMeanwhile:
    """A Reconfigure that finds the address while a check runs wins over the check."""

    # The answer of Yasno to the check, and the result that the check keeps. The
    # group 53.1 is a new group that the planned outages list.
    @pytest.mark.parametrize(
        "answer",
        [
            (AddressResult.NOT_FOUND, None),
            (AddressResult.FOUND, "53.1"),
            (AddressResult.UNKNOWN, None),
        ],
        ids=["not_found", "other_group", "no_answer"],
    )
    @pytest.mark.parametrize("force", [False, True], ids=["poll", "force"])
    async def test_old_answer_writes_nothing(
        self, hass, aioclient_mock, hass_storage, caplog, answer, force
    ):
        """
        The answer that comes after the Reconfigure changes no state, group or issue.

        The second Not found result would create the issue, and a new group that
        is pending would switch the entry. The state of the Reconfigure stays.
        """
        caplog.set_level(logging.INFO, logger=LOGGER_NAME)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=1)
        )

        async def found_while_yasno_answers(_address):
            await coordinator.async_address_found(ADDRESS)
            return answer

        with patch.object(
            coordinator.api, "resolve_address", side_effect=found_while_yasno_answers
        ):
            await _run_check(coordinator, force=force)
        await hass.async_block_till_done()

        # The result of the check stays for the button and the diagnostics
        assert coordinator.address_check_result is answer[0]
        assert _issue(hass, entry) is None
        assert coordinator._address_check == AddressCheck(
            ADDRESS, dt_utils.utcnow() + WEEK
        )
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        assert entry.data[CONF_GROUP] == "1.1"
        assert entry.runtime_data is coordinator
        # No warning about the address and no line about a new group
        assert _records(caplog, logging.WARNING) == []
        assert _records(caplog, logging.INFO) == []
        await _unload(hass, entry)

    @pytest.mark.parametrize("force", [False, True], ids=["poll", "force"])
    async def test_found_while_the_texts_of_the_issue_load(
        self, hass, aioclient_mock, hass_storage, force
    ):
        """
        The second Not found result creates no issue after the Reconfigure cleared it.

        The issue waits for the name of the integration, and the Reconfigure comes
        in that time. The state that the Reconfigure kept stays, also in the store.
        """
        _serve(aioclient_mock, streets=NO_STREET)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=1)
        )

        async def title_after_found():
            await coordinator.async_address_found(ADDRESS)
            return INTEGRATION

        with patch.object(
            coordinator, "_async_integration_title", side_effect=title_after_found
        ) as title:
            await _run_check(coordinator, force=force)

        title.assert_awaited_once()
        assert coordinator.address_check_result is AddressResult.NOT_FOUND
        assert _issue(hass, entry) is None
        assert coordinator._address_check == AddressCheck(
            ADDRESS, dt_utils.utcnow() + WEEK
        )
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + WEEK)
        await _unload(hass, entry)


def _notice(language: str, old: str, new: str) -> tuple[str, str]:
    """Return the title and the message of the notification about a new group."""
    if language == "uk":
        title = "Нова група Yasno"
        message = (
            f"Група Yasno для «{ADDRESS_TEXT}» змінилася з {old} на {new}. "
            "Запис тепер показує графік нової групи."
        )
    else:
        title = "New Yasno group"
        message = (
            f"The Yasno group of «{ADDRESS_TEXT}» changed from {old} to {new}. "
            "The entry now shows the schedule of the new group."
        )
    return title, message


# A text of the notification that a translation could give instead of the English one
OWN_MESSAGE = "{entry}: {old_group}>{new_group}"


def _group_changed(entry: MockConfigEntry, old: str, new: str) -> dict:
    """Build the data of the event about a new group of the entry."""
    return {"config_entry_id": entry.entry_id, "old_group": old, "new_group": new}


def _notification(hass, entry: MockConfigEntry) -> dict | None:
    """Return the notification about the new group of the entry, if it exists."""
    return async_get_persistent_notifications(hass).get(
        group_changed_notification_id(entry.entry_id)
    )


def _texts_of(notification: dict | None) -> tuple[str, str] | None:
    """Return the title and the message of a notification, as the user reads them."""
    if notification is None:
        return None
    return notification["title"], notification["message"]


async def _press_the_check_button(hass, entry: MockConfigEntry) -> None:
    """Press the button of the entry that checks its group at once."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_check_group"
    )
    assert entity_id is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )


def _assert_no_address(event, address: dict) -> None:
    """Check that the event has the three keys of the notice, and no address."""
    assert set(event.data) == {"config_entry_id", "old_group", "new_group"}
    text = json.dumps(dict(event.data), ensure_ascii=False)
    for key in (CONF_CITY, CONF_STREET, CONF_HOUSE):
        assert key not in event.data
        # An entry without a city has no city to find
        assert not address.get(key) or address[key] not in text


class TestGroupChangedNotice:
    """The switch to a new group: an event for automations and a notification."""

    @pytest.mark.parametrize("how", ["call", "button"])
    async def test_forced_check_tells_the_user(
        self, hass, aioclient_mock, hass_storage, how
    ):
        """
        A forced check that finds a new group fires one event and shows one notice.

        The button of the entry and the call of the coordinator end the same way.
        """
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        assert events == []
        assert async_get_persistent_notifications(hass) == {}

        if how == "button":
            await _press_the_check_button(hass, entry)
        else:
            await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "53.1"
        assert [(e.event_type, dict(e.data)) for e in events] == [
            ("svitlo_yeah_group_changed", _group_changed(entry, "1.1", "53.1"))
        ]
        notifications = async_get_persistent_notifications(hass)
        assert list(notifications) == [f"svitlo_yeah_group_changed_{entry.entry_id}"]
        assert _texts_of(_notification(hass, entry)) == _notice("en", "1.1", "53.1")
        await _unload(hass, entry)

    async def test_texts_follow_the_language_of_the_server(
        self, hass, aioclient_mock, hass_storage
    ):
        """The title and the message come in the language of Home Assistant."""
        hass.config.language = "uk"
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert [dict(e.data) for e in events] == [_group_changed(entry, "1.1", "53.1")]
        assert len(async_get_persistent_notifications(hass)) == 1
        assert _texts_of(_notification(hass, entry)) == _notice("uk", "1.1", "53.1")
        await _unload(hass, entry)

    async def test_second_poll_tells_the_user_and_the_first_one_does_not(
        self, hass, aioclient_mock, hass_storage, nine_o_clock
    ):
        """
        The first check keeps the new group pending, and it tells nothing yet.

        The second check, an hour later, switches the entry and tells the user.
        """
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow())
        )

        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "1.1"
        assert events == []
        assert async_get_persistent_notifications(hass) == {}

        nine_o_clock.tick(HOUR)
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "53.1"
        assert [dict(e.data) for e in events] == [_group_changed(entry, "1.1", "53.1")]
        assert len(async_get_persistent_notifications(hass)) == 1
        assert _texts_of(_notification(hass, entry)) == _notice("en", "1.1", "53.1")
        await _unload(hass, entry)

    # The reply of Yasno to the check, and the result that the check keeps
    @pytest.mark.parametrize(
        ("reply", "result"),
        [
            ({"group": GROUP_1_1}, AddressResult.FOUND),
            ({"group": GROUP_60_1}, AddressResult.FOUND),
            ({"streets": NO_STREET}, AddressResult.NOT_FOUND),
            ({"group": SERVER_ERROR}, AddressResult.UNKNOWN),
        ],
        ids=["same_group", "unlisted_group", "not_found", "unknown"],
    )
    @pytest.mark.parametrize("force", [False, True], ids=["poll", "force"])
    async def test_a_check_without_a_switch_tells_nothing(
        self, hass, aioclient_mock, hass_storage, reply, result, force
    ):
        """
        A check that does not switch the entry fires no event and shows no notice.

        The group 53.1 is pending, and the second Not found result makes the issue.
        """
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock, **reply)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=1)
        )

        await _run_check(coordinator, force=force)
        await hass.async_block_till_done()

        assert coordinator.address_check_result is result
        assert entry.data[CONF_GROUP] == "1.1"
        assert entry.runtime_data is coordinator
        assert events == []
        assert async_get_persistent_notifications(hass) == {}
        await _unload(hass, entry)

    async def test_reconfigure_of_the_user_tells_nothing(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        A Reconfigure that gives the entry the group of its address is the user's act.

        The flow writes the new group, and the update listener reloads the entry.
        The user chose this group, so nothing tells the user about it.
        """
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + WEEK)
        )

        result = await _reconfigure_to_the_address(hass, entry)
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_GROUP] == "53.1"
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data is not coordinator
        assert events == []
        assert async_get_persistent_notifications(hass) == {}
        await _unload(hass, entry)

    async def test_event_has_no_address(self, hass, aioclient_mock, hass_storage):
        """The event names the entry by its id: no street, house or city goes out."""
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert len(events) == 1
        _assert_no_address(events[0], dict(entry.data))
        assert (entry.data[CONF_STREET], entry.data[CONF_HOUSE]) == (
            YASNO_KYIV_STREET,
            YASNO_KYIV_HOUSE,
        )
        await _unload(hass, entry)

    async def test_event_of_an_entry_with_a_city_has_no_city(self, hass):
        """The event of an entry that has a city names no city, street or house."""
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        city = "м. Тестове"
        data = {**YASNO_KYIV_ADDRESS_1_1, CONF_CITY: city}
        entry = MockConfigEntry(
            domain=DOMAIN, data=data, title=f"{city}, {ADDRESS_TEXT}"
        )
        entry.add_to_hass(hass)

        YasnoCoordinator(hass, entry)._notify_group_changed("1.1", "53.1")
        await hass.async_block_till_done()

        assert [dict(e.data) for e in events] == [_group_changed(entry, "1.1", "53.1")]
        _assert_no_address(events[0], data)

    async def test_later_switch_replaces_the_notification(
        self, hass, aioclient_mock, hass_storage
    ):
        """A second switch of the entry shows one notice, with the last change."""
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        await coordinator.async_check_address_now()
        await hass.async_block_till_done()
        assert _texts_of(_notification(hass, entry)) == _notice("en", "1.1", "53.1")

        _serve(aioclient_mock, group=GROUP_2_1)
        reloaded = entry.runtime_data
        assert reloaded is not coordinator
        await reloaded.async_check_address_now()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "2.1"
        assert [dict(e.data) for e in events] == [
            _group_changed(entry, "1.1", "53.1"),
            _group_changed(entry, "53.1", "2.1"),
        ]
        assert list(async_get_persistent_notifications(hass)) == [
            f"svitlo_yeah_group_changed_{entry.entry_id}"
        ]
        assert _texts_of(_notification(hass, entry)) == _notice("en", "53.1", "2.1")
        await _unload(hass, entry)

    async def test_check_that_finds_the_new_group_in_the_entry_tells_nothing(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        A second check before the reload finds the new group in the entry already.

        The update listener is away, so that no reload comes between the checks.
        The data does not change the second time, so the user gets one notice.
        """
        events = async_capture_events(hass, EVENT_GROUP_CHANGED)
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        listeners = entry.update_listeners.copy()
        entry.update_listeners.clear()

        await coordinator.async_check_address_now()
        await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert entry.data[CONF_GROUP] == "53.1"
        assert [dict(e.data) for e in events] == [_group_changed(entry, "1.1", "53.1")]
        assert len(async_get_persistent_notifications(hass)) == 1
        entry.update_listeners.extend(listeners)
        await _unload(hass, entry)

    async def test_reload_and_unload_keep_the_notification(
        self, hass, aioclient_mock, hass_storage
    ):
        """
        The new group reloads the entry, and the notice must outlive the reload.

        An unload keeps it too: only the removal of the entry takes it away.
        """
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert entry.runtime_data is not coordinator
        notice = _notification(hass, entry)
        assert _texts_of(notice) == _notice("en", "1.1", "53.1")

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert _notification(hass, entry) == notice

        await _unload(hass, entry)

        assert _notification(hass, entry) == notice

    @pytest.mark.parametrize("unloaded", [False, True], ids=["loaded", "unloaded"])
    async def test_removal_dismisses_the_notification(
        self, hass, aioclient_mock, hass_storage, unloaded
    ):
        """The removal of the entry dismisses its notice, and no other notice."""
        persistent_notification.async_create(
            hass, "Another message", title="Another title", notification_id="another"
        )
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )
        await coordinator.async_check_address_now()
        await hass.async_block_till_done()
        assert _notification(hass, entry) is not None
        if unloaded:
            await _unload(hass, entry)

        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

        assert _notification(hass, entry) is None
        assert list(async_get_persistent_notifications(hass)) == ["another"]

    # What the common translations of the poll hold: no group text, or one of them
    @pytest.mark.parametrize(
        ("translations", "title", "message"),
        [
            ({}, GROUP_CHANGED_TITLE, GROUP_CHANGED_MESSAGE),
            (
                {TRANSLATION_KEY_GROUP_CHANGED_TITLE: "Own title"},
                "Own title",
                GROUP_CHANGED_MESSAGE,
            ),
            (
                {TRANSLATION_KEY_GROUP_CHANGED_MESSAGE: OWN_MESSAGE},
                GROUP_CHANGED_TITLE,
                OWN_MESSAGE,
            ),
        ],
        ids=["no_texts", "only_title", "only_message"],
    )
    async def test_missing_translation_falls_back_to_english(
        self, hass, aioclient_mock, hass_storage, translations, title, message
    ):
        """Each text that the translations lack comes from the English constants."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow() + timedelta(days=5))
        )

        async def fetch_the_given_texts():
            coordinator.translations = translations

        with patch.object(
            coordinator, "async_fetch_translations", side_effect=fetch_the_given_texts
        ):
            await coordinator.async_check_address_now()
        await hass.async_block_till_done()

        assert coordinator.translations == translations
        assert entry.data[CONF_GROUP] == "53.1"
        assert _texts_of(_notification(hass, entry)) == (
            title,
            message.format(entry=ADDRESS_TEXT, old_group="1.1", new_group="53.1"),
        )
        await _unload(hass, entry)

    def test_fallback_texts_are_the_english_texts(self):
        """The constants of the code say what en.json says: a fallback reads alike."""
        english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
        common = english["common"]
        title, message = _notice("en", "1.1", "53.1")

        assert common["group_changed_title"] == GROUP_CHANGED_TITLE
        assert common["group_changed_message"] == GROUP_CHANGED_MESSAGE
        assert title == GROUP_CHANGED_TITLE
        assert message == GROUP_CHANGED_MESSAGE.format(
            entry=ADDRESS_TEXT, old_group="1.1", new_group="53.1"
        )

    @pytest.mark.parametrize("language", ["en", "uk"])
    def test_translation_uses_the_sent_placeholders(self, language):
        """The message names the entry and both groups, and the title names nothing."""
        common = json.loads(
            (TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")
        )["common"]

        assert _placeholders(common["group_changed_title"]) == set()
        assert _placeholders(common["group_changed_message"]) == {
            "entry",
            "old_group",
            "new_group",
        }


class TestUnknown:
    """A check that gets no sure answer."""

    @pytest.mark.parametrize("schedule", [True, False], ids=["schedule", "no_schedule"])
    async def test_retry_in_an_hour_and_nothing_else_changes(
        self, hass, aioclient_mock, hass_storage, schedule
    ):
        """The pending group and the count stay; the flags of the schedule too."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=1)
        )
        _serve(aioclient_mock, group=SERVER_ERROR, schedule=schedule)

        if schedule:
            await coordinator.async_refresh()
        else:
            # A due check waits while the schedule fails, so the button forces it
            await coordinator.async_check_address_now()

        assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
        assert coordinator.address_check_result is AddressResult.UNKNOWN
        assert _kept_check(hass_storage, entry) == _check(
            dt_utils.utcnow() + HOUR, pending="53.1", count=1
        )
        assert coordinator.last_fetch_failed is not schedule
        assert coordinator.last_update_success is True
        assert entry.data[CONF_GROUP] == "1.1"
        await _unload(hass, entry)

    async def test_failed_check_does_not_fail_the_poll(
        self, hass, aioclient_mock, hass_storage, caplog
    ):
        """An error inside the check counts as no answer, and its text stays out."""
        _serve(aioclient_mock)
        entry, coordinator = await _start(
            hass, hass_storage, check=_check(dt_utils.utcnow())
        )

        with patch.object(
            YasnoApi, "resolve_address", side_effect=KeyError(YASNO_KYIV_STREET)
        ):
            await coordinator.async_refresh()

        assert coordinator.last_update_success is True
        assert coordinator.last_fetch_failed is False
        assert coordinator.address_check_result is AddressResult.UNKNOWN
        assert _kept_check(hass_storage, entry) == _check(dt_utils.utcnow() + HOUR)
        assert _records(caplog, logging.WARNING) == [
            f"The check of the address of entry {entry.entry_id} failed with KeyError"
        ]
        await _unload(hass, entry)


class TestOtherEntries:
    """Only a Yasno entry with an address checks its group."""

    async def test_group_entry_asks_no_address(
        self, hass, aioclient_mock, hass_storage, nine_o_clock
    ):
        """A Yasno entry with a group only keeps the data that it kept before."""
        _serve(aioclient_mock)
        entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data

        for _ in range(2):
            await coordinator.async_refresh()
            await coordinator.async_check_address_now()
            nine_o_clock.tick(WEEK + HOUR)

        assert _address_requests(aioclient_mock) == []
        assert set(hass_storage[store_key(entry.entry_id)]["data"]["source"]) == {
            "planned_outage_data",
            "region",
        }
        assert coordinator.address_check_diagnostics() is None
        await _unload(hass, entry)

    async def test_dtek_entry_asks_no_address(self, hass, aioclient_mock, nine_o_clock):
        """A DTEK entry never asks Yasno for an address."""
        dtek_answers(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))
        entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        for _ in range(2):
            await entry.runtime_data.async_refresh()
            nine_o_clock.tick(WEEK + HOUR)

        assert _address_requests(aioclient_mock) == []
        await _unload(hass, entry)


async def test_no_log_line_has_the_address(
    hass, aioclient_mock, hass_storage, nine_o_clock, caplog
):
    """
    The log of each step of the check names the entry by its id (plan Behavior 14).

    The steps: the clock, a new group, the switch and the reload, two Not found
    results, no answer, and an error with the street in its text.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    _serve(aioclient_mock)
    entry, coordinator = await _start(hass, hass_storage)
    await coordinator.async_refresh()
    for _ in range(2):
        nine_o_clock.tick(WEEK)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert entry.data[CONF_GROUP] == "53.1"

    coordinator = entry.runtime_data
    _serve(aioclient_mock, streets=NO_STREET)
    for _ in range(2):
        nine_o_clock.tick(WEEK)
        await coordinator.async_refresh()
    assert _issue(hass, entry) is not None
    _serve(aioclient_mock, group=SERVER_ERROR)
    nine_o_clock.tick(WEEK)
    await coordinator.async_refresh()
    with patch.object(
        YasnoApi, "resolve_address", side_effect=ValueError(YASNO_KYIV_STREET)
    ):
        nine_o_clock.tick(WEEK)
        await coordinator.async_refresh()
    await _unload(hass, entry)

    lines = [r.getMessage() for r in caplog.records if r.name.startswith(LOGGER_NAME)]
    assert f"The Yasno group of entry {entry.entry_id} changed from 1.1 to 53.1" in (
        lines
    )
    assert [_ for _ in lines if "Сверстюка" in _ or YASNO_KYIV_HOUSE in _] == []


async def test_diagnostics_show_the_check_without_the_address(
    hass, hass_client, aioclient_mock, hass_storage
):
    """The diagnostics show the state and the last result of the check, no address."""
    _serve(aioclient_mock, group=SERVER_ERROR)
    entry, coordinator = await _start(
        hass, hass_storage, check=_check(dt_utils.utcnow(), pending="53.1", count=1)
    )
    await coordinator.async_refresh()

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result["coordinator"]["address_check"] == {
        "next_check": (dt_utils.utcnow() + HOUR).isoformat(),
        "pending_group": "53.1",
        "not_found_count": 1,
        "last_result": "unknown",
    }
    data = result["entry"]["data"]
    assert (data[CONF_STREET], data[CONF_HOUSE]) == ("**REDACTED**",) * 2
    text = json.dumps(result, ensure_ascii=False)
    assert "Сверстюка" not in text
    assert YASNO_KYIV_HOUSE not in text
    await _unload(hass, entry)


async def test_diagnostics_before_the_first_check(
    hass, hass_client, aioclient_mock, hass_storage
):
    """An address entry without a kept state shows an empty state of the check."""
    _serve(aioclient_mock)
    entry, _ = await _start(hass, hass_storage)

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result["coordinator"]["address_check"] == {
        "next_check": None,
        "pending_group": None,
        "not_found_count": 0,
        "last_result": None,
    }
    await _unload(hass, entry)


@pytest.mark.parametrize(
    "kept",
    [
        None,
        [],
        {},
        _check(datetime.now(UTC)) | {"address": ADDRESS_TEXT},
        _check(datetime.now(UTC)) | {"address": {CONF_STREET: YASNO_KYIV_STREET}},
        _check(datetime.now(UTC)) | {"next_check": None},
        _check(datetime.now(UTC)) | {"next_check": "next week"},
        _check(datetime.now(UTC)) | {"next_check": "2026-10-21T09:00:00"},
        _check(datetime.now(UTC)) | {"pending_group": 53.1},
        _check(datetime.now(UTC)) | {"not_found_count": True},
        _check(datetime.now(UTC)) | {"not_found_count": -1},
        _check(datetime.now(UTC)) | {"not_found_count": "2"},
    ],
    ids=[
        "none",
        "a_list",
        "empty",
        "address_text",
        "address_without_house",
        "no_time",
        "time_not_iso",
        "naive_time",
        "pending_not_text",
        "count_bool",
        "count_negative",
        "count_text",
    ],
)
def test_kept_state_of_another_shape_is_no_state(kept):
    """A kept state that this version cannot read counts as no state."""
    assert AddressCheck.from_dict(kept) is None


def test_kept_state_goes_back_as_it_was():
    """The kept form of the state gives the same state back."""
    check = AddressCheck(
        YasnoAddress(city="м. Дніпро", street="вул. Шевченка ", house="1"),
        datetime.now(UTC),
        pending_group="3.1",
        not_found_count=1,
    )

    assert AddressCheck.from_dict(check.as_dict()) == check
