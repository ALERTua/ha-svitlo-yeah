"""
The button that checks the group of the address at once (silver action-exceptions).

The entries have the address in their data, as the config flow writes it. The
address requests of Yasno answer with the measured chain of Київ: the street
«вул. Сверстюка Євгена», the house 6 with its Cyrillic letter, the group 53.1.
"""

import logging
from unittest.mock import patch

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.api.yasno import AddressResult
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    DOMAIN,
    YASNO_ADDRESSES_ENDPOINT,
)
from tests.helpers import (
    PROVIDERS,
    YASNO_ENTRY_NOT_FOUND_REPLY,
    YASNO_GROUP_1_1_REPLY,
    YASNO_KYIV_1_1,
    YASNO_KYIV_ADDRESS_1_1,
    YASNO_KYIV_HOUSE,
    YASNO_KYIV_STREET,
    YASNO_NO_STREET_REPLY,
    YASNO_SERVER_ERROR_REPLY,
    yasno_address_answers,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

LOGGER_NAME = "custom_components.svitlo_yeah"
ADDRESS_TEXT = f"{YASNO_KYIV_STREET}, {YASNO_KYIV_HOUSE}"
# The ids that Home Assistant gives for the address entry
BUTTON_ID = "button.vul_sverstiuka_evgena_6a_update_group"
REFRESH_BUTTON_ID = "button.vul_sverstiuka_evgena_6a_force_refresh_now"
GROUP_SENSOR_ID = "sensor.vul_sverstiuka_evgena_6a_group"
ELECTRICITY_ID = "sensor.vul_sverstiuka_evgena_6a_electricity"


async def _start(
    hass, data: dict = YASNO_KYIV_ADDRESS_1_1, title: str = ADDRESS_TEXT
) -> MockConfigEntry:
    """Add an entry with this data, and set it up."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=title)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that its timers stop."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _press(hass, entity_id: str = BUTTON_ID) -> None:
    """Press the button, and wait for the reload that a new group starts."""
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def _button(hass, entry: MockConfigEntry, key: str) -> er.RegistryEntry | None:
    """Return the registry entry of a button of the entry, if the registry has it."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_{key}"
    )
    return registry.async_get(entity_id) if entity_id else None


def _address_requests(mock) -> list[str]:
    """Return the address endpoint of each request that went out, in order."""
    paths = [
        url.path.rsplit("/", 1)[-1]
        for _, url, _, _ in mock.mock_calls
        if str(url).startswith(YASNO_ADDRESSES_ENDPOINT)
    ]
    return [_ for _ in paths if _ != "regions"]


async def test_address_entry_has_the_button(hass, aioclient_mock):
    """A Yasno entry with an address has a button in the config category."""
    yasno_address_answers(aioclient_mock)

    entry = await _start(hass)

    button = _button(hass, entry, "check_group")
    assert button is not None
    assert button.entity_id == BUTTON_ID
    assert button.unique_id == f"{entry.entry_id}_check_group"
    assert button.entity_category is EntityCategory.CONFIG
    assert button.translation_key == "check_group"
    state = hass.states.get(BUTTON_ID)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    # The refresh button stays beside it
    assert _button(hass, entry, "refresh").entity_id == REFRESH_BUTTON_ID
    await _unload(hass, entry)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_entry_without_an_address_has_no_button(hass, aioclient_mock, provider):
    """A group entry of Yasno, and a DTEK or SOE entry, have none."""
    data, answers = PROVIDERS[provider]
    answers(aioclient_mock, answer=True)

    entry = await _start(hass, data, "Mock Title")

    assert _button(hass, entry, "check_group") is None
    assert _button(hass, entry, "refresh") is not None
    await _unload(hass, entry)


