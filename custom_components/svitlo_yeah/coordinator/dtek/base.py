"""Base class for DTEK Coordinator implementations."""

import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryError
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.dtek.base import FetchResult
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    DOMAIN,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from custom_components.svitlo_yeah.coordinator.coordinator import IntegrationCoordinator
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEventType,
)
from custom_components.svitlo_yeah.models.providers import DTEKJsonProvider

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from custom_components.svitlo_yeah.api.dtek.base import DtekAPIBase

LOGGER = logging.getLogger(__name__)


class DtekCoordinatorBase(IntegrationCoordinator):
    """Class to manage fetching DTEK outages data."""

    config_entry: ConfigEntry
    api: DtekAPIBase
    region_name: str = ""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        # Get configuration
        provider_id = config_entry.data.get(CONF_PROVIDER)
        # The config flow always writes these settings, so a broken entry
        # cannot load until the user adds it again
        if not provider_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_provider",
            )

        group = config_entry.data.get(CONF_GROUP)
        if not group:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_group",
            )
        self.provider_id = provider_id
        self.group = group

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_PLANNED_OUTAGE)}"
                f"{self._group_str}"
            ),
        }

    async def _async_update_data(self) -> None:
        """Fetch data from DTEK API."""
        await self.async_fetch_translations()

        now = dt_utils.now()
        result = await self.api.fetch_data()
        LOGGER.debug("Fetched %s data for %s", result, self)
        # An outdated schedule is an answer of the source, not a failure
        self._set_last_fetch_failed(failed=result is FetchResult.UNAVAILABLE)

        # Only fresh data can tell whether the source still lists the group.
        if result is FetchResult.FRESH:
            await self._async_update_group_listed(listed=self.api.is_group_listed())

        # Check if outage data has changed (used for last_data_change attribute)
        current_events = self.api.get_events(now, now + datetime.timedelta(hours=24))
        self.check_outage_data_changed(current_events)
        await self._async_store_last_data()

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        key = f"component.svitlo_yeah.common.{self.provider_id}"
        return self.translations.get(key, "")

    @property
    def provider(self) -> DTEKJsonProvider:
        """Get the configured provider."""
        return DTEKJsonProvider(region_name=self.provider_id)

    def get_scheduled_events_between(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get scheduled outage events."""
        events = self.api.get_scheduled_events(start_date, end_date)
        output = [
            self._get_scheduled_calendar_event(_, rrule="FREQ=WEEKLY") for _ in events
        ]
        return [_ for _ in output if _]

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE

        return ConnectivityState.STATE_NORMAL
