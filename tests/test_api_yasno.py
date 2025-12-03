"""Tests for Svitlo Yeah API."""

import datetime
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.yasno import (
    YasnoApi,
    _merge_adjacent_events,
    _minutes_to_time,
    _parse_day_schedule,
)
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoRegion,
)

TEST_REGION_ID = 25
TEST_PROVIDER_ID = 902
TEST_GROUP = "3.1"


@pytest.fixture(name="api")
def _api():
    """Create an API instance."""
    return YasnoApi(
        region_id=TEST_REGION_ID, provider_id=TEST_PROVIDER_ID, group=TEST_GROUP
    )


@pytest.fixture
def regions_data():
    """Sample regions data."""
    return [
        {
            "hasCities": False,
            "dsos": [
                {"id": TEST_PROVIDER_ID, "name": "ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»"}
            ],
            "id": TEST_REGION_ID,
            "value": "Київ",
        },
        {
            "hasCities": True,
            "dsos": [{"id": 301, "name": "ДнЕМ"}, {"id": 303, "name": "ЦЕК"}],
            "id": 3,
            "value": "Дніпро",
        },
    ]


@pytest.fixture
def planned_outage_data(today, tomorrow):
    """Sample planned outage data."""
    return {
        TEST_GROUP: {
            "today": {
                "slots": [
                    {"start": 0, "end": 960, "type": "NotPlanned"},
                    {"start": 960, "end": 1200, "type": "Definite"},
                    {"start": 1200, "end": 1440, "type": "NotPlanned"},
                ],
                "date": today.isoformat(),
                "status": "ScheduleApplies",
            },
            "tomorrow": {
                "slots": [
                    {"start": 0, "end": 900, "type": "NotPlanned"},
                    {"start": 900, "end": 1080, "type": "Definite"},
                    {"start": 1080, "end": 1440, "type": "NotPlanned"},
                ],
                "date": tomorrow.isoformat(),
                "status": "ScheduleApplies",
            },
            "updatedOn": today.isoformat(),
        }
    }


@pytest.fixture
def emergency_outage_data(today, tomorrow):
    """Sample emergency outage data."""
    return {
        TEST_GROUP: {
            "today": {
                "slots": [],
                "date": today.isoformat(),
                "status": "EmergencyShutdowns",
            },
            "tomorrow": {
                "slots": [],
                "date": tomorrow.isoformat(),
                "status": "EmergencyShutdowns",
            },
            "updatedOn": today.isoformat(),
        }
    }


class TestYasnoApiInit:
    """Test YasnoApi initialization."""

    def test_init_with_params(self):
        """Test initialization with parameters."""
        api = YasnoApi(
            region_id=TEST_REGION_ID, provider_id=TEST_PROVIDER_ID, group=TEST_GROUP
        )
        assert api.region_id == TEST_REGION_ID
        assert api.provider_id == TEST_PROVIDER_ID
        assert api.group == TEST_GROUP
        assert api.regions is None
        assert api.planned_outage_data is None

    def test_init_without_params(self):
        """Test initialization without parameters."""
        api = YasnoApi()
        assert api.region_id is None
        assert api.provider_id is None
        assert api.group is None


class TestYasnoApiFetchData:
    """Test data fetching methods."""

    async def test_fetch_regions_success(self, api, regions_data):
        """Test successful regions fetch."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value=regions_data)
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value.__aenter__.return_value = mock_response

            await api.fetch_yasno_regions()
            assert api.__class__._regions == [
                YasnoRegion.from_dict(_) for _ in regions_data
            ]

    async def test_fetch_regions_error(self, api):
        """Test regions fetch with error."""
        YasnoApi._regions = None
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.side_effect = aiohttp.ClientError()
            await api.fetch_yasno_regions()
            assert api.regions is None

    async def test_fetch_planned_outage_success(self, api, planned_outage_data):
        """Test successful planned outage fetch."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value=planned_outage_data)
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value.__aenter__.return_value = mock_response

            await api.fetch_planned_outage_data()
            assert api.planned_outage_data == planned_outage_data

    async def test_fetch_planned_outage_no_config(self, api):
        """Test planned outage fetch without region/provider."""
        # Save original values
        original_region_id = api.region_id
        original_provider_id = api.provider_id

        api.region_id = None
        api.provider_id = None

        await api.fetch_planned_outage_data()
        assert api.planned_outage_data is None

        # Restore original values
        api.region_id = original_region_id
        api.provider_id = original_provider_id


