"""Tests for common_tools module."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.common_tools import parse_timestamp


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
        assert isinstance(result, datetime.datetime)
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
        """Test that naive DD.MM.YYYY formats are treated as Europe/Kyiv and converted to local."""
        # Test a specific naive format
        timestamp_str = "07.12.2025 00:01"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        # Should be parsed as Europe/Kyiv and converted to local
        expected_kyiv = datetime.datetime(
            2025, 12, 7, 0, 1, tzinfo=ZoneInfo("Europe/Kyiv")
        )
        expected_local = dt_utils.as_local(expected_kyiv)
        assert result == expected_local

    def test_parse_timestamp_iso_with_timezone(self):
        """Test parsing ISO 8601 with timezone offset."""
        timestamp_str = "2025-12-07T11:10:49.815+02:00"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        # Should be converted to local timezone
        expected_utc = datetime.datetime(
            2025, 12, 7, 9, 10, 49, 815000, tzinfo=datetime.UTC
        )
        expected_local = dt_utils.as_local(expected_utc)
        assert result == expected_local

    def test_parse_timestamp_iso_utc(self):
        """Test parsing ISO 8601 UTC format."""
        timestamp_str = "2025-12-07T11:10:49.815Z"
        result = parse_timestamp(timestamp_str)

        assert result is not None
        expected_utc = datetime.datetime(
            2025, 12, 7, 11, 10, 49, 815000, tzinfo=datetime.UTC
        )
        expected_local = dt_utils.as_local(expected_utc)
        assert result == expected_local
