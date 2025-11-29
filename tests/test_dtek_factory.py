"""Tests for DTEK API factory function and region selection."""

from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson
from custom_components.svitlo_yeah.const import DTEK_PROVIDER_URLS

TEST_GROUP = "1.1"


class TestCreateDtekApi:
    """Test the create_dtek_api factory function."""

    def test_create_json_api_with_region(self):
        """Test creating JSON API when region is specified."""
        provider_key = "kyiv_region"
        api = DtekAPIJson(
            urls=next(iter(DTEK_PROVIDER_URLS.values())), group=TEST_GROUP
        )
        assert isinstance(api, DtekAPIJson)
        assert api.group == TEST_GROUP
        assert api.urls == DTEK_PROVIDER_URLS[provider_key]

    def test_create_api_for_all_regions(self):
        """Test factory can create JSON APIs for all regions."""
        for provider_key in DTEK_PROVIDER_URLS:
            api = DtekAPIJson(DTEK_PROVIDER_URLS[provider_key], TEST_GROUP)
            assert isinstance(api, DtekAPIJson)
            assert api.urls == DTEK_PROVIDER_URLS[provider_key]
