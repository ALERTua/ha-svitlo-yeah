"""E-Svitlo API client."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..models import ESvitloProvider, PlannedOutageEvent

from ..const import E_SVITLO_ERROR_NOT_LOGGED_IN, E_SVITLO_SUMY_BASE_URL
from ..models import PlannedOutageEvent, PlannedOutageEventType

LOGGER = logging.getLogger(__name__)


class ESvitloClient:
    """E-Svitlo API client."""

    base_url: str = E_SVITLO_SUMY_BASE_URL

    def __init__(self, hass: HomeAssistant, provider: ESvitloProvider) -> None:
        """Initialize the E-Svitlo client."""
        self.hass = hass
        self.session: aiohttp.ClientSession = async_get_clientsession(hass)
        self.user_name = provider.user_name
        self.pwd = provider.password
        self.is_authenticated = False
        self.user_id: str | int | None = provider.account_id
        self.group: str | None = None
        self._cached_events: list[PlannedOutageEvent] = []
        self._last_update: datetime | None = None

    async def login(self) -> bool:
        """Authenticate with E-Svitlo API."""
        try:
            async with self.session.post(
                url=self.base_url + "api_main/login_api.json",
                data={
                    "login_name": self.user_name,
                    "pass_name": self.pwd,
                },
            ) as response:
                if response.status == 200:  # noqa: PLR2004
                    result = await response.json()
                    # Check if login was successful based on response
                    if result.get("data", {}).get("login", False) is True:
                        self.is_authenticated = True
                        LOGGER.debug("Successfully authenticated with E-Svitlo API")
                        return True

                    error_msg = result.get("error", "Unknown error")
                    LOGGER.error("E-Svitlo login failed: %s", error_msg)
                    return False

                LOGGER.error("E-Svitlo login HTTP error: %s", response.status)
                return False
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Exception during E-Svitlo login")
            return False

    async def get_accounts(self) -> list[dict] | None:
        """Get list of available accounts."""
        if not self.is_authenticated and not await self.login():
            return None

        try:
            async with self.session.post(
                url=self.base_url + "api_main_reg/short_list_ls_api.json"
            ) as response:
                data = await response.json()
                if response.status == 200:  # noqa: PLR2004
                    if self.is_logged_out(data):
                        # Session expired, try to re-authenticate
                        self.is_authenticated = False
                        if await self.login():
                            return await self.get_accounts()
                        return None

                    return data.get("data", {}).get("lst_ls", [])

                LOGGER.error("E-Svitlo accounts HTTP error: %s", response.status)
                return None
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Exception getting E-Svitlo accounts")
            return None

    async def get_user_info(self) -> dict | None:
        """Get user information from E-Svitlo API."""
        if not self.is_authenticated and not await self.login():
            return None

        try:
            # If we don't have a user_id (account_id),
            # we need to fetch the list and pick one
            if not self.user_id:
                start_data = await self.get_accounts()
                if start_data:
                    # Default to first account if not specified
                    self.user_id = start_data[0].get("a")

            if not self.user_id:
                LOGGER.error("No account ID found for E-Svitlo")
                return None

            async with self.session.post(
                url=self.base_url + "/api_main_reg/all_details_ls_api.json",
                data={"a": self.user_id},
            ) as response_all:
                data_all = await response_all.json()

                # Check for session expiration in this separate call too just in case
                if self.is_logged_out(data_all):
                    self.is_authenticated = False
                    if await self.login():
                        return await self.get_user_info()
                    return None

                identifiers = data_all.get("data", {}).get("lst_cherga")
                if identifiers:
                    # ``` "lst_cherga": [
                    #     "4.1",
                    #     "\"4 черга 1 підчерга ГПВ\"",
                    #     "infinity",
                    #     "infinity"
                    #  ]```
                    self.group = identifiers[0]
                LOGGER.debug("E-Svitlo all_user info: %s", data_all)

                return data_all

        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Exception getting E-Svitlo user info")
            return None

    async def get_disconnections(self) -> list[PlannedOutageEvent] | None:
        """Get user disconnections from E-Svitlo API."""
        if not await self._ensure_connection():
            return None
        try:
            async with self.session.post(
                url=self.base_url + "api_main/get_user_disconnections_image_api.json",
                data={"a": self.user_id, "cherga": self.group, "mobile_v": True},
            ) as response:
                if response.status == 200:  # noqa: PLR2004
                    data = await response.json()
                    events = self._parse_disconnections(data)
                    self._cached_events = events or []
                    # Store last update timestamp from API response
                    main_data = data.get("data", {})
                    last_update_str = main_data.get("dict_tom", {}).get(
                        "last_update", ""
                    ) or main_data.get("last_update", "")
                    if last_update_str and "Оновлено:" in last_update_str:
                        # Parse format: "Оновлено: 13.12.2025 10:59"
                        try:
                            date_part = last_update_str.replace("Оновлено:", "").strip()
                            self._last_update = datetime.strptime(
                                date_part, "%d.%m.%Y %H:%M"
                            ).replace(tzinfo=ZoneInfo("Europe/Kyiv"))
                        except ValueError:
                            LOGGER.debug(
                                "Failed to parse last_update: %s", last_update_str
                            )
                            self._last_update = datetime.now(ZoneInfo("Europe/Kyiv"))
                    else:
                        self._last_update = datetime.now(ZoneInfo("Europe/Kyiv"))
                    return events

                LOGGER.error("E-Svitlo disconnections HTTP error: %s", response.status)
                return None
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Exception getting E-Svitlo disconnections")
            return None

    async def _ensure_connection(self) -> bool:
        """Check and ensure connection is authenticated."""
        if not self.is_authenticated and not await self.login():
            return False

        # Simplified check: if no ID or Group - try to get them
        return (
            self.user_id is not None and self.group is not None
        ) or await self.get_user_info() is not None

    def is_logged_out(self, data: dict) -> bool:
        """Check if the response indicates a logged out state."""
        return data.get("error", {}).get("err") == E_SVITLO_ERROR_NOT_LOGGED_IN

    def _parse_disconnections(self, data: dict) -> list[PlannedOutageEvent]:
        """Parse disconnections data into PlannedOutageEvent objects."""
        events = []
        LOGGER.debug("E-Svitlo disconnections data: %s", data)

        main_data = data.get("data", {})
        if not main_data:
            LOGGER.warning("No data found in E-Svitlo response")
            return events

        today = main_data.get("lst_time_disc", {})
        if today:
            events = self._parse_day_data(today, main_data.get("date_today", ""))

        tomorrow = main_data.get("dict_tom", {})
        if items := tomorrow.get("lst_time_disc", {}):
            events.extend(self._parse_day_data(items, tomorrow.get("date_today", "")))

        LOGGER.debug("Parsed %d disconnection events from E-Svitlo data", len(events))
        return events

    def _parse_day_data(self, periods: list, date_str: str) -> list[PlannedOutageEvent]:
        """Parse disconnection periods for a single day."""
        events = []

        if not date_str:
            return events

        try:
            # Parse date string to date object (timezone not applicable for date)
            base_date = datetime.strptime(date_str, "%d.%m.%Y").date()  # noqa: DTZ007
        except ValueError:
            LOGGER.exception("Failed to parse date %s", date_str)
            return events

        for period in periods:
            event = self._parse_period(period, base_date)
            if event:
                events.append(event)

        return events

    def _parse_period(self, period: dict, base_date: date) -> PlannedOutageEvent | None:
        """Parse a single disconnection period."""
        try:
            start_time_str = period.get("start_time", "")
            end_time_str = period.get("end_time", "")

            if not start_time_str or not end_time_str:
                return None

            start_time = time.fromisoformat(start_time_str)
            end_time = time.fromisoformat(end_time_str)

            start_datetime = datetime.combine(
                base_date, start_time, tzinfo=ZoneInfo("Europe/Kyiv")
            )
            end_datetime = datetime.combine(
                base_date, end_time, tzinfo=ZoneInfo("Europe/Kyiv")
            )

            # Handle end time on next day (e.g., 23:00-04:00)
            if end_time < start_time:
                end_datetime = end_datetime.replace(day=end_datetime.day + 1)

            return PlannedOutageEvent(
                start=start_datetime,
                end=end_datetime,
                event_type=PlannedOutageEventType.DEFINITE,
            )

        except (ValueError, TypeError):
            LOGGER.exception("Failed to parse disconnection period %s", period)
            return None

    def get_current_event(self, at: datetime) -> PlannedOutageEvent | None:
        """Get the current event at a specific time."""
        for event in self._cached_events:
            if event.start <= at < event.end:
                return event
        return None

    def get_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        return [
            event
            for event in self._cached_events
            if event.end >= start_date and event.start <= end_date
        ]

    def get_updated_on(self) -> datetime | None:
        """Get the last update timestamp."""
        return self._last_update
