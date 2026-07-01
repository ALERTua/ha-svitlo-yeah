"""Tests for JSON DTEK API (alternative data sources)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.svitlo_yeah.api.dtek.json import (
    DtekAPIJson,
    FetchResult,
    _is_data_sufficiently_fresh,
)
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TEST_GROUP = "1.1"
TEST_URLS = ["https://example.com/data1.json", "https://example.com/data2.json"]


@pytest.fixture(name="api")
def _api():
    """Create a JSON DTEK API instance."""
    return DtekAPIJson(urls=TEST_URLS, group=TEST_GROUP)


def _make_response(payload: dict | None = None, *, raise_error: bool = False):
    """Build a mocked aiohttp response yielding `payload` from .text()."""
    resp = AsyncMock()
    if raise_error:
        resp.raise_for_status = MagicMock(side_effect=Exception("Connection failed"))
    else:
        resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value=json.dumps(payload) if payload is not None else ""
    )
    return resp


def _patch_session(responses: list):
    """Patch aiohttp.ClientSession so each URL fetch yields the next response."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=responses)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "custom_components.svitlo_yeah.api.dtek.json.aiohttp.ClientSession",
        return_value=mock_session,
    )


def _payload(update_dt: datetime, preset: dict | None = None) -> dict:
    """Wrap sample fact data in the real `{fact, preset}` source envelope."""
    return {"fact": create_sample_json_data(update_dt), "preset": preset or {}}


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

    @pytest.mark.e2e(reason="Requires real network access to DTEK endpoints")
    @pytest.mark.parametrize("provider_key", list(DTEK_PROVIDER_URLS))
    async def test_fetch_data_real_endpoints(self, provider_key):
        """
        Test fetching real data from a DTEK JSON endpoint.

        Stale upstream data is not our bug, so those providers are skipped
        rather than failed; a genuinely unreachable/broken source still fails.
        """
        urls = DTEK_PROVIDER_URLS[provider_key]
        api = DtekAPIJson(urls=urls)
        result = await api.fetch_data()
        if result is FetchResult.STALE:
            pytest.skip(f"{provider_key}: upstream data is stale {urls}")
        assert result is FetchResult.FRESH, (
            f"failed to fetch fresh data for {provider_key} {urls} (result={result})"
        )

        groups = api.get_dtek_region_groups()
        assert isinstance(groups, list), (
            f"wrong data type for groups while getting info for {provider_key}"
        )
        assert len(groups), f"no groups while getting info for {provider_key}"

        api.group = groups[0]
        updated_on = api.get_updated_on()
        assert updated_on, f"no updated_on while getting info for {provider_key}"


class TestJsonDtekAPIStaleData:
    """Test the FetchResult contract and stale-data adoption."""

    async def test_fresh_returns_fresh_regardless_of_flag(self, api):
        """A fresh source yields FRESH and populated data under either flag."""
        fresh = _payload(datetime.now(UTC) - timedelta(hours=1))

        for allow in (False, True):
            api.data = None
            with _patch_session([_make_response(fresh)]):
                result = await api.fetch_data(allow_stale_data=allow)
            assert result is FetchResult.FRESH
            assert api.data is not None

    async def test_stale_without_allow_keeps_data_none(self, api):
        """All-stale sources yield STALE but do not populate data by default."""
        stale = _payload(datetime.now(UTC) - timedelta(days=1000))

        with _patch_session([_make_response(stale), _make_response(stale)]):
            result = await api.fetch_data()

        assert result is FetchResult.STALE
        assert api.data is None

    async def test_stale_with_allow_adopts_data(self, api):
        """With consent, the freshest stale source is adopted into data."""
        stale = _payload(datetime.now(UTC) - timedelta(days=1000))

        with _patch_session([_make_response(stale)]):
            result = await api.fetch_data(allow_stale_data=True)

        assert result is FetchResult.STALE
        assert api.data is not None
        assert api.get_dtek_region_groups() == ["1.1"]

    async def test_stale_with_allow_picks_freshest(self, api):
        """When several stale sources exist, the newest one wins."""
        older = _payload(datetime.now(UTC) - timedelta(days=1000))
        newer = _payload(datetime.now(UTC) - timedelta(days=10))

        with _patch_session([_make_response(older), _make_response(newer)]):
            result = await api.fetch_data(allow_stale_data=True)

        assert result is FetchResult.STALE
        assert api.data["update"] == newer["fact"]["update"]

    async def test_no_sources_returns_unavailable(self, api):
        """When every source errors, the result is UNAVAILABLE under any flag."""
        for allow in (False, True):
            api.data = None
            with _patch_session(
                [_make_response(raise_error=True), _make_response(raise_error=True)]
            ):
                result = await api.fetch_data(allow_stale_data=allow)
            assert result is FetchResult.UNAVAILABLE
            assert api.data is None


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
