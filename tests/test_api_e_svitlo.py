"""Tests for E-Svitlo API."""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from custom_components.svitlo_yeah.api.e_svitlo import ESvitloClient, LoginResult
from custom_components.svitlo_yeah.const import E_SVITLO_ERROR_NOT_LOGGED_IN, TZ_UA
from custom_components.svitlo_yeah.models import ESvitloProvider, PlannedOutageEventType

TEST_USERNAME = "test_user"
TEST_PWD = "test_password"
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
        "custom_components.svitlo_yeah.api.e_svitlo.async_create_clientsession"
    ) as mock_helper:
        # The provided snippet seems to be a mix of client and coordinator setup.
        # Assuming the intent was to keep the client setup and potentially add
        # coordinator setup elsewhere.
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

    @pytest.mark.parametrize(
        ("status", "body", "error", "expected"),
        [
            (200, {"data": {"login": True}}, None, LoginResult.OK),
            (200, {"data": {"login": False}}, None, LoginResult.REJECTED),
            (500, None, None, LoginResult.UNREACHABLE),
            (None, None, ClientError(), LoginResult.UNREACHABLE),
            (None, None, TimeoutError(), LoginResult.UNREACHABLE),
            (200, ValueError("not JSON"), None, LoginResult.UNREACHABLE),
            (200, {"data": None}, None, LoginResult.REJECTED),
            (200, [], None, LoginResult.UNREACHABLE),
        ],
        ids=[
            "accepted",
            "refused",
            "http_500",
            "client_error",
            "timeout",
            "not_json",
            "null_data",
            "not_an_object",
        ],
    )
    async def test_try_login_tells_refused_from_unreachable(
        self, client, mock_session_post, status, body, error, expected
    ):
        """Refused credentials differ from a server that gave no answer."""
        if error:
            mock_session_post.side_effect = error
        else:
            mock_response = AsyncMock(status=status)
            if isinstance(body, Exception):
                mock_response.json = AsyncMock(side_effect=body)
            else:
                mock_response.json = AsyncMock(return_value=body)
            mock_session_post.return_value.__aenter__.return_value = mock_response

        assert await client.try_login() is expected

    async def test_new_login_logs_in_at_the_next_request(
        self, client, mock_session_post
    ):
        """After use_login, the next request logs in with the new credentials."""
        client.is_authenticated = True
        client.use_login("u2", "p2")
        mock_response = AsyncMock(status=200)
        mock_response.json = AsyncMock(return_value={"data": {"login": True}})
        mock_session_post.return_value.__aenter__.return_value = mock_response

        await client.get_accounts()

        login = mock_session_post.call_args_list[0]
        assert login.kwargs["data"] == {"login_name": "u2", "pass_name": "p2"}

    async def test_request_answer_that_is_not_json_is_no_answer(
        self, client, mock_session_post
    ):
        """A body that is not JSON gives no data, as a network error does."""
        client.is_authenticated = True
        mock_response = AsyncMock(status=200)
        mock_response.json = AsyncMock(side_effect=ValueError("not JSON"))
        mock_session_post.return_value.__aenter__.return_value = mock_response

        assert await client.get_accounts() is None


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
        # Note: logic calls login() which does a POST, then get_accounts(),
        # which does a POST
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

    async def test_user_info_log_keeps_the_personal_data_out(
        self, client, mock_session_post, caplog
    ):
        """
        The debug log of the account details names the group and the keys only.

        README asks the user to attach the debug log to a public issue.
        """
        caplog.set_level(logging.DEBUG, logger="custom_components.svitlo_yeah")
        client.user_id = 101
        client.is_authenticated = True
        details = {
            "data": {
                "lst_cherga": ["4.1"],
                "address": "Sumy, Test street 1",
                "owner": "Testenko Test",
            }
        }
        resp_info = AsyncMock(status=200)
        resp_info.json = AsyncMock(return_value=details)
        mock_session_post.return_value.__aenter__.return_value = resp_info

        assert await client.get_user_info() == details

        assert "Sumy, Test street 1" not in caplog.text
        assert "Testenko Test" not in caplog.text
        assert (
            "E-Svitlo account details: group 4.1, keys "
            "['address', 'lst_cherga', 'owner']" in caplog.text
        )

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

    @pytest.mark.parametrize(
        ("date_str", "end"),
        [
            ("30.09.2026", datetime(2026, 10, 1, 2, 0, tzinfo=TZ_UA)),
            ("31.12.2026", datetime(2027, 1, 1, 2, 0, tzinfo=TZ_UA)),
        ],
    )
    async def test_overnight_period_on_the_last_day_of_a_month(
        self, client, mock_session_post, date_str, end
    ):
        """An outage past midnight on the last day of a month ends on the next day."""
        client.is_authenticated = True
        client.group = "4.1"
        response_data = {
            "data": {
                "date_today": date_str,
                "lst_time_disc": [{"start_time": "23:00", "end_time": "02:00"}],
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()

        assert len(events) == 1
        assert events[0].end == end

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

        # _ensure_connection is called internally by getters, but we can call it
        # if exposed
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
        """Empty data is no schedule, so the answer counts as no answer."""
        client.is_authenticated = True
        client.group = "4.1"
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value={"data": {}})  # Empty main data
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        assert await client.get_disconnections() is None
        assert client.last_answer is None

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

    @pytest.mark.parametrize(
        ("periods", "date_today"),
        [
            (
                ["10:00-12:00", None, ["10:00", "12:00"], {"start_time": "10:00"}],
                "15.12.2025",
            ),
            (5, "15.12.2025"),
            ([{"start_time": "10:00", "end_time": "12:00"}], 15122025),
        ],
        ids=["periods_of_another_shape", "periods_not_a_list", "date_not_text"],
    )
    async def test_day_of_another_shape_gives_no_events(
        self, client, mock_session_post, periods, date_today
    ):
        """Periods or a date of another shape give no events, and no error."""
        client.is_authenticated = True
        client.group = "4.1"
        response_data = {
            "data": {
                "date_today": date_today,
                "lst_time_disc": periods,
                "dict_tom": {
                    "date_today": "16.12.2025",
                    "lst_time_disc": [{"start_time": "08:00", "end_time": "09:00"}],
                },
            }
        }
        mock_resp = AsyncMock(status=200)
        mock_resp.json = AsyncMock(return_value=response_data)
        mock_session_post.return_value.__aenter__.return_value = mock_resp

        events = await client.get_disconnections()

        assert [(e.start.day, e.start.hour) for e in events] == [(16, 8)]

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