class TestYasnoApiGroups:
    """Test group-related methods."""

    def test_get_groups(self, api, planned_outage_data):
        """Test getting groups list."""
        api.planned_outage_data = planned_outage_data
        assert api.get_yasno_groups() == [TEST_GROUP]

    def test_get_groups_empty(self, api):
        """Test getting groups when none loaded."""
        assert api.get_yasno_groups() == []


class TestYasnoApiTimeConversion:
    """Test time conversion methods."""

    def test_minutes_to_time(self):
        """Test converting minutes to time."""
        date = dt_utils.now()
        result = _minutes_to_time(960, date)
        assert result.hour == 16
        assert result.minute == 0

    def test_minutes_to_time_end_of_day(self):
        """Test converting 24:00 to time."""
        date = dt_utils.now()
        result = _minutes_to_time(1440, date)
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0


class TestYasnoApiScheduleParsing:
    """Test schedule parsing methods."""

    def test_parse_day_schedule(self, today):
        """Test parsing day schedule."""
        day_data = {
            "slots": [
                {"start": 960, "end": 1200, "type": "Definite"},
                {"start": 1200, "end": 1440, "type": "NotPlanned"},
            ],
            "date": today.isoformat(),
        }
        date = today
        events = _parse_day_schedule(day_data, date)
        assert len(events) == 1
        assert events[0].event_type == PlannedOutageEventType.DEFINITE
        assert events[0].start.hour == 16  # 960

    def test_parse_emergency_shutdown(self, api, today, tomorrow):
        """Test parsing emergency shutdown."""
        day_data = {
            "status": "EmergencyShutdowns",
            "slots": [],
            "date": today.isoformat(),
        }
        date_ = dt_utils.parse_datetime(today.isoformat())
        api.planned_outage_data = {TEST_GROUP: {"today": day_data}}
        events = api.get_events(date_, date_ + timedelta(days=1))
        assert len(events) == 1
        assert events[0].all_day is True
        assert events[0].event_type == PlannedOutageEventType.EMERGENCY
        assert events[0].start == date(today.year, today.month, today.day)
        assert events[0].end == date(tomorrow.year, tomorrow.month, tomorrow.day)


