"""Yasno API client for Svitlo Yeah integration."""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.core import HomeAssistant

from custom_components.svitlo_yeah.const import (
    BLOCK_KEY_STATUS,
    HOURS_IN_DAY,
    MINUTES_IN_DAY,
    TZ_UA,
    YASNO_ADDRESS_MATCHES_CAP,
    YASNO_ADDRESSES_ENDPOINT,
    YASNO_HOUSE_LIST_REQUESTS_MAX,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from custom_components.svitlo_yeah.models import (
    PlannedOutageEvent,
    PlannedOutageEventType,
    YasnoAddress,
    YasnoAddressItem,
    YasnoPlannedOutageDayStatus,
    YasnoRegion,
)

from .common_tools import (
    REQUEST_ERRORS,
    _merge_adjacent_events,
    parse_timestamp,
    start_moment,
)

LOGGER = logging.getLogger(__name__)

_TIMEOUT_SECS: Final = 60

# The list of the houses of a street asks this many requests at the same time
_HOUSE_REQUESTS_AT_ONCE: Final = 5
# The list of the houses of a street asks one query for each digit
_DIGITS: Final = "0123456789"
# The number at the start of the number of a house, for the natural order
_LEADING_NUMBER = re.compile(r"\d+")
# The code of the 404 body for an id or an address that Yasno does not know
_ENTRY_NOT_FOUND: Final = "EntryNotFound"
# The kind of a place at the start of its name: a word with a dot, with or without
# a space after it («вул. Хрещатик», «м.Дніпро»), or the kinds of a settlement and of
# a town, which stand with a space
_PLACE_KIND = re.compile(
    r"^(?:\w+(?:-\w+)?\.\s*|(?:смт|с-ще)\s+)"  # noqa: RUF001  # the Cyrillic kinds
)

# Yasno does not find a house when a letter of its number is Latin. Each Latin
# letter on the left looks like the Cyrillic letter at the same place on the right,
# in the same case. A small b, h, k, m or t does not look like its Cyrillic pair.
_LATIN_TO_CYRILLIC = str.maketrans(
    "ABCEHIKMOPTXYaceiopxy",
    "АВСЕНІКМОРТХУасеіорху",  # noqa: RUF001  # the Cyrillic look-alikes
)


class AddressResult(StrEnum):
    """
    The result of a check of an address.

    Found gives a group. Not found means that Yasno does not know the address.
    Unknown means that the answer says nothing: no answer, an odd answer, or
    a match that is not sure.
    """

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


def cyrillic_look_alikes(text: str) -> str:
    """
    Return the text with Cyrillic letters in place of the Latin look-alikes.

    The config flow gives a typed house through it. The check of a stored
    address does not, because Yasno wrote the stored name itself.
    """
    return text.translate(_LATIN_TO_CYRILLIC)


def normalize_name(name: str) -> str:
    """
    Return the name in the form that two writings of it share.

    One space between words, Cyrillic letters in place of the Latin ones that
    look the same, and no case. Thus a Latin and a Cyrillic A are one letter. The
    letters change before the case goes, because only a capital Latin B looks
    like the Cyrillic letter VE.
    """
    return cyrillic_look_alikes(" ".join(name.split())).casefold()


def name_without_kind(name: str) -> str:
    """
    Return the normal form of the name without the kind of the place at its start.

    «вул. Хрещатик» gives «хрещатик», and «м. Дніпро» gives «дніпро». Only one kind
    goes away: a second word with a dot stays.
    """
    return _PLACE_KIND.sub("", normalize_name(name), count=1)


def exact_matches(items: list[YasnoAddressItem], name: str) -> list[YasnoAddressItem]:
    """Return the items whose value is the name, as normalize_name reads both."""
    wanted = normalize_name(name)
    return [_ for _ in items if normalize_name(_.value) == wanted]


def _address_items(answer: object) -> list[YasnoAddressItem] | None:
    """Return the matches of a search answer, or None for another shape."""
    if not isinstance(answer, list):
        return None
    items = []
    for item in answer:
        if not (
            isinstance(item, dict)
            # The id is a whole number; a bool would pass isinstance(_, int)
            and type(item.get("id")) is int
            and isinstance(item.get("value"), str)
        ):
            return None
        items.append(YasnoAddressItem(id=item["id"], value=item["value"]))
    return items


def _is_entry_not_found(status: int | None, answer: object) -> bool:
    """
    Tell whether Yasno says that it does not know the id or the address.

    Only a 404 with the code EntryNotFound says so. Another 404 says nothing sure,
    for example after Yasno moved an endpoint.
    """
    return (
        status == HTTPStatus.NOT_FOUND
        and isinstance(answer, dict)
        and answer.get("code") == _ENTRY_NOT_FOUND
    )


def _house_order(house: YasnoAddressItem) -> tuple[int, int, str]:
    """
    Return the key of a house for the natural order: 2, 6, 6Б, 10, 10Б.

    The number at the start comes first, as a number, and the rest of the value
    follows. A value without a number at the start goes last.
    """
    if number := _LEADING_NUMBER.match(house.value):
        return 0, int(number[0]), house.value[number.end() :].casefold()
    return 1, 0, house.value.casefold()


def _one_match(
    items: list[YasnoAddressItem] | None, name: str
) -> YasnoAddressItem | AddressResult:
    """
    Return the one item that is the name, or the result that ends the check.

    A list as long as the cap is cut, so the name can be missing from it.
    """
    if items is None:
        return AddressResult.UNKNOWN
    matches = exact_matches(items, name)
    if len(matches) == 1:
        return matches[0]
    # Two exact matches: the name does not tell which one is the address
    if matches or len(items) >= YASNO_ADDRESS_MATCHES_CAP:
        return AddressResult.UNKNOWN
    return AddressResult.NOT_FOUND


def _minutes_to_time(minutes: int, dt: datetime) -> datetime:
    """Convert minutes from start of day to datetime."""
    hours = minutes // 60
    mins = minutes % 60

    # Handle end of day (24:00) as 00:00 of the next day
    if hours == HOURS_IN_DAY:
        dt = dt + timedelta(days=1)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    return dt.replace(hour=hours, minute=mins, second=0, microsecond=0)


def _parse_day_schedule(day_data: dict, dt: datetime) -> list[PlannedOutageEvent]:
    """
    Parse schedule for a single day.

    {
      "3.1": {
        "today": {
          "slots": [
            {
              "start": 0,
              "end": 960,
              "type": "NotPlanned"
            },
            {
              "start": 960,
              "end": 1200,
              "type": "Definite"
            },
            {
              "start": 1200,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-27T00:00:00+02:00",
          "status": "ScheduleApplies"
        },
        "tomorrow": {
          "slots": [
            {
              "start": 0,
              "end": 900,
              "type": "NotPlanned"
            },
            {
              "start": 900,
              "end": 1080,
              "type": "Definite"
            },
            {
              "start": 1080,
              "end": 1440,
              "type": "NotPlanned"
            }
          ],
          "date": "2025-10-28T00:00:00+02:00",
          "status": "WaitingForSchedule"
        },
        "updatedOn": "2025-10-27T13:42:41+00:00"
      },
    }
    """
    events = []
    slots = day_data.get("slots", [])

    for slot in slots:
        start_minutes = slot["start"]
        end_minutes = slot["end"]
        slot_type = slot["type"]

        # parse only outages, and a slot without a duration is no outage
        if (
            slot_type != PlannedOutageEventType.DEFINITE.value
            or start_minutes == end_minutes
        ):
            continue

        event_start = _minutes_to_time(start_minutes, dt)
        event_end = _minutes_to_time(end_minutes, dt)

        events.append(
            PlannedOutageEvent(
                start=event_start,
                end=event_end,
                event_type=PlannedOutageEventType(slot_type),
            ),
        )

    return events


def _is_day(day: dict) -> bool:
    """Return whether a day of a group has the shape that the parsers read."""
    slots = day.get("slots", [])
    return (
        isinstance(day.get("date"), str | None)
        and isinstance(slots, list)
        and all(
            isinstance(slot, dict)
            # The minutes are whole numbers; a bool would pass isinstance(_, int)
            and all(
                type(slot.get(key)) is int and 0 <= slot[key] <= MINUTES_IN_DAY
                for key in ("start", "end")
            )
            # HA refuses a calendar event that ends before it starts
            and slot["start"] <= slot["end"]
            and isinstance(slot.get("type"), str)
            for slot in slots
        )
    )


def is_planned_outages(answer: object) -> bool:
    """Return whether planned outages have the shape that the parsers read."""
    return isinstance(answer, dict) and all(
        isinstance(group, dict)
        # The parsers skip a value that is not a day, for example updatedOn
        and all(_is_day(day) for day in group.values() if isinstance(day, dict))
        for group in answer.values()
    )


def _in_range(
    events: list[PlannedOutageEvent], start_date: datetime, end_date: datetime
) -> list[PlannedOutageEvent]:
    """Sort and merge the events, and keep those in the range and each all-day one."""
    events = _merge_adjacent_events(sorted(events, key=start_moment))
    return [
        _
        for _ in events
        if _.all_day or not (_.end <= start_date or _.start >= end_date)
    ]


class YasnoApi:
    """Class to interact with Yasno API."""

    _regions: list[YasnoRegion] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        region_id: int | None = None,
        provider_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Initialize the Yasno API."""
        self.hass = hass
        self.session: aiohttp.ClientSession = async_get_clientsession(hass)
        self.region_id: int | None = region_id
        self.provider_id: int | None = provider_id
        self.group: str | None = group
        self.planned_outage_data: dict | None = None

    async def _get_route_data(
        self,
        url: str,
        timeout_secs: int = _TIMEOUT_SECS,
    ) -> Any:
        """Fetch the JSON of the URL: a list or a dict, or None after a failure."""
        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
            ) as response:
                response.raise_for_status()
                return await response.json()

        except REQUEST_ERRORS:
            # The coordinator logs once when Yasno stops answering
            LOGGER.debug("Error fetching data from %s", url, exc_info=True)
            return None

    async def fetch_yasno_regions(self) -> None:
        """Fetch regions and providers data."""
        if YasnoApi._regions:
            return

        result = await self._get_route_data(YASNO_REGIONS_ENDPOINT)

        if result:
            YasnoApi._regions = [YasnoRegion.from_dict(_) for _ in result]

        LOGGER.debug("Fetched yasno regions data: %s", YasnoApi._regions)

    async def fetch_planned_outage_data(self) -> bool:
        """Fetch the planned outages of the region, and tell whether Yasno answered."""
        if not self.region_id or not self.provider_id:
            LOGGER.error(
                "Region ID %s and Provider ID %s must be set before fetching outages",
                self.region_id,
                self.provider_id,
            )
            return False

        url = YASNO_PLANNED_OUTAGES_ENDPOINT.format(
            region_id=self.region_id,
            dso_id=self.provider_id,
        )
        LOGGER.debug("Fetching Yasno planned outage data: %s", url)
        output = await self._get_route_data(url)
        if output is None or not is_planned_outages(output):
            # A failed request or an answer of another shape says nothing new,
            # so the last planned outages stay
            LOGGER.debug("Keeping the last Yasno planned outage data")
            return False
        LOGGER.debug("Filling Yasno planned outage data with: %s", output)
        self.planned_outage_data = output

        return True

    @property
    def regions(self) -> list[YasnoRegion] | None:
        """Return the list of regions."""
        return YasnoApi._regions

    def get_region_by_id(self, region_id: int) -> YasnoRegion | None:
        """Get region data by name."""
        if not self.regions:
            LOGGER.debug(
                "Yasno API get_region_by_id %s while regions are not yet fetched",
                region_id,
            )
            return None

        LOGGER.debug("Getting region by id: %s among %s", region_id, self.regions)
        return next((_ for _ in self.regions if _.id == region_id), None)

    def get_yasno_groups(self) -> list[str]:
        """Get groups from planned outage data."""
        if not self.planned_outage_data:
            LOGGER.debug("Cannot get yasno groups: no planned outage data yet")
            return []

        return list(self.planned_outage_data.keys())

    def is_group_listed(self) -> bool | None:
        """
        Tell whether the planned outage data has the configured group.

        None: there is no data or no configured group, so the source says
        nothing about the group.
        """
        if (
            not self.group
            or not isinstance(self.planned_outage_data, dict)
            or not self.planned_outage_data
        ):
            return None
        return self.group in self.planned_outage_data

    def _get_group_data(self) -> dict | None:
        """
        Get data for the configured group.

        {
          'today': {
            'slots': [
              {
                'start': 0,
                'end': 1140,
                'type': 'NotPlanned'
              },
              {
                'start': 1140,
                'end': 1320,
                'type': 'Definite'
              },
              {
                'start': 1320,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-28T00:00:00+02:00',
            'status': 'ScheduleApplies'
          },
          'tomorrow': {
            'slots': [
              {
                'start': 0,
                'end': 960,
                'type': 'NotPlanned'
              },
              {
                'start': 960,
                'end': 1200,
                'type': 'Definite'
              },
              {
                'start': 1200,
                'end': 1440,
                'type': 'NotPlanned'
              }
            ],
            'date': '2025-10-29T00:00:00+02:00',
            'status': 'WaitingForSchedule'
          },
          'updatedOn': '2025-10-28T10:23:56+00:00'
        }
        """
        if not self.planned_outage_data or self.group not in self.planned_outage_data:
            LOGGER.debug("No planned outage data for group %s", self.group)
            return None

        # noinspection PyTypeChecker
        return self.planned_outage_data[self.group]

    def get_updated_on(self) -> datetime | None:
        """Get the updated on timestamp for the configured group."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("Cannot get_updated_on: no group_data data yet")
            return None

        if "updatedOn" not in group_data:
            LOGGER.debug(
                "Cannot get_updated_on: updatedOn not in group_data %s", group_data
            )
            return None

        return parse_timestamp(group_data["updatedOn"])

    def get_current_event(self, at: datetime) -> PlannedOutageEvent | None:
        """Get the current event."""
        all_events = self.get_events(at, at + timedelta(days=1))
        # The date of an all-day event is a day in Kyiv
        day = at.astimezone(TZ_UA).date()
        for event in all_events:
            if event.all_day and event.start == day:
                return event
            if not event.all_day and event.start <= at < event.end:
                return event

        return None

    def _days(self) -> Iterator[tuple[str | None, dict, datetime]]:
        """Yield the status, the data and the moment of each day of the group."""
        group_data = self._get_group_data()
        if not group_data:
            LOGGER.debug("No days: no group_data yet")
            return

        for key, day_data in group_data.items():
            # parse only "today" and "tomorrow"
            if key == "updatedOn" or not isinstance(day_data, dict):
                continue

            date_str = day_data.get("date")
            if not date_str:
                continue

            day_dt = dt_utils.parse_datetime(date_str)
            if not day_dt:
                continue

            # The slots are minutes of the day in Kyiv, whatever the time zone of HA
            yield day_data.get(BLOCK_KEY_STATUS), day_data, day_dt.astimezone(TZ_UA)

    def get_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get all events within the date range."""
        events: list[PlannedOutageEvent] = []
        for status, day_data, day_dt in self._days():
            if status == YasnoPlannedOutageDayStatus.STATUS_SCHEDULE_APPLIES.value:
                events.extend(_parse_day_schedule(day_data, day_dt))
            elif status == YasnoPlannedOutageDayStatus.STATUS_EMERGENCY_SHUTDOWNS.value:
                """
                {
                    "3.1": {
                        "today": {
                            "slots": [],
                            "date": "2025-10-27T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "tomorrow": {
                            "slots": [],
                            "date": "2025-10-28T00:00:00+02:00",
                            "status": "EmergencyShutdowns"
                        },
                        "updatedOn": "2025-10-27T07:04:31+00:00"
                    }
                }
                """
                events.append(
                    PlannedOutageEvent(
                        start=day_dt.date(),
                        end=day_dt.date() + timedelta(days=1),
                        all_day=True,
                        event_type=PlannedOutageEventType.EMERGENCY,
                    )
                )
        return _in_range(events, start_date, end_date)

    def get_scheduled_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[PlannedOutageEvent]:
        """Get scheduled events (includes WaitingForSchedule status)."""
        events = [
            event
            for status, day_data, day_dt in self._days()
            if status == YasnoPlannedOutageDayStatus.STATUS_WAITING_FOR_SCHEDULE.value
            for event in _parse_day_schedule(day_data, day_dt)
        ]
        return _in_range(events, start_date, end_date)

    async def fetch_data(self) -> bool:
        """
        Fetch all required data, and tell whether Yasno gave the planned outages.

        The regions only name the device, so their request does not count.
        """
        await self.fetch_yasno_regions()
        return await self.fetch_planned_outage_data()

    async def _get_address_answer(
        self, path: str, params: dict[str, int | str]
    ) -> tuple[int | None, Any]:
        """
        Ask an address endpoint, and return the HTTP status with the JSON body.

        Any status that has a JSON body counts, because a 404 EntryNotFound means
        that Yasno does not know the address. No answer is (None, None). The query
        holds the address of a person, so the log names the path and the status only.
        """
        try:
            async with self.session.get(
                YASNO_ADDRESSES_ENDPOINT + path,
                params=params,
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT_SECS),
            ) as response:
                status = response.status
                body = await response.json()
        except REQUEST_ERRORS as err:
            # The message of an error can hold the URL with the query
            LOGGER.debug(
                "No answer from the Yasno address endpoint %s: %s",
                path,
                type(err).__name__,
            )
            return None, None
        LOGGER.debug("The Yasno address endpoint %s answered %s", path, status)
        return status, body

    def _address_params(
        self, city_id: int | None, **params: int | str
    ) -> dict[str, int | str] | None:
        """Return the parameters of an address request, or None without a region."""
        if self.region_id is None or self.provider_id is None:
            LOGGER.error(
                "Region ID %s and Provider ID %s must be set before an address request",
                self.region_id,
                self.provider_id,
            )
            return None
        output: dict[str, int | str] = {
            "regionId": self.region_id,
            "dsoId": self.provider_id,
            **params,
        }
        if city_id is not None:
            output["cityId"] = city_id
        return output

    async def _search_address(
        self, path: str, city_id: int | None, **params: int | str
    ) -> list[YasnoAddressItem] | None:
        """
        Return the matches of a search, or None when Yasno says nothing sure.

        A 404 EntryNotFound is no match, for example for a street id that Yasno
        changed.
        """
        request = self._address_params(city_id, **params)
        if request is None:
            return None
        status, answer = await self._get_address_answer(path, request)
        if _is_entry_not_found(status, answer):
            return []
        if status != HTTPStatus.OK:
            return None
        return _address_items(answer)

    async def search_cities(self, query: str) -> list[YasnoAddressItem] | None:
        """Search the cities of the region, at most YASNO_ADDRESS_MATCHES_CAP."""
        return await self._search_address("cities", None, query=query.strip())

    async def search_streets(
        self, query: str, city_id: int | None = None
    ) -> list[YasnoAddressItem] | None:
        """Search the streets of the region, or of the city in it."""
        return await self._search_address("streets", city_id, query=query.strip())

    async def search_houses(
        self, street_id: int, query: str, city_id: int | None = None
    ) -> list[YasnoAddressItem] | None:
        """Search the houses of a street; a typed query needs cyrillic_look_alikes."""
        return await self._search_address(
            "houses", city_id, streetId=street_id, query=query.strip()
        )

    async def all_houses(
        self, street_id: int, city_id: int | None = None
    ) -> list[YasnoAddressItem] | None:
        """
        Return the houses of a street that the queries find, in the natural order.

        Yasno finds a query inside the number of a house, and it gives at most
        YASNO_ADDRESS_MATCHES_CAP houses for one query. So each digit is a query, and
        a query that got the cap gets ten longer ones. A cut answer can hide a house,
        so the house step also searches a typed number at Yasno. A query without a
        sure answer gives None. The search stops after YASNO_HOUSE_LIST_REQUESTS_MAX
        requests.
        """
        semaphore = asyncio.Semaphore(_HOUSE_REQUESTS_AT_ONCE)

        async def search(query: str) -> list[YasnoAddressItem] | None:
            async with semaphore:
                return await self.search_houses(street_id, query, city_id)

        houses: dict[int, YasnoAddressItem] = {}
        queries = list(_DIGITS)
        asked = 0
        while queries:
            room = YASNO_HOUSE_LIST_REQUESTS_MAX - asked
            if room <= 0:
                # The log has the number of requests only, never an address
                LOGGER.debug("The list of houses stops after %s requests", asked)
                break
            wave, queries = queries[:room], queries[room:]
            asked += len(wave)
            answers = await asyncio.gather(*(search(query) for query in wave))
            for query, answer in zip(wave, answers, strict=True):
                if answer is None:
                    return None
                for house in answer:
                    houses.setdefault(house.id, house)
                if len(answer) >= YASNO_ADDRESS_MATCHES_CAP:
                    queries.extend(query + digit for digit in _DIGITS)
        return sorted(houses.values(), key=_house_order)

    async def get_address_group(
        self, street_id: int, house_id: int, city_id: int | None = None
    ) -> tuple[AddressResult, str | None]:
        """Ask for the group of a house, as "<group>.<subgroup>" when Yasno gives it."""
        request = self._address_params(city_id, streetId=street_id, houseId=house_id)
        if request is None:
            return AddressResult.UNKNOWN, None
        status, answer = await self._get_address_answer("group", request)
        if _is_entry_not_found(status, answer):
            return AddressResult.NOT_FOUND, None
        if (
            status == HTTPStatus.OK
            and isinstance(answer, dict)
            # Whole numbers; a bool would pass isinstance(_, int)
            and type(answer.get("group")) is int
            and type(answer.get("subgroup")) is int
        ):
            return AddressResult.FOUND, f"{answer['group']}.{answer['subgroup']}"
        return AddressResult.UNKNOWN, None

    async def resolve_address(
        self, address: YasnoAddress
    ) -> tuple[AddressResult, str | None]:
        """
        Find the group of a stored address, level by level.

        Each level searches for its stored name, and goes on with the one item
        that has this name. Yasno changes its ids, so the names are stored and
        the ids are searched again. When the query of the stored house is cut at
        the cap without the house, the result is Unknown, because each other query
        that can find the house gives a longer list.
        """
        city_id = None
        if address.city is not None:
            city = _one_match(await self.search_cities(address.city), address.city)
            if isinstance(city, AddressResult):
                return city, None
            city_id = city.id

        street = _one_match(
            await self.search_streets(address.street, city_id), address.street
        )
        if isinstance(street, AddressResult):
            return street, None

        house = _one_match(
            await self.search_houses(street.id, address.house, city_id), address.house
        )
        if isinstance(house, AddressResult):
            return house, None

        return await self.get_address_group(street.id, house.id, city_id)
