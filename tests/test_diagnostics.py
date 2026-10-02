"""
The diagnostics of an entry help a bug report (gold diagnostics).

They keep the personal data out.
"""

import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.svitlo_yeah.const import DOMAIN
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import E_SVITLO_ACCOUNT_101, PROVIDERS

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

REDACTED = "**REDACTED**"


async def _diagnostics(
    hass, hass_client, aioclient_mock, provider: str, **data_changes
) -> dict:
    data, answers = PROVIDERS[provider]
    data = {**data, **data_changes}
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await get_diagnostics_for_config_entry(hass, hass_client, entry)


async def test_e_svitlo_diagnostics_keep_the_personal_data_out(
    hass, hass_client, aioclient_mock
):
    """The login, the password, the personal account and its address are redacted."""
    # A login that no key of the diagnostics contains
    login = {"username": "petro.sumy@example.com"}
    result = await _diagnostics(hass, hass_client, aioclient_mock, "e_svitlo", **login)

    data = result["entry"]["data"]
    assert {key: data[key] for key in ("username", "password", "account_id")} == {
        "username": REDACTED,
        "password": REDACTED,
        "account_id": REDACTED,
    }
    assert data["address_str"] == REDACTED
    assert data["provider"] == "sumy"
    text = json.dumps(result, ensure_ascii=False)
    personal = {**E_SVITLO_ACCOUNT_101, **login}
    for secret in ("password", "address_str", "username"):
        assert personal[secret] not in text
    assert result["coordinator"]["group"] == "4.1"


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
    assert coordinator["login_rejected"] is False
    assert coordinator["schedule_updated_on"] is not None
    assert len(result["events"]) == 1
    assert result["events"][0]["start"] is not None
    assert isinstance(result["scheduled_events"], list)
