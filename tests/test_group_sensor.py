"""
The group sensor: a diagnostic sensor that each Yasno entry has.

The integration enables it on an entry with an address, because only an address can
give the entry a new group. It disables it on a group entry, and enables it again when
a Reconfigure gives that entry an address.
"""

import logging
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.svitlo_yeah.const import CONF_GROUP, DOMAIN
from tests.helpers import (
    PROVIDERS,
    YASNO_GROUP_1_1_REPLY,
    YASNO_KYIV_1_1,
    YASNO_KYIV_ADDRESS_1_1,
    YASNO_KYIV_HOUSE,
    YASNO_KYIV_STREET,
    yasno_address_answers,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

LOGGER_NAME = "custom_components.svitlo_yeah"
ADDRESS_TEXT = f"{YASNO_KYIV_STREET}, {YASNO_KYIV_HOUSE}"
# The ids that Home Assistant gave in the registry, read once and pinned here
GROUP_ENTRY_SENSOR_ID = "sensor.kiiv_dtek_1_1_group"
ADDRESS_ENTRY_SENSOR_ID = "sensor.vul_sverstiuka_evgena_6a_group"
# Home Assistant reloads an entry this long after an entity of it got enabled
RELOAD_AFTER_ENABLE = timedelta(seconds=30)


def _add(hass, data: dict, title: str = "Mock Title") -> MockConfigEntry:
    """Add an entry with this data, and leave it without a setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=title)
    entry.add_to_hass(hass)
    return entry


async def _setup(hass, entry: MockConfigEntry) -> None:
    """Set up the entry."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _start(hass, data: dict, title: str = "Mock Title") -> MockConfigEntry:
    """Add an entry with this data, and set it up."""
    entry = _add(hass, data, title)
    await _setup(hass, entry)
    return entry


async def _unload(hass, entry: MockConfigEntry) -> None:
    """Unload the entry, so that its timers stop."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _give_an_address(hass, entry: MockConfigEntry) -> None:
    """Give the entry an address, as a Reconfigure does, and wait for the reload."""
    hass.config_entries.async_update_entry(entry, data=YASNO_KYIV_ADDRESS_1_1)
    await hass.async_block_till_done()


async def _wait_for_the_reload_of_home_assistant(hass) -> None:
    """Move the time past the delay after which Home Assistant reloads the entry."""
    later = dt_utils.utcnow() + RELOAD_AFTER_ENABLE + timedelta(seconds=1)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()


def _register_group_sensor(
    hass,
    entry: MockConfigEntry,
    entity_id: str,
    disabled_by: er.RegistryEntryDisabler | None,
) -> er.RegistryEntry:
    """Put the group sensor in the registry, as an earlier run of the entry left it."""
    return er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_group",
        config_entry=entry,
        suggested_object_id=entity_id.removeprefix("sensor."),
        disabled_by=disabled_by,
    )


def _group_sensor(hass, entry: MockConfigEntry) -> er.RegistryEntry | None:
    """Return the registry entry of the group sensor of the entry, if it has one."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_group"
    )
    return registry.async_get(entity_id) if entity_id else None


async def test_group_entry_has_the_group_sensor_disabled(hass, aioclient_mock):
    """
    A new group entry has the group sensor in the registry, and it is disabled.

    Only an address can give an entry a new group, so a group entry has nothing to
    watch. The id of the sensor comes from the group, and the other sensors stay
    enabled.
    """
    yasno_address_answers(aioclient_mock)

    entry = await _start(hass, YASNO_KYIV_1_1, "Київ ДТЕК 1.1")

    sensor = _group_sensor(hass, entry)
    assert sensor is not None
    assert sensor.entity_id == GROUP_ENTRY_SENSOR_ID
    assert sensor.unique_id == f"{entry.entry_id}_group"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.translation_key == "group"
    assert sensor.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID) is None
    assert hass.states.get("sensor.kiiv_dtek_1_1_electricity") is not None
    await _unload(hass, entry)


