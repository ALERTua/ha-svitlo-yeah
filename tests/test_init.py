"""The config flow and the entry setup on a real Home Assistant (the hass fixture)."""

import logging

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah import button, calendar, sensor
from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.coordinator.dtek.json import DtekCoordinatorJson
from custom_components.svitlo_yeah.coordinator.yasno import YasnoCoordinator
from tests.helpers import (
    E_SVITLO_ACCOUNT_101,
    PROVIDERS,
    YASNO_PLANNED_URL,
    e_svitlo_answers,
    kyiv_midnight,
    yasno_outage_all_day_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

KYIV_REGIONS = [{"id": 25, "value": "Київ", "dsos": [{"id": 902, "name": "ДТЕК"}]}]
INTEGRATION_LOGGER = "custom_components.svitlo_yeah"


def _planned_outages(*groups: str) -> dict:
    """Build a Yasno answer in which each group has a day without outages."""
    today = kyiv_midnight()
    day = {"slots": [], "date": today.isoformat(), "status": "ScheduleApplies"}
    return {group: {"today": day, "updatedOn": today.isoformat()} for group in groups}


async def test_yasno_flow_creates_a_loaded_entry(hass, aioclient_mock, caplog):
    """
    The user picks a Yasno provider and a group, and the entry sets up.

    The flow, the setup and the unload are not news for the user, so the
    integration writes no info line on the way.
    """
    caplog.set_level(logging.INFO, logger=INTEGRATION_LOGGER)
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=KYIV_REGIONS)
    aioclient_mock.get(
        YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=25, dso_id=902),
        json=_planned_outages("1.1", "1.2"),
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROVIDER: "yasnoprovider_25_902"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "group"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GROUP: "1.1"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.kiiv_dtek_1_1_electricity").state == "normal"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    assert [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith(INTEGRATION_LOGGER) and r.levelno >= logging.INFO
    ] == []


async def test_device_without_a_provider_logs_from_the_entity_module(
    hass, aioclient_mock, caplog
):
    """
    Without the Yasno regions the device has no provider name.

    entity.py says so in its own log.
    """
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
    aioclient_mock.get(YASNO_PLANNED_URL, json=yasno_outage_all_day_today())
    entry = MockConfigEntry(domain=DOMAIN, data=PROVIDERS["yasno"][0])
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    records = [
        r for r in caplog.records if "Device info without a provider" in r.getMessage()
    ]
    assert records
    assert {r.name for r in records} == {"custom_components.svitlo_yeah.entity"}
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_each_e_svitlo_entry_logs_in_with_its_own_session(hass, aioclient_mock):
    """
    Two E-Svitlo accounts do not share the cookies of one login.

    The shared session of Home Assistant keeps the cookies of all integrations.
    """
    e_svitlo_answers(aioclient_mock, answer=True)
    entries = []
    for account in ("101", "102"):
        entry = MockConfigEntry(
            domain=DOMAIN, data={**E_SVITLO_ACCOUNT_101, CONF_ACCOUNT_ID: account}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        entries.append(entry)
    await hass.async_block_till_done()

    first, second = (entry.runtime_data.api.session for entry in entries)
    assert first is not second
    assert async_get_clientsession(hass) not in (first, second)
    for entry in entries:
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_only_the_button_limits_parallel_calls(hass, aioclient_mock):
    """
    The presses of an entry run one after another.

    The read-only platforms set no limit.
    """
    data, answers = PROVIDERS["dtek"]
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    limits = {
        platform.domain: platform.parallel_updates
        for platform in entity_platform.async_get_platforms(hass, DOMAIN)
        if platform.config_entry is entry
    }

    # Silver parallel-updates wants the value set in each platform, also the default 0
    assert (sensor.PARALLEL_UPDATES, calendar.PARALLEL_UPDATES) == (0, 0)
    assert button.PARALLEL_UPDATES == 1
    assert set(limits) == {"sensor", "calendar", "button"}
    assert limits["sensor"] is None
    assert limits["calendar"] is None
    assert limits["button"]._value == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({CONF_GROUP: "1.1"}, "unknown_provider_type"),
        ({CONF_PROVIDER_TYPE: "unknown", CONF_GROUP: "1.1"}, "unknown_provider_type"),
        (
            {CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON, CONF_GROUP: "1.1"},
            "entry_without_provider",
        ),
        (
            {CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON, CONF_PROVIDER: "kyiv_region"},
            "entry_without_group",
        ),
        (
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
                CONF_PROVIDER: "removed_region",
                CONF_GROUP: "1.1",
            },
            "unknown_dtek_provider",
        ),
        (
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
                CONF_PROVIDER: 902,
                CONF_GROUP: "1.1",
            },
            "entry_without_region",
        ),
        (
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
                CONF_REGION: 25,
                CONF_GROUP: "1.1",
            },
            "entry_without_provider",
        ),
        (
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
                CONF_REGION: 25,
                CONF_PROVIDER: 902,
            },
            "entry_without_group",
        ),
        (
            {CONF_PROVIDER_TYPE: PROVIDER_TYPE_E_SVITLO, CONF_PROVIDER: "sumy"},
            "entry_without_login",
        ),
    ],
    ids=[
        "no_provider_type",
        "unknown_provider_type",
        "dtek_without_provider",
        "dtek_without_group",
        "dtek_unknown_source",
        "yasno_without_region",
        "yasno_without_provider",
        "yasno_without_group",
        "e_svitlo_without_login",
    ],
)
async def test_broken_entry_stops_with_a_translated_error(hass, data, error):
    """
    An entry that cannot work stops its setup.

    It tells the user why, in the language of the user.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == error


async def test_changed_data_reload_the_entry(hass, aioclient_mock):
    """
    A change of the data of an entry sets it up again with a new coordinator.

    Reconfigure writes the new group into the data and relies on this reload.
    """
    data, answers = PROVIDERS["dtek"]
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old_coordinator = entry.runtime_data

    hass.config_entries.async_update_entry(entry, data={**data, CONF_GROUP: "1.2"})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_coordinator
    assert entry.runtime_data.group == "1.2"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("provider", "coordinator_class", "options"),
    [
        (
            "dtek",
            DtekCoordinatorJson,
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
                CONF_PROVIDER: "dnipro",
                CONF_GROUP: "9.9",
            },
        ),
        (
            "yasno",
            YasnoCoordinator,
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
                CONF_REGION: 3,
                CONF_PROVIDER: 301,
                CONF_GROUP: "9.9",
            },
        ),
    ],
    ids=["dtek", "yasno"],
)
async def test_settings_come_from_the_data_only(
    hass, aioclient_mock, provider, coordinator_class, options
):
    """
    The options of an entry change nothing.

    Only the options flow of 0.5.0 and 0.5.1 wrote options, and such entries
    have no provider type, so they cannot load since 0.5.7.
    """
    data, answers = PROVIDERS[provider]
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert isinstance(coordinator, coordinator_class)
    assert (coordinator.provider_id, coordinator.group) == (
        data[CONF_PROVIDER],
        data[CONF_GROUP],
    )
    assert getattr(coordinator, "region_id", None) == data.get(CONF_REGION)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
