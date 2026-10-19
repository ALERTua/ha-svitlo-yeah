"""Coordinator of the public schedule of Sumyoblenergo (SOE)."""

import logging
from typing import TYPE_CHECKING

from custom_components.svitlo_yeah.api.soe import SoeClient
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
    common_translation_key,
)
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEventType,
    SoeProvider,
)

from .coordinator import IntegrationCoordinator

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)


class SoeCoordinator(IntegrationCoordinator[SoeClient, str]):
    """Coordinator of one sub-queue of the schedule on the site of SOE."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator of the configured sub-queue."""
        super().__init__(hass, config_entry)
        self._provider = SoeProvider()
        self.provider_id = self._provider.provider_id
        self.group = self._required_setting(
            CONF_GROUP, translation_key="entry_without_group"
        )
        # One client for the coordinator, so a failed request keeps the last answer
        self.api = SoeClient(hass, self.group)

    @property
    def provider(self) -> SoeProvider:
        """Get the provider: one for all entries of SOE."""
        return self._provider

    @property
    def region_name(self) -> str:
        """Get the region name in the language of the server, as the entry title has."""
        region = self.provider.region_name
        return self.translations.get(common_translation_key(region), region)

    @property
    def provider_name(self) -> str:
        """Name the provider, as the device name and the entry title show it."""
        return self.provider.short_name

    @property
    def event_name_map(self) -> dict:
        """Return a mapping of event names to translations."""
        return {
            PlannedOutageEventType.DEFINITE: (
                f"{self.translations.get(TRANSLATION_KEY_EVENT_PLANNED_OUTAGE)}"
                f"{self._group_str}"
            ),
        }

    async def _async_fetch(self) -> bool:
        """Fetch the schedule, and tell whether the site answered."""
        LOGGER.debug("Updating SOE data for group %s", self.group)
        return await self.api.fetch_data()

    async def _async_use_answer(self, answer: bool) -> None:  # noqa: FBT001  # the answer of _async_fetch
        """Keep whether the site answered, and whether its answer lists the group."""
        self._set_last_fetch_failed(failed=not answer)
        await self._async_update_group_listed(listed=self.api.is_group_listed())

    def _source_data(self) -> dict | None:
        """Keep the last answer with the day that it gives."""
        if self.api.answer is None or self.api.day is None:
            return None
        return {"answer": self.api.answer, "day": self.api.day.isoformat()}

    def _restore_source_data(self, source: dict) -> None:
        """Give the kept answer and its day to the client until the site answers."""
        self.api.restore(source.get("answer"), source.get("day"))

    def _event_to_state(self, event: CalendarEvent | None) -> ConnectivityState | None:
        """Map event to connectivity state."""
        if event is not None and event.uid == PlannedOutageEventType.DEFINITE.value:
            return ConnectivityState.STATE_PLANNED_OUTAGE
        return ConnectivityState.STATE_NORMAL