async def test_press_finds_the_same_group(hass, aioclient_mock, caplog):
    """The check finds the group of the entry: no error, and the group stays."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    yasno_address_answers(aioclient_mock, group=YASNO_GROUP_1_1_REPLY)
    entry = await _start(hass)
    coordinator = entry.runtime_data

    await _press(hass)

    assert _address_requests(aioclient_mock) == ["streets", "houses", "group"]
    assert coordinator.address_check_result is AddressResult.FOUND
    assert entry.data[CONF_GROUP] == "1.1"
    assert entry.runtime_data is coordinator
    assert hass.states.get(GROUP_SENSOR_ID).state == "1.1"
    # The log names the entry by its id, never by its address
    lines = [r.getMessage() for r in caplog.records if r.name.startswith(LOGGER_NAME)]
    assert f"Manual check of the group requested for entry {entry.entry_id}" in lines
    assert [_ for _ in lines if "Сверстюка" in _ or YASNO_KYIV_HOUSE in _] == []
    await _unload(hass, entry)


async def test_press_switches_to_a_new_group_at_once(hass, aioclient_mock):
    """
    The press skips the second check: the entry gets the new group, and no error.

    The update listener reloads the entry, and the group sensor shows the new group.
    """
    yasno_address_answers(aioclient_mock)
    entry = await _start(hass)
    coordinator = entry.runtime_data
    assert hass.states.get(GROUP_SENSOR_ID).state == "1.1"

    await _press(hass)

    assert entry.data[CONF_GROUP] == "53.1"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not coordinator
    assert hass.states.get(GROUP_SENSOR_ID).state == "53.1"
    # The reloaded entry has its button again, with the same id
    assert _button(hass, entry, "check_group").entity_id == BUTTON_ID
    assert hass.states.get(BUTTON_ID).state != STATE_UNAVAILABLE
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("replies", "translation_key"),
    [
        pytest.param(
            {"group": YASNO_SERVER_ERROR_REPLY},
            "check_group_failed",
            id="group_server_error",
        ),
        pytest.param(
            {"streets": YASNO_SERVER_ERROR_REPLY},
            "check_group_failed",
            id="street_server_error",
        ),
        pytest.param(
            {"streets": {"exc": ClientError()}},
            "check_group_failed",
            id="no_connection",
        ),
        pytest.param(
            {"streets": YASNO_NO_STREET_REPLY},
            "address_not_found",
            id="no_such_street",
        ),
        pytest.param(
            {"group": YASNO_ENTRY_NOT_FOUND_REPLY},
            "address_not_found",
            id="group_not_found",
        ),
    ],
)
async def test_press_without_a_sure_group_fails_and_keeps_the_states(
    hass, aioclient_mock, replies, translation_key
):
    """
    A press that gets no group fails with a translated error.

    No answer is Unknown, and an address that Yasno does not know is Not found.
    The entry keeps its group, and the entities keep their states.
    """
    yasno_address_answers(aioclient_mock)
    entry = await _start(hass)
    aioclient_mock.clear_requests()
    yasno_address_answers(aioclient_mock, **replies)
    coordinator = entry.runtime_data

    with pytest.raises(HomeAssistantError) as error:
        await _press(hass)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == translation_key
    assert entry.data[CONF_GROUP] == "1.1"
    assert entry.runtime_data is coordinator
    assert hass.states.get(GROUP_SENSOR_ID).state == "1.1"
    for entity_id in (ELECTRICITY_ID, BUTTON_ID):
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
    await _unload(hass, entry)


async def test_poll_that_stops_before_the_check_fails_the_press(hass, aioclient_mock):
    """The press does not count the result of an earlier check as its own."""
    yasno_address_answers(aioclient_mock, group=YASNO_GROUP_1_1_REPLY)
    entry = await _start(hass)
    coordinator = entry.runtime_data
    await _press(hass)
    assert coordinator.address_check_result is AddressResult.FOUND

    with (
        patch.object(
            coordinator, "_async_use_answer", side_effect=RuntimeError("broken")
        ),
        pytest.raises(HomeAssistantError) as error,
    ):
        await _press(hass)

    assert error.value.translation_key == "check_group_failed"
    assert coordinator.address_check_result is None
    await _unload(hass, entry)


async def test_group_entry_loses_a_kept_button_at_the_setup(hass, aioclient_mock):
    """The registry has a button of an address that the entry does not have any more."""
    yasno_address_answers(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1, title="Mock Title")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    kept = registry.async_get_or_create(
        "button",
        DOMAIN,
        f"{entry.entry_id}_check_group",
        config_entry=entry,
        suggested_object_id="kiiv_dtek_1_1_update_group",
    )
    assert registry.async_get(kept.entity_id) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(kept.entity_id) is None
    assert hass.states.get(kept.entity_id) is None
    assert _button(hass, entry, "refresh") is not None
    await _unload(hass, entry)


async def test_reconfigure_that_removes_the_address_removes_the_button(
    hass, aioclient_mock, caplog
):
    """
    A Reconfigure back to a group takes the button away, and keeps the other entities.

    The entry data loses the address, and the update listener reloads the entry.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    yasno_address_answers(aioclient_mock)
    entry = await _start(hass)
    assert hass.states.get(BUTTON_ID) is not None

    hass.config_entries.async_update_entry(entry, data=YASNO_KYIV_1_1)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert _button(hass, entry, "check_group") is None
    assert hass.states.get(BUTTON_ID) is None
    assert _button(hass, entry, "refresh") is not None
    # The entity ids that the address gave stay
    assert hass.states.get(ELECTRICITY_ID) is not None
    assert hass.states.get(GROUP_SENSOR_ID).state == "1.1"
    # The entity id of the button has the address, so the log never has it
    lines = [r.getMessage() for r in caplog.records if r.name.startswith(LOGGER_NAME)]
    assert f"Remove the group button of entry {entry.entry_id}" in lines
    assert [_ for _ in lines if "Сверстюка" in _ or "sverstiuka" in _] == []
    await _unload(hass, entry)
