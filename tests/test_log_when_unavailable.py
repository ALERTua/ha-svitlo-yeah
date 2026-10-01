"""A source that stops answering is logged once, and once when it answers again (silver log-when-unavailable)."""

import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import DOMAIN
from tests.helpers import PROVIDERS

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

INTEGRATION_LOGGER = "custom_components.svitlo_yeah"
GONE = "does not answer"
BACK = "answers again"


def _integration_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith(INTEGRATION_LOGGER)]


def _infos(caplog, text: str) -> int:
    return sum(
        r.levelno == logging.INFO and text in r.getMessage()
        for r in _integration_records(caplog)
    )


def _problems(caplog) -> list[str]:
    """Return the warnings and errors of the integration."""
    return [
        r.getMessage()
        for r in _integration_records(caplog)
        if r.levelno >= logging.WARNING
    ]


async def _set_up(hass, aioclient_mock, provider: str, *, answer: bool):
    """Set up an entry of the provider, and return the entry and its coordinator."""
    data, answers = PROVIDERS[provider]
    answers(aioclient_mock, answer)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data


async def _unload(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_source_down_is_logged_once_and_back_once(
    hass, aioclient_mock, caplog, provider
):
    """Two failed polls give one info line, the first answer after them gives one more."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    entry, coordinator = await _set_up(hass, aioclient_mock, provider, answer=True)
    _, answers = PROVIDERS[provider]
    assert _infos(caplog, GONE) == 0

    aioclient_mock.clear_requests()
    answers(aioclient_mock, False)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert _infos(caplog, GONE) == 1
    assert _problems(caplog) == []

    aioclient_mock.clear_requests()
    answers(aioclient_mock, True)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert _infos(caplog, BACK) == 1
    assert _infos(caplog, GONE) == 1
    await _unload(hass, entry)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_new_entry_without_an_answer_logs_once(
    hass, aioclient_mock, caplog, provider
):
    """A source that does not answer at the first start gives one info line, no error."""
    caplog.set_level(logging.DEBUG, logger=INTEGRATION_LOGGER)
    entry, coordinator = await _set_up(hass, aioclient_mock, provider, answer=False)

    await coordinator.async_refresh()

    assert coordinator.last_fetch_failed
    assert _infos(caplog, GONE) == 1
    assert _problems(caplog) == []
    await _unload(hass, entry)