class TestYasnoApiEventMerging:
    """Test event merging functionality."""

    def test_merge_adjacent_datetime_events(self, today, tomorrow):
        """Test merging adjacent datetime events of same type."""
        dt1 = today.replace(hour=22)
        dt2 = tomorrow
        dt3 = tomorrow.replace(hour=2)

        events = [
            PlannedOutageEvent(
                start=dt1,
                end=dt2,
                event_type=PlannedOutageEventType.DEFINITE,
            ),
            PlannedOutageEvent(
                start=dt2,
                end=dt3,
                event_type=PlannedOutageEventType.DEFINITE,
            ),
        ]

        merged = _merge_adjacent_events(events)
        assert len(merged) == 1
        assert merged[0].start == dt1
        assert merged[0].end == dt3
        assert merged[0].event_type == PlannedOutageEventType.DEFINITE

    def test_merge_adjacent_all_day_events(self, today, tomorrow):
        """Test merging adjacent all-day events of same type."""
        date1 = today
        date2 = tomorrow
        date3 = tomorrow + timedelta(days=1)

        events = [
            PlannedOutageEvent(
                start=date1,
                end=date2,
                all_day=True,
                event_type=PlannedOutageEventType.EMERGENCY,
            ),
            PlannedOutageEvent(
                start=date2,
                end=date3,
                all_day=True,
                event_type=PlannedOutageEventType.EMERGENCY,
            ),
        ]

        merged = _merge_adjacent_events(events)
        assert len(merged) == 1
        assert merged[0].start == date1
        assert merged[0].end == date3
        assert merged[0].event_type == PlannedOutageEventType.EMERGENCY
        assert merged[0].all_day is True

    def test_no_merge_different_types(self, today, tomorrow):
        """Test that events of different types are not merged."""
        dt1 = today.replace(hour=22)
        dt2 = tomorrow

        events = [
            PlannedOutageEvent(
                start=dt1,
                end=dt2,
                event_type=PlannedOutageEventType.DEFINITE,
            ),
            PlannedOutageEvent(
                start=dt2,
                end=tomorrow.replace(hour=2),
                event_type=PlannedOutageEventType.EMERGENCY,
            ),
        ]

        merged = _merge_adjacent_events(events)
        assert len(merged) == 2
        assert merged[0].event_type == PlannedOutageEventType.DEFINITE
        assert merged[1].event_type == PlannedOutageEventType.EMERGENCY

    def test_no_merge_non_adjacent(self, today):
        """Test that non-adjacent events are not merged."""
        dt1 = today.replace(hour=20)
        dt2 = today.replace(hour=22)

        events = [
            PlannedOutageEvent(
                start=dt1,
                end=dt1 + timedelta(hours=1),  # less than 22-20
                event_type=PlannedOutageEventType.DEFINITE,
            ),
            PlannedOutageEvent(
                start=dt2,
                end=dt2 + timedelta(hours=1),
                event_type=PlannedOutageEventType.DEFINITE,
            ),
        ]

        merged = _merge_adjacent_events(events)
        assert len(merged) == 2, "non-adjacent events should not be merged."

    def test_merge_empty_list(self):
        """Test merging empty event list."""
        merged = _merge_adjacent_events([])
        assert merged == []

    def test_merge_single_event(self, today, tomorrow):
        """Test merging single event."""
        dt1 = today.replace(hour=22)
        events = [
            PlannedOutageEvent(
                start=dt1,
                end=tomorrow,
                event_type=PlannedOutageEventType.DEFINITE,
            ),
        ]

        merged = _merge_adjacent_events(events)
        assert len(merged) == 1
        assert merged[0] == events[0]

    def test_midnight_spanning_events_integration(self, api, today, tomorrow):
        """Test midnight-spanning events are merged in get_events."""
        # Simulate data with midnight-spanning outage
        api.planned_outage_data = {
            TEST_GROUP: {
                "today": {
                    "slots": [
                        {"start": 0, "end": 1320, "type": "NotPlanned"},  # 00:00-22:00
                        {"start": 1320, "end": 1440, "type": "Definite"},  # 22:00-24:00
                    ],
                    "date": today.isoformat(),
                    "status": "ScheduleApplies",
                },
                "tomorrow": {
                    "slots": [
                        {"start": 0, "end": 120, "type": "Definite"},  # 00:00-02:00
                        {
                            "start": 120,
                            "end": 1440,
                            "type": "NotPlanned",
                        },  # 02:00-24:00
                    ],
                    "date": tomorrow.isoformat(),
                    "status": "ScheduleApplies",
                },
                "updatedOn": today.isoformat(),
            }
        }

        start = today
        end = tomorrow + timedelta(days=1)
        events = api.get_events(start, end)

        # Should have merged into one continuous event from 22:00 to 02:00
        assert len(events) == 1
        assert events[0].start.hour == 22  # 1320
        assert events[0].start.minute == 0
        assert events[0].end.hour == 2  # 120 of the next day
        assert events[0].end.minute == 0
        assert events[0].event_type == PlannedOutageEventType.DEFINITE


