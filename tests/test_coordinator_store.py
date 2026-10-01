"""The last data of an entry stays across a restart (AGENTS.md, «Old states until new data»)."""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    PROVIDER_TYPE_DTEK_JSON,
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


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""


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