async def test_group_entry_keeps_its_group_sensor_disabled_after_a_reload(
    hass, aioclient_mock
):
    """A new setup of a group entry does not enable the sensor that was disabled."""
    yasno_address_answers(aioclient_mock)
    entry = await _start(hass, YASNO_KYIV_1_1, "Київ ДТЕК 1.1")

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    sensor = _group_sensor(hass, entry)
    assert sensor.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID) is None
    await _unload(hass, entry)


async def test_address_entry_has_the_group_sensor_enabled(hass, aioclient_mock):
    """
    A new address entry has the group sensor enabled, and it shows the group.

    The id of the sensor comes from the address. The unique id has the entry id and
    the key, as the unique id of each sensor.
    """
    yasno_address_answers(aioclient_mock)

    entry = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)

    sensor = _group_sensor(hass, entry)
    assert sensor is not None
    assert sensor.entity_id == ADDRESS_ENTRY_SENSOR_ID
    assert sensor.unique_id == f"{entry.entry_id}_group"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.translation_key == "group"
    assert sensor.disabled_by is None
    state = hass.states.get(ADDRESS_ENTRY_SENSOR_ID)
    assert state is not None
    assert state.state == "1.1"
    assert state.attributes["friendly_name"].endswith(" Group")
    await _unload(hass, entry)


async def test_dtek_entry_has_no_group_sensor(hass, aioclient_mock):
    """A DTEK entry keeps the sensors that it had."""
    data, answers = PROVIDERS["dtek"]
    answers(aioclient_mock, answer=True)

    entry = await _start(hass, data)

    assert _group_sensor(hass, entry) is None
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert [_ for _ in entities if _.translation_key == "group"] == []
    await _unload(hass, entry)


async def test_sensor_shows_the_new_group_after_a_switch(hass, aioclient_mock):
    """
    The entry gets the new group of its address, and the sensor shows it.

    The update listener reloads the entry. The sensor stays the same one in the
    registry, so its entity id stays too.
    """
    yasno_address_answers(aioclient_mock)
    entry = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)
    assert hass.states.get(ADDRESS_ENTRY_SENSOR_ID).state == "1.1"
    registry_id = _group_sensor(hass, entry).id

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_GROUP: "53.1"}
    )
    await hass.async_block_till_done()

    assert hass.states.get(ADDRESS_ENTRY_SENSOR_ID).state == "53.1"
    assert _group_sensor(hass, entry).id == registry_id
    await _unload(hass, entry)


async def test_group_entry_that_gets_an_address_enables_the_group_sensor(
    hass, aioclient_mock
):
    """
    A Reconfigure that gives a group entry an address enables its group sensor.

    The registry has the sensor as disabled by the integration, and the reload of
    the update listener enables it, so it shows the group at once. Home Assistant
    reloads the entry once more 30 seconds after that, and the entry stays loaded
    with its sensor.
    """
    yasno_address_answers(aioclient_mock, group=YASNO_GROUP_1_1_REPLY)
    entry = await _start(hass, YASNO_KYIV_1_1, "Київ ДТЕК 1.1")
    before = _group_sensor(hass, entry)
    assert before.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID) is None

    await _give_an_address(hass, entry)

    sensor = _group_sensor(hass, entry)
    assert sensor.disabled_by is None
    assert sensor.id == before.id
    assert sensor.entity_id == GROUP_ENTRY_SENSOR_ID
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID).state == "1.1"

    coordinator = entry.runtime_data
    await _wait_for_the_reload_of_home_assistant(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not coordinator
    assert _group_sensor(hass, entry).disabled_by is None
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID).state == "1.1"
    await _unload(hass, entry)


