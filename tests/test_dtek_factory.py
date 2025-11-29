"""Tests for DTEK API factory function and region selection."""

from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS
from custom_components.svitlo_yeah.models.providers import DTEKJsonProvider


class TestCreateDtekApi:
    """Test the create_dtek_api factory function."""

    def test_create_json_api_with_region(self):
        """Test creating JSON API when region is specified."""
        region = DTEKJsonProvider.KYIV_REGION
        api = DtekAPIJson(DTEK_PROVIDER_URLS[region], "2.2")
        assert isinstance(api, DtekAPIJson)
        assert api.group == "2.2"
        assert api.urls == DTEK_PROVIDER_URLS[region]

    def test_create_api_for_all_regions(self):
        """Test factory can create JSON APIs for all regions."""
        for region in DTEKJsonProvider:
            api = DtekAPIJson(DTEK_PROVIDER_URLS[region], "1.1")
            assert isinstance(api, DtekAPIJson)
            assert api.urls == DTEK_PROVIDER_URLS[region]
