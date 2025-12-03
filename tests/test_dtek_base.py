"""Tests for DTEK base API functionality."""

import datetime

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.dtek.base import (
    _parse_group_hours,
    _parse_preset_group_hours,
)
from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TEST_GROUP = "1.1"
TEST_TIMESTAMP = "1761688800"


@pytest.fixture(name="api")
def _api():
    """Create a DTEK API instance for testing base functionality."""
    return DtekAPIJson(urls=next(iter(DTEK_PROVIDER_URLS.values())), group=TEST_GROUP)


@pytest.fixture
def sample_data():
    """Sample parsed schedule data."""
    return {
        "data": {
            TEST_TIMESTAMP: {
                "GPV1.1": {
                    "1": "yes",
                    "10": "yes",
                    "11": "yes",
                    "12": "yes",
                    "13": "second",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "first",
                    "18": "yes",
                    "19": "yes",
                    "2": "yes",
                    "20": "yes",
                    "21": "yes",
                    "22": "yes",
                    "23": "yes",
                    "24": "yes",
                    "3": "yes",
                    "4": "yes",
                    "5": "yes",
                    "6": "yes",
                    "7": "yes",
                    "8": "yes",
                    "9": "yes",
                },
                "GPV1.2": {
                    "1": "yes",
                    "2": "yes",
                    "3": "yes",
                    "4": "yes",
                    "5": "yes",
                    "6": "yes",
                    "7": "yes",
                    "8": "yes",
                    "9": "yes",
                    "10": "yes",
                    "11": "yes",
                    "12": "yes",
                    "13": "yes",
                    "14": "yes",
                    "15": "yes",
                    "16": "yes",
                    "17": "yes",
                    "18": "yes",
                    "19": "yes",
                    "20": "yes",
                    "21": "yes",
                    "22": "yes",
                    "23": "yes",
                    "24": "yes",
                },
            },
        },
        "update": "29.10.2025 13:51",
        "today": 1761688800,
    }


class TestDtekAPIBaseGroups:
    """Test group-related methods."""

    def test_get_groups_success(self, api, sample_data):
        """Test getting groups list."""
        api.data = sample_data
        groups = api.get_dtek_region_groups()
        assert "1.1" in groups
        assert "1.2" in groups
        assert groups == ["1.1", "1.2"]

    def test_get_groups_no_data(self, api):
        """Test getting groups without data."""
        assert api.get_dtek_region_groups() == []

    def test_get_groups_missing_data_key(self, api):
        """Test getting groups with missing data key."""
        api.data = {"update": "29.10.2025 13:51"}
        assert api.get_dtek_region_groups() == []

    def test_get_groups_empty_data(self, api):
        """Test getting groups with empty data."""
        api.data = {"data": {}}
        assert api.get_dtek_region_groups() == []


class TestDtekAPIBaseParseGroupHours:
    """Test _parse_group_hours method."""

    @pytest.mark.parametrize(
        "group_hours,expected",  # noqa: PT006
        [
            # 0 All yes - no outages
            ({str(i): "yes" for i in range(1, 25)}, []),
            # 1 All no - full day outage
            (
                {str(i): "no" for i in range(1, 25)},
                [(datetime.time(0, 0), datetime.time(23, 59, 59))],
            ),
            # 2 One range of no
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "14": "no",
                    "15": "no",
                    "16": "no",
                },
                [(datetime.time(13, 0), datetime.time(16, 0))],
            ),
            # 3 Two ranges of no
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "9": "no",
                    "10": "no",
                    "20": "no",
                    "21": "no",
                },
                [
                    (datetime.time(8, 0), datetime.time(10, 0)),
                    (datetime.time(19, 0), datetime.time(21, 0)),
                ],
            ),
            # 4 One range: second + no + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "13": "second",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "first",
                },
                [(datetime.time(12, 30), datetime.time(16, 30))],
            ),
            # 5 Two ranges: second + no + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "9": "second",
                    "10": "no",
                    "11": "first",
                    "20": "second",
                    "21": "no",
                    "22": "first",
                },
                [
                    (datetime.time(8, 30), datetime.time(10, 30)),
                    (datetime.time(19, 30), datetime.time(21, 30)),
                ],
            ),
            # 6 Adjacent second + first
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "21": "second",
                    "22": "first",
                },
                [(datetime.time(20, 30), datetime.time(21, 30))],
            ),
            # 7 mfirst status converted to no (ends at hour boundary)
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "13": "second",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "mfirst",
                },
                [(datetime.time(12, 30), datetime.time(17, 0))],
            ),
            # 8 msecond + mfirst combination (full outage)
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "13": "msecond",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                    "17": "mfirst",
                },
                [(datetime.time(12, 0), datetime.time(17, 0))],
            ),
        ],
    )
    def test_parse_group_hours(self, group_hours, expected):
        """Test parsing various group hour patterns."""
        result = _parse_group_hours(group_hours)
        assert result == expected


