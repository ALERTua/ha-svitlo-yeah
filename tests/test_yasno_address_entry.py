"""A Yasno entry with an address: the names of its device and entities, and its log."""

import logging

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import (
    CONF_HOUSE,
    DEVICE_MANUFACTURER,
    DOMAIN,
)
from tests.helpers import (
    YASNO_KYIV_1_1,
    YASNO_KYIV_ADDRESS_1_1,
    YASNO_KYIV_HOUSE,
    YASNO_KYIV_STREET,
    yasno_answers,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

LOGGER_NAME = "custom_components.svitlo_yeah"
# The street and the house 6 with its Cyrillic letter: the name of the device, and the
# title of the entry
ADDRESS_TEXT = f"{YASNO_KYIV_STREET}, {YASNO_KYIV_HOUSE}"
# The entity ids that Home Assistant gives for this address, and for the group 1.1
ADDRESS_ENTITY_IDS = {
    "button.vul_sverstiuka_evgena_6a_force_refresh_now",
    "button.vul_sverstiuka_evgena_6a_update_group",
    "calendar.vul_sverstiuka_evgena_6a_planned_outages",
    "calendar.vul_sverstiuka_evgena_6a_scheduled_outages",
    "sensor.vul_sverstiuka_evgena_6a_electricity",
    "sensor.vul_sverstiuka_evgena_6a_group",
    "sensor.vul_sverstiuka_evgena_6a_next_connectivity",
    "sensor.vul_sverstiuka_evgena_6a_next_planned_outage",
    "sensor.vul_sverstiuka_evgena_6a_next_scheduled_outage",
    "sensor.vul_sverstiuka_evgena_6a_schedule_data_changed_on",
    "sensor.vul_sverstiuka_evgena_6a_schedule_updated_on",
}
# The ids of a group entry from before the group sensor. They must not change: a user
# has automations and dashboards that name them.
GROUP_ENTITY_IDS = {
    "button.kiiv_dtek_1_1_force_refresh_now",
    "calendar.kiiv_dtek_1_1_planned_outages",
    "calendar.kiiv_dtek_1_1_scheduled_outages",
    "sensor.kiiv_dtek_1_1_electricity",
    "sensor.kiiv_dtek_1_1_next_connectivity",
    "sensor.kiiv_dtek_1_1_next_planned_outage",
    "sensor.kiiv_dtek_1_1_next_scheduled_outage",
    "sensor.kiiv_dtek_1_1_schedule_data_changed_on",
    "sensor.kiiv_dtek_1_1_schedule_updated_on",
}
# The only new entity of a group entry: the group sensor
GROUP_SENSOR_ID = "sensor.kiiv_dtek_1_1_group"


async def _start(hass, data: dict, title: str = "Mock Title") -> MockConfigEntry:
    """Add an entry with this data, and set it up."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=title)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that its timers stop."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _device(hass, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Return the device of the entry."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    return device


def _entity_ids(hass, entry: MockConfigEntry) -> set[str]:
    """Return the entity ids that the registry has for the entry."""
    return {
        _.entity_id
        for _ in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_device_has_the_address_as_its_name(hass, aioclient_mock):
    """The device of an address is named by the address: no region, no group."""
    yasno_answers(aioclient_mock, answer=True)

    entry = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)

    device = _device(hass, entry)
    assert device.name == ADDRESS_TEXT
    assert device.manufacturer == DEVICE_MANUFACTURER
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.name_by_user is None
    await _unload(hass, entry)


async def test_entity_ids_come_from_the_address(hass, aioclient_mock):
    """
    Each entity id of a new address entry has the address, the calendars too.

    Home Assistant gave `sensor.vul_sverstiuka_evgena_6a_electricity` for the
    sensor of the entry. The group of the address is in no id.
    """
    yasno_answers(aioclient_mock, answer=True)

    entry = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)

    assert _entity_ids(hass, entry) == ADDRESS_ENTITY_IDS
    assert hass.states.get("sensor.vul_sverstiuka_evgena_6a_electricity") is not None
    assert hass.states.get("calendar.vul_sverstiuka_evgena_6a_planned_outages")
    assert hass.states.get("calendar.vul_sverstiuka_evgena_6a_scheduled_outages")
    await _unload(hass, entry)


async def test_group_entry_keeps_its_device_name_and_entity_ids(hass, aioclient_mock):
    """
    An entry with a group only has the names that it had before addresses.

    The entity ids that it had stay, and it has the group sensor besides them. It has
    no button that checks an address.
    """
    yasno_answers(aioclient_mock, answer=True)

    entry = await _start(hass, YASNO_KYIV_1_1, "Київ ДТЕК 1.1")

    assert _device(hass, entry).name == "Київ ДТЕК 1.1"
    assert _entity_ids(hass, entry) == GROUP_ENTITY_IDS | {GROUP_SENSOR_ID}
    await _unload(hass, entry)


async def test_two_addresses_in_one_group_have_their_own_ids(hass, aioclient_mock):
    """The group is in no id, so two addresses of one group never share an id."""
    yasno_answers(aioclient_mock, answer=True)
    other_data = {**YASNO_KYIV_ADDRESS_1_1, CONF_HOUSE: "2"}

    first = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)
    second = await _start(hass, other_data, f"{YASNO_KYIV_STREET}, 2")

    assert _device(hass, second).name == f"{YASNO_KYIV_STREET}, 2"
    assert _entity_ids(hass, first) == ADDRESS_ENTITY_IDS
    assert _entity_ids(hass, second) == {
        entity_id.replace("_6a_", "_2_") for entity_id in ADDRESS_ENTITY_IDS
    }
    await _unload(hass, first)
    await _unload(hass, second)


async def test_debug_log_has_no_address(hass, aioclient_mock, caplog):
    """The log lines of the setup and the unload name the entry by its id."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    yasno_answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(
        domain=DOMAIN, data=YASNO_KYIV_ADDRESS_1_1, title=ADDRESS_TEXT
    )
    entry.add_to_hass(hass)
    # The entry shows its title in its text, so a log line of the entry could show it
    assert "Сверстюка" in repr(entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _unload(hass, entry)

    lines = [_.getMessage() for _ in caplog.records if _.name.startswith(LOGGER_NAME)]
    # The platforms and the entry wrote their lines, each with the id of the entry
    for text in (
        "Setup entry",
        "Setup new sensor",
        "Setup new button",
        "Setup new calendar entry",
        "Unload entry",
    ):
        assert f"{text}: {entry.entry_id}" in lines
    assert [_ for _ in lines if "Сверстюка" in _] == []
