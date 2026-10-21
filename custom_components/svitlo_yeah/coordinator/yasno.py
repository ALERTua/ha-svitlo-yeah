"""Coordinator for Svitlo Yeah integration."""

import datetime as dt
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, override

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from homeassistant.components.calendar import CalendarEvent
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from custom_components.svitlo_yeah.api.yasno import (
    AddressResult,
    YasnoApi,
    is_planned_outages,
)
from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_PROVIDER,
    CONF_REGION,
    CONF_STREET,
    DOMAIN,
    EVENT_GROUP_CHANGED,
    ISSUE_ADDRESS_NOT_FOUND,
    TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE,
    TRANSLATION_KEY_EVENT_PLANNED_OUTAGE,
    TRANSLATION_KEY_GROUP_CHANGED_MESSAGE,
    TRANSLATION_KEY_GROUP_CHANGED_TITLE,
    YASNO_REGION_PAGES,
)
from custom_components.svitlo_yeah.models import (
    ConnectivityState,
    PlannedOutageEventType,
    YasnoAddress,
    YasnoProvider,
    YasnoRegion,
)

from .coordinator import IntegrationCoordinator

LOGGER = logging.getLogger(__name__)

# Yasno moves a house to another group only rarely, so the check runs once a week
ADDRESS_CHECK_INTERVAL = dt.timedelta(days=7)
# The next try after a result that needs another check soon, for example no answer
ADDRESS_RETRY_INTERVAL = dt.timedelta(hours=1)
# After this many Not found results in a row, a repair issue asks for the address
NOT_FOUND_IN_A_ROW = 2
# The key of the state of the check in the kept data of the source
_ADDRESS_CHECK_KEY = "address_check"
# The region of Київ: its page is the page of a region that YASNO_REGION_PAGES lacks,
# as in the config flow
_KYIV_REGION_ID = 25
# The texts of the notification about a new group, when the translations lack them
GROUP_CHANGED_TITLE = "New Yasno group"
GROUP_CHANGED_MESSAGE = (
    "The Yasno group of «{entry}» changed from {old_group} to {new_group}. "
    "The entry now shows the schedule of the new group."
)


def address_not_found_issue_id(entry_id: str) -> str:
    """Return the id of the repair issue about an address that Yasno does not find."""
    return f"{ISSUE_ADDRESS_NOT_FOUND}_{entry_id}"


def group_changed_notification_id(entry_id: str) -> str:
    """Return the id of the notification about the new group of an entry."""
    return f"{EVENT_GROUP_CHANGED}_{entry_id}"


