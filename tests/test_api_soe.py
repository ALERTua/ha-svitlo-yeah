"""Tests for the client of the public schedule of SOE (Sumyoblenergo)."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from aiohttp import ClientError

from custom_components.svitlo_yeah.api.common_tools import parse_periods
from custom_components.svitlo_yeah.api.soe import SoeClient
from custom_components.svitlo_yeah.const import SOE_SCHEDULE_URL, TZ_UA
from custom_components.svitlo_yeah.models import PlannedOutageEventType
from tests.helpers import soe_group

UPDATE = "11.10.2026 18:48"
# 20:30 in Kyiv on 11 October 2026
EVENING = datetime(2026, 10, 11, 20, 30, tzinfo=TZ_UA)


def _kyiv(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ_UA)


def _answer(*groups: dict) -> dict:
    return {"data": list(groups)}


ANSWER = _answer(
    soe_group("1.1", [("20:00", "22:00")], UPDATE),
    soe_group("3.2", [("10:30", "12:30"), ("17:00", "17:30")], UPDATE),
    soe_group("4.2", [], UPDATE),
    soe_group("6.2", [("22:00", "00:00")], UPDATE),
)


async def _client(hass, aioclient_mock, group: str | None, answer: dict) -> SoeClient:
    """Return a client that fetched this answer."""
    aioclient_mock.get(SOE_SCHEDULE_URL, json=answer)
    client = SoeClient(hass, group)
    assert await client.fetch_data() is True
    return client


def _spans(client: SoeClient, start: datetime, end: datetime) -> list:
    return [(e.start, e.end) for e in client.get_events(start, end)]


@pytest.fixture(autouse=True)
def _evening(freezer):
    freezer.move_to(EVENING)


async def test_groups_come_in_the_order_of_the_site(hass, aioclient_mock):
    """The group list of the config flow has each sub-queue of the answer."""
    client = await _client(hass, aioclient_mock, None, ANSWER)

    assert client.get_groups() == ["1.1", "3.2", "4.2", "6.2"]
    assert client.day == EVENING.date()


@pytest.mark.parametrize(
    ("group", "spans"),
    [
        ("1.1", [(_kyiv(11, 20), _kyiv(11, 22))]),
        (
            "3.2",
            [
                (_kyiv(11, 10, 30), _kyiv(11, 12, 30)),
                (_kyiv(11, 17), _kyiv(11, 17, 30)),
            ],
        ),
        ("6.2", [(_kyiv(11, 22), _kyiv(12, 0))]),
        ("4.2", []),
    ],
    ids=["one_outage", "two_outages", "until_midnight", "no_outages"],
)
async def test_outages_of_the_group_on_the_day_of_the_answer(
    hass, aioclient_mock, group, spans
):
    """The intervals of the sub-queue are outages on the day of the fetch in Kyiv."""
    client = await _client(hass, aioclient_mock, group, ANSWER)

    assert _spans(client, _kyiv(11, 0), _kyiv(13, 0)) == spans
    assert all(
        e.event_type is PlannedOutageEventType.DEFINITE
        for e in client.get_events(_kyiv(11, 0), _kyiv(13, 0))
    )


async def test_adjacent_outages_are_one(hass, aioclient_mock):
    """The power comes back at the end of the last adjacent outage, not between them."""
    answer = _answer(soe_group("2.1", [("12:00", "14:00"), ("10:00", "12:00")], UPDATE))
    client = await _client(hass, aioclient_mock, "2.1", answer)

    assert _spans(client, _kyiv(11, 0), _kyiv(12, 0)) == [
        (_kyiv(11, 10), _kyiv(11, 14))
    ]
    current = client.get_current_event(_kyiv(11, 12, 30))
    assert current is not None
    assert current.end == _kyiv(11, 14)


async def test_current_event(hass, aioclient_mock):
    """The current event is the outage that holds the moment, else none."""
    client = await _client(hass, aioclient_mock, "1.1", ANSWER)

    assert client.get_current_event(_kyiv(11, 21)) is not None
    assert client.get_current_event(_kyiv(11, 22)) is None
    assert client.get_current_event(_kyiv(11, 19, 59)) is None


async def test_reads_do_not_parse_the_answer_again(hass, aioclient_mock):
    """The entities read the outages often, and the client parses each answer once."""
    client = await _client(hass, aioclient_mock, "1.1", ANSWER)

    with patch(
        "custom_components.svitlo_yeah.api.soe.parse_periods", wraps=parse_periods
    ) as parse:
        for _ in range(3):
            client.get_events(_kyiv(11, 0), _kyiv(12, 0))
            client.get_current_event(_kyiv(11, 21))
        assert parse.call_count == 0

        client.restore(ANSWER, "2026-10-10")
        assert parse.call_count == 1
    assert _spans(client, _kyiv(10, 0), _kyiv(11, 0)) == [
        (_kyiv(10, 20), _kyiv(10, 22))
    ]


async def test_events_outside_the_range_are_left_out(hass, aioclient_mock):
    """An outage that ends at the start of the range is not in the range."""
    client = await _client(hass, aioclient_mock, "1.1", ANSWER)

    assert _spans(client, _kyiv(11, 22), _kyiv(11, 23)) == []
    assert _spans(client, _kyiv(11, 21, 59), _kyiv(11, 23)) == [
        (_kyiv(11, 20), _kyiv(11, 22))
    ]


@pytest.mark.parametrize(
    ("group", "listed"),
    [("4.2", True), ("1.1", True), ("5.1", False), (None, None)],
    ids=["empty_list", "with_outages", "missing", "no_group"],
)
async def test_group_listed(hass, aioclient_mock, group, listed):
    """A sub-queue with an empty list is listed; one that the answer lacks is not."""
    client = await _client(hass, aioclient_mock, group, ANSWER)

    assert client.is_group_listed() is listed


async def test_nothing_is_known_before_the_first_answer(hass):
    """Without an answer the client knows no groups, outages or update time."""
    client = SoeClient(hass, "1.1")

    assert client.get_groups() == []
    assert client.is_group_listed() is None
    assert client.get_events(_kyiv(11, 0), _kyiv(12, 0)) == []
    assert client.get_current_event(_kyiv(11, 21)) is None
    assert client.get_updated_on() is None


@pytest.mark.parametrize(
    ("group", "updated"),
    [("1.1", _kyiv(11, 18, 48)), ("5.1", None)],
    ids=["listed", "missing"],
)
async def test_update_time_of_the_group(hass, aioclient_mock, group, updated):
    """«Оновлено: DD.MM.YYYY HH:MM» is the update time in Kyiv."""
    client = await _client(hass, aioclient_mock, group, ANSWER)

    assert client.get_updated_on() == updated


async def test_update_time_of_another_shape_is_none(hass, aioclient_mock):
    """A sub-queue without a readable update time has none."""
    group = soe_group("1.1", [], UPDATE)
    group["last_update"] = None
    client = await _client(hass, aioclient_mock, "1.1", _answer(group))

    assert client.get_updated_on() is None


@pytest.mark.parametrize(
    "reply",
    [
        {"exc": ClientError()},
        {"exc": TimeoutError()},
        {"status": 500},
        {"status": 503, "json": _answer(soe_group("1.1", [], UPDATE))},
        {"text": "<html>maintenance</html>"},
        {"json": {"data": []}},
        {"json": {"data": "1.1"}},
        {"json": {"message": "Not Found"}},
        {"json": [{"cherga_n": "1.1"}]},
        {"json": {"data": [{"cherga_n": 11, "lst_time_disc": []}]}},
        {"json": {"data": [None]}},
    ],
    ids=[
        "no_connection",
        "timeout",
        "server_error",
        "server_error_with_a_schedule",
        "not_json",
        "no_sub_queues",
        "data_not_a_list",
        "no_data",
        "a_list",
        "sub_queue_name_not_text",
        "sub_queue_not_a_dict",
    ],
)
async def test_bad_answer_keeps_the_last_answer(hass, aioclient_mock, reply):
    """A failed request or an answer of another shape keeps the last answer and day."""
    client = await _client(hass, aioclient_mock, "1.1", ANSWER)
    aioclient_mock.clear_requests()
    aioclient_mock.get(SOE_SCHEDULE_URL, **reply)

    assert await client.fetch_data() is False

    assert client.answer == ANSWER
    assert client.day == EVENING.date()
    assert _spans(client, _kyiv(11, 0), _kyiv(12, 0)) == [
        (_kyiv(11, 20), _kyiv(11, 22))
    ]


async def test_the_answer_of_yesterday_gives_no_outages_today(
    hass, aioclient_mock, freezer
):
    """After midnight the kept answer stays on its day until the next fetch."""
    answer = _answer(soe_group("1.1", [("10:00", "12:00")], UPDATE))
    client = await _client(hass, aioclient_mock, "1.1", answer)

    freezer.move_to(_kyiv(12, 0, 5))
    assert _spans(client, _kyiv(12, 0), _kyiv(13, 0)) == []

    assert await client.fetch_data() is True
    assert client.day == _kyiv(12, 0).date()
    assert _spans(client, _kyiv(12, 0), _kyiv(13, 0)) == [
        (_kyiv(12, 10), _kyiv(12, 12))
    ]


@pytest.mark.parametrize(
    ("moment", "day"),
    [
        (datetime(2026, 10, 11, 20, 59, tzinfo=UTC), 11),
        (datetime(2026, 10, 11, 21, 30, tzinfo=UTC), 12),
    ],
    ids=["before_midnight_in_kyiv", "after_midnight_in_kyiv"],
)
async def test_the_day_is_the_day_in_kyiv(hass, aioclient_mock, freezer, moment, day):
    """At 21:30 UTC it is 00:30 of the next day in Kyiv, and the answer is of it."""
    freezer.move_to(moment)
    client = await _client(hass, aioclient_mock, "1.1", ANSWER)

    assert client.day == _kyiv(day, 0).date()


async def test_restore_uses_the_kept_answer_and_its_day(hass):
    """A kept answer gives its outages on its own day, without a request."""
    client = SoeClient(hass, "1.1")

    client.restore(ANSWER, "2026-10-10")

    assert client.day == _kyiv(10, 0).date()
    assert _spans(client, _kyiv(10, 0), _kyiv(12, 0)) == [
        (_kyiv(10, 20), _kyiv(10, 22))
    ]


@pytest.mark.parametrize(
    ("answer", "day"),
    [
        (ANSWER, None),
        (ANSWER, "yesterday"),
        (ANSWER, 20261010),
        ({"data": []}, "2026-10-10"),
        ([], "2026-10-10"),
        (None, "2026-10-10"),
    ],
    ids=["no_day", "day_not_a_date", "day_not_text", "no_sub_queues", "a_list", "none"],
)
async def test_restore_of_another_shape_keeps_nothing(hass, answer, day):
    """A kept answer or day of another shape is no kept answer."""
    client = SoeClient(hass, "1.1")

    client.restore(answer, day)

    assert client.answer is None
    assert client.day is None