class TestDtekAPIBaseParsePresetGroupHours:
    """Test _parse_preset_group_hours method."""

    @pytest.mark.parametrize(
        "group_hours,expected",  # noqa: PT006
        [
            # Test hour format detection - "0" key present (0-23 format)
            (
                {"0": "yes", "1": "yes", "23": "yes"},
                [],
            ),
            # Test hour format detection - no "0" key (1-24 format)
            (
                {"1": "yes", "2": "yes", "24": "yes"},
                [],
            ),
            # Test basic outage with "no" status
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "11": "no",
                    "12": "no",
                },
                [(datetime.time(10, 0), datetime.time(12, 0))],
            ),
            # Test half-hour precision with "first" and "second"
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "11": "first",  # 10:00-10:30
                    "12": "second",  # 11:30-12:00
                },
                [
                    (datetime.time(10, 0), datetime.time(10, 30)),
                    (datetime.time(11, 30), datetime.time(12, 0)),
                ],
            ),
            # Test "maybe" status (treated as outage)
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "16": "maybe",
                },
                [(datetime.time(15, 0), datetime.time(16, 0))],
            ),
            # Test multiple separate outages
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "10": "no",
                    "11": "no",
                    "21": "no",
                },
                [
                    (datetime.time(9, 0), datetime.time(11, 0)),
                    (datetime.time(20, 0), datetime.time(21, 0)),
                ],
            ),
            # Test continuous outage across multiple hours
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "13": "no",
                    "14": "no",
                    "15": "no",
                    "16": "no",
                },
                [(datetime.time(12, 0), datetime.time(16, 0))],
            ),
            # Test "second" starting new outage
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "11": "second",  # Starts at 10:30
                },
                [(datetime.time(10, 30), datetime.time(11, 0))],
            ),
            # Test "first" ending outage at half-hour
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "11": "first",  # Ends at 10:30
                },
                [(datetime.time(10, 0), datetime.time(10, 30))],
            ),
            # Test end of day handling
            (
                {
                    **{str(i): "yes" for i in range(1, 25)},
                    "24": "no",  # Last hour
                },
                [(datetime.time(23, 0), datetime.time(23, 59, 59))],
            ),
        ],
    )
    def test_parse_preset_group_hours(self, group_hours, expected):
        """Test parsing various preset group hour patterns."""
        result = _parse_preset_group_hours(group_hours)
        assert result == expected


class TestDtekAPIBaseScheduledEvents:
    """Test get_scheduled_events method."""

    def test_get_scheduled_events_with_valid_data(self, api):
        """Test getting scheduled events with valid preset data."""
        # Mock preset data
        api.preset_data = {
            "data": {
                "GPV1.1": {
                    "1": {"10": "no", "11": "no"},  # Monday: 10:00-12:00 outage
                    "2": {"15": "yes"},  # Tuesday: no outage
                }
            }
        }
        api.group = "1.1"

        start_date = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=7)

        events = api.get_scheduled_events(start_date, end_date)

        # Should have events for Monday (day 1)
        assert len(events) > 0
        # Check that events have correct type and times
        for event in events:
            assert event.event_type.value == "Definite"
            if event.start.hour == 10:
                assert event.end.hour == 12

    def test_get_scheduled_events_no_preset_data(self, api):
        """Test getting scheduled events without preset data."""
        api.preset_data = None
        api.group = "1.1"

        start_date = dt_utils.now()
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_scheduled_events(start_date, end_date)
        assert events == []

    def test_get_scheduled_events_no_group(self, api):
        """Test getting scheduled events without group set."""
        api.preset_data = {"data": {}}
        api.group = None

        start_date = dt_utils.now()
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_scheduled_events(start_date, end_date)
        assert events == []

    def test_get_scheduled_events_empty_data(self, api):
        """Test getting scheduled events with empty preset data."""
        api.preset_data = {"data": {}}
        api.group = "1.1"

        start_date = dt_utils.now()
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_scheduled_events(start_date, end_date)
        assert events == []

    def test_get_scheduled_events_date_filtering(self, api):
        """Test that events are properly filtered by date range."""
        base_date = dt_utils.now().replace(hour=0, minute=0, second=0, microsecond=0)
        api.preset_data = {
            "data": {
                "GPV1.1": {
                    "1": {"10": "no"},  # Monday outage
                }
            }
        }
        api.group = "1.1"

        # Test range that includes Monday
        monday = base_date + datetime.timedelta(days=(7 - base_date.weekday()))
        start_date = monday
        end_date = monday + datetime.timedelta(days=1)

        events = api.get_scheduled_events(start_date, end_date)
        assert len(events) > 0

        # Test range that excludes Monday
        start_date = monday + datetime.timedelta(days=2)
        end_date = monday + datetime.timedelta(days=3)

        events = api.get_scheduled_events(start_date, end_date)
        assert len(events) == 0


