"""The device of an E-Svitlo entry has no address in its name or in its entity ids."""

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import CONF_ADDRESS_STR, DOMAIN
from tests.helpers import E_SVITLO_ACCOUNT_101, e_svitlo_answers

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# The address of the account as an entity id shows it
ADDRESS = slugify(E_SVITLO_ACCOUNT_101[CONF_ADDRESS_STR])


async def _set_up(hass, aioclient_mock) -> MockConfigEntry:
    """Add an E-Svitlo entry; the caller sets it up after it prepares the registries."""
    e_svitlo_answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=E_SVITLO_ACCOUNT_101)
    entry.add_to_hass(hass)
    return entry


async def _start(hass, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Set up the entry, and return its device."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    return device


async def _unload(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_new_entry_has_no_address_in_its_names(hass, aioclient_mock):
    """The device is «Sumy E-Svitlo 4.1», and no entity id has the address."""
    entry = await _set_up(hass, aioclient_mock)

    device = await _start(hass, entry)

    assert device.name == "Sumy E-Svitlo 4.1"
    entity_ids = [
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]
    assert len(entity_ids) == 9
    assert [e for e in entity_ids if ADDRESS in e] == []
    await _unload(hass, entry)


async def test_older_device_gets_the_new_name_and_keeps_its_entity_ids(
    hass, aioclient_mock
):
    """The next start renames the device of an older entry; its entity ids stay."""
    entry = await _set_up(hass, aioclient_mock)
    old_name = f"sumy {E_SVITLO_ACCOUNT_101[CONF_ADDRESS_STR]} 4.1"
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=old_name,
    )
    old_entity = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_electricity",
        suggested_object_id=f"sumy_{ADDRESS}_4_1_electricity",
        config_entry=entry,
    )

    device = await _start(hass, entry)

    assert device.name == "Sumy E-Svitlo 4.1"
    assert hass.states.get(old_entity.entity_id) is not None
    await _unload(hass, entry)
