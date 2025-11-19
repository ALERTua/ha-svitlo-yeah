"""Tests for JSON DTEK API (alternative data sources)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.svitlo_yeah.api.dtek.json import (
    DtekAPIJson,
    _is_data_sufficiently_fresh,
)
from custom_components.svitlo_yeah.models import DTEK_PROVIDER_URLS, DTEKJsonProvider

TEST_GROUP = "1.1"
TEST_URLS = ["https://example.com/data1.json", "https://example.com/data2.json"]


@pytest.fixture(name="api")
def _api():
    """Create a JSON DTEK API instance."""
    return DtekAPIJson(urls=TEST_URLS, group=TEST_GROUP)


def create_sample_json_data(update_dt: datetime | None = None):
    """Create sample JSON data with specified update_dt."""
    now = datetime.now(UTC)
    update_dt = update_dt or now
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "data": {
            str(midnight.timestamp()): {
                "GPV1.1": {
                    "1": "yes",
                    "2": "yes",
                    "3": "yes",
                    "10": "no",
                    "11": "no",
                    "12": "no",
                    "13": "yes",
                    "14": "yes",
                    "15": "yes",
                },
            },
        },
        "update": update_dt.strftime("%d.%m.%Y %H:%M"),
        "today": midnight.timestamp(),
    }


class TestJsonDtekAPIInit:
    """Test JsonDtekAPI initialization."""

    def test_init_with_group_and_urls(self):
        """Test initialization with group and URLs."""
        api = DtekAPIJson(urls=TEST_URLS, group=TEST_GROUP)
        assert api.group == TEST_GROUP
        assert api.urls == TEST_URLS
        assert api.data is None

    def test_init_without_group(self):
        """Test initialization without group."""
        api = DtekAPIJson(urls=TEST_URLS)
        assert api.group is None


class TestJsonDtekAPIFetchData:
    """Test JSON data fetching methods."""

    async def test_fetch_data_no_fallback_when_stale(self, api):
        """Test that when all sources are stale, data remains None (no fallback implemented)."""
        stale_data = create_sample_json_data(
            datetime.now(UTC) - timedelta(days=1000)
        )  # 2+ days old

        with patch(
            "custom_components.svitlo_yeah.api.dtek.json.aiohttp.ClientSession"
        ) as mock_session_class:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value=stale_data)
            mock_response.raise_for_status = MagicMock()

            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            # First call - all sources stale, so data remains None
            await api.fetch_data()
            assert api.data is None

            # Second call - still None (no caching of stale data)
            await api.fetch_data()
            assert api.data is None

    async def test_fetch_data_all_fail(self, api):
        """Test when all URLs fail."""
        with patch(
            "custom_components.svitlo_yeah.api.dtek.json.aiohttp.ClientSession"
        ) as mock_session_class:
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock(
                side_effect=Exception("Connection failed")
            )

            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await api.fetch_data()
            # Should not crash, data remains None
            assert api.data is None

    @pytest.mark.skip(reason="Manual test only - requires real network access")
    async def test_fetch_data_real_endpoints(self):
        """Test fetching real data from DTEK JSON endpoints."""
        for region in DTEKJsonProvider:
            urls = DTEK_PROVIDER_URLS[region]
            api = DtekAPIJson(urls=urls)
            await api.fetch_data()
            assert api.data is not None, f"error getting data for {region}"
            groups = api.get_dtek_region_groups()
            assert isinstance(groups, list), (
                f"wrong data type for groups while getting info for {region}"
            )
            assert len(groups), f"no groups while getting info for {region}"

            api.group = groups[0]
            updated_on = api.get_updated_on()
            assert updated_on, f"no updated_on while getting info for {region}"


class TestJsonDtekAPIFreshness:
    """Test data freshness checking."""

    def test_is_data_fresh(self):
        """Test freshness detection."""
        # Test with current time minus 1 hour (should definitely be fresh)
        recent_time = datetime.now(UTC) - timedelta(hours=1)
        current_data = create_sample_json_data(recent_time)
        assert _is_data_sufficiently_fresh(current_data)

    def test_is_data_stale(self):
        """Test stale data detection."""
        # Very old data
        old_data = create_sample_json_data(datetime.now(UTC) - timedelta(days=1000))
        assert not _is_data_sufficiently_fresh(old_data)

    def test_is_data_missing_timestamp(self):
        """Test data without timestamp."""
        data_no_timestamp = {}
        assert not _is_data_sufficiently_fresh(data_no_timestamp)

    def test_is_data_invalid_timestamp(self):
        """Test data with invalid timestamp."""
        data_bad_timestamp = {
            "regionId": "test",
            "fact": {
                "update": "invalid-date",
            },
        }
        assert not _is_data_sufficiently_fresh(data_bad_timestamp)
