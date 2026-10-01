"""The config flow and the entry setup on a real Home Assistant (the hass fixture)."""

import pytest
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
    PROVIDER_TYPE_YASNO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import PROVIDERS

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

KYIV_REGIONS = [{"id": 25, "value": "Київ", "dsos": [{"id": 902, "name": "ДТЕК"}]}]


def _planned_outages(*groups: str) -> dict:
    """Build a Yasno answer in which each group has a day without outages."""
    today = dt_utils.as_local(dt_utils.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    day = {"slots": [], "date": today.isoformat(), "status": "ScheduleApplies"}
    return {group: {"today": day, "updatedOn": today.isoformat()} for group in groups}


async def test_yasno_flow_creates_a_loaded_entry(hass, aioclient_mock):
    """The user picks a Yasno provider and a group, and the entry sets up."""
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
    "data",
    [
        {CONF_PROVIDER_TYPE: "unknown", CONF_GROUP: "1.1"},
        {CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON, CONF_GROUP: "1.1"},
        {CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON, CONF_PROVIDER: "kyiv_region"},
        {
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
            CONF_PROVIDER: 902,
            CONF_GROUP: "1.1",
        },
        {CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO, CONF_REGION: 25, CONF_GROUP: "1.1"},
        {CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO, CONF_REGION: 25, CONF_PROVIDER: 902},
    ],
    ids=[
        "unknown_provider_type",
        "dtek_without_provider",
        "dtek_without_group",
        "yasno_without_region",
        "yasno_without_provider",
        "yasno_without_group",
    ],
)
async def test_broken_entry_does_not_load(hass, data):
    """An entry without a setting that the config flow always writes stops its setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


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
