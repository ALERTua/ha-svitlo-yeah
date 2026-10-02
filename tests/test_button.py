"""The refresh button reports a source without an answer (silver action-exceptions)."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import ClientError
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import DOMAIN, YASNO_REGIONS_ENDPOINT
from custom_components.svitlo_yeah.models import ConnectivityState
from tests.helpers import (
    PROVIDERS,
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
    dtek_answers,
    fact_with_an_outage_today,
    yasno_outage_all_day_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)


async def _set_up(hass, aioclient_mock, data: dict, answers) -> MockConfigEntry:
    """Set up an entry whose source answers with an outage all day today."""
    answers(aioclient_mock, answer=True)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _electricity(hass, entry) == ConnectivityState.STATE_PLANNED_OUTAGE
    return entry


def _entity_id(hass, entry: MockConfigEntry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id
    return entity_id


def _electricity(hass, entry: MockConfigEntry) -> str:
    return hass.states.get(_entity_id(hass, entry, "sensor", "electricity")).state


async def _press(hass, entry: MockConfigEntry) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity_id(hass, entry, "button", "refresh")},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _unload(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_press_without_an_answer_fails_and_keeps_the_states(
    hass, aioclient_mock, provider
):
    """The press says that the source did not answer; the entities keep their states."""
    data, answers = PROVIDERS[provider]
    entry = await _set_up(hass, aioclient_mock, data, answers)
    aioclient_mock.clear_requests()
    answers(aioclient_mock, answer=False)

    with pytest.raises(HomeAssistantError) as error:
        await _press(hass, entry)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "refresh_failed"
    assert _electricity(hass, entry) == ConnectivityState.STATE_PLANNED_OUTAGE
    button = hass.states.get(_entity_id(hass, entry, "button", "refresh"))
    assert button.state != STATE_UNAVAILABLE
    await _unload(hass, entry)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_press_with_an_answer_succeeds(hass, aioclient_mock, provider):
    """The press gives no error while the source answers."""
    data, answers = PROVIDERS[provider]
    entry = await _set_up(hass, aioclient_mock, data, answers)

    await _press(hass, entry)

    assert _electricity(hass, entry) == ConnectivityState.STATE_PLANNED_OUTAGE
    await _unload(hass, entry)


async def test_press_while_the_yasno_regions_fail_succeeds(
    hass, aioclient_mock, caplog
):
    """The regions only name the device: a press that gets the outages succeeds."""
    caplog.set_level(logging.INFO, logger="custom_components.svitlo_yeah")
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
    aioclient_mock.get(YASNO_PLANNED_URL, json=yasno_outage_all_day_today())
    entry = MockConfigEntry(domain=DOMAIN, data=YASNO_KYIV_1_1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _press(hass, entry)

    assert _electricity(hass, entry) == ConnectivityState.STATE_PLANNED_OUTAGE
    assert "does not answer" not in caplog.text
    await _unload(hass, entry)


async def test_press_with_an_outdated_dtek_schedule_succeeds(hass, aioclient_mock):
    """An outdated DTEK schedule is an answer: no error, the last fresh copy stays."""
    data, answers = PROVIDERS["dtek"]
    entry = await _set_up(hass, aioclient_mock, data, answers)
    aioclient_mock.clear_requests()
    dtek_answers(
        aioclient_mock,
        fact_with_an_outage_today(datetime.now(UTC) - timedelta(days=30)),
    )

    await _press(hass, entry)

    assert _electricity(hass, entry) == ConnectivityState.STATE_PLANNED_OUTAGE
    await _unload(hass, entry)
