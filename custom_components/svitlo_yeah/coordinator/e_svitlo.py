"""E-Svitlo coordinator for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.exceptions import ConfigEntryError
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.e_svitlo import ESvitloClient
from custom_components.svitlo_yeah.const import (
    DOMAIN,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    ESvitloProvider,
    PlannedOutageEventType,
)

from .coordinator import CHANGE_CHECK_WINDOW, IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class ESvitloCoordinator(IntegrationCoordinator):
    """Coordinator for E-Svitlo API integration."""

    api: ESvitloClient
    provider: ESvitloProvider

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the E-Svitlo coordinator."""
        super().__init__(hass, config_entry)

        username = config_entry.data.get("username")
        password = config_entry.data.get("password")
        if not username or not password:
            # The config flow always writes the login, so the user adds the entry again
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_login",
            )

        # Create provider from config entry data
        self.provider: ESvitloProvider = ESvitloProvider(
            user_name=username,
            password=password,
            account_id=config_entry.data.get("account_id"),
        )

        # Initialize API client
        self.api: ESvitloClient = ESvitloClient(hass, self.provider)

        # Set group to auto - will be updated after first API call
        self.group = "auto"

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        return self.provider.region_name

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        return self.config_entry.data.get(
            "address_str",
            f"E-Svitlo ({self.provider.user_name})",
        )

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

    async def _async_update_data(self) -> None:
        """Fetch data from E-Svitlo API."""
        LOGGER.debug("Updating E-Svitlo data")

        # Fetch translations
        await self.async_fetch_translations()

        # Ensure we have user info (including group) before fetching disconnections
        if isinstance(self.api, ESvitloClient):
            if not self.api.user_id or not self.api.group:
                await self.api.get_user_info()

            # Update group from API if available
            if self.api.group:
                self.group = self.api.group

            # Get disconnections data
            events = await self.api.get_disconnections()
            # A refused login is an answer of the server, not a missing answer
            self._set_last_fetch_failed(
                failed=events is None and not self.api.login_rejected
            )
            self._set_login_rejected(rejected=self.api.login_rejected)

            if events is not None:
                LOGGER.debug(
                    "Successfully updated E-Svitlo data with %d events", len(events)
                )
                # Check if outage data has changed
                now = dt_utils.now()
                current_events = self.api.get_events(now, now + CHANGE_CHECK_WINDOW)
                self.check_outage_data_changed(current_events, now)
            else:
                LOGGER.debug("Failed to fetch E-Svitlo data")
                # Keep existing data if fetch fails

            await self._async_store_last_data()

    def _set_login_rejected(self, *, rejected: bool) -> None:
        """
        Ask for the new login once the server refuses it, and log each change once.

        The polls go on with the old login. The server can refuse it for a
        while, for example during maintenance, and then the next poll that
        logs in brings the schedule back without any action of the user, and
        closes the open reauthentication.
        """
        if rejected == self.login_rejected:
            return
        self.login_rejected = rejected
        entry_id = self.config_entry.entry_id
        if rejected:
            LOGGER.warning(
                "E-Svitlo refused the login of entry %s, so Home Assistant "
                "asks for the new login; the entities keep the last schedule",
                entry_id,
            )
            self.config_entry.async_start_reauth(self.hass)
        else:
            LOGGER.info("E-Svitlo accepts the login of entry %s again", entry_id)
            # The open reauthentication would ask for a login that works again
            for flow in list(
                self.config_entry.async_get_active_flows(self.hass, {SOURCE_REAUTH})
            ):
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    def _source_data(self) -> dict | None:
        """Keep the raw answer of the last disconnections request, and the group."""
        if self.api.last_answer is None:
            return None
        last_update = self.api.get_updated_on()
        return {
            "disconnections": self.api.last_answer,
            "last_update": last_update.isoformat() if last_update else None,
            "group": self.group,
        }

    def _restore_source_data(self, source: dict) -> None:
        """
        Give the kept answer back to the client, until the server answers.

        The kept group names the device only. The client still asks the server
        for the group, so a change of the group on the server comes through.
        """
        if answer := source.get("disconnections"):
            last_update = source.get("last_update")
            self.api.restore_disconnections(
                answer, dt_utils.parse_datetime(last_update) if last_update else None
            )
        if group := source.get("group"):
            self.group = group

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        if event is None:
            return ConnectivityState.STATE_NORMAL

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.debug("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL

    @property
    def _group_str(self) -> str:
        return ""
