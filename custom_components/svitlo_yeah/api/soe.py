"""Client of the public outage schedule of Sumyoblenergo (SOE) on soe.com.ua."""

import datetime as dt
import logging
from typing import TYPE_CHECKING, TypeIs

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_utils

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.svitlo_yeah.models import PlannedOutageEvent

from custom_components.svitlo_yeah.const import SOE_SCHEDULE_URL, TZ_UA

from .common_tools import (
    REQUEST_ERRORS,
    _merge_adjacent_events,
    parse_periods,
    parse_timestamp,
)

LOGGER = logging.getLogger(__name__)

# The update time of a sub-queue: «Оновлено: 11.10.2026 18:48», Kyiv time
UPDATED_PREFIX = "Оновлено:"


def is_soe_answer(answer: object) -> TypeIs[dict]:
    """
    Return whether an answer of the site has the shape that the parsers read.

    {"data": [{"cherga_n": "1.1", "no_data": false,
               "last_update": "Оновлено: 11.10.2026 18:48",
               "lst_time_disc": [{"start_time": "20:00", "end_time": "22:00"}]}]}

    A list without sub-queues names no group, so it is no usable answer.
    """
    if not isinstance(answer, dict):
        return False
    groups = answer.get("data")
    return (
        isinstance(groups, list)
        and bool(groups)
        and all(
            isinstance(group, dict) and isinstance(group.get("cherga_n"), str)
            for group in groups
        )
    )


def _kyiv_today() -> dt.date:
    """Return the day in Kyiv: the site gives the schedule of this day only."""
    return dt_utils.now(TZ_UA).date()


class SoeClient:
    """
    Read the schedule of each sub-queue from the site of SOE.

    The answer has no date and no tomorrow: the site shows the schedule of the
    current day in Kyiv. So the client keeps each answer with the day of its
    fetch, and an answer of an earlier day gives no outages for today.
    """

    def __init__(self, hass: HomeAssistant, group: str | None = None) -> None:
        """Initialize the client of one sub-queue, or of none for the group list."""
        self.session: aiohttp.ClientSession = async_get_clientsession(hass)
        self.group = group
        self.answer: dict | None = None
        self.day: dt.date | None = None
        # The outages of the sub-queue in the last answer, parsed once for each answer
        self._outages: list[PlannedOutageEvent] = []

    async def fetch_data(self) -> bool:
        """Fetch the schedule, and tell whether the site gave a usable answer."""
        try:
            async with self.session.get(
                SOE_SCHEDULE_URL, timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                response.raise_for_status()
                answer = await response.json()
        except REQUEST_ERRORS:
            # The coordinator logs once when the site stops answering
            LOGGER.debug("Error fetching data from %s", SOE_SCHEDULE_URL, exc_info=True)
            return False

        if not is_soe_answer(answer):
            # An answer of another shape says nothing new, so the last one stays
            LOGGER.debug("Keeping the last SOE schedule, the answer has another shape")
            return False
        self.answer = answer
        self.day = _kyiv_today()
        self._outages = self._parse_outages()
        return True

    def restore(self, answer: object, day: object) -> None:
        """Use a kept answer and its day until the site answers, if both can be read."""
        if not is_soe_answer(answer) or not isinstance(day, str):
            return
        try:
            kept_day = dt.date.fromisoformat(day)
        except ValueError:
            return
        self.answer = answer
        self.day = kept_day
        self._outages = self._parse_outages()

    def get_groups(self) -> list[str]:
        """Return the sub-queues of the last answer, in the order of the site."""
        if self.answer is None:
            return []
        return [group["cherga_n"] for group in self.answer["data"]]

    def is_group_listed(self) -> bool | None:
        """Tell whether the last answer has the sub-queue; None without an answer."""
        if not self.group or self.answer is None:
            return None
        return self.group in self.get_groups()

    def _group_data(self) -> dict | None:
        """Return the sub-queue of the last answer, or None."""
        if self.answer is None:
            return None
        return next(
            (_ for _ in self.answer["data"] if _["cherga_n"] == self.group), None
        )

    def _parse_outages(self) -> list[PlannedOutageEvent]:
        """
        Return the outages of the sub-queue on the day of the last answer.

        An empty list means no outages: the site of SOE shows a dash for it.
        """
        group = self._group_data()
        if group is None or self.day is None:
            return []
        events = parse_periods(group.get("lst_time_disc"), self.day)
        # The end of one outage is the start of the next one, so they are one
        return _merge_adjacent_events(sorted(events, key=lambda e: e.start))

    def get_current_event(self, at: dt.datetime) -> PlannedOutageEvent | None:
        """Return the outage at the moment, or None."""
        return next((e for e in self._outages if e.start <= at < e.end), None)

    def get_events(
        self, start_date: dt.datetime, end_date: dt.datetime
    ) -> list[PlannedOutageEvent]:
        """Return the outages that overlap the range."""
        return [e for e in self._outages if e.end > start_date and e.start < end_date]

    def get_updated_on(self) -> dt.datetime | None:
        """Return when SOE last updated the schedule of the sub-queue, or None."""
        group = self._group_data()
        text = group.get("last_update") if group else None
        if not isinstance(text, str):
            return None
        return parse_timestamp(text.removeprefix(UPDATED_PREFIX).strip())
