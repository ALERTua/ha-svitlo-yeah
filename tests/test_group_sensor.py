"""The group sensor: a diagnostic sensor that each Yasno entry has."""

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import CONF_GROUP, DOMAIN
from tests.helpers import (
    PROVIDERS,
    YASNO_KYIV_1_1,
    YASNO_KYIV_ADDRESS_1_1,
    YASNO_KYIV_HOUSE,
    YASNO_KYIV_STREET,
    yasno_address_answers,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

ADDRESS_TEXT = f"{YASNO_KYIV_STREET}, {YASNO_KYIV_HOUSE}"
# The ids that Home Assistant gave in the registry, read once and pinned here
GROUP_ENTRY_SENSOR_ID = "sensor.kiiv_dtek_1_1_group"
ADDRESS_ENTRY_SENSOR_ID = "sensor.vul_sverstiuka_evgena_6a_group"


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


def _group_sensor(hass, entry: MockConfigEntry) -> er.RegistryEntry | None:
    """Return the registry entry of the group sensor of the entry, if it has one."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_group"
    )
    return registry.async_get(entity_id) if entity_id else None


@pytest.mark.parametrize(
    ("data", "title", "entity_id"),
    [
        (YASNO_KYIV_1_1, "Київ ДТЕК 1.1", GROUP_ENTRY_SENSOR_ID),
        (YASNO_KYIV_ADDRESS_1_1, ADDRESS_TEXT, ADDRESS_ENTRY_SENSOR_ID),
    ],
    ids=["group_entry", "address_entry"],
)
async def test_yasno_entry_has_the_group_sensor(
    hass, aioclient_mock, data, title, entity_id
):
    """
    A Yasno entry has a diagnostic sensor with its group, as a group or an address.

    The id of a group entry comes from its group, and the id of an address entry
    from its address. The unique id has the entry id and the key, as the unique id of
    each sensor.
    """
    yasno_address_answers(aioclient_mock)

    entry = await _start(hass, data, title)

    sensor = _group_sensor(hass, entry)
    assert sensor is not None
    assert sensor.entity_id == entity_id
    assert sensor.unique_id == f"{entry.entry_id}_group"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.translation_key == "group"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "1.1"
    assert state.attributes["friendly_name"].endswith(" Group")
    await _unload(hass, entry)


@pytest.mark.parametrize("provider", ["dtek", "e_svitlo", "soe"])
async def test_other_providers_have_no_group_sensor(hass, aioclient_mock, provider):
    """A DTEK, E-Svitlo or SOE entry keeps the sensors that it had."""
    data, answers = PROVIDERS[provider]
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
