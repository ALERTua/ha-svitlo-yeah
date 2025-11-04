"""Coordinator for Svitlo Yeah integration."""

import datetime
import logging

from homeassistant.components.calendar import CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_utils

from ..api.yasno import YasnoApi
from ..const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_REGION,
    CONF_UPDATE_INTERVAL,
    DEBUG,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PROVIDER_DTEK_FULL,
    PROVIDER_DTEK_SHORT,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
    TRANSLATION_KEY_TIME_LESS_THAN_MINUTE,
)
from ..models import (
    ConnectivityState,
    PlannedOutageEvent,
    PlannedOutageEventType,
)

LOGGER = logging.getLogger(__name__)

TIMEFRAME_TO_CHECK = datetime.timedelta(hours=24)


class YasnoCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Yasno outages data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        # Get update interval from config, with fallback to default
        update_interval_minutes = config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(minutes=update_interval_minutes),
        )
        self.hass = hass
        self.config_entry = config_entry
        self.translations = {}

        # Get configuration values
        self.region = config_entry.options.get(
            CONF_REGION,
            config_entry.data.get(CONF_REGION),
        )
        self.provider = config_entry.options.get(
            CONF_PROVIDER,
            config_entry.data.get(CONF_PROVIDER),
        )
        self.group = config_entry.options.get(
            CONF_GROUP,
            config_entry.data.get(CONF_GROUP),
        )

        if not self.region:
            region_required_msg = (
                "Region not set in configuration - this should not happen "
                "with proper config flow"
            )
            region_error = "Region configuration is required"
            LOGGER.error(region_required_msg)
            raise ValueError(region_error)

        if not self.provider:
            provider_required_msg = (
                "Provider not set in configuration - this should not happen "
                "with proper config flow"
            )
            provider_error = "Provider configuration is required"
            LOGGER.error(provider_required_msg)
            raise ValueError(provider_error)

        if not self.group:
            group_required_msg = (
                "Group not set in configuration - this should not happen "
                "with proper config flow"
            )
            group_error = "Group configuration is required"
            LOGGER.error(group_required_msg)
            raise ValueError(group_error)

        # Initialize with names first, then we'll update with IDs when we fetch data
        self.region_id = None
        self.provider_id = None
        self._provider_name = ""  # Cache the provider name

        # Cache for group data to avoid repeated API calls
        self._cached_group_data = None
        self._group_data_cache_time = None

        # Initialize API and resolve IDs
        self.api = YasnoApi()
        # Note: We'll resolve IDs and update API during first data update

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: self.translations.get(
                TRANSLATION_KEY_EVENT_PLANNED_OUTAGE
            ),
            PlannedOutageEventType.EMERGENCY: self.translations.get(
                TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE
            ),
        }

    async def _resolve_ids(self) -> None:
        """Resolve region and provider IDs from names."""
        if not self.api.regions_data:
            await self.api.fetch_yasno_regions()

        if self.region:
            region_data = self.api.get_region_by_name(self.region)
            if region_data:
                self.region_id = region_data["id"]
                if self.provider:
                    provider_data = self.api.get_yasno_provider_by_name(
                        self.region, self.provider
                    )
                    if provider_data:
                        self.provider_id = provider_data["id"]
                        # Cache the provider name for device naming
                        self._provider_name = provider_data["name"]

    async def _async_update_data(self) -> None:
        """Fetch data from Svitlo Yeah API."""
        await self.async_fetch_translations()

        # Resolve IDs if not already resolved
        if self.region_id is None or self.provider_id is None:
            await self._resolve_ids()

            # Update API with resolved IDs
            self.api = YasnoApi(
                region_id=self.region_id,
                provider_id=self.provider_id,
                group=self.group,
            )

        # Fetch outages data (now async with aiohttp, not blocking)
        await self.api.fetch_data()

        # Invalidate cache when we fetch new data
        self._cached_group_data = None
        self._group_data_cache_time = None

    async def async_fetch_translations(self) -> None:
        """Fetch translations."""
        self.translations = await async_get_translations(
            self.hass,
            self.hass.config.language,
            "common",
            [DOMAIN],
        )
        LOGGER.debug(
            "Translations for %s:\n%s", self.hass.config.language, self.translations
        )

    def _get_next_event_of_type(
        self, state_type: ConnectivityState
    ) -> CalendarEvent | None:
        """Get the next event of a specific type."""
        now = dt_utils.now()
        # Sort events to handle multi-day spanning events correctly
        next_events = sorted(
            self.get_events_between(
                now,
                now + TIMEFRAME_TO_CHECK,
            ),
            key=lambda _: _.start,
        )
        LOGGER.debug("Next events: %s", next_events)
        for event in next_events:
            if self._event_to_state(event) == state_type and event.start > now:
                return event
        return None

    @property
    def next_planned_outage(self) -> datetime.date | datetime.datetime | None:
        """Get the next planned outage time."""
        if not self._has_outages_planned():
            return None

        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        LOGGER.debug("Next planned outage: %s", event)
        return event.start if event else None

    @property
    def next_planned_outage_duration(self) -> int | None:
        """
        Get the next planned outage duration in minutes.

        Returns:
            int: Duration in minutes when outage is planned
            0: No outages planned (data available)
            None: No data available or error

        """
        # First check if we have any data at all
        group_data = self._get_group_data_or_none()
        if not group_data:
            return None  # No data available - unknown

        # We have data, check for outages
        if not self._has_outages_planned():
            return 0

        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        if event and event.start and event.end:
            duration = event.end - event.start
            duration_minutes = int(duration.total_seconds() / 60)
            return duration_minutes
        return None

    @property
    def current_day_status(self) -> str | None:
        """Get the status of the current day."""
        group_data = self._get_group_data_or_none()
        if not group_data:
            return None

        now = dt_utils.now()
        current_date = now.date()

        # Check all available days in group data
        for key, day_data in group_data.items():
            if key == "updatedOn" or not isinstance(day_data, dict):
                continue

            if "date" not in day_data:
                continue

            day_dt = dt_utils.parse_datetime(day_data["date"])
            if day_dt:
                if day_dt.date() == current_date:
                    status = day_data.get("status")
                    return status

        # If no matching date found, check if we're currently in an outage
        current_event = self.get_current_event()
        if (
            current_event
            and self._event_to_state(current_event) != ConnectivityState.STATE_NORMAL
        ):
            # If there's a current outage but no status found, it might be emergency
            return "EmergencyShutdowns"

        return None

    @property
    def next_outage_type(self) -> str | None:
        """Get the type of the next planned outage."""
        # Check if we have data
        group_data = self._get_group_data_or_none()
        if not group_data:
            return None  # No data available - show "Невідомо"

        # We have data, check for next outage
        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        if event:
            return event.uid  # This contains the PlannedOutageEventType value

        # Data available but no outages planned
        return "NotPlanned"

    def _has_outages_planned(self) -> bool:
        """Check if there are any outages planned."""
        group_data = self._get_group_data_or_none()
        if not group_data:
            return False

        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        return event is not None

    def _get_group_data_or_none(self):
        """
        Get group data with caching to reduce API calls.

        Helper method to reduce code duplication for data availability checks.
        Caches the result until the next data update to avoid repeated API calls
        during the same update cycle.
        """
        now = dt_utils.now()

        # Use cache if it's fresh (within the current update interval)
        cache_duration = min(
            60, self.update_interval.total_seconds() / 2
        )  # Half of update interval, max 1 minute
        if (
            self._cached_group_data is not None
            and self._group_data_cache_time is not None
            and (now - self._group_data_cache_time).total_seconds() < cache_duration
        ):
            return self._cached_group_data

        # Fetch fresh data and cache it
        self._cached_group_data = self.api._get_group_data()
        self._group_data_cache_time = now

        return self._cached_group_data

    def _get_localized_less_than_minute(self) -> str:
        """Get localized text for 'less than a minute'."""
        return self.translations.get(
            TRANSLATION_KEY_TIME_LESS_THAN_MINUTE,
            "less than a minute",  # fallback to English
        )

    def _is_time_delta_positive(self, delta: datetime.timedelta) -> bool:
        """Check if time delta is positive (future time)."""
        return delta.total_seconds() > 0

    def _invalidate_group_data_cache(self):
        """
        Invalidate the group data cache.

        Forces fresh data fetch on next access. Useful for testing or
        when we know the data has changed.
        """
        self._cached_group_data = None
        self._group_data_cache_time = None

    def _format_time_delta(self, delta: datetime.timedelta) -> str:
        """
        Format time delta to human readable format: XдXчXм (days, hours, minutes).

        Args:
            delta: Time delta to format

        Returns:
            Formatted string or localized "less than a minute" if less than a minute

        """
        if delta.total_seconds() <= 0:
            return self._get_localized_less_than_minute()

        # Calculate components
        total_seconds = int(delta.total_seconds())
        days = total_seconds // (24 * 3600)
        remaining_seconds = total_seconds % (24 * 3600)
        hours = remaining_seconds // 3600
        remaining_seconds %= 3600
        minutes = remaining_seconds // 60

        # Format result
        parts = []
        if days > 0:
            parts.append(f"{days}д")
            # Always show hours when we have days
            parts.append(f"{hours}ч")
        elif hours > 0:
            # Show hours when we don't have days but have hours
            parts.append(f"{hours}ч")

        # Always show minutes
        if minutes > 0 or (days == 0 and hours == 0):
            parts.append(f"{minutes}м")

        return " ".join(parts) if parts else self._get_localized_less_than_minute()

    def _format_event_time(
        self, event_time, default_time_for_date: str = "00:00"
    ) -> str | None:
        """
        Format event time to HH:MM format.

        Args:
            event_time: datetime.datetime or datetime.date object
            default_time_for_date: Default time to use for date objects (e.g., "00:00" for start, "23:59" for end)

        Returns:
            Formatted time string or None if event_time is None

        """
        if not event_time:
            return None

        if isinstance(event_time, datetime.datetime):
            return event_time.strftime("%H:%M")
        if isinstance(event_time, datetime.date):
            return default_time_for_date
        return None

    @property
    def time_until_connectivity(self) -> str | None:
        """
        Get time until power restoration in human readable format.

        Shows countdown in format: XдXчXм (days, hours, minutes)
        Logic:
        - If currently in outage: time until current outage ends
        - If power is on: time until next outage ends
        Returns None if no outage is planned.
        """
        if not self._has_outages_planned():
            return None

        current_event = self.get_current_event()
        current_state = self._event_to_state(current_event)

        connectivity_time = None

        if current_state == ConnectivityState.STATE_PLANNED_OUTAGE:
            # Currently in outage - when does current outage end?
            if current_event and current_event.end:
                connectivity_time = current_event.end
        else:
            # Not in outage - when does next outage end?
            next_outage = self._get_next_event_of_type(
                ConnectivityState.STATE_PLANNED_OUTAGE
            )
            if next_outage and next_outage.end:
                connectivity_time = next_outage.end

        if not connectivity_time:
            return None

        now = dt_utils.now()
        delta = connectivity_time - now

        if not self._is_time_delta_positive(delta):
            return None

        return self._format_time_delta(delta)

    @property
    def time_until_outage(self) -> str | None:
        """
        Get time until next power outage in human readable format.

        Shows countdown in format: XдXчXм (days, hours, minutes)
        Logic:
        - If currently in outage: None (already in outage)
        - If power is on: time until next outage starts
        Returns None if no outage is planned or already in outage.
        """
        if not self._has_outages_planned():
            return None

        current_event = self.get_current_event()
        current_state = self._event_to_state(current_event)

        # If already in outage, don't show time until next outage
        if current_state == ConnectivityState.STATE_PLANNED_OUTAGE:
            return None

        # Find next outage start time
        next_outage = self._get_next_event_of_type(
            ConnectivityState.STATE_PLANNED_OUTAGE
        )
        if not next_outage or not next_outage.start:
            return None

        now = dt_utils.now()
        delta = next_outage.start - now

        if not self._is_time_delta_positive(delta):
            return None

        return self._format_time_delta(delta)

    @property
    def next_planned_outage_start_time(self) -> str | None:
        """Get the next planned outage start time in HH:MM format."""
        if not self._has_outages_planned():
            return None

        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        if event and event.start:
            return self._format_event_time(event.start)
        return None

    @property
    def next_planned_outage_end_time(self) -> str | None:
        """
        Get the next planned outage end time in HH:MM format.

        Smart sensor that shows:
        - If power is OFF now: when current outage ends
        - If power is ON now: when next outage ends
        """
        if not self._has_outages_planned():
            return None

        # Check if we're currently in an outage
        current_event = self.get_current_event()
        current_state = self._event_to_state(current_event)

        event_to_use = None

        # If currently in outage state, use current outage
        if current_state == ConnectivityState.STATE_PLANNED_OUTAGE:
            event_to_use = current_event
        else:
            # Otherwise, use the next outage
            event_to_use = self._get_next_event_of_type(
                ConnectivityState.STATE_PLANNED_OUTAGE
            )

        if event_to_use and event_to_use.end:
            return self._format_event_time(event_to_use.end, "23:59")
        return None

    @property
    def next_connectivity(self) -> datetime.date | datetime.datetime | None:
        """
        Get next connectivity time.

        Smart sensor that shows:
        - If power is OFF now: when current outage ends
        - If power is ON now: when next outage ends
        """
        if not self._has_outages_planned():
            return None

        current_event = self.get_current_event()
        current_state = self._event_to_state(current_event)

        # If currently in outage state, return when it ends
        if current_state == ConnectivityState.STATE_PLANNED_OUTAGE:
            return current_event.end if current_event else None

        # Otherwise, return the end of the next outage
        event = self._get_next_event_of_type(ConnectivityState.STATE_PLANNED_OUTAGE)
        LOGGER.debug("Next connectivity: %s", event)
        return event.end if event else None

    @property
    def next_planned_reconnection(self) -> datetime.date | datetime.datetime | None:
        """
        Get next planned power reconnection time.

        Shows the start time of the next normal period (when power comes back on).
        This is different from next_connectivity which shows smart logic based on current state.
        """
        if not self._has_outages_planned():
            return None

        # Find the next outage
        next_outage = self._get_next_event_of_type(
            ConnectivityState.STATE_PLANNED_OUTAGE
        )
        if next_outage and next_outage.end:
            return next_outage.end
        return None

    @property
    def current_state(self) -> str:
        """Get the current state."""
        event = self.get_current_event()
        return self._event_to_state(event)

    @property
    def schedule_updated_on(self) -> datetime.datetime | None:
        """Get the schedule last updated timestamp."""
        return self.api.get_updated_on()

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        return self.region or ""

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        # Return cached name if available (but apply simplification first)
        if self._provider_name:
            return self._simplify_provider_name(self._provider_name)

        # Fallback to lookup if not cached yet
        if not self.api.regions_data:
            return ""

        region_data = self.api.get_region_by_name(self.region)
        if not region_data:
            return ""

        providers = region_data.get("dsos", [])
        for provider in providers:
            if (provider_name := provider.get("name", "")) == self.provider:
                # Cache the simplified name
                self._provider_name = provider_name
                return self._simplify_provider_name(provider_name)

        return ""

    def get_current_event(self) -> CalendarEvent | None:
        """Get the event at the present time."""
        return self.get_event_at(dt_utils.now())

    def get_event_at(self, at: datetime.datetime) -> CalendarEvent | None:
        """Get the event at a given time."""
        event = self.api.get_current_event(at)
        return self._get_calendar_event(event)

    def get_events_between(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get all events."""
        events = self.api.get_events(start_date, end_date)
        return [self._get_calendar_event(event) for event in events]

    def _get_calendar_event(
        self, event: PlannedOutageEvent | None
    ) -> CalendarEvent | None:
        """Transform an event into a CalendarEvent."""
        if not event:
            return None

        summary: str = self.event_name_map.get(event.event_type)
        if DEBUG:
            summary += (
                f" {event.start.date().day}.{event.start.date().month}"
                f"@{event.start.time()}"
                f"-{event.end.date().day}.{event.end.date().month}"
                f"@{event.end.time()}"
            )

        # noinspection PyTypeChecker
        output = CalendarEvent(
            summary=summary,
            start=event.start,
            end=event.end,
            description=event.event_type.value,
            uid=event.event_type.value,
        )
        LOGGER.debug("Calendar Event: %s", output)
        return output

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState:
        if not event:
            return ConnectivityState.STATE_NORMAL

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.warning("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL

    def _simplify_provider_name(self, provider_name: str) -> str:
        """Simplify provider names for cleaner display in device names."""
        # Replace long DTEK provider names with just "ДТЕК"
        if PROVIDER_DTEK_FULL in provider_name.upper():
            return PROVIDER_DTEK_SHORT

        # Add more provider simplifications here as needed
        return provider_name
