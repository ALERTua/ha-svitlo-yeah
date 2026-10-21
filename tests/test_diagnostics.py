"""The diagnostics of an entry help a bug report (gold diagnostics)."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.svitlo_yeah.const import DOMAIN
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import PROVIDERS

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


async def _diagnostics(hass, hass_client, aioclient_mock, provider: str) -> dict:
    data, answers = PROVIDERS[provider]
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await get_diagnostics_for_config_entry(hass, hass_client, entry)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_diagnostics_show_what_the_coordinator_knows(
    hass, hass_client, aioclient_mock, provider
):
    """The diagnostics show the state, the flags and the outage of today."""
    result = await _diagnostics(hass, hass_client, aioclient_mock, provider)

    coordinator = result["coordinator"]
    assert coordinator["current_state"] == ConnectivityState.STATE_PLANNED_OUTAGE
    assert coordinator["last_update_success"] is True
    assert coordinator["last_exception"] is None
    assert coordinator["last_fetch_failed"] is False
    assert coordinator["schedule_updated_on"] is not None
    assert len(result["events"]) == 1
    assert result["events"][0]["start"] is not None
    assert isinstance(result["scheduled_events"], list)
