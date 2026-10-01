"""E-Svitlo refuses the login: one reauthentication, the old states stay, the polls go on (silver reauthentication-flow)."""

import logging

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    DOMAIN,
    E_SVITLO_ERROR_NOT_LOGGED_IN,
)
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import (
    E_SVITLO_ACCOUNT_101,
    E_SVITLO_DETAILS_URL,
    E_SVITLO_DISCONNECTIONS_URL,
    E_SVITLO_LOGIN_URL,
    e_svitlo_answers,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

INTEGRATION_LOGGER = "custom_components.svitlo_yeah"


def _refuse_the_login(aioclient_mock) -> None:
    """End the session of the client, and refuse each new login."""
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": False}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    aioclient_mock.post(
        E_SVITLO_DISCONNECTIONS_URL,
        json={"error": {"err": E_SVITLO_ERROR_NOT_LOGGED_IN}},
    )


def _reauth_flows(hass) -> list:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


def _login_requests(aioclient_mock) -> int:
    return sum(str(call[1]) == E_SVITLO_LOGIN_URL for call in aioclient_mock.mock_calls)


def _messages(caplog, level: int, text: str) -> int:
    return sum(
        r.name.startswith(INTEGRATION_LOGGER)
        and r.levelno == level
        and text in r.getMessage()
        for r in caplog.records
    )


def _entity_id(hass, entry: MockConfigEntry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id
    return entity_id


async def _press(hass, entry: MockConfigEntry) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity_id(hass, entry, "button", "refresh")},
        blocking=True,
    )


async def _set_up(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _unload(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_refused_login_asks_once_keeps_the_states_and_polls_on(
    hass, aioclient_mock, caplog
):
    """A refused login starts one reauthentication; the next poll that logs in heals the entry."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    e_svitlo_answers(aioclient_mock, answer=True)
    entry = await _set_up(hass)
    coordinator = entry.runtime_data
    electricity = _entity_id(hass, entry, "sensor", "electricity")

    aioclient_mock.clear_requests()
    _refuse_the_login(aioclient_mock)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(_reauth_flows(hass)) == 1
    assert _messages(caplog, logging.WARNING, "refused the login") == 1
    assert _messages(caplog, logging.ERROR, "") == 0
    assert _messages(caplog, logging.INFO, "does not answer") == 0
    assert _login_requests(aioclient_mock) >= 2  # each poll tries the old login
    assert hass.states.get(electricity).state == ConnectivityState.STATE_PLANNED_OUTAGE
    with pytest.raises(HomeAssistantError) as error:
        await _press(hass, entry)
    assert error.value.translation_key == "login_rejected"

    # Another entry waits for its own new login
    other = MockConfigEntry(
        domain=DOMAIN, data={**E_SVITLO_ACCOUNT_101, CONF_ACCOUNT_ID: "102"}
    )
    other.add_to_hass(hass)
    await other.start_reauth_flow(hass)

    aioclient_mock.clear_requests()
    e_svitlo_answers(aioclient_mock, answer=True)
    await coordinator.async_refresh()

    assert _messages(caplog, logging.INFO, "accepts the login") == 1
    assert not coordinator.login_rejected
    # The working login needs no new one, the other entry still does
    assert [f["context"]["entry_id"] for f in _reauth_flows(hass)] == [other.entry_id]
    await _press(hass, entry)
    await _unload(hass, entry)


async def test_refused_login_at_the_first_start_asks_once(hass, aioclient_mock, caplog):
    """A refused login at the first start loads the entry and starts one reauthentication."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    _refuse_the_login(aioclient_mock)

    entry = await _set_up(hass)

    assert len(_reauth_flows(hass)) == 1
    assert _messages(caplog, logging.WARNING, "refused the login") == 1
    assert _messages(caplog, logging.INFO, "does not answer") == 0
    await _unload(hass, entry)
