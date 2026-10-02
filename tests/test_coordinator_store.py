"""
The last data of an entry stays across a restart.

AGENTS.md tells why, in «Old states until new data».
"""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.const import (
    DOMAIN,
    EVENT_DATA_CHANGED,
    TZ_UA,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.coordinator.coordinator import (
    STORE_VERSION,
    group_not_listed_issue_id,
    store_key,
)
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    E_SVITLO_ACCOUNT_101,
    E_SVITLO_DETAILS_URL,
    E_SVITLO_DISCONNECTIONS_URL,
    E_SVITLO_LOGIN_URL,
    KYIV_REGION_URLS,
    YASNO_KYIV,
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
    dtek_answers,
    e_svitlo_outage_all_day_today,
    fact_with_an_outage_today,
    yasno_outage_all_day_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


def _kept(source: dict, **fields) -> dict:
    """Wrap the kept data of an entry in the envelope of the store."""
    return {
        "version": STORE_VERSION,
        "minor_version": 1,
        "key": "",
        "data": {
            "source": source,
            "group": "1.1",
            "group_listed": True,
            "outage_data_last_changed": None,
            **fields,
        },
    }


async def _set_up(hass, entry: MockConfigEntry):
    """Set up the entry and return its coordinator."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that no timer of it outlives the test."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_fresh_dtek_data_goes_into_the_store(hass, aioclient_mock, hass_storage):
    """A fresh DTEK schedule is kept for the next start of Home Assistant."""
    fact = fact_with_an_outage_today(datetime.now(UTC))
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": {}})
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    kept = hass_storage[store_key(entry.entry_id)]["data"]
    assert kept["source"] == {"fact": fact, "preset": {}}
    assert (kept["group"], kept["group_listed"]) == ("1.1", True)
    await _unload(hass, entry)


@pytest.mark.parametrize(
    "kept",
    [
        {"version": STORE_VERSION + 1, "minor_version": 1, "data": {"source": {}}},
        {"version": STORE_VERSION, "minor_version": 1, "data": {"group": "1.1"}},
    ],
    ids=["newer_version", "no_source"],
)
async def test_unreadable_store_does_not_stop_the_setup(
    hass, aioclient_mock, hass_storage, caplog, kept
):
    """A kept store that this version cannot read is skipped, and the source answers."""
    dtek_answers(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = {**kept, "key": store_key(entry.entry_id)}

    coordinator = await _set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert "cannot be read" in caplog.text
    # The fresh data replaces the store that could not be read
    assert hass_storage[store_key(entry.entry_id)]["version"] == STORE_VERSION
    assert "source" in hass_storage[store_key(entry.entry_id)]["data"]
    await _unload(hass, entry)


async def test_stale_dtek_data_stays_out_of_the_store(
    hass, aioclient_mock, hass_storage
):
    """A new entry with an outdated source keeps nothing, as it uses nothing."""
    fact = fact_with_an_outage_today(datetime.now(UTC) - timedelta(days=30))
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": {}})
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_NORMAL
    assert store_key(entry.entry_id) not in hass_storage
    await _unload(hass, entry)


async def test_restart_without_an_answer_shows_the_kept_schedule(
    hass, aioclient_mock, hass_storage
):
    """After a restart, the kept schedule gives the old states until an answer comes."""
    fact = fact_with_an_outage_today(datetime.now(UTC) - timedelta(hours=2))
    changed = dt_utils.now() - timedelta(hours=3)
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        {"fact": fact, "preset": {}}, outage_data_last_changed=changed.isoformat()
    )

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert coordinator.schedule_updated_on is not None
    assert coordinator.outage_data_last_changed == changed
    await _unload(hass, entry)


async def test_kept_answer_about_another_group_is_not_used(
    hass, aioclient_mock, hass_storage
):
    """After a Reconfigure, the kept answer about the old group raises no issue."""
    fact = fact_with_an_outage_today(datetime.now(UTC) - timedelta(hours=2))
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        {"fact": fact, "preset": {}}, group="7.1", group_listed=False
    )

    coordinator = await _set_up(hass, entry)

    assert coordinator.group_listed is None
    issue_id = group_not_listed_issue_id(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    await _unload(hass, entry)


async def test_yasno_data_goes_into_the_store(hass, aioclient_mock, hass_storage):
    """The Yasno planned outages and the region are kept for the next start."""
    outage = yasno_outage_all_day_today()
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    aioclient_mock.get(YASNO_PLANNED_URL, json=outage)
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    entry.add_to_hass(hass)

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    kept = hass_storage[store_key(entry.entry_id)]["data"]
    assert kept["source"] == {"planned_outage_data": outage, "region": YASNO_KYIV}
    await _unload(hass, entry)


async def test_yasno_restart_without_an_answer_shows_the_kept_schedule(
    hass, aioclient_mock, hass_storage
):
    """After a restart, Yasno shows the kept outage, and the device keeps its name."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
    aioclient_mock.get(YASNO_PLANNED_URL, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        {"planned_outage_data": yasno_outage_all_day_today(), "region": YASNO_KYIV}
    )

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert (coordinator.region_name, coordinator.provider_name) == ("Київ", "ДТЕК")
    # The kept region names only this device, the config flow still asks Yasno
    assert YasnoApi._regions is None
    await _unload(hass, entry)


async def test_e_svitlo_data_goes_into_the_store(hass, aioclient_mock, hass_storage):
    """The raw E-Svitlo answer, its update time and the group are kept."""
    answer = e_svitlo_outage_all_day_today()
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    aioclient_mock.post(E_SVITLO_DISCONNECTIONS_URL, json=answer)
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    kept = hass_storage[store_key(entry.entry_id)]["data"]["source"]
    updated = datetime.now(TZ_UA).replace(hour=10, minute=0, second=0, microsecond=0)
    assert kept == {
        "disconnections": answer,
        "last_update": updated.isoformat(),
        "group": "4.1",
    }
    await _unload(hass, entry)


@pytest.mark.parametrize(
    "body",
    [{"error": {"err": "Технічні роботи"}}, {"data": {}}],
    ids=["error_text", "empty_data"],
)
async def test_e_svitlo_answer_without_a_schedule_keeps_the_last_one(
    hass, aioclient_mock, hass_storage, body
):
    """An answer 200 without a schedule counts as no answer: the old states stay."""
    answer = e_svitlo_outage_all_day_today()
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    aioclient_mock.post(E_SVITLO_DISCONNECTIONS_URL, json=answer)
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)
    coordinator = await _set_up(hass, entry)
    changes = async_capture_events(hass, EVENT_DATA_CHANGED)

    aioclient_mock.clear_requests()
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    aioclient_mock.post(E_SVITLO_DISCONNECTIONS_URL, json=body)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert coordinator.last_fetch_failed
    assert changes == []
    kept = hass_storage[store_key(entry.entry_id)]["data"]["source"]
    assert kept["disconnections"] == answer
    await _unload(hass, entry)