async def test_address_entry_keeps_a_group_sensor_that_the_user_disabled(
    hass, aioclient_mock
):
    """The user disabled the sensor, so the setup of an address entry leaves it so."""
    yasno_address_answers(aioclient_mock)
    entry = _add(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)
    _register_group_sensor(
        hass, entry, ADDRESS_ENTRY_SENSOR_ID, er.RegistryEntryDisabler.USER
    )

    await _setup(hass, entry)

    sensor = _group_sensor(hass, entry)
    assert sensor.disabled_by is er.RegistryEntryDisabler.USER
    assert hass.states.get(ADDRESS_ENTRY_SENSOR_ID) is None
    await _unload(hass, entry)


async def test_address_entry_that_goes_back_to_a_group_keeps_the_sensor(
    hass, aioclient_mock
):
    """
    A Reconfigure back to a group leaves the sensor enabled, and it shows the group.

    The entity id that the address gave stays too.
    """
    yasno_address_answers(aioclient_mock, group=YASNO_GROUP_1_1_REPLY)
    entry = await _start(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)
    registry_id = _group_sensor(hass, entry).id

    hass.config_entries.async_update_entry(entry, data=YASNO_KYIV_1_1)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    sensor = _group_sensor(hass, entry)
    assert sensor.id == registry_id
    assert sensor.entity_id == ADDRESS_ENTRY_SENSOR_ID
    assert sensor.disabled_by is None
    assert hass.states.get(ADDRESS_ENTRY_SENSOR_ID).state == "1.1"
    await _unload(hass, entry)


async def test_group_entry_keeps_a_group_sensor_that_the_registry_has_enabled(
    hass, aioclient_mock
):
    """
    A group entry keeps a group sensor that an earlier version of the code enabled.

    Home Assistant reads the default of the sensor only for a new registry entry.
    """
    yasno_address_answers(aioclient_mock)
    entry = _add(hass, YASNO_KYIV_1_1, "Київ ДТЕК 1.1")
    kept = _register_group_sensor(hass, entry, GROUP_ENTRY_SENSOR_ID, None)
    assert kept.entity_id == GROUP_ENTRY_SENSOR_ID

    await _setup(hass, entry)

    assert _group_sensor(hass, entry).disabled_by is None
    assert hass.states.get(GROUP_ENTRY_SENSOR_ID).state == "1.1"
    await _unload(hass, entry)


async def test_enabling_the_sensor_logs_the_entry_id_and_never_the_address(
    hass, aioclient_mock, caplog
):
    """
    The debug line of the enable names the entry by its id.

    The entity id of the sensor has the address, so no line of the setup has it.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    yasno_address_answers(aioclient_mock)
    entry = _add(hass, YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT)
    disabled = _register_group_sensor(
        hass, entry, ADDRESS_ENTRY_SENSOR_ID, er.RegistryEntryDisabler.INTEGRATION
    )
    assert disabled.entity_id == ADDRESS_ENTRY_SENSOR_ID

    await _setup(hass, entry)
    await _wait_for_the_reload_of_home_assistant(hass)

    assert _group_sensor(hass, entry).disabled_by is None
    lines = [r.getMessage() for r in caplog.records if r.name.startswith(LOGGER_NAME)]
    assert f"Enable the group sensor of entry {entry.entry_id}" in lines
    assert [_ for _ in lines if "Сверстюка" in _ or "sverstiuka" in _] == []
    await _unload(hass, entry)


async def test_option_to_disable_new_entities_keeps_the_group_sensor_disabled(
    hass, aioclient_mock
):
    """
    The system option «Enable newly added entities» is off: the sensor stays disabled.

    Home Assistant then disables each new entity of the entry, also the group sensor
    of an address entry. A later setup must not enable it against that choice.
    """
    yasno_address_answers(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=YASNO_KYIV_ADDRESS_1_1,
        title=ADDRESS_TEXT,
        pref_disable_new_entities=True,
    )
    entry.add_to_hass(hass)
    await _setup(hass, entry)
    assert (
        _group_sensor(hass, entry).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    )

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        _group_sensor(hass, entry).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    )
    assert hass.states.get(ADDRESS_ENTRY_SENSOR_ID) is None
    await _unload(hass, entry)
