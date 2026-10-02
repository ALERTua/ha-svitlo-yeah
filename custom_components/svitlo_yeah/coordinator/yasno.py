"""Coordinator for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime

    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_REGION,
    DOMAIN,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
)
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEventType,
    YasnoProvider,
    YasnoRegion,
)

from .coordinator import CHANGE_CHECK_WINDOW, IntegrationCoordinator

LOGGER = logging.getLogger(__name__)


class YasnoCoordinator(IntegrationCoordinator):
    """Class to manage fetching Yasno outages data."""

    api: YasnoApi

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        # Get configuration values
        region_id = config_entry.data.get(CONF_REGION)
        provider_id = config_entry.data.get(CONF_PROVIDER)
        group = config_entry.data.get(CONF_GROUP)

        # The config flow always writes these settings, so a broken entry
        # cannot load until the user adds it again
        if not region_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_region",
            )
        if not provider_id:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_provider",
            )
        if not group:
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="entry_without_group",
            )
        self.region_id = region_id
        self.provider_id = provider_id
        self.group = group

        self._region: YasnoRegion | None = None
        # Whether the region was looked up among the regions that Yasno gave
        self._source_region_checked = False
        # One API for the life of the coordinator, so that a failed request
        # keeps the planned outages of the last successful one.
        self.api = YasnoApi(
            hass,
            region_id=self.region_id,
            provider_id=self.provider_id,
            group=self.group,
        )

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_PLANNED_OUTAGE)}"
                f"{self._group_str}"
            ),
            PlannedOutageEventType.EMERGENCY: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE)}"
                f"{self._group_str}"
            ),
        }

    async def _async_update_data(self) -> None:
        """Fetch data from Svitlo Yeah API."""
        await self.async_fetch_translations()

        # Fetch outages data (now async with aiohttp, not blocking)
        answered = await self.api.fetch_data()
        # The entry can be unloaded or removed while the source answers
        if self._shutdown_requested:
            return
        self._set_last_fetch_failed(failed=not answered)
        await self._async_update_group_listed(listed=self.api.is_group_listed())

        # Check if outage data has changed (used for last_data_change attribute)
        now = dt_utils.now()
        current_events = self.api.get_events(now, now + CHANGE_CHECK_WINDOW)
        self.check_outage_data_changed(current_events, now)
        await self._async_store_last_data()

    def _source_data(self) -> dict | None:
        """Keep the planned outages, and the region that names the device."""
        if self.api.planned_outage_data is None:
            return None
        region = self.region
        return {
            "planned_outage_data": self.api.planned_outage_data,
            "region": None
            if region is None
            else {
                "id": region.id,
                "value": region.name,
                "dsos": [{"id": dso.id, "name": dso.name} for dso in region.dsos],
            },
        }

    def _restore_source_data(self, source: dict) -> None:
        """
        Give the kept planned outages back to the API, until the source answers.

        The kept region names the device while the regions request fails. It
        stays out of the class cache of YasnoApi, which the config flow uses.
        """
        self.api.planned_outage_data = source.get("planned_outage_data")
        if region := source.get("region"):
            self._region = YasnoRegion.from_dict(region)

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

    @property
    def region(self) -> YasnoRegion | None:
        """Get the region that Yasno gives, or the kept one while Yasno gives none."""
        if not self._source_region_checked and self.api.regions:
            self._source_region_checked = True
            if region := self.api.get_region_by_id(self.region_id):
                self._region = region
                LOGGER.debug("Caching region to %s", self._region)
        return self._region

    @property
    def region_name(self) -> str:
        """Get the configured region name."""
        if not self.region:
            LOGGER.debug("Trying to get region_name without region")
            return ""

        return self.region.name or ""

    @property
    def provider(self) -> YasnoProvider | None:
        """Get the configured provider."""
        if not self.region:
            LOGGER.debug("Trying to get provider without region")
            return None

        return next(
            (_ for _ in self.region.dsos if _.provider_id == self.provider_id), None
        )

    @property
    def provider_name(self) -> str:
        """Get the configured provider name."""
        if not self.provider:
            LOGGER.debug("Trying to get provider_name without provider")
            return ""

        return self.provider.short_name

    def get_scheduled_events_between(
        self,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Get scheduled outage events."""
        events = self.api.get_scheduled_events(start_date, end_date)
        output = [self._get_scheduled_calendar_event(_, rrule=None) for _ in events]
        return [_ for _ in output if _]

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        if not event:
            return ConnectivityState.STATE_NORMAL

        # Map event types to states using the uid field
        if event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        if event.uid == PlannedOutageEventType.EMERGENCY.value:
            return ConnectivityState.STATE_EMERGENCY

        LOGGER.debug("Unknown event type: %s", event.uid)
        return ConnectivityState.STATE_NORMAL
