"""The diagnostics of an entry help a bug report (gold diagnostics)."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_HOUSE,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_STREET,
    DOMAIN,
)
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import PROVIDERS, REMOVED_E_SVITLO_ENTRY

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


# The login and the account of an entry of the removed E-Svitlo provider
E_SVITLO_LOGIN = {
    key: value
    for key, value in REMOVED_E_SVITLO_ENTRY.items()
    if key not in (CONF_PROVIDER_TYPE, CONF_PROVIDER)
}


async def _diagnostics(
    hass, hass_client, aioclient_mock, provider: str, extra: dict | None = None
) -> dict:
    data, answers = PROVIDERS[provider]
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data={**data, **(extra or {})})
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


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_diagnostics_hide_the_login_of_an_old_e_svitlo_entry(
    hass, hass_client, aioclient_mock, provider
):
    """The data of an entry of the removed E-Svitlo provider never shows its login."""
    result = await _diagnostics(
        hass, hass_client, aioclient_mock, provider, E_SVITLO_LOGIN
    )

    data = result["entry"]["data"]
    assert {key: data[key] for key in E_SVITLO_LOGIN} == dict.fromkeys(
        E_SVITLO_LOGIN, "**REDACTED**"
    )
    # A short value, such as the account number, can be a part of a time by chance
    texts = [_ for _ in E_SVITLO_LOGIN.values() if len(_) > len("user")]
    assert texts
    assert not [_ for _ in texts if _ in str(result)]


async def test_diagnostics_hide_the_address_of_an_entry_with_a_city(
    hass, hass_client, aioclient_mock
):
    """The city, the street and the house of an address entry never show."""
    address = {CONF_CITY: "м. Тестове", CONF_STREET: "вул. Тестова", CONF_HOUSE: "77Б"}

    result = await _diagnostics(hass, hass_client, aioclient_mock, "yasno", address)

    data = result["entry"]["data"]
    assert {key: data[key] for key in address} == dict.fromkeys(address, "**REDACTED**")
    assert not [_ for _ in address.values() if _ in str(result)]


async def test_diagnostics_of_an_entry_that_never_loaded(hass, hass_client):
    """
    An old E-Svitlo entry stops at its setup, so it has no coordinator.

    Its diagnostics have the entry settings only, and its login stays hidden.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=REMOVED_E_SVITLO_ENTRY, title="Old")
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    login = dict.fromkeys(E_SVITLO_LOGIN, "**REDACTED**")
    assert result == {
        "entry": {"data": {**REMOVED_E_SVITLO_ENTRY, **login}, "options": {}}
    }