class TestDtekAPIBaseTimestamps:
    """Test timestamp-related methods."""

    def test_get_updated_on_success(self, api):
        """Test getting updated timestamp."""
        api.data = {
            "data": {},
            "update": "29.10.2025 13:51",
            "today": int(TEST_TIMESTAMP),
        }
        updated = api.get_updated_on()
        assert updated is not None

    def test_get_updated_on_no_data(self, api):
        """Test getting updated timestamp without data."""
        assert api.get_updated_on() is None

    def test_get_updated_on_missing_update(self, api):
        """Test getting updated timestamp with missing update field."""
        api.data = {"data": {}}
        assert api.get_updated_on() is None


class TestDtekAPIBaseEvents:
    """Test event-related methods."""

    def test_get_current_event_during_outage(self, api, sample_data):
        """Test getting current event during an outage."""
        api.data = sample_data

        # Create a time during the outage (13:00 on the test day)
        day_dt = dt_utils.utc_from_timestamp(int(TEST_TIMESTAMP))
        day_dt = dt_utils.as_local(day_dt)
        current_time = day_dt.replace(hour=13, minute=0)

        event = api.get_current_event(current_time)
        assert event is not None
        assert event.start <= current_time < event.end

    def test_get_current_event_no_outage(self, api, sample_data):
        """Test getting current event when there's no outage."""
        api.data = sample_data

        # Create a time outside the outage (10:00 on the test day)
        day_dt = dt_utils.utc_from_timestamp(int(TEST_TIMESTAMP))
        day_dt = dt_utils.as_local(day_dt)
        current_time = day_dt.replace(hour=10, minute=0)

        event = api.get_current_event(current_time)
        assert event is None

    def test_get_current_event_no_data(self, api):
        """Test getting current event without data."""
        current_time = dt_utils.now()
        assert api.get_current_event(current_time) is None


