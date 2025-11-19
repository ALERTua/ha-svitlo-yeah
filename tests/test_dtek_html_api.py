"""Tests for HTML DTEK API (original DTEK scraping)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.svitlo_yeah.api.dtek.html import DtekAPIHtml

TEST_GROUP = "1.1"
TEST_TIMESTAMP = "1761688800"


@pytest.fixture(name="api")
def _api():
    """Create a HTML DTEK API instance."""
    return DtekAPIHtml(group=TEST_GROUP)


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
            },
        },
        "update": "29.10.2025 13:51",
        "today": 1761688800,
    }


@pytest.fixture
def sample_html():
    """Sample HTML with DisconSchedule.fact."""
    return """<html><body><script>
DisconSchedule.currentWeekDayIndex = 3
DisconSchedule.fact = {"data":{"1761688800":{"GPV1.1":{"1":"yes","2":"yes","3":"yes","4":"yes","5":"yes","6":"yes","7":"yes","8":"yes","9":"yes","10":"yes","11":"yes","12":"yes","13":"second","14":"no","15":"no","16":"no","17":"first","18":"yes","19":"yes","20":"yes","21":"yes","22":"yes","23":"yes","24":"yes"},"GPV1.2":{"1":"yes","2":"yes","3":"yes","4":"yes","5":"yes","6":"yes","7":"yes","8":"yes","9":"yes","10":"yes","11":"yes","12":"yes","13":"second","14":"no","15":"no","16":"no","17":"first","18":"yes","19":"yes","20":"yes","21":"yes","22":"yes","23":"yes","24":"yes"}},"1761775200":{"GPV1.1":{"1":"yes","2":"yes","3":"yes","4":"yes","5":"yes","6":"yes","7":"yes","8":"yes","9":"yes","10":"yes","11":"yes","12":"yes","13":"yes","14":"yes","15":"yes","16":"yes","17":"yes","18":"yes","19":"yes","20":"yes","21":"yes","22":"yes","23":"yes","24":"yes"}},"update":"29.10.2025 13:51","today":1761688800}}</script><script type="text/javascript" src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3&ns=1&cb=330913616" async></script>
</body></html>"""


class TestHtmlDtekAPIInit:
    """Test HtmlDtekAPI initialization."""

    def test_init_with_group(self):
        """Test initialization with group."""
        api = DtekAPIHtml(group=TEST_GROUP)
        assert api.group == TEST_GROUP
        assert api.data is None

    def test_init_without_group(self):
        """Test initialization without group."""
        api = DtekAPIHtml()
        assert api.group is None


class TestHtmlDtekAPIFetchData:
    """Test HTML data fetching methods."""

    async def test_fetch_data_success(self, api, sample_html):
        """Test successful HTML data fetch."""
        with patch(
            "custom_components.svitlo_yeah.api.dtek.html.aiohttp.ClientSession"
        ) as mock_session_class:
            mock_response = AsyncMock()
            mock_response.text = AsyncMock(return_value=sample_html)
            mock_response.raise_for_status = MagicMock()

            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            await api.fetch_data()
            assert api.data is not None
            assert "data" in api.data
            assert TEST_TIMESTAMP in api.data["data"]

    @pytest.mark.skip(reason="Manual test only - requires real network access")
    async def test_real_data(self):
        """Test fetching real data from DTEK website."""
        api = DtekAPIHtml(group=TEST_GROUP)
        await api.fetch_data()
        assert api.data is not None
        assert "data" in api.data
        assert "update" in api.data