async def test_e_svitlo_restart_without_an_answer_shows_the_kept_schedule(
    hass, aioclient_mock, hass_storage
):
    """After a restart, E-Svitlo shows the kept outage, and the device has its group."""
    updated = datetime.now(TZ_UA).replace(hour=10, minute=0, second=0, microsecond=0)
    aioclient_mock.post(E_SVITLO_LOGIN_URL, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        {
            "disconnections": e_svitlo_outage_all_day_today(),
            "last_update": updated.isoformat(),
            "group": "4.1",
        },
        group="4.1",
    )

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert coordinator.schedule_updated_on == updated
    assert coordinator.group == "4.1"
    # The client still asks the server for the group, the kept one names the device
    assert coordinator.api.group is None
    await _unload(hass, entry)


def _dtek_restart(mock, *, changed: bool) -> tuple[dict, dict, str]:
    """Keep a DTEK outage all day; serve it again, or power all day."""
    fact = fact_with_an_outage_today(datetime.now(UTC) - timedelta(hours=1))
    ((day, groups),) = fact["data"].items()
    no_outage = {**groups, "GPV1.1": dict.fromkeys(groups["GPV1.1"], "yes")}
    dtek_answers(mock, {**fact, "data": {day: no_outage}} if changed else fact)
    return DTEK_KYIV_REGION_1_1, {"fact": fact, "preset": {}}, "1.1"


