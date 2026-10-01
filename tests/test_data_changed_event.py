"""A changed schedule fires svitlo_yeah_data_changed with the data of the entry."""

from datetime import UTC, datetime

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.svitlo_yeah.const import DOMAIN, EVENT_DATA_CHANGED
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    dtek_answers,
    fact_with_an_outage_today,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


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
