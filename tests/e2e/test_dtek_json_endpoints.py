"""End-to-end tests against the real DTEK JSON sources (real network access)."""

from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.svitlo_yeah.api.dtek.base import DtekAPIBase
from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson, FetchResult
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS


async def _make_api_real(**kwargs: object) -> DtekAPIJson:
    """Create a DtekAPIJson with a real aiohttp session for e2e tests."""
    session = aiohttp.ClientSession()
    hass = MagicMock()

    # Create API instance manually to bypass async_get_clientsession
    api = object.__new__(DtekAPIJson)
    # noinspection PyTypeChecker
    DtekAPIBase.__init__(api, kwargs.get("group"))
    api.hass = hass
    api.session = session
    api.urls = kwargs.get("urls", [])
    api.preset_data = None

    return api


class TestJsonDtekAPIRealEndpoints:
    """Fetch every configured DTEK JSON source over the network."""

    @pytest.mark.parametrize("provider_key", list(DTEK_PROVIDER_URLS))
    async def test_fetch_data_real_endpoints(self, provider_key):
        """
        Test fetching real data from a DTEK JSON endpoint.

        Stale upstream data is not our bug, so those providers are skipped
        rather than failed; a genuinely unreachable/broken source still fails.
        """
        urls = DTEK_PROVIDER_URLS[provider_key]
        api = await _make_api_real(urls=urls)
        try:
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
        finally:
            await api.session.close()

    @pytest.mark.parametrize("provider_key", list(DTEK_PROVIDER_URLS))
    async def test_setup_groups_real_endpoints(self, provider_key):
        """
        Every provider must offer groups on setup, as the config flow asks for them.

        The config flow accepts stale data with consent, so stale upstream data
        must still give groups, from the fact or from the preset schedule.
        """
        urls = DTEK_PROVIDER_URLS[provider_key]
        api = await _make_api_real(urls=urls)
        try:
            result = await api.fetch_data(allow_stale_data=True)
            assert result is not FetchResult.UNAVAILABLE, (
                f"no source could be fetched for {provider_key} {urls}"
            )
            assert api.get_dtek_region_groups(), (
                f"no groups on setup for {provider_key} {urls} (result={result})"
            )
        finally:
            await api.session.close()
