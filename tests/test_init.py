"""The config flow and the entry setup on a real Home Assistant (the hass fixture)."""

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    DOMAIN,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)

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
