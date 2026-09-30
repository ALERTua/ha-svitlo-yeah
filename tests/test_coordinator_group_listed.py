"""Tests for group_listed of the DTEK and Yasno coordinators and its effects."""

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.dtek.base import FetchResult
from custom_components.svitlo_yeah.const import CONF_GROUP, CONF_PROVIDER, CONF_REGION
from custom_components.svitlo_yeah.coordinator.dtek.json import DtekCoordinatorJson
from custom_components.svitlo_yeah.coordinator.yasno import YasnoCoordinator
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEventType,
)
from custom_components.svitlo_yeah.sensor import SENSORS, IntegrationSensor

LOGGER_NAME = "custom_components.svitlo_yeah.coordinator.coordinator"
ELECTRICITY = next(s for s in SENSORS if s.key == "electricity")


def _entry(data: dict) -> MagicMock:
    """Build a config entry with the given data and no options."""
    entry = MagicMock()
    entry.data = data
    entry.options = {}
    entry.entry_id = "test_entry"
    return entry


def _records(caplog, level: int) -> list[logging.LogRecord]:
    """Return the records of the coordinator logger at the given level."""
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno == level]


@pytest.fixture(name="dtek")
def _dtek():
    """Build a DTEK JSON coordinator with a mocked API."""
    with patch(
        "custom_components.svitlo_yeah.api.dtek.json.async_get_clientsession",
        return_value=MagicMock(),
    ):
        coordinator = DtekCoordinatorJson(
            MagicMock(spec=HomeAssistant),
            _entry({CONF_PROVIDER: "kyiv_region", CONF_GROUP: "3.1"}),
        )
    coordinator.async_fetch_translations = AsyncMock()
    coordinator.api = MagicMock()
    coordinator.api.get_events = MagicMock(return_value=[])
    return coordinator


async def _update_dtek(coordinator, result: FetchResult, listed: bool | None):
    """Run one update where fetch_data gives `result` and the API `listed`."""
    coordinator.api.fetch_data = AsyncMock(return_value=result)
    coordinator.api.is_group_listed = MagicMock(return_value=listed)
    await coordinator._async_update_data()


class TestDtekCoordinatorGroupListed:
    """The DTEK coordinator takes the answer from fresh data only."""

    async def test_starts_unknown(self, dtek):
        """Before any update the answer is unknown."""
        assert dtek.group_listed is None

    async def test_fresh_data_without_the_group(self, dtek, caplog):
        """Fresh data without the group gives False and one warning."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await _update_dtek(dtek, FetchResult.FRESH, listed=False)

        assert dtek.group_listed is False
        assert len(_records(caplog, logging.WARNING)) == 1

    async def test_fresh_data_with_the_group(self, dtek, caplog):
        """Fresh data with the group gives True and no log record."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await _update_dtek(dtek, FetchResult.FRESH, listed=True)

        assert dtek.group_listed is True
        assert not _records(caplog, logging.WARNING)
        assert not _records(caplog, logging.INFO)

    @pytest.mark.parametrize("result", [FetchResult.STALE, FetchResult.UNAVAILABLE])
    async def test_no_fresh_data_keeps_the_last_answer(self, dtek, result):
        """Stale or unavailable data does not ask the API and keeps the answer."""
        dtek.group_listed = False

        await _update_dtek(dtek, result, listed=True)

        assert dtek.group_listed is False
        dtek.api.is_group_listed.assert_not_called()

    async def test_fresh_data_without_an_answer_keeps_the_last_answer(self, dtek):
        """Fresh data that says nothing about the group keeps the answer."""
        dtek.group_listed = False

        await _update_dtek(dtek, FetchResult.FRESH, listed=None)

        assert dtek.group_listed is False

    async def test_missing_twice_logs_once(self, dtek, caplog):
        """The warning comes once, when the answer changes."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await _update_dtek(dtek, FetchResult.FRESH, listed=False)
            await _update_dtek(dtek, FetchResult.FRESH, listed=False)

        assert len(_records(caplog, logging.WARNING)) == 1

    async def test_group_comes_back(self, dtek, caplog):
        """A group that comes back gives True and one info record."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await _update_dtek(dtek, FetchResult.FRESH, listed=False)
            await _update_dtek(dtek, FetchResult.FRESH, listed=True)

        assert dtek.group_listed is True
        assert len(_records(caplog, logging.WARNING)) == 1
        assert len(_records(caplog, logging.INFO)) == 1


