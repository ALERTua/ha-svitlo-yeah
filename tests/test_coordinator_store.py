"""The last data of an entry stays across a restart (AGENTS.md, «Old states until new data»)."""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_ADDRESS_STR,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    E_SVITLO_SUMY_BASE_URL,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
    TZ_UA,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.coordinator.coordinator import (
    STORE_VERSION,
    group_not_listed_issue_id,
    store_key,
)
from custom_components.svitlo_yeah.models import ConnectivityState

KYIV_REGION_URLS = DTEK_PROVIDER_URLS["kyiv_region"]
DTEK_KYIV_REGION_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    CONF_PROVIDER: "kyiv_region",
    CONF_GROUP: "1.1",
}

YASNO_KYIV_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
    CONF_REGION: 25,
    CONF_PROVIDER: 902,
    CONF_GROUP: "1.1",
}
YASNO_PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=25, dso_id=902)
YASNO_KYIV = {
    "id": 25,
    "value": "Київ",
    "dsos": [{"id": 902, "name": "ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»"}],
}


def _yasno_outage_all_day_today() -> dict:
    """Build a Yasno answer with a planned outage for group 1.1 all day today."""
    today = dt_utils.start_of_local_day()
    return {
        "1.1": {
            "today": {
                "slots": [{"start": 0, "end": 1440, "type": "Definite"}],
                "date": today.isoformat(),
                "status": "ScheduleApplies",
            },
            "updatedOn": today.isoformat(),
        }
    }


def _fact_with_an_outage_today(update: datetime) -> dict:
    """Build a DTEK fact schedule in which group 1.1 has no power all day today."""
    today = int(dt_utils.start_of_local_day().timestamp())
    day = {"GPV1.1": {str(hour): "no" for hour in range(1, 25)}, "GPV1.2": {}}
    return {
        "data": {str(today): day},
        "update": update.strftime("%d.%m.%Y %H:%M"),
        "today": today,
    }


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


E_SVITLO_ACCOUNT_101 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_E_SVITLO,
    CONF_PROVIDER: "sumy",
    "username": "user",
    "password": "secret",
    CONF_ACCOUNT_ID: "101",
    CONF_ADDRESS_STR: "Суми, вул. Перша, 1",
}
E_SVITLO_LOGIN_URL = E_SVITLO_SUMY_BASE_URL + "api_main/login_api.json"
E_SVITLO_DETAILS_URL = E_SVITLO_SUMY_BASE_URL + "/api_main_reg/all_details_ls_api.json"
E_SVITLO_DISCONNECTIONS_URL = (
    E_SVITLO_SUMY_BASE_URL + "api_main/get_user_disconnections_image_api.json"
)


def _e_svitlo_outage_all_day_today() -> dict:
    """Build an E-Svitlo answer with an outage all day today, updated at 10:00."""
    today = datetime.now(TZ_UA)
    return {
        "data": {
            "date_today": today.strftime("%d.%m.%Y"),
            "lst_time_disc": [{"start_time": "00:00", "end_time": "23:59"}],
            "last_update": f"Оновлено: {today:%d.%m.%Y} 10:00",
        }
    }


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def _empty_yasno_region_cache(monkeypatch):
    """Make each Yasno setup fetch the regions again."""
    monkeypatch.setattr(YasnoApi, "_regions", None)


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
    fact = _fact_with_an_outage_today(datetime.now(UTC))
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


async def test_stale_dtek_data_stays_out_of_the_store(
    hass, aioclient_mock, hass_storage
):
    """A new entry with an outdated source keeps nothing, as it uses nothing."""
    fact = _fact_with_an_outage_today(datetime.now(UTC) - timedelta(days=30))
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
    """After a restart, the kept schedule gives the old states until the source answers."""
    fact = _fact_with_an_outage_today(datetime.now(UTC) - timedelta(hours=2))
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
    fact = _fact_with_an_outage_today(datetime.now(UTC) - timedelta(hours=2))
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
    outage = _yasno_outage_all_day_today()
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
        {"planned_outage_data": _yasno_outage_all_day_today(), "region": YASNO_KYIV}
    )

    coordinator = await _set_up(hass, entry)

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert (coordinator.region_name, coordinator.provider_name) == ("Київ", "ДТЕК")
    # The kept region names only this device, the config flow still asks Yasno
    assert YasnoApi._regions is None
    await _unload(hass, entry)


async def test_e_svitlo_data_goes_into_the_store(hass, aioclient_mock, hass_storage):
    """The raw E-Svitlo answer, its update time and the group are kept."""
    answer = _e_svitlo_outage_all_day_today()
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


async def test_e_svitlo_restart_without_an_answer_shows_the_kept_schedule(
    hass, aioclient_mock, hass_storage
):
    """After a restart, E-Svitlo shows the kept outage, and the device keeps its group."""
    updated = datetime.now(TZ_UA).replace(hour=10, minute=0, second=0, microsecond=0)
    aioclient_mock.post(E_SVITLO_LOGIN_URL, exc=ClientError())
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)
    hass_storage[store_key(entry.entry_id)] = _kept(
        {
            "disconnections": _e_svitlo_outage_all_day_today(),
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
    fact = _fact_with_an_outage_today(datetime.now(UTC))
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": {}})
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    assert store_key(entry.entry_id) in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert store_key(entry.entry_id) not in hass_storage