class TestYasnoApiEvents:
    """Test event retrieval methods."""

    def test_get_updated_on(self, api, planned_outage_data):
        """Test getting updated timestamp."""
        api.planned_outage_data = planned_outage_data
        updated = api.get_updated_on()
        assert updated is not None
        assert updated.year == 2025

    def test_get_updated_on_no_data(self, api):
        """Test getting updated timestamp without data."""
        assert api.get_updated_on() is None

    def test_get_events(self, api, planned_outage_data, today, tomorrow):
        """Test getting events."""
        api.planned_outage_data = planned_outage_data
        # there has to be 2 events in the debug data
        events = api.get_events(today, tomorrow.replace(hour=23, minute=59, second=59))
        assert len(events) == 2

    def test_get_events_emergency(self, api, emergency_outage_data, today, tomorrow):
        """Test getting emergency events."""
        api.planned_outage_data = emergency_outage_data
        start = today
        end = tomorrow + timedelta(days=1)
        events = api.get_events(start, end)
        assert len(events) == 1  # Merged into single continuous event
        assert events[0].event_type == PlannedOutageEventType.EMERGENCY
        assert events[0].all_day is True
        assert events[0].start == start.date()
        assert events[0].end == end.date()

    def test_get_current_event(self, api, planned_outage_data, today):
        """Test getting current event."""
        api.planned_outage_data = planned_outage_data
        at = today.replace(hour=17)  # this has to be in the debug data
        event = api.get_current_event(at)
        assert event is not None
        assert event.event_type == PlannedOutageEventType.DEFINITE

    def test_get_current_event_none(self, api, planned_outage_data, today):
        """Test getting current event when none active."""
        api.planned_outage_data = planned_outage_data
        at = today.replace(hour=8)  # this has to be in the debug data
        event = api.get_current_event(at)
        assert event is None


class TestYasnoApiScheduledEvents:
    """Test get_scheduled_events method."""

    def test_get_scheduled_events_schedule_applies(self, api, today, tomorrow):
        """Test getting scheduled events with ScheduleApplies status."""
        api.planned_outage_data = {
            TEST_GROUP: {
                "today": {
                    "slots": [
                        {"start": 960, "end": 1200, "type": "Definite"},
                    ],
                    "date": today.isoformat(),
                    "status": "ScheduleApplies",
                },
                "tomorrow": {
                    "slots": [],
                    "date": tomorrow.isoformat(),
                    "status": "WaitingForSchedule",
                },
                "updatedOn": today.isoformat(),
            }
        }

        start_date = today
        end_date = tomorrow + timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert len(events) == 1
        assert events[0].event_type == PlannedOutageEventType.DEFINITE
        assert events[0].start.hour == 16  # 960 minutes

    def test_get_scheduled_events_waiting_for_schedule(self, api, today):
        """Test getting scheduled events with WaitingForSchedule status."""
        api.planned_outage_data = {
            TEST_GROUP: {
                "today": {
                    "slots": [
                        {"start": 600, "end": 900, "type": "Definite"},
                    ],
                    "date": today.isoformat(),
                    "status": "WaitingForSchedule",
                },
                "updatedOn": today.isoformat(),
            }
        }

        start_date = today
        end_date = today + datetime.timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert len(events) == 1
        assert events[0].event_type == PlannedOutageEventType.DEFINITE

    def test_get_scheduled_events_emergency_shutdowns(self, api, today):
        """Test getting scheduled events with EmergencyShutdowns status."""
        api.planned_outage_data = {
            TEST_GROUP: {
                "today": {
                    "slots": [],
                    "date": today.isoformat(),
                    "status": "EmergencyShutdowns",
                },
                "updatedOn": today.isoformat(),
            }
        }

        start_date = today
        end_date = today + datetime.timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert len(events) == 1
        assert events[0].event_type == PlannedOutageEventType.EMERGENCY
        assert events[0].all_day is True

    def test_get_scheduled_events_no_data(self, api, today):
        """Test getting scheduled events without data."""
        api.planned_outage_data = None

        start_date = today
        end_date = today + datetime.timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert events == []

    def test_get_scheduled_events_date_filtering(self, api, today, tomorrow):
        """Test that scheduled events are filtered by date range."""
        api.planned_outage_data = {
            TEST_GROUP: {
                "today": {
                    "slots": [{"start": 960, "end": 1200, "type": "Definite"}],
                    "date": today.isoformat(),
                    "status": "ScheduleApplies",
                },
                "tomorrow": {
                    "slots": [{"start": 960, "end": 1200, "type": "Definite"}],
                    "date": tomorrow.isoformat(),
                    "status": "ScheduleApplies",
                },
                "updatedOn": today.isoformat(),
            }
        }

        # Test range that only includes today
        start_date = today
        end_date = today + datetime.timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert len(events) == 1
        assert events[0].start.date() == today.date()

        # Test range that includes both days
        start_date = today
        end_date = tomorrow + datetime.timedelta(days=1)
        events = api.get_scheduled_events(start_date, end_date)

        assert len(events) == 2
