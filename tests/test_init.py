"""The config flow and the entry setup on a real Home Assistant (the hass fixture)."""

import logging

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_platform
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah import button, calendar, sensor
from custom_components.svitlo_yeah.const import (
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
from tests.helpers import PROVIDERS, YASNO_PLANNED_URL, yasno_outage_all_day_today

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

KYIV_REGIONS = [{"id": 25, "value": "Київ", "dsos": [{"id": 902, "name": "ДТЕК"}]}]
INTEGRATION_LOGGER = "custom_components.svitlo_yeah"


def _planned_outages(*groups: str) -> dict:
    """Build a Yasno answer in which each group has a day without outages."""
    today = dt_utils.as_local(dt_utils.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
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
    """Without the Yasno regions the device has no provider name, and entity.py says so in its own log."""
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


async def test_only_the_button_limits_parallel_calls(hass, aioclient_mock):
    """The presses of an entry run one after another; the read-only platforms set no limit."""
    data, answers = PROVIDERS["dtek"]
    answers(aioclient_mock, True)
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
    """An entry that cannot work stops its setup and tells the user why, in the user's language."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == error


async def test_changed_options_reload_the_entry(hass, aioclient_mock):
    """A change of the options of an entry sets it up again with a new coordinator."""
    data, answers = PROVIDERS["dtek"]
    answers(aioclient_mock, True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old_coordinator = entry.runtime_data

    hass.config_entries.async_update_entry(entry, options={CONF_GROUP: "1.1"})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_coordinator
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