class TestDtekAPIBaseEventMerging:
    """Test event merging functionality in DTEK base API."""

    def test_merge_adjacent_events_in_get_events(self, api):
        """Test that adjacent events are merged in get_events method."""
        # Create test data with two adjacent outage periods
        # This simulates: 10:00-11:00 and 11:00-12:00 outages
        test_timestamp = str(int(dt_utils.now().timestamp()))
        api.data = {
            "data": {
                test_timestamp: {
                    "GPV1.1": {
                        # All "yes" except hours 11 and 12 (10:00-12:00 outage)
                        **{str(i): "yes" for i in range(1, 25)},
                        "11": "no",  # 10:00-11:00
                        "12": "no",  # 11:00-12:00
                    },
                },
            },
            "update": "29.10.2025 13:51",
        }

        day_dt = dt_utils.utc_from_timestamp(int(test_timestamp))
        day_dt = dt_utils.as_local(day_dt)

        start_date = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_events(start_date, end_date)

        # Should be merged into one continuous event
        assert len(events) == 1
        assert events[0].start.hour == 10
        assert events[0].start.minute == 0
        assert events[0].end.hour == 12
        assert events[0].end.minute == 0
        assert events[0].event_type.value == "Definite"

    def test_merge_multiple_adjacent_events(self, api):
        """Test merging multiple adjacent events."""
        # Create test data with three adjacent outage periods
        # This simulates: 14:00-15:00, 15:00-16:00, and 16:00-17:00
        test_timestamp = str(int(dt_utils.now().timestamp()))
        api.data = {
            "data": {
                test_timestamp: {
                    "GPV1.1": {
                        # All "yes" except hours 15, 16, 17 (14:00-17:00 outage)
                        **{str(i): "yes" for i in range(1, 25)},
                        "15": "no",  # 14:00-15:00
                        "16": "no",  # 15:00-16:00
                        "17": "no",  # 16:00-17:00
                    },
                },
            },
            "update": "29.10.2025 13:51",
        }

        day_dt = dt_utils.utc_from_timestamp(int(test_timestamp))
        day_dt = dt_utils.as_local(day_dt)

        start_date = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_events(start_date, end_date)

        # Should be merged into one continuous event
        assert len(events) == 1
        assert events[0].start.hour == 14
        assert events[0].start.minute == 0
        assert events[0].end.hour == 17
        assert events[0].end.minute == 0

    def test_no_merge_non_adjacent_events(self, api):
        """Test that non-adjacent events are not merged."""
        # Create test data with two separate outage periods
        # This simulates: 10:00-11:00 and 13:00-14:00 (with gap at 12:00)
        test_timestamp = str(int(dt_utils.now().timestamp()))
        api.data = {
            "data": {
                test_timestamp: {
                    "GPV1.1": {
                        # All "yes" except hours 11 and 14
                        **{str(i): "yes" for i in range(1, 25)},
                        "11": "no",  # 10:00-11:00
                        "14": "no",  # 13:00-14:00
                    },
                },
            },
            "update": "29.10.2025 13:51",
        }

        day_dt = dt_utils.utc_from_timestamp(int(test_timestamp))
        day_dt = dt_utils.as_local(day_dt)

        start_date = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_events(start_date, end_date)

        # Should remain as two separate events
        assert len(events) == 2
        assert events[0].start.hour == 10
        assert events[0].end.hour == 11
        assert events[1].start.hour == 13
        assert events[1].end.hour == 14

    def test_merge_adjacent_with_half_hour_precision(self, api):
        """Test merging events with half-hour precision (second/first)."""
        # Create test data with adjacent half-hour periods
        # This simulates: 12:30-13:00 and 13:00-13:30
        test_timestamp = str(int(dt_utils.now().timestamp()))
        api.data = {
            "data": {
                test_timestamp: {
                    "GPV1.1": {
                        # All "yes" except specific half-hours
                        **{str(i): "yes" for i in range(1, 25)},
                        "13": "second",  # 12:30-13:00
                        "14": "first",  # 13:00-13:30
                    },
                },
            },
            "update": "29.10.2025 13:51",
        }

        day_dt = dt_utils.utc_from_timestamp(int(test_timestamp))
        day_dt = dt_utils.as_local(day_dt)

        start_date = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_events(start_date, end_date)

        # Should be merged into one continuous event
        assert len(events) == 1
        assert events[0].start.hour == 12
        assert events[0].start.minute == 30
        assert events[0].end.hour == 13
        assert events[0].end.minute == 30

    def test_merge_across_midnight_not_supported(self, api):
        """Test that events across midnight are not merged (DTEK doesn't span days)."""
        # DTEK API processes one day at a time, so midnight spanning isn't relevant
        # This test just ensures the basic functionality works
        test_timestamp = str(int(dt_utils.now().timestamp()))
        api.data = {
            "data": {
                test_timestamp: {
                    "GPV1.1": {
                        # Simple case: 23:00-24:00 outage
                        **{str(i): "yes" for i in range(1, 25)},
                        "24": "no",
                    },
                },
            },
            "update": "29.10.2025 13:51",
        }

        day_dt = dt_utils.utc_from_timestamp(int(test_timestamp))
        day_dt = dt_utils.as_local(day_dt)

        start_date = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + datetime.timedelta(days=1)

        events = api.get_events(start_date, end_date)

        assert len(events) == 1
        assert events[0].start.hour == 23
        assert events[0].start.minute == 0
        assert events[0].end.hour == 0
        assert events[0].end.minute == 0
        assert events[0].end.second == 0
