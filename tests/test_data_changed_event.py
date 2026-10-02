"""A changed schedule fires svitlo_yeah_data_changed with the data of the entry."""

from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.svitlo_yeah.const import (
    DOMAIN,
    EVENT_DATA_CHANGED,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
    dtek_answers,
    fact_with_an_outage_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


def _yasno_outage_today(start_minute: int, end_minute: int) -> dict:
    """Build a Yasno answer with one outage of group 1.1 today."""
    today = dt_utils.start_of_local_day()
    day = {
        "slots": [{"start": start_minute, "end": end_minute, "type": "Definite"}],
        "date": today.isoformat(),
        "status": "ScheduleApplies",
    }
    return {"1.1": {"today": day, "updatedOn": today.isoformat()}}


async def test_changed_dtek_schedule_names_the_region_and_the_group(
    hass, aioclient_mock
):
    """The event of a DTEK entry names its region key, its group and the entry."""
    dtek_answers(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))
    entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    changes = async_capture_events(hass, EVENT_DATA_CHANGED)

    # The outage of today is gone from the source
    fact = fact_with_an_outage_today(datetime.now(UTC))
    for day in fact["data"].values():
        day["GPV1.1"] = {str(hour): "yes" for hour in range(1, 25)}
    aioclient_mock.clear_requests()
    dtek_answers(aioclient_mock, fact)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(changes) == 1
    data = changes[0].data
    assert (data["region_name"], data["group"], data["config_entry_id"]) == (
        "kyiv_region",
        "1.1",
        entry.entry_id,
    )
    assert data["last_data_change"] is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_changed_yasno_schedule_without_the_regions(
    hass, aioclient_mock, freezer
):
    """
    A Yasno entry without its region names the event with None, and stays available.

    While the regions request fails, the entry has no provider.
    """
    freezer.move_to(dt_utils.start_of_local_day() + timedelta(hours=9))
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
    aioclient_mock.get(YASNO_PLANNED_URL, json=_yasno_outage_today(600, 720))
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    changes = async_capture_events(hass, EVENT_DATA_CHANGED)

    # The outage starts one hour earlier
    aioclient_mock.clear_requests()
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
    aioclient_mock.get(YASNO_PLANNED_URL, json=_yasno_outage_today(540, 720))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.last_update_success
    assert len(changes) == 1
    assert changes[0].data["region_name"] is None
    electricity = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_electricity"
    )
    assert hass.states.get(electricity).state != "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
