"""Tests for common_tools module."""

import datetime as dt
import logging

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.common_tools import (
    parse_periods,
    parse_timestamp,
)
from custom_components.svitlo_yeah.const import TZ_UA
from custom_components.svitlo_yeah.models import PlannedOutageEventType

DAY = dt.date(2026, 10, 11)


def _kyiv(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ_UA)


class TestParsePeriods:
    """The periods of E-Svitlo and of the site of SOE give the outages of one day."""

    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            ("10:30", "12:00", (_kyiv(11, 10, 30), _kyiv(11, 12))),
            ("22:00", "00:00", (_kyiv(11, 22), _kyiv(12, 0))),
            ("00:00", "00:00", (_kyiv(11, 0), _kyiv(12, 0))),
            ("23:00", "02:00", (_kyiv(11, 23), _kyiv(12, 2))),
            ("22:00", "24:00", (_kyiv(11, 22), _kyiv(12, 0))),
            ("00:00", "24:00", (_kyiv(11, 0), _kyiv(12, 0))),
        ],
        ids=[
            "same_day",
            "until_midnight",
            "whole_day",
            "past_midnight",
            "until_24_00",
            "whole_day_until_24_00",
        ],
    )
    def test_period_gives_the_outage(self, start, end, expected):
        """The ends "00:00" and "24:00", and an end before the start, are next day."""
        events = parse_periods([{"start_time": start, "end_time": end}], DAY)

        assert [(e.start, e.end) for e in events] == [expected]
        assert events[0].event_type is PlannedOutageEventType.DEFINITE

    @pytest.mark.parametrize(
        "periods",
        [
            None,
            "10:00-12:00",
            {"start_time": "10:00", "end_time": "12:00"},
            ["10:00-12:00", None, ["10:00", "12:00"]],
            [{"start_time": "10:00"}, {"end_time": "12:00"}, {}],
            [{"start_time": "10:00", "end_time": ""}],
            [{"start_time": "25:00", "end_time": "12:00"}],
            [{"start_time": 10, "end_time": 12}],
        ],
        ids=[
            "none",
            "text",
            "one_period_not_in_a_list",
            "periods_of_another_shape",
            "missing_times",
            "empty_time",
            "bad_time",
            "times_not_text",
        ],
    )
    def test_periods_of_another_shape_give_no_outages(self, periods):
        """A period without usable times gives no outage, and raises no error."""
        assert parse_periods(periods, DAY) == []

    def test_period_without_a_time_logs_no_error(self, caplog):
        """A period that has no end yet is no parse error, so it logs nothing."""
        caplog.set_level(logging.DEBUG)

        assert parse_periods([{"start_time": "10:00", "end_time": None}], DAY) == []
        assert caplog.records == []

    def test_bad_period_does_not_hide_the_good_ones(self):
        """The periods with usable times give outages next to a bad period."""
        events = parse_periods(
            [
                {"start_time": "INVALID", "end_time": "12:00"},
                {"start_time": "14:00", "end_time": "14:30"},
            ],
            DAY,
        )

        assert [(e.start, e.end) for e in events] == [
            (_kyiv(11, 14), _kyiv(11, 14, 30))
        ]


class TestParseTimestamp:
    """Test parse_timestamp function."""

    @pytest.mark.parametrize(
        ("timestamp_str", "expected_description"),
        [
            ("1733520000", "Unix timestamp"),
            ("1733520000.5", "Unix timestamp with decimals"),
            ("07.12.2025 00:01", "DD.MM.YYYY HH:MM format"),
            ("00:01 07.12.2025", "HH:MM DD.MM.YYYY format"),
            ("2025-12-07T11:10:49.815+02:00", "ISO 8601 with timezone"),
            ("2025-12-07T11:10:49.815Z", "ISO 8601 UTC"),
            ("2025-12-07T11:10:49", "ISO 8601 without microseconds"),
        ],
    )
    def test_parse_timestamp_formats(self, timestamp_str, expected_description):
        """Test parsing various timestamp formats."""
        result = parse_timestamp(timestamp_str)
        assert result is not None, (
            f"Failed to parse {expected_description}: {timestamp_str}"
        )
        assert isinstance(result, dt.datetime)
        assert result.tzinfo is not None, (
            f"Parsed datetime should be timezone-aware: {result}"
        )

    def test_parse_timestamp_invalid(self):
        """Test parsing invalid timestamp strings."""
        result = parse_timestamp("invalid timestamp")
        assert result is None

    def test_parse_timestamp_empty(self):
        """Test parsing empty string."""
        result = parse_timestamp("")
        assert result is None

    def test_parse_timestamp_none(self):
        """Test parsing None."""
        result = parse_timestamp(None)
        assert result is None

    def test_parse_timestamp_naive_formats_as_local(self):
        """
        A naive DD.MM.YYYY format means the time of Europe/Kyiv.

        The parser converts it to the local time.
        """
        # Test a specific naive format
        timestamp_str = "07.12.2025 00:01"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        # Should be parsed as Europe/Kyiv and converted to local
        expected_kyiv = dt.datetime(2025, 12, 7, 0, 1, tzinfo=TZ_UA)
        expected_local = dt_utils.as_local(expected_kyiv)
        assert result == expected_local

    def test_parse_timestamp_iso_with_timezone(self):
        """Test parsing ISO 8601 with timezone offset."""
        timestamp_str = "2025-12-07T11:10:49.815+02:00"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        # Should be converted to local timezone
        expected_utc = dt.datetime(2025, 12, 7, 9, 10, 49, 815000, tzinfo=dt.UTC)
        expected_local = dt_utils.as_local(expected_utc)
        assert result == expected_local

    def test_parse_timestamp_iso_utc(self):
        """Test parsing ISO 8601 UTC format."""
        timestamp_str = "2025-12-07T11:10:49.815Z"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        expected_utc = dt.datetime(2025, 12, 7, 11, 10, 49, 815000, tzinfo=dt.UTC)
        expected_local = dt_utils.as_local(expected_utc)
        assert result == expected_local