@dataclass(frozen=True)
class AddressCheck:
    """
    The state of the check of the group of an address, kept across a restart.

    The state is about its address: a Reconfigure that changes the address makes
    the state count as no state. A pending group waits for a second check, which
    must find it again before the entry gets it.
    """

    address: YasnoAddress
    # When the next check is due, an aware datetime in UTC. A local time plus a week
    # keeps the local hour, so a DST change would move the check by one hour.
    next_check: dt.datetime
    pending_group: str | None = None
    # The Not found results in a row
    not_found_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return the state in the form that the store keeps."""
        return {
            "address": {
                CONF_CITY: self.address.city,
                CONF_STREET: self.address.street,
                CONF_HOUSE: self.address.house,
            },
            "next_check": self.next_check.isoformat(),
            "pending_group": self.pending_group,
            "not_found_count": self.not_found_count,
        }

    @classmethod
    def from_dict(cls, data: object) -> AddressCheck | None:
        """Return the kept state, or None for a kept state of another shape."""
        if not isinstance(data, dict):
            return None
        address, next_check = data.get("address"), data.get("next_check")
        pending, count = data.get("pending_group"), data.get("not_found_count")
        if not (
            isinstance(address, dict)
            and isinstance(next_check, str)
            and isinstance(pending, str | None)
            # A whole number; a bool would pass isinstance(_, int)
            and type(count) is int
            and count >= 0
        ):
            return None
        kept_address = YasnoAddress.from_entry_data(address)
        moment = dt_utils.parse_datetime(next_check)
        if kept_address is None or moment is None or moment.tzinfo is None:
            return None
        return cls(kept_address, moment, pending, count)


class YasnoCoordinator(IntegrationCoordinator[YasnoApi, int]):
    """Class to manage fetching Yasno outages data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, config_entry)
        self.translations = {}

        self.region_id = self._required_setting(
            CONF_REGION, translation_key="entry_without_region"
        )
        self.provider_id = self._required_setting(
            CONF_PROVIDER, translation_key="entry_without_provider"
        )
        self.group = self._required_setting(
            CONF_GROUP, translation_key="entry_without_group"
        )

        self._region: YasnoRegion | None = None
        # Whether the region was looked up among the regions that Yasno gave
        self._source_region_checked = False
        # One API for the coordinator, so a failed request keeps the last outages
        self.api = YasnoApi(
            hass,
            region_id=self.region_id,
            provider_id=self.provider_id,
            group=self.group,
        )

        # The address of the entry, or None for an entry with a group only
        self._address = YasnoAddress.from_entry_data(config_entry.data)
        # The state of the check of the group of the address, or None until a poll
        self._address_check: AddressCheck | None = None
        # The result of the last check of the address, for the button and diagnostics
        self.address_check_result: AddressResult | None = None
        # Whether the next check runs at once and switches to a new group at once
        self._force_address_check = False

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

    async def _async_fetch(self) -> bool:
        """Fetch the planned outages, and tell whether Yasno answered."""
        return await self.api.fetch_data()

    async def _async_use_answer(self, answer: bool) -> None:  # noqa: FBT001  # the answer of _async_fetch
        """Keep whether Yasno answered, and whether its data lists the group."""
        self._set_last_fetch_failed(failed=not answer)
        await self._async_update_group_listed(listed=self.api.is_group_listed())

    def _source_data(self) -> dict | None:
        """
        Keep the planned outages, and the region that names the device.

        An entry with an address keeps the state of the check of its group too.
        """
        if self.api.planned_outage_data is None:
            return None
        region = self.region
        output: dict[str, Any] = {
            "planned_outage_data": self.api.planned_outage_data,
            "region": None
            if region is None
            else {
                "id": region.id,
                "value": region.name,
                "dsos": [{"id": dso.id, "name": dso.name} for dso in region.dsos],
            },
        }
        if self._address_check is not None:
            output[_ADDRESS_CHECK_KEY] = self._address_check.as_dict()
        return output

    def _restore_source_data(self, source: dict) -> None:
        """
        Give the kept planned outages back to the API, until the source answers.

        The kept region names the device while the regions request fails. It
        stays out of the class cache of YasnoApi, which the config flow uses.
        """
        planned = source.get("planned_outage_data")
        # Kept planned outages of another shape are no kept planned outages
        if is_planned_outages(planned):
            self.api.planned_outage_data = planned
        if region := source.get("region"):
            self._region = YasnoRegion.from_dict(region)
        check = AddressCheck.from_dict(source.get(_ADDRESS_CHECK_KEY))
        # After a Reconfigure, the kept state is about another address
        if check is not None and check.address == self._address:
            self._address_check = check

    @override
    async def _async_restore(self, stored: dict) -> None:
        """Give the kept data back, and the repair issue of an address not found."""
        await super()._async_restore(stored)
        check = self._address_check
        if check is not None and check.not_found_count >= NOT_FOUND_IN_A_ROW:
            await self._async_create_address_issue()

    async def async_check_address_now(self) -> None:
        """
        Check the group of the address at once, and switch to a new group at once.

        The check runs inside a poll, so it waits for the lock of the poll. After
        it, address_check_result is the result of this check, or None when the poll
        stopped before the check.
        """
        # The result of an earlier check must not count as the result of this one
        self.address_check_result = None
        self._force_address_check = True
        try:
            await self.async_refresh()
        finally:
            # The force goes back after the check, and also after a poll that
            # stopped before the check, so that no later poll gets it
            self._force_address_check = False

    async def async_address_found(self, address: YasnoAddress) -> None:
        """
        Keep that a Reconfigure found the address of the entry: the clock starts again.

        The Not found results of the address and its repair issue go away. A new
        group of the address comes with the Reconfigure, so no group is pending.
        Another address needs nothing: the kept state of another address is no state.
        """
        if address != self._address:
            return
        self._address_check = AddressCheck(
            address, dt_utils.utcnow() + ADDRESS_CHECK_INTERVAL
        )
        ir.async_delete_issue(
            self.hass, DOMAIN, address_not_found_issue_id(self.config_entry.entry_id)
        )
        await self._async_store_last_data()

    @override
    async def _async_after_update(self) -> None:
        """
        Check the group of the address of the entry, when the check is due.

        The check never runs in the first refresh: the update listener that
        reloads the entry with a new group comes only after it, and the first
        refresh holds up the start of Home Assistant.
        """
        if (
            self._address is None
            or self.config_entry.state is ConfigEntryState.SETUP_IN_PROGRESS
        ):
            return
        now = dt_utils.utcnow()
        check = self._address_check
        force = self._force_address_check
        if not force:
            if check is None:
                # A missing time starts the clock, so the check does not repeat the
                # search of the config flow, and a restart starts no check
                self._address_check = AddressCheck(
                    self._address, now + ADDRESS_CHECK_INTERVAL
                )
                await self._async_store_last_data()
                return
            if now < check.next_check:
                return
        await self._async_check_address(
            check or AddressCheck(self._address, now), force=force
        )

    async def _async_check_address(self, check: AddressCheck, *, force: bool) -> None:
        """
        Ask Yasno for the group of the address, and keep what the answer says.

        A check never fails the poll: the schedule and its flags stay as the
        fetch of the schedule set them.
        """
        entry_id = self.config_entry.entry_id
        address = check.address
        # A Reconfigure that finds the address keeps a newer state meanwhile
        kept = self._address_check
        try:
            result, group = await self.api.resolve_address(address)
        except Exception as err:  # noqa: BLE001  # a failed check must not fail the poll
            # The text of an error can hold the address, so the log names its type
            LOGGER.warning(
                "The check of the address of entry %s failed with %s",
                entry_id,
                type(err).__name__,
            )
            result, group = AddressResult.UNKNOWN, None
        self.address_check_result = result
        # The entry can be unloaded, removed or get another address meanwhile, and a
        # Reconfigure that found the address makes this answer an old one
        if (
            self._shutdown_requested
            or self._entry_address() != address
            or self._address_check is not kept
        ):
            return
        LOGGER.debug("The check of the address of entry %s gives %s", entry_id, result)
        now = dt_utils.utcnow()
        if result is AddressResult.FOUND and group == self.group:
            self._address_check = AddressCheck(address, now + ADDRESS_CHECK_INTERVAL)
            ir.async_delete_issue(
                self.hass, DOMAIN, address_not_found_issue_id(entry_id)
            )
        elif (
            result is AddressResult.FOUND
            and group is not None
            # The schedule of a group that the planned outages lack would be empty
            and group in self.api.get_yasno_groups()
        ):
            if force or check.pending_group == group:
                await self._async_switch_group(address, group, now)
                return
            # A second check one hour later must find the new group again. Yasno
            # found the address, so the Not found results in a row end.
            self._address_check = replace(
                check,
                pending_group=group,
                not_found_count=0,
                next_check=now + ADDRESS_RETRY_INTERVAL,
            )
        elif result is AddressResult.NOT_FOUND:
            await self._async_address_not_found(check, now)
        else:
            # No sure answer, or a new group that the planned outages do not list
            self._address_check = replace(
                check, next_check=now + ADDRESS_RETRY_INTERVAL
            )
        await self._async_store_last_data()

    async def _async_address_not_found(
        self, check: AddressCheck, now: dt.datetime
    ) -> None:
        """
        Count a Not found result; the group of the entry stays.

        One result can be a passing fault of Yasno, so the next try is soon. After
        NOT_FOUND_IN_A_ROW results, a warning and a repair issue ask for the address.
        """
        count = check.not_found_count + 1
        # A new group must come from two checks with no Not found between them
        check = replace(check, pending_group=None, not_found_count=count)
        if count < NOT_FOUND_IN_A_ROW:
            self._address_check = replace(
                check, next_check=now + ADDRESS_RETRY_INTERVAL
            )
            return
        self._address_check = replace(check, next_check=now + ADDRESS_CHECK_INTERVAL)
        if count == NOT_FOUND_IN_A_ROW:
            # The id, not the title: the title of an address entry is the address
            LOGGER.warning(
                "Yasno does not find the address of entry %s any more, so the entry "
                "keeps group %s",
                self.config_entry.entry_id,
                self.group,
            )
        await self._async_create_address_issue()

    async def _async_switch_group(
        self, address: YasnoAddress, group: str, now: dt.datetime
    ) -> None:
        """
        Give the entry the new group of its address; the update listener reloads it.

        The store gets the state of the check first, because the coordinator of
        the reloaded entry reads it.
        """
        self._address_check = AddressCheck(address, now + ADDRESS_CHECK_INTERVAL)
        data = self._last_data()
        if data is not None:
            # The kept answer is about the new group, which the planned outages list
            data |= {"group": group, "group_listed": True}
        await self._async_store_last_data(data)
        # The entry can change while the store saves. No await comes after this check.
        if self._shutdown_requested or self._entry_address() != address:
            return
        # A second check before the reload finds the entry with the new group already
        if self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_GROUP: group}
        ):
            # The id, not the title: the title of an address entry is the address
            LOGGER.info(
                "The Yasno group of entry %s changed from %s to %s",
                self.config_entry.entry_id,
                self.group,
                group,
            )
            self._notify_group_changed(str(self.group), group)

    def _notify_group_changed(self, old_group: str, new_group: str) -> None:
        """
        Tell the user about the new group: a notification, and an event for automations.

        The event has no address, because the recorder keeps each event: the entry
        id gives its title. The texts come from the translations of this poll, in
        the language of the server, so no await comes after the check of the entry.
        A later change replaces the notification of the entry.
        """
        entry_id = self.config_entry.entry_id
        self.hass.bus.async_fire(
            EVENT_GROUP_CHANGED,
            {
                "config_entry_id": entry_id,
                "old_group": old_group,
                "new_group": new_group,
            },
        )
        message = self.translations.get(
            TRANSLATION_KEY_GROUP_CHANGED_MESSAGE, GROUP_CHANGED_MESSAGE
        )
        persistent_notification.async_create(
            self.hass,
            message.format(
                entry=self.config_entry.title, old_group=old_group, new_group=new_group
            ),
            title=self.translations.get(
                TRANSLATION_KEY_GROUP_CHANGED_TITLE, GROUP_CHANGED_TITLE
            ),
            notification_id=group_changed_notification_id(entry_id),
        )

    def _entry_address(self) -> YasnoAddress | None:
        """Return the address that the entry has now: a Reconfigure can change it."""
        return YasnoAddress.from_entry_data(self.config_entry.data)

    async def _async_create_address_issue(self) -> None:
        """
        Show a repair issue that asks for the address, which Yasno does not find.

        The issue shows only while the state counts enough Not found results: a
        Reconfigure that finds the address can clear them while the texts load.
        """
        integration = await self._async_integration_title()
        check = self._address_check
        if check is None or check.not_found_count < NOT_FOUND_IN_A_ROW:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            address_not_found_issue_id(self.config_entry.entry_id),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ADDRESS_NOT_FOUND,
            translation_placeholders={
                # The title of an address entry is the address
                "entry": self.config_entry.title,
                "group": str(self.group),
                "url": YASNO_REGION_PAGES.get(
                    self.region_id, YASNO_REGION_PAGES[_KYIV_REGION_ID]
                ),
                # The way to Reconfigure goes through the list of integrations
                "integration": integration,
            },
        )

    def address_check_diagnostics(self) -> dict[str, Any] | None:
        """Return the state of the check without the address, or None without one."""
        if self._address is None:
            return None
        check = self._address_check
        return {
            "next_check": check.next_check.isoformat() if check else None,
            "pending_group": check.pending_group if check else None,
            "not_found_count": check.not_found_count if check else 0,
            "last_result": self.address_check_result,
        }

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
        start_date: dt.datetime,
        end_date: dt.datetime,
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
