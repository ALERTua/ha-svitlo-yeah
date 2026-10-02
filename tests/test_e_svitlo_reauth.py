"""
E-Svitlo refuses the login (silver reauthentication-flow).

One reauthentication starts, the old states stay, and the polls go on.
"""

import logging
from unittest.mock import patch

import pytest
from aiohttp import ClientError
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
    E_SVITLO_ACCOUNTS_URL,
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
    """
    A refused login starts one reauthentication.

    The next poll that logs in heals the entry.
    """
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
    """
    A refused login at the first start loads the entry.

    It starts one reauthentication.
    """
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    _refuse_the_login(aioclient_mock)

    entry = await _set_up(hass)

    assert len(_reauth_flows(hass)) == 1
    assert _messages(caplog, logging.WARNING, "refused the login") == 1
    assert _messages(caplog, logging.INFO, "does not answer") == 0
    await _unload(hass, entry)


async def test_server_that_stops_answering_after_a_refusal_does_not_answer(
    hass, aioclient_mock, caplog
):
    """
    After a refused login, a server without any answer counts as no answer.

    The open reauthentication stays, and the next login that works closes it.
    """
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    e_svitlo_answers(aioclient_mock, answer=True)
    entry = await _set_up(hass)
    coordinator = entry.runtime_data
    electricity = _entity_id(hass, entry, "sensor", "electricity")

    aioclient_mock.clear_requests()
    _refuse_the_login(aioclient_mock)
    await coordinator.async_refresh()
    assert (coordinator.login_rejected, coordinator.last_fetch_failed) == (True, False)

    aioclient_mock.clear_requests()
    for url in (E_SVITLO_LOGIN_URL, E_SVITLO_DETAILS_URL, E_SVITLO_DISCONNECTIONS_URL):
        aioclient_mock.post(url, exc=ClientError())
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert (coordinator.login_rejected, coordinator.last_fetch_failed) == (True, True)
    assert _messages(caplog, logging.INFO, "does not answer") == 1
    assert len(_reauth_flows(hass)) == 1
    assert hass.states.get(electricity).state == ConnectivityState.STATE_PLANNED_OUTAGE
    # The press got no answer, so its error tells that, not the earlier refusal
    with pytest.raises(HomeAssistantError) as error:
        await _press(hass, entry)
    assert error.value.translation_key == "refresh_failed"

    aioclient_mock.clear_requests()
    e_svitlo_answers(aioclient_mock, answer=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert (coordinator.login_rejected, coordinator.last_fetch_failed) == (False, False)
    assert _messages(caplog, logging.INFO, "answers again") == 1
    assert _reauth_flows(hass) == []
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("password", "reloads"),
    [("new secret", 1), (E_SVITLO_ACCOUNT_101["password"], 0)],
    ids=["new_login", "same_login"],
)
async def test_reauth_reloads_a_loaded_entry_only_for_a_new_login(
    hass, aioclient_mock, caplog, password, reloads
):
    """
    A new login reloads the entry once, through its update listener.

    The same login changes nothing. Home Assistant reports no misuse of the listener.
    """
    e_svitlo_answers(aioclient_mock, answer=True)
    aioclient_mock.post(
        E_SVITLO_ACCOUNTS_URL, json={"data": {"lst_ls": [{"a": "101"}]}}
    )
    entry = await _set_up(hass)
    coordinator = entry.runtime_data
    calls = []
    real_reload = hass.config_entries.async_reload

    async def counting_reload(entry_id: str) -> bool:
        calls.append(entry_id)
        return await real_reload(entry_id)

    with patch.object(hass.config_entries, "async_reload", counting_reload):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": E_SVITLO_ACCOUNT_101["username"], "password": password},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == password
    assert len(calls) == reloads
    assert (entry.runtime_data is coordinator) == (reloads == 0)
    assert entry.state is ConfigEntryState.LOADED
    assert not [r for r in caplog.records if "update listener" in r.getMessage()]
    await _unload(hass, entry)