def _yasno_restart(mock, *, changed: bool) -> tuple[dict, dict, str]:
    """
    Keep Yasno outages all day today and late tomorrow.

    Serve them again, or no outage today. The outage of tomorrow starts more
    than 24 hours after 09:00 today.
    """
    tomorrow = dt_utils.start_of_local_day() + timedelta(days=1)
    late_tomorrow = {
        "slots": [{"start": 1320, "end": 1440, "type": "Definite"}],
        "date": tomorrow.isoformat(),
        "status": "ScheduleApplies",
    }
    outage = yasno_outage_all_day_today()
    outage["1.1"]["tomorrow"] = late_tomorrow
    served = yasno_outage_all_day_today()
    served["1.1"]["tomorrow"] = late_tomorrow
    if changed:
        served["1.1"]["today"]["slots"] = []
    mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    mock.get(YASNO_PLANNED_URL, json=served)
    source = {"planned_outage_data": outage, "region": YASNO_KYIV}
    return YASNO_KYIV_1_1, source, "1.1"


def _e_svitlo_restart(mock, *, changed: bool) -> tuple[dict, dict, str]:
    """Keep an E-Svitlo outage all day; serve it again, or a day without outages."""
    answer = e_svitlo_outage_all_day_today()
    served = {"data": {**answer["data"], "lst_time_disc": []}} if changed else answer
    mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    mock.post(E_SVITLO_DISCONNECTIONS_URL, json=served)
    source = {"disconnections": answer, "last_update": None, "group": "4.1"}
    return E_SVITLO_ACCOUNT_101, source, "4.1"


@pytest.mark.parametrize("changed", [True, False], ids=["changed", "same"])
@pytest.mark.parametrize(
    "restart",
    [_dtek_restart, _yasno_restart, _e_svitlo_restart],
    ids=["dtek", "yasno", "e_svitlo"],
)
async def test_first_answer_after_a_restart_is_compared_with_the_kept_schedule(
    hass, aioclient_mock, hass_storage, freezer, restart, changed
):
    """
    A schedule that changed while Home Assistant was down fires one event.

    The same schedule fires none and keeps the kept time of the last change.
    """
    freezer.move_to(dt_utils.start_of_local_day() + timedelta(hours=9))
    data, source, group = restart(aioclient_mock, changed=changed)
    kept_change = dt_utils.now() - timedelta(days=2)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        source, group=group, outage_data_last_changed=kept_change.isoformat()
    )
    changes = async_capture_events(hass, EVENT_DATA_CHANGED)

    coordinator = await _set_up(hass, entry)

    assert len(changes) == int(changed)
    assert (coordinator.outage_data_last_changed != kept_change) is changed
    kept = hass_storage[store_key(entry.entry_id)]["data"]
    assert kept["outage_data_last_changed"] == (
        coordinator.outage_data_last_changed.isoformat()
    )
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("data", "urls"),
    [
        (YASNO_KYIV_1_1, [YASNO_REGIONS_ENDPOINT, YASNO_PLANNED_URL]),
        (E_SVITLO_ACCOUNT_101, [E_SVITLO_LOGIN_URL]),
    ],
    ids=["yasno", "e_svitlo"],
)
async def test_new_entry_without_an_answer_keeps_nothing(
    hass, aioclient_mock, hass_storage, data, urls
):
    """A new entry whose source does not answer has nothing to keep."""
    for url in urls:
        aioclient_mock.get(url, exc=ClientError())
        aioclient_mock.post(url, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    await _set_up(hass, entry)

    assert store_key(entry.entry_id) not in hass_storage
    await _unload(hass, entry)


async def test_removed_entry_takes_its_store_along(hass, aioclient_mock, hass_storage):
    """The kept data goes away together with the entry."""
    fact = fact_with_an_outage_today(datetime.now(UTC))
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": {}})
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    assert store_key(entry.entry_id) in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert store_key(entry.entry_id) not in hass_storage
