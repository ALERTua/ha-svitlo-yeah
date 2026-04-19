"""Tests for JSON DTEK API (alternative data sources)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.svitlo_yeah.api.dtek.json import (
    DtekAPIJson,
    _is_data_sufficiently_fresh,
)
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TEST_GROUP = "1.1"
TEST_URLS = ["https://example.com/data1.json", "https://example.com/data2.json"]


def _build_json_payload(update_dt: datetime) -> dict:
    """Build a `{fact, preset}` payload with the given update datetime."""
    fact = create_sample_json_data(update_dt)
    preset = {"data": {f"GPV{TEST_GROUP}": {}}}
    return {"fact": fact, "preset": preset}


def _make_mock_session(payloads_by_url: dict[str, str | Exception]):
    """
    Build a mock aiohttp.ClientSession driven by per-URL payloads.

    Each value is either a JSON string to be returned as response text,
    or an Exception to raise from `raise_for_status()`.
    """

    def _session_factory():
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        async def _get(url: str, *_args: object, **_kwargs: object):
            payload = payloads_by_url[url]
            mock_response = AsyncMock()
            if isinstance(payload, Exception):
                mock_response.raise_for_status = MagicMock(side_effect=payload)
            else:
                mock_response.raise_for_status = MagicMock()
                mock_response.text = AsyncMock(return_value=payload)
            return mock_response

        mock_session.get = _get
        return mock_session

    return MagicMock(side_effect=_session_factory)


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

    @pytest.mark.e2e(reason="Requires real network access to DTEK endpoints")
    async def test_fetch_data_real_endpoints(self):
        """Test fetching real data from DTEK JSON endpoints."""
        for provider_key in DTEK_PROVIDER_URLS:
            urls = DTEK_PROVIDER_URLS[provider_key]
            api = DtekAPIJson(urls=urls)
            await api.fetch_data()
            assert api.data is not None, f"error getting data for {provider_key}"
            groups = api.get_dtek_region_groups()
            assert isinstance(groups, list), (
                f"wrong data type for groups while getting info for {provider_key}"
            )
            assert len(groups), f"no groups while getting info for {provider_key}"

            api.group = groups[0]
            updated_on = api.get_updated_on()
            assert updated_on, f"no updated_on while getting info for {provider_key}"


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


class TestFetchDataAllowStale:
    """Exercise the allow_stale_data flag of DtekAPIJson.fetch_data."""

    @staticmethod
    def _patch_session(payloads: dict[str, str | Exception]) -> object:
        return patch(
            "custom_components.svitlo_yeah.api.dtek.json.aiohttp.ClientSession",
            new=_make_mock_session(payloads),
        )

    async def test_stale_without_allow_stale_returns_false_false(self, api):
        """Default flag keeps historical behavior: stale is discarded."""
        stale_dt = datetime.now(UTC) - timedelta(days=10)
        payload = json.dumps(_build_json_payload(stale_dt))
        payloads = dict.fromkeys(TEST_URLS, payload)

        with self._patch_session(payloads):
            success, is_stale = await api.fetch_data()

        assert success is False
        assert is_stale is False
        assert api.data is None

    async def test_stale_with_allow_stale_returns_true_true(self, api):
        """allow_stale_data=True accepts the freshest stale source."""
        stale_dt = datetime.now(UTC) - timedelta(days=10)
        payload = json.dumps(_build_json_payload(stale_dt))
        payloads = dict.fromkeys(TEST_URLS, payload)

        with self._patch_session(payloads):
            success, is_stale = await api.fetch_data(allow_stale_data=True)

        assert success is True
        assert is_stale is True
        assert api.data is not None
        assert api.data.get("update")
        assert api.get_dtek_region_groups() == [TEST_GROUP]

    @pytest.mark.parametrize("allow_stale_data", [False, True])
    async def test_fresh_returns_true_false_regardless_of_flag(
        self, api, allow_stale_data
    ):
        """Fresh data short-circuits; is_stale is always False."""
        fresh_dt = datetime.now(UTC) - timedelta(hours=1)
        payload = json.dumps(_build_json_payload(fresh_dt))
        payloads = dict.fromkeys(TEST_URLS, payload)

        with self._patch_session(payloads):
            success, is_stale = await api.fetch_data(
                allow_stale_data=allow_stale_data,
            )

        assert success is True
        assert is_stale is False
        assert api.data is not None

    @pytest.mark.parametrize("allow_stale_data", [False, True])
    async def test_no_sources_returns_false_false(self, api, allow_stale_data):
        """All URLs failing → (False, False) under either flag value."""
        payloads = dict.fromkeys(TEST_URLS, RuntimeError("boom"))

        with self._patch_session(payloads):
            success, is_stale = await api.fetch_data(
                allow_stale_data=allow_stale_data,
            )

        assert success is False
        assert is_stale is False
        assert api.data is None

    async def test_picks_freshest_stale(self, api):
        """With multiple stale sources, the newest one wins."""
        older = datetime.now(UTC) - timedelta(days=30)
        newer = datetime.now(UTC) - timedelta(days=5)
        payloads = {
            TEST_URLS[0]: json.dumps(_build_json_payload(older)),
            TEST_URLS[1]: json.dumps(_build_json_payload(newer)),
        }

        with self._patch_session(payloads):
            success, is_stale = await api.fetch_data(allow_stale_data=True)

        assert success is True
        assert is_stale is True
        assert api.data["update"] == newer.strftime("%d.%m.%Y %H:%M")