@pytest.fixture(name="yasno")
def _yasno():
    """Build a Yasno coordinator."""
    with patch(
        "custom_components.svitlo_yeah.api.yasno.async_get_clientsession",
        return_value=MagicMock(),
    ):
        coordinator = YasnoCoordinator(
            MagicMock(spec=HomeAssistant),
            _entry({CONF_REGION: 25, CONF_PROVIDER: 902, CONF_GROUP: "1.2"}),
        )
    coordinator.async_fetch_translations = AsyncMock()
    return coordinator


async def _update_yasno(coordinator, listed: bool | None):
    """Run one update where the new YasnoApi answers `listed`."""
    api = MagicMock()
    api.fetch_data = AsyncMock()
    api.is_group_listed = MagicMock(return_value=listed)
    api.get_events = MagicMock(return_value=[])
    with patch(
        "custom_components.svitlo_yeah.coordinator.yasno.YasnoApi",
        return_value=api,
    ):
        await coordinator._async_update_data()


class TestYasnoCoordinatorGroupListed:
    """The Yasno coordinator takes the answer after each update."""

    async def test_planned_outages_with_the_group(self, yasno):
        """Planned outages with the group give True."""
        await _update_yasno(yasno, listed=True)
        assert yasno.group_listed is True

    async def test_planned_outages_without_the_group(self, yasno, caplog):
        """Planned outages without the group give False and one warning."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await _update_yasno(yasno, listed=False)

        assert yasno.group_listed is False
        assert len(_records(caplog, logging.WARNING)) == 1

    async def test_failed_request_keeps_the_last_answer(self, yasno):
        """A failed request says nothing about the group and keeps the answer."""
        yasno.group_listed = False

        await _update_yasno(yasno, listed=None)

        assert yasno.group_listed is False


def _planned_outage_now() -> CalendarEvent:
    """Build a planned outage that is in progress now."""
    now = dt_utils.now()
    return CalendarEvent(
        summary="Planned outage",
        start=now - timedelta(minutes=5),
        end=now + timedelta(hours=1),
        description=PlannedOutageEventType.DEFINITE.value,
        uid=PlannedOutageEventType.DEFINITE.value,
    )


class TestElectricityWithoutGroupSchedule:
    """Electricity is unknown while the source has no schedule for the group."""

    @pytest.mark.parametrize("group_listed", [True, None])
    def test_listed_or_unknown_group_keeps_the_event_state(self, dtek, group_listed):
        """A listed group, or no answer yet, keeps the state of the event."""
        dtek.group_listed = group_listed
        dtek.get_current_event = MagicMock(return_value=_planned_outage_now())
        assert dtek.current_state == ConnectivityState.STATE_PLANNED_OUTAGE

    @pytest.mark.parametrize("coordinator_name", ["dtek", "yasno"])
    def test_missing_group_gives_unknown(self, request, coordinator_name):
        """A missing group gives None, even when an event is in progress."""
        coordinator = request.getfixturevalue(coordinator_name)
        coordinator.group_listed = False
        coordinator.get_current_event = MagicMock(return_value=_planned_outage_now())
        assert coordinator.current_state is None

    def test_electricity_sensor_is_unknown_for_a_missing_group(self, dtek):
        """The Electricity sensor gives no value, which Home Assistant shows as unknown."""
        dtek.group_listed = False
        dtek.get_current_event = MagicMock(return_value=None)
        assert IntegrationSensor(dtek, ELECTRICITY).native_value is None

    def test_electricity_sensor_is_normal_for_a_listed_group(self, dtek):
        """The Electricity sensor shows normal for a listed group without events."""
        dtek.group_listed = True
        dtek.get_current_event = MagicMock(return_value=None)
        sensor = IntegrationSensor(dtek, ELECTRICITY)
        assert sensor.native_value == ConnectivityState.STATE_NORMAL
