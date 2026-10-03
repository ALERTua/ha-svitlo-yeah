"""A source answer of another shape never makes the entities unavailable."""

import logging
from datetime import UTC, datetime

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import DOMAIN, YASNO_REGIONS_ENDPOINT
from custom_components.svitlo_yeah.coordinator.coordinator import store_key
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
    e_svitlo_answers,
    e_svitlo_outage_all_day_today,
    fact_with_an_outage_today,
    kyiv_midnight,
    yasno_outage_all_day_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


def _serve_dtek(aioclient_mock, fact, preset=None) -> None:
    """Serve this fact schedule and preset on each DTEK feed of the Kyiv region."""
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, json={"fact": fact, "preset": preset or {}})


def _serve_yasno(aioclient_mock, answer) -> None:
    """Serve the Yasno regions and this answer of the planned outages."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    aioclient_mock.get(YASNO_PLANNED_URL, json=answer)


async def _set_up(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _states(hass, entry: MockConfigEntry) -> dict:
    """Return the state of each entity of the entry by its unique id."""
    return {
        e.unique_id: hass.states.get(e.entity_id)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


def _errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def _fact_with(day_data) -> dict:
    """Return a fresh fact schedule whose days are this value."""
    fact = fact_with_an_outage_today(datetime.now(UTC))
    fact["data"] = day_data
    return fact


@pytest.mark.parametrize(
    "days",
    [
        "text",
        {"tomorrow": {"GPV1.1": {"1": "no"}}},
        {str(int(kyiv_midnight().timestamp())): {"GPV1.1": ["no"]}},
        {"²": {"GPV1.1": {"1": "no"}}},
        {"9" * 30: {"GPV1.1": {"1": "no"}}},
    ],
    ids=[
        "days_are_text",
        "day_key_is_not_a_number",
        "hours_are_a_list",
        "day_key_is_a_superscript_digit",
        "day_key_is_out_of_range",
    ],
)
async def test_dtek_fact_of_another_shape_is_no_answer(
    hass, aioclient_mock, caplog, days
):
    """The entities keep the last schedule, and the entry reports no answer."""
    _serve_dtek(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    await _set_up(hass, entry)
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    _serve_dtek(aioclient_mock, _fact_with(days))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert coordinator.last_fetch_failed
    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert _errors(caplog) == []
    await _unload(hass, entry)


async def test_dtek_preset_of_another_shape_is_no_preset(hass, aioclient_mock, caplog):
    """A preset group of another shape drops the preset, not the entities."""
    preset = {"data": {"GPV1.1": None}}
    _serve_dtek(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)), preset)
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)

    await _set_up(hass, entry)

    states = _states(hass, entry)
    assert len(states) == 9
    assert [key for key, state in states.items() if state is None] == []
    assert entry.runtime_data.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert _errors(caplog) == []
    await _unload(hass, entry)


@pytest.mark.parametrize(
    "answer",
    [
        ["1.1"],
        {"1.1": "text"},
        {"1.1": {"today": {"slots": [{"start": "0", "end": 60, "type": "Definite"}]}}},
        {"1.1": {"today": {"slots": [{"start": 0, "end": 1500, "type": "Definite"}]}}},
        {"1.1": {"today": {"slots": [{"start": -60, "end": 60, "type": "Definite"}]}}},
        {"1.1": {"today": {"slots": [{"start": 120, "end": 60, "type": "Definite"}]}}},
    ],
    ids=[
        "list_with_the_group",
        "group_is_text",
        "slot_start_is_text",
        "slot_ends_after_the_day",
        "slot_starts_before_the_day",
        "slot_ends_before_it_starts",
    ],
)
async def test_yasno_answer_of_another_shape_is_no_answer(
    hass, aioclient_mock, caplog, answer
):
    """The entities keep the last schedule, and the entry reports no answer."""
    _serve_yasno(aioclient_mock, yasno_outage_all_day_today())
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    await _set_up(hass, entry)
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    _serve_yasno(aioclient_mock, answer)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert coordinator.last_fetch_failed
    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert _errors(caplog) == []
    await _unload(hass, entry)


async def test_e_svitlo_periods_of_another_shape_are_skipped(
    hass, aioclient_mock, caplog
):
    """An answer whose periods have another shape is an answer without outages."""
    e_svitlo_answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    await _set_up(hass, entry)
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    answer = e_svitlo_outage_all_day_today()
    answer["data"]["lst_time_disc"] = ["00:00-23:59", None]
    aioclient_mock.post(E_SVITLO_DISCONNECTIONS_URL, json=answer)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert not coordinator.last_fetch_failed
    assert coordinator.current_state == ConnectivityState.STATE_NORMAL
    assert _errors(caplog) == []
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("data", "source"),
    [
        (DTEK_KYIV_REGION_1_1, {"fact": ["odd"], "preset": {}}),
        (YASNO_KYIV_1_1, {"planned_outage_data": ["1.1"], "region": None}),
    ],
    ids=["dtek_fact_is_a_list", "yasno_outages_are_a_list"],
)
async def test_kept_data_of_another_shape_is_no_kept_data(
    hass, aioclient_mock, caplog, hass_storage, data, source
):
    """A store of another shape loads the entry without kept data."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    hass_storage[store_key(entry.entry_id)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(entry.entry_id),
        "data": {
            "source": source,
            "group": "1.1",
            "group_listed": None,
            "outage_data_last_changed": None,
        },
    }
    for url in KYIV_REGION_URLS:
        aioclient_mock.get(url, status=500)
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    aioclient_mock.get(YASNO_PLANNED_URL, status=500)

    await _set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.current_state == ConnectivityState.STATE_NORMAL
    assert _errors(caplog) == []
    await _unload(hass, entry)


async def test_dtek_feed_of_another_shape_aborts_the_setup(hass, aioclient_mock):
    """The config flow offers no groups that come from a fact of another shape."""
    _serve_dtek(aioclient_mock, _fact_with({"1": "GPV1.1"}))
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"provider": "dtekjsonprovider_kyiv_region"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "dtek_json_unavailable"
