"""Tests for E-Svitlo API."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from custom_components.svitlo_yeah.api.e_svitlo import ESvitloClient
from custom_components.svitlo_yeah.const import E_SVITLO_ERROR_NOT_LOGGED_IN, TZ_UA
from custom_components.svitlo_yeah.models import ESvitloProvider, PlannedOutageEventType

TEST_USERNAME = "test_user"
TEST_PWD = "test_password"  # noqa: S105
TEST_ACCOUNT_ID = "12345"
TEST_REGION = "Sumy"


@pytest.fixture(name="provider")
def _provider():
    return ESvitloProvider(
        user_name=TEST_USERNAME,
        password=TEST_PWD,
        region_name=TEST_REGION,
        account_id=TEST_ACCOUNT_ID,
    )


@pytest.fixture(name="mock_session_post")
def _mock_session_post():
    """Mock aiohttp session post."""
    with patch("aiohttp.ClientSession.post") as mock_post:
        yield mock_post


@pytest.fixture(name="client")
def _client(provider, mock_session_post):
    """Create a client instance with mocked session."""
    hass_mock = MagicMock()
    with patch(
        "custom_components.svitlo_yeah.api.e_svitlo.async_get_clientsession"
    ) as mock_helper:
        # The provided snippet seems to be a mix of client and coordinator setup.
        # Assuming the intent was to keep the client setup and potentially add coordinator setup elsewhere.
        # For now, faithfully applying the client-related part of the snippet.
        mock_helper.return_value = MagicMock()
        mock_helper.return_value.post = mock_session_post
        client = ESvitloClient(hass_mock, provider)
        yield client


@pytest.mark.asyncio
class TestESvitloClientBase:
    """Base tests for auth and init."""

    async def test_init(self, client):
        """Test initialization."""
        assert client.user_name == TEST_USERNAME
        assert client.user_id == TEST_ACCOUNT_ID

    async def test_login_success(self, client, mock_session_post):
        """Test successful login."""
        mock_response = AsyncMock(status=200)
        mock_response.json = AsyncMock(return_value={"data": {"login": True}})
        mock_session_post.return_value.__aenter__.return_value = mock_response

        assert await client.login() is True
        assert client.is_authenticated is True

    async def test_login_failure(self, client, mock_session_post):
        """Test failed login."""
        mock_response = AsyncMock(status=200)
        mock_response.json = AsyncMock(return_value={"data": {"login": False}})
        mock_session_post.return_value.__aenter__.return_value = mock_response

        assert await client.login() is False
        assert client.is_authenticated is False

    async def test_login_http_error(self, client, mock_session_post):
        """Test login HTTP error."""
        mock_response = AsyncMock(status=500)
        mock_session_post.return_value.__aenter__.return_value = mock_response
        assert await client.login() is False

    async def test_login_exception(self, client, mock_session_post):
        """Test login exception."""
        mock_session_post.side_effect = ClientError()
        assert await client.login() is False


@pytest.mark.asyncio
class TestESvitloClientData:
    """Tests for data fetching."""

    async def test_get_accounts(self, client, mock_session_post):
        """Test get accounts."""
        client.is_authenticated = True
        data = {"data": {"lst_ls": [{"a": 123}]}}

        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        accounts = await client.get_accounts()
        assert accounts == [{"a": 123}]

    async def test_get_accounts_relogin(self, client, mock_session_post):
        """Test automatic re-login when session expired."""
        client.is_authenticated = True
        expired = {"error": {"err": E_SVITLO_ERROR_NOT_LOGGED_IN}}
        login_ok = {"data": {"login": True}}
        data = {"data": {"lst_ls": [{"a": 999}]}}

        resp_expired = AsyncMock(status=200)
        resp_expired.json = AsyncMock(return_value=expired)

        resp_login = AsyncMock(status=200)
        resp_login.json = AsyncMock(return_value=login_ok)

        resp_data = AsyncMock(status=200)
        resp_data.json = AsyncMock(return_value=data)

        # Sequence: get_accounts (fail) -> login -> get_accounts (success)
        # Note: logic calls login() which does a POST, then get_accounts() which does a POST
        mock_session_post.return_value.__aenter__.side_effect = [
            resp_expired,
            resp_login,
            resp_data,
        ]

        accounts = await client.get_accounts()
        assert accounts == [{"a": 999}]

    async def test_get_accounts_relogin_fail(self, client, mock_session_post):
        """Test get accounts relogin failure."""
        client.is_authenticated = True
        expired = {"error": {"err": E_SVITLO_ERROR_NOT_LOGGED_IN}}
        # Login returns false (using status 200 but logic false)
        login_fail = {"data": {"login": False}}

        resp_expired = AsyncMock(status=200)
        resp_expired.json = AsyncMock(return_value=expired)

        resp_login = AsyncMock(status=200)
        resp_login.json = AsyncMock(return_value=login_fail)

        mock_session_post.return_value.__aenter__.side_effect = [
            resp_expired,
            resp_login,
        ]

        # Should return None if relogin fails
        assert await client.get_accounts() is None

    async def test_get_user_info_no_id(self, client, mock_session_post):
        """Test fetching user info when user_id is missing."""
        client.user_id = None
        client.is_authenticated = True

        # 1. get_accounts to find ID
        # 2. get_user_info
        accounts_data = {"data": {"lst_ls": [{"a": 555}]}}
        user_info = {"data": {"info": "ok", "lst_cherga": ["4.1"]}}

        resp_acc = AsyncMock(status=200)
        resp_acc.json = AsyncMock(return_value=accounts_data)

        resp_info = AsyncMock(status=200)
        resp_info.json = AsyncMock(return_value=user_info)

        mock_session_post.return_value.__aenter__.side_effect = [resp_acc, resp_info]

        info = await client.get_user_info()
        assert client.user_id == 555
        assert client.group == "4.1"
        assert info == user_info

    async def test_get_accounts_login_fail(self, client, mock_session_post):
        """Test login failure inside get_accounts."""
        client.is_authenticated = False
        # Login fails
        mock_resp = AsyncMock(status=401)
        mock_session_post.return_value.__aenter__.return_value = mock_resp
        assert await client.get_accounts() is None

    async def test_get_accounts_http_error(self, client, mock_session_post):
        """Test get accounts HTTP error."""
        client.is_authenticated = True
        mock_resp = AsyncMock(status=500)
        mock_session_post.return_value.__aenter__.return_value = mock_resp
        assert await client.get_accounts() is None

    async def test_get_accounts_exception(self, client, mock_session_post):
        """Test get accounts exception."""
        client.is_authenticated = True
        mock_session_post.return_value.__aenter__.side_effect = ClientError()
        assert await client.get_accounts() is None

    async def test_get_user_info_relogin_fail(self, client, mock_session_post):
        """Test user info re-login failure."""
        client.is_authenticated = True

        expired = {"error": {"err": E_SVITLO_ERROR_NOT_LOGGED_IN}}
        login_fail = {"data": {"login": False}}

        resp_expired = AsyncMock(status=200)
        resp_expired.json = AsyncMock(return_value=expired)

        resp_login = AsyncMock(status=200)
        resp_login.json = AsyncMock(return_value=login_fail)

        mock_session_post.return_value.__aenter__.side_effect = [
            resp_expired,
            resp_login,
        ]

        assert await client.get_user_info() is None

    async def test_get_user_info_no_id_no_accounts(self, client, mock_session_post):
        """Test get user info with no ID and no accounts."""
        client.user_id = None
        client.is_authenticated = True
        mock_session_post.return_value.__aenter__.return_value = AsyncMock(
            status=200, json=AsyncMock(return_value={"data": {"lst_ls": []}})
        )
        assert await client.get_user_info() is None


@pytest.mark.asyncio
class TestESvitloClientDisconnections:
    """Tests for disconnection parsing."""

    async def test_get_disconnections_parsing(self, client, mock_session_post):
        """Test parsing of disconnections."""
        client.is_authenticated = True
        client.group = "4.1"

        response_data = {
            "data": {
                "date_today": "15.12.2025",
                "lst_time_disc": [{"start_time": "10:00", "end_time": "12:00"}],
                "dict_tom": {
                    "date_today": "16.12.2025",
                    "lst_time_disc": [{"start_time": "22:00", "end_time": "02:00"}],
                    "last_update": "Оновлено: 15.12.2025 10:00",
                },
            }
        }

        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()
        assert len(events) == 2

        # Event 1: Today 10-12
        assert events[0].start == datetime(2025, 12, 15, 10, 0, tzinfo=TZ_UA)
        assert events[0].end == datetime(2025, 12, 15, 12, 0, tzinfo=TZ_UA)

        # Event 2: Tomorrow 22:00 - Next Day 02:00
        assert events[1].start == datetime(2025, 12, 16, 22, 0, tzinfo=TZ_UA)
        # Should be 17th
        assert events[1].end == datetime(2025, 12, 17, 2, 0, tzinfo=TZ_UA)

        # Check last update parsing
        assert client.get_updated_on() == datetime(2025, 12, 15, 10, 0, tzinfo=TZ_UA)

    async def test_get_disconnections_parse_error(self, client, mock_session_post):
        """Test parsing error."""
        client.is_authenticated = True
        client.group = "4.1"
        # Invalid time format to trigger ValueError in _parse_period
        response_data = {
            "data": {
                "date_today": "15.12.2025",
                "lst_time_disc": [{"start_time": "INVALID", "end_time": "12:00"}],
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()
        assert len(events) == 0

    async def test_get_events_filtering(self, client, mock_session_post):
        """Test get_events and get_current_event using cached data."""
        # Setup cached events
        dt1 = datetime(2025, 12, 15, 10, 0, tzinfo=TZ_UA)
        dt2 = datetime(2025, 12, 15, 12, 0, tzinfo=TZ_UA)

        # Mock get_disconnections to populate cache
        client.is_authenticated = True
        client.group = "4.1"
        response_data = {
            "data": {
                "date_today": "15.12.2025",
                "lst_time_disc": [{"start_time": "10:00", "end_time": "12:00"}],
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        await client.get_disconnections()

        # Test get_current_event
        now = datetime(2025, 12, 15, 11, 0, tzinfo=TZ_UA)
        event = client.get_current_event(now)
        assert event is not None
        assert event.event_type == PlannedOutageEventType.DEFINITE

        # Test get_events
        events = client.get_events(dt1, dt2)
        assert len(events) == 1

    async def test_ensure_connection_relogin(self, client, mock_session_post):
        """Test ensuring connection calls login if needed."""
        client.is_authenticated = False

        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value={"data": {"login": True}})
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        # _ensure_connection is called internally by getters, but we can call it if exposed
        # or verify side effect via get_disconnections
        await client.get_disconnections()
        assert client.is_authenticated is True

    async def test_get_disconnections_login_fail(self, client, mock_session_post):
        """Test login failure in get_disconnections."""
        client.is_authenticated = False
        # Login mock returns false
        mock_resp = AsyncMock(status=401)
        mock_session_post.return_value.__aenter__.return_value = mock_resp
        assert await client.get_disconnections() is None

    async def test_get_disconnections_http_error(self, client, mock_session_post):
        """Test get_disconnections HTTP error."""
        client.is_authenticated = True
        client.group = "4.1"
        mock_resp = AsyncMock(status=500)
        mock_session_post.return_value.__aenter__.return_value = mock_resp
        assert await client.get_disconnections() is None

    async def test_get_disconnections_exception(self, client, mock_session_post):
        """Test get_disconnections exception."""
        client.is_authenticated = True
        client.group = "4.1"
        mock_session_post.return_value.__aenter__.side_effect = ClientError()
        assert await client.get_disconnections() is None

    async def test_parse_day_data_date_error(self, client, mock_session_post):
        """Test parsing day data with date error."""
        client.is_authenticated = True
        client.group = "4.1"
        response_data = {
            "data": {
                "date_today": "INVALID_DATE",
                "lst_time_disc": [],
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()
        assert len(events) == 0

    async def test_ensure_connection_missing_group(self, client, mock_session_post):
        """Test that missing group triggers get_user_info."""
        client.is_authenticated = True
        client.user_id = TEST_ACCOUNT_ID
        client.group = None  # Missing group

        resp_info = AsyncMock(status=200)
        resp_info.json = AsyncMock(return_value={"data": {"lst_cherga": ["3.2"]}})

        resp_disc = AsyncMock(status=200)
        resp_disc.json = AsyncMock(return_value={"data": {}})

        mock_session_post.return_value.__aenter__.side_effect = [resp_info, resp_disc]

        await client.get_disconnections()
        assert client.group == "3.2"

    async def test_get_disconnections_empty_data(self, client, mock_session_post):
        """Test get_disconnections with empty data."""
        client.is_authenticated = True
        client.group = "4.1"
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value={"data": {}})  # Empty main data
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()
        assert len(events) == 0

    async def test_get_disconnections_missing_times(self, client, mock_session_post):
        """Test get_disconnections with missing times."""
        client.is_authenticated = True
        client.group = "4.1"
        response_data = {
            "data": {
                "date_today": "15.12.2025",
                # missing start_time
                "lst_time_disc": [{"end_time": "12:00"}],
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()
        assert len(events) == 0

    async def test_get_user_info_no_id_found(self, client, mock_session_post):
        """Test case where no ID is found even after fetching accounts."""
        client.user_id = None
        client.is_authenticated = True

        # get_accounts returns empty
        resp_acc = AsyncMock(status=200)
        resp_acc.json = AsyncMock(return_value={"data": {"lst_ls": []}})

        mock_session_post.return_value.__aenter__.return_value = resp_acc

        assert await client.get_user_info() is None

    async def test_get_disconnections_relogin(self, client, mock_session_post):
        """Test get_disconnections re-login on session expiration."""
        client.is_authenticated = True
        client.group = "4.1"

        expired = {"error": {"err": E_SVITLO_ERROR_NOT_LOGGED_IN}}
        login_ok = {"data": {"login": True}}

        response_data = {
            "data": {
                "date_today": "15.12.2025",
                "lst_time_disc": [{"start_time": "10:00", "end_time": "12:00"}],
            }
        }

        # 1. get_disconnections -> expired
        resp_expired = AsyncMock(status=200)
        resp_expired.json = AsyncMock(return_value=expired)

        # 2. login -> ok
        resp_login = AsyncMock(status=200)
        resp_login.json = AsyncMock(return_value=login_ok)

        # 3. get_disconnections -> success
        resp_data = AsyncMock(status=200)
        resp_data.json = AsyncMock(return_value=response_data)

        mock_session_post.return_value.__aenter__.side_effect = [
            resp_expired,
            resp_login,
            resp_data,
        ]

        events = await client.get_disconnections()
        assert len(events) == 1
        assert events[0].start == datetime(2025, 12, 15, 10, 0, tzinfo=TZ_UA)
