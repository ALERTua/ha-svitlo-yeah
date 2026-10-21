"""Tests for the address search of the Yasno client."""

import logging
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import ClientError
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from custom_components.svitlo_yeah.api.yasno import (
    AddressResult,
    YasnoApi,
    cyrillic_look_alikes,
    exact_matches,
    normalize_name,
)
from custom_components.svitlo_yeah.const import (
    YASNO_ADDRESS_MATCHES_CAP,
    YASNO_ADDRESSES_ENDPOINT,
)
from custom_components.svitlo_yeah.models import (
    YasnoAddress,
    YasnoAddressItem,
    YasnoRegion,
)

# Yasno writes the number of a house with a Cyrillic letter
HOUSE_6A = "6\N{CYRILLIC CAPITAL LETTER A}"
HOUSE_6A_LATIN = "6A"

# The measured chain of Київ (region 25, DSO 902): street, house, group
KYIV_STREET = {"id": 1647, "value": "вул. Сверстюка Євгена"}
KYIV_HOUSE = {"id": 41362, "value": HOUSE_6A}
KYIV_ADDRESS = YasnoAddress(street="вул. Сверстюка Євгена", house=HOUSE_6A)
KYIV_CHAIN = {
    "streets": {"json": [KYIV_STREET]},
    "houses": {"json": [KYIV_HOUSE]},
    "group": {"json": {"group": 53, "subgroup": 1}},
}

# The measured chain of Дніпро (region 3, DSO 301, ДнЕМ): the city comes first.
# Yasno writes the name of the street with a space at the end.
DNIPRO_CITY = {"id": 6, "value": "м. Дніпро"}
DNIPRO_STREET = {"id": 644, "value": "вул. Шевченка "}
DNIPRO_HOUSE = {"id": 190821, "value": "1"}
DNIPRO_ADDRESS = YasnoAddress(city="м. Дніпро", street="вул. Шевченка ", house="1")
DNIPRO_CHAIN = {
    "cities": {"json": [DNIPRO_CITY]},
    "streets": {"json": [DNIPRO_STREET]},
    "houses": {"json": [DNIPRO_HOUSE]},
    "group": {"json": {"group": 3, "subgroup": 1}},
}
# The requests of a check of an address with a city, in order
DNIPRO_ORDER = ["cities", "streets", "houses", "group"]

# What Yasno answers for an id that it does not know
ENTRY_NOT_FOUND = {
    "code": "EntryNotFound",
    "detail": "Street 644 not found in Region 3 and Dso 301",
}

# The searches: the endpoint, and the call that asks it
SEARCHES = [
    pytest.param("cities", lambda api: api.search_cities("дні"), id="cities"),
    pytest.param("streets", lambda api: api.search_streets("свер"), id="streets"),
    pytest.param("houses", lambda api: api.search_houses(1647, "6"), id="houses"),
]
# The matches that each endpoint gives
MATCHES = {
    "cities": [DNIPRO_CITY],
    "streets": [KYIV_STREET],
    "houses": [KYIV_HOUSE],
}

# The answers of an endpoint that say nothing sure, for a search and for a group
NO_SURE_ANSWER = [
    pytest.param({"exc": ClientError()}, id="no_connection"),
    pytest.param({"exc": TimeoutError()}, id="timeout"),
    pytest.param({"status": 500, "json": ENTRY_NOT_FOUND}, id="server_error_json"),
    pytest.param({"status": 500}, id="server_error_no_body"),
    pytest.param({"status": 503, "text": "<html>maintenance</html>"}, id="maintenance"),
    pytest.param({"status": 403, "json": []}, id="forbidden"),
    pytest.param({"status": 404, "text": "<html>Not Found</html>"}, id="404_not_json"),
    pytest.param({"text": "<html>maintenance</html>"}, id="not_json"),
    pytest.param({"text": "null"}, id="null"),
]

# The answers with status 200 that are not a list of matches
ODD_LISTS = [
    pytest.param({"json": {"id": 1647, "value": "вул. Інша"}}, id="a_dict"),
    pytest.param({"json": "вул. Сверстюка Євгена"}, id="a_string"),
    pytest.param({"json": 1647}, id="a_number"),
    pytest.param({"json": ["вул. Інша"]}, id="item_not_a_dict"),
    pytest.param({"json": [{"value": "вул. Інша"}]}, id="item_without_id"),
    pytest.param({"json": [{"id": True, "value": "вул. Інша"}]}, id="bool_id"),
    pytest.param({"json": [{"id": "1647", "value": "вул. Інша"}]}, id="str_id"),
    pytest.param({"json": [{"id": 1647.0, "value": "вул. Інша"}]}, id="float_id"),
    pytest.param({"json": [{"id": 1647}]}, id="item_without_value"),
    pytest.param({"json": [{"id": 1647, "value": 6}]}, id="value_not_a_string"),
    pytest.param(
        {"json": [KYIV_STREET, {"id": "2", "value": "вул. Інша"}]},
        id="one_odd_item_among_good_ones",
    ),
]


def _url(path: str) -> str:
    return YASNO_ADDRESSES_ENDPOINT + path


def _requests(mock) -> list[tuple[str, dict[str, str]]]:
    """Return the endpoint and the query of each request that went out, in order."""
    return [
        (url.path.rsplit("/", 1)[-1], dict(url.query))
        for _, url, _, _ in mock.mock_calls
    ]


def _serve(mock, chain: dict[str, dict], **changes: dict) -> None:
    """Serve the chain of an address, with other replies at some endpoints."""
    for path, reply in (chain | changes).items():
        mock.get(_url(path), **reply)


def _others(count: int) -> list[dict]:
    """Return matches of streets that are not the one that the tests look for."""
    return [{"id": 9000 + _, "value": f"вул. Інша {_}"} for _ in range(count)]


# The mock must patch the creation of the session before the client takes its session
@pytest.fixture(name="kyiv")
def _kyiv(hass, aioclient_mock) -> YasnoApi:  # noqa: ARG001
    return YasnoApi(hass, region_id=25, provider_id=902)


@pytest.fixture(name="dnipro")
def _dnipro(hass, aioclient_mock) -> YasnoApi:  # noqa: ARG001
    return YasnoApi(hass, region_id=3, provider_id=301)


@pytest.mark.parametrize(
    ("name", "normal"),
    [
        pytest.param("вул. Сверстюка Євгена", "вул. сверстюка євгена", id="case"),
        pytest.param(
            " вул.  Сверстюка   Євгена ", "вул. сверстюка євгена", id="spaces"
        ),
        pytest.param("вул. Шевченка ", "вул. шевченка", id="space_at_the_end"),
        pytest.param(HOUSE_6A, "6\N{CYRILLIC SMALL LETTER A}", id="cyrillic_house"),
        pytest.param(HOUSE_6A_LATIN, "6\N{CYRILLIC SMALL LETTER A}", id="latin_house"),
        pytest.param("6a", "6\N{CYRILLIC SMALL LETTER A}", id="latin_house_small"),
        pytest.param(
            "вул. \N{LATIN CAPITAL LETTER C}верстюка",
            "вул. сверстюка",
            id="latin_letter_in_a_word",
        ),
        pytest.param(
            "abcehikmoptxy ABCEHIKMOPTXY",
            "авсенікмортху авсенікмортху",
            id="each_look_alike_letter",
        ),
        pytest.param("DFGJLNQRSUVWZ", "dfgjlnqrsuvwz", id="other_latin_letters_stay"),
        pytest.param("", "", id="empty"),
    ],
)
def test_normalize_name(name, normal):
    """Two writings of one name give one normal form."""
    assert normalize_name(name) == normal


def test_exact_matches_are_the_items_with_the_name():
    """An item matches by its normal form, not by a part of its value."""
    short = YasnoAddressItem(id=1, value="6")
    letter = YasnoAddressItem(id=2, value=HOUSE_6A)
    spaced = YasnoAddressItem(id=3, value=" вул.  Шевченка ")
    other = YasnoAddressItem(id=4, value="вул. Шевченка 2")
    items = [short, letter, spaced, other]

    assert exact_matches(items, "6") == [short]
    assert exact_matches(items, HOUSE_6A_LATIN) == [letter]
    assert exact_matches(items, "ВУЛ. шевченка") == [spaced]
    assert exact_matches(items, "вул.") == []
    assert exact_matches([], "6") == []


@pytest.mark.parametrize(("path", "search"), SEARCHES)
async def test_search_gives_the_matches(kyiv, aioclient_mock, path, search):
    """A 200 answer with a list of matches gives them, with their ids and values."""
    items = MATCHES[path]
    aioclient_mock.get(_url(path), json=items)

    assert await search(kyiv) == [YasnoAddressItem(_["id"], _["value"]) for _ in items]


@pytest.mark.parametrize(("path", "search"), SEARCHES)
async def test_search_without_matches_gives_an_empty_list(
    kyiv, aioclient_mock, path, search
):
    """A 200 answer with an empty list is no match, and it is an answer."""
    aioclient_mock.get(_url(path), json=[])

    assert await search(kyiv) == []


@pytest.mark.parametrize(("path", "search"), SEARCHES)
async def test_search_for_an_unknown_id_gives_an_empty_list(
    kyiv, aioclient_mock, path, search
):
    """Yasno answers 404 EntryNotFound for an id that it changed, which is no match."""
    aioclient_mock.get(_url(path), status=404, json=ENTRY_NOT_FOUND)

    assert await search(kyiv) == []


@pytest.mark.parametrize(("path", "search"), SEARCHES)
@pytest.mark.parametrize("reply", NO_SURE_ANSWER + ODD_LISTS)
async def test_search_without_a_sure_answer_gives_none(
    kyiv, aioclient_mock, path, search, reply
):
    """No answer, another status and another shape say nothing about the matches."""
    aioclient_mock.get(_url(path), **reply)

    assert await search(kyiv) is None


@pytest.mark.parametrize(
    ("path", "search", "query"),
    [
        pytest.param(
            "cities",
            lambda api: api.search_cities(" дні "),
            {"query": "дні"},
            id="cities",
        ),
        pytest.param(
            "streets",
            lambda api: api.search_streets(" вул. Шевченка "),
            {"query": "вул. Шевченка"},
            id="streets",
        ),
        pytest.param(
            "streets",
            lambda api: api.search_streets("свер", 6),
            {"query": "свер", "cityId": "6"},
            id="streets_of_a_city",
        ),
        pytest.param(
            "houses",
            lambda api: api.search_houses(1647, "6"),
            {"streetId": "1647", "query": "6"},
            id="houses",
        ),
        pytest.param(
            "houses",
            lambda api: api.search_houses(644, "", 6),
            {"streetId": "644", "query": "", "cityId": "6"},
            id="houses_of_a_city_with_no_text",
        ),
    ],
)
async def test_search_sends_the_region_the_provider_and_the_query(
    kyiv, aioclient_mock, path, search, query
):
    """A search sends the region, the DSO and the query, and cityId only with a city."""
    expected = {"regionId": "25", "dsoId": "902"} | query
    # The mock matches the query parts that it holds, and the check below
    # makes sure that nothing else went out
    aioclient_mock.get(_url(path), params=expected, json=[])

    await search(kyiv)

    assert _requests(aioclient_mock) == [(path, expected)]


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        pytest.param(HOUSE_6A_LATIN, HOUSE_6A, id="latin_capital_a"),
        pytest.param("6a", "6\N{CYRILLIC SMALL LETTER A}", id="latin_small_a"),
        pytest.param(HOUSE_6A, HOUSE_6A, id="cyrillic_a"),
        pytest.param("12K", "12\N{CYRILLIC CAPITAL LETTER KA}", id="latin_capital_k"),
        # Only the look-alike letters change, and the case stays as it was typed
        pytest.param(
            "12\N{CYRILLIC CAPITAL LETTER BE}",
            "12\N{CYRILLIC CAPITAL LETTER BE}",
            id="other_letter",
        ),
    ],
)
def test_a_typed_house_gets_cyrillic_look_alike_letters(typed, sent):
    """Yasno does not find a house with a Latin A, so a typed house gets a Cyrillic."""
    assert cyrillic_look_alikes(typed) == sent


async def test_house_query_goes_as_given(kyiv, aioclient_mock):
    """
    The search sends the house without a change of its letters.

    The check sends the name that Yasno wrote, and Yasno finds its own name.
    """
    aioclient_mock.get(_url("houses"), json=[])

    await kyiv.search_houses(1647, f" {HOUSE_6A_LATIN} ")

    assert _requests(aioclient_mock)[0][1]["query"] == HOUSE_6A_LATIN


async def test_street_query_keeps_its_letters(kyiv, aioclient_mock):
    """Only a house number changes its letters: a street has the text that was typed."""
    aioclient_mock.get(_url("streets"), json=[])

    await kyiv.search_streets("Kyiv street")

    assert _requests(aioclient_mock)[0][1]["query"] == "Kyiv street"


@pytest.mark.parametrize(
    ("reply", "answer"),
    [
        pytest.param(
            {"json": {"group": 53, "subgroup": 1}},
            (200, {"group": 53, "subgroup": 1}),
            id="200",
        ),
        # A 404 keeps its status, as raise_for_status would turn it into no answer
        pytest.param(
            {"status": 404, "json": ENTRY_NOT_FOUND},
            (404, ENTRY_NOT_FOUND),
            id="404",
        ),
        pytest.param(
            {"status": 500, "json": ENTRY_NOT_FOUND},
            (500, ENTRY_NOT_FOUND),
            id="500_with_json",
        ),
        pytest.param({"status": 500}, (None, None), id="500_without_json"),
        pytest.param({"text": "<html>maintenance</html>"}, (None, None), id="not_json"),
        pytest.param({"exc": ClientError()}, (None, None), id="no_connection"),
        pytest.param({"exc": TimeoutError()}, (None, None), id="timeout"),
    ],
)
async def test_address_answer_keeps_the_status(kyiv, aioclient_mock, reply, answer):
    """A status that has a JSON body reaches the caller: only no answer is None."""
    aioclient_mock.get(_url("group"), **reply)

    assert await kyiv._get_address_answer("group", {"regionId": 25}) == answer


async def test_group_request_sends_the_street_and_the_house(kyiv, aioclient_mock):
    """The group request names the street and the house, and no city for Київ."""
    expected = {
        "regionId": "25",
        "dsoId": "902",
        "streetId": "1647",
        "houseId": "41362",
    }
    aioclient_mock.get(
        _url("group"), params=expected, json={"group": 53, "subgroup": 1}
    )

    result = await kyiv.get_address_group(1647, 41362)

    assert result == (AddressResult.FOUND, "53.1")
    assert _requests(aioclient_mock) == [("group", expected)]


async def test_group_request_sends_the_city(dnipro, aioclient_mock):
    """For Дніпро the group request holds the city, or Yasno answers 404."""
    expected = {
        "regionId": "3",
        "dsoId": "301",
        "streetId": "644",
        "houseId": "190821",
        "cityId": "6",
    }
    aioclient_mock.get(_url("group"), params=expected, json={"group": 3, "subgroup": 1})

    result = await dnipro.get_address_group(644, 190821, 6)

    assert result == (AddressResult.FOUND, "3.1")
    assert _requests(aioclient_mock) == [("group", expected)]


async def test_group_of_an_unknown_house_is_not_found(kyiv, aioclient_mock):
    """Yasno answers 404 EntryNotFound for a street or a house that it does not know."""
    aioclient_mock.get(_url("group"), status=404, json=ENTRY_NOT_FOUND)

    assert await kyiv.get_address_group(1647, 1) == (AddressResult.NOT_FOUND, None)


@pytest.mark.parametrize(
    "reply",
    [
        *NO_SURE_ANSWER,
        pytest.param(
            {"status": 500, "json": {"group": 53, "subgroup": 1}}, id="5xx_with_a_group"
        ),
        pytest.param({"json": 53}, id="a_bare_number"),
        pytest.param({"json": "53.1"}, id="a_string"),
        pytest.param({"json": [{"group": 53, "subgroup": 1}]}, id="a_list"),
        pytest.param({"json": {}}, id="empty_dict"),
        pytest.param({"json": {"group": 53}}, id="no_subgroup"),
        pytest.param({"json": {"subgroup": 1}}, id="no_group"),
        pytest.param({"json": {"group": True, "subgroup": 1}}, id="bool_group"),
        pytest.param({"json": {"group": 53, "subgroup": True}}, id="bool_subgroup"),
        pytest.param({"json": {"group": "53", "subgroup": 1}}, id="str_group"),
        pytest.param({"json": {"group": 53, "subgroup": "1"}}, id="str_subgroup"),
        pytest.param({"json": {"group": 53.0, "subgroup": 1}}, id="float_group"),
        pytest.param({"json": {"group": None, "subgroup": None}}, id="null_group"),
    ],
)
async def test_group_without_a_sure_answer_is_unknown(kyiv, aioclient_mock, reply):
    """Only a 200 answer with a whole group and subgroup is a group."""
    aioclient_mock.get(_url("group"), **reply)

    assert await kyiv.get_address_group(1647, 41362) == (AddressResult.UNKNOWN, None)


async def test_resolve_address_of_a_region_without_cities(kyiv, aioclient_mock):
    """Київ: the street, the house and the group, and no city in any request."""
    _serve(aioclient_mock, KYIV_CHAIN)

    result = await kyiv.resolve_address(KYIV_ADDRESS)

    assert result == (AddressResult.FOUND, "53.1")
    base = {"regionId": "25", "dsoId": "902"}
    assert _requests(aioclient_mock) == [
        ("streets", base | {"query": "вул. Сверстюка Євгена"}),
        ("houses", base | {"streetId": "1647", "query": HOUSE_6A}),
        ("group", base | {"streetId": "1647", "houseId": "41362"}),
    ]


async def test_resolve_address_of_a_region_with_cities(dnipro, aioclient_mock):
    """Дніпро: the city comes first, and each next request holds its id."""
    _serve(aioclient_mock, DNIPRO_CHAIN)

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.FOUND, "3.1")
    base = {"regionId": "3", "dsoId": "301"}
    with_city = base | {"cityId": "6"}
    assert _requests(aioclient_mock) == [
        ("cities", base | {"query": "м. Дніпро"}),
        # The name of the street has a space at the end, and the query has none
        ("streets", with_city | {"query": "вул. Шевченка"}),
        ("houses", with_city | {"streetId": "644", "query": "1"}),
        ("group", with_city | {"streetId": "644", "houseId": "190821"}),
    ]


@pytest.mark.parametrize(
    "address",
    [
        pytest.param(
            YasnoAddress(city="м. Дніпро", street="вул. Шевченка", house="1"),
            id="street_without_the_space_at_the_end",
        ),
        pytest.param(
            YasnoAddress(city="м. ДНІПРО", street="ВУЛ.  ШЕВЧЕНКА ", house="1"),
            id="other_case_and_spaces",
        ),
    ],
)
async def test_resolve_address_ignores_case_and_spaces(dnipro, aioclient_mock, address):
    """Yasno writes a name with a space at the end, and the match does not need it."""
    _serve(aioclient_mock, DNIPRO_CHAIN)

    assert await dnipro.resolve_address(address) == (AddressResult.FOUND, "3.1")


async def test_resolve_address_with_a_latin_letter_in_the_house(kyiv, aioclient_mock):
    """
    A stored house with a Latin letter goes as it is, and matches by its normal form.

    Yasno wrote the stored name, so the query keeps its letters.
    """
    _serve(aioclient_mock, KYIV_CHAIN)
    address = YasnoAddress(street="вул. Сверстюка Євгена", house=HOUSE_6A_LATIN)

    assert await kyiv.resolve_address(address) == (AddressResult.FOUND, "53.1")
    assert _requests(aioclient_mock)[1][1]["query"] == HOUSE_6A_LATIN


@pytest.mark.parametrize("level", ["cities", "streets", "houses"])
@pytest.mark.parametrize(
    "reply",
    [
        pytest.param({"json": []}, id="no_matches"),
        pytest.param({"status": 404, "json": ENTRY_NOT_FOUND}, id="404"),
        pytest.param({"json": _others(YASNO_ADDRESS_MATCHES_CAP - 1)}, id="short_list"),
    ],
)
async def test_resolve_address_not_found_at_a_level(
    dnipro, aioclient_mock, level, reply
):
    """No exact match in an answer that is not cut: Yasno does not know the name."""
    _serve(aioclient_mock, DNIPRO_CHAIN, **{level: reply})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.NOT_FOUND, None)
    # The check stops at the level, and it asks no further
    asked = [path for path, _ in _requests(aioclient_mock)]
    assert asked == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]


async def test_resolve_address_not_found_for_the_group(dnipro, aioclient_mock):
    """Yasno knows the street and the house, but answers 404 for the group."""
    _serve(aioclient_mock, DNIPRO_CHAIN, group={"status": 404, "json": ENTRY_NOT_FOUND})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.NOT_FOUND, None)
    assert len(_requests(aioclient_mock)) == len(DNIPRO_ORDER)


@pytest.mark.parametrize("level", ["cities", "streets", "houses"])
async def test_resolve_address_with_a_cut_list_and_no_exact_match_is_unknown(
    dnipro, aioclient_mock, level
):
    """A list as long as the cap is cut, so the name can be missing from it."""
    cut = {"json": _others(YASNO_ADDRESS_MATCHES_CAP)}
    _serve(aioclient_mock, DNIPRO_CHAIN, **{level: cut})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.UNKNOWN, None)
    asked = [path for path, _ in _requests(aioclient_mock)]
    assert asked == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]


@pytest.mark.parametrize("level", ["cities", "streets", "houses"])
async def test_resolve_address_with_a_cut_list_and_an_exact_match_goes_on(
    dnipro, aioclient_mock, level
):
    """The exact match in a cut list is sure: the cut hides only other names."""
    exact = DNIPRO_CHAIN[level]["json"]
    cut = {"json": [*_others(YASNO_ADDRESS_MATCHES_CAP - 1), *exact]}
    _serve(aioclient_mock, DNIPRO_CHAIN, **{level: cut})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.FOUND, "3.1")


@pytest.mark.parametrize("level", ["cities", "streets", "houses"])
@pytest.mark.parametrize("spaced", [False, True], ids=["same_name", "spaces_around"])
async def test_resolve_address_with_two_exact_matches_is_unknown(
    dnipro, aioclient_mock, level, spaced
):
    """Two items with the name of the address: the name does not say which one."""
    (item,) = DNIPRO_CHAIN[level]["json"]
    value = f" {item['value']} " if spaced else item["value"]
    twins = {"json": [item, {"id": item["id"] + 1, "value": value}]}
    _serve(aioclient_mock, DNIPRO_CHAIN, **{level: twins})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.UNKNOWN, None)
    asked = [path for path, _ in _requests(aioclient_mock)]
    assert asked == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]


@pytest.mark.parametrize("level", DNIPRO_ORDER)
@pytest.mark.parametrize(
    "reply",
    [
        pytest.param({"exc": ClientError()}, id="no_connection"),
        pytest.param({"status": 500, "json": ENTRY_NOT_FOUND}, id="server_error"),
        pytest.param({"json": 53}, id="a_bare_number"),
    ],
)
async def test_resolve_address_unknown_when_a_level_gives_no_sure_answer(
    dnipro, aioclient_mock, level, reply
):
    """No answer at one level says nothing, so the check ends there as unknown."""
    _serve(aioclient_mock, DNIPRO_CHAIN, **{level: reply})

    result = await dnipro.resolve_address(DNIPRO_ADDRESS)

    assert result == (AddressResult.UNKNOWN, None)
    asked = [path for path, _ in _requests(aioclient_mock)]
    assert asked == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]


async def test_resolve_address_skips_the_city_of_an_address_without_one(
    dnipro, aioclient_mock
):
    """An address without a city asks for no city, also in a region that has cities."""
    _serve(aioclient_mock, DNIPRO_CHAIN)
    address = YasnoAddress(street="вул. Шевченка", house="1")

    await dnipro.resolve_address(address)

    requests = _requests(aioclient_mock)
    assert [path for path, _ in requests] == ["streets", "houses", "group"]
    assert all("cityId" not in query for _, query in requests)


async def test_requests_without_a_region_ask_nothing(hass, aioclient_mock, caplog):
    """A client without a region or a DSO cannot ask, so it says nothing sure."""
    api = YasnoApi(hass)

    assert await api.search_cities("дні") is None
    assert await api.search_streets("свер") is None
    assert await api.search_houses(1647, "6") is None
    assert await api.get_address_group(1647, 41362) == (AddressResult.UNKNOWN, None)
    assert await api.resolve_address(KYIV_ADDRESS) == (AddressResult.UNKNOWN, None)

    assert aioclient_mock.call_count == 0
    assert "must be set before an address request" in caplog.text


async def test_log_has_no_part_of_the_address(kyiv, aioclient_mock, caplog):
    """The query of a request is the address of a person, so no log line holds it."""
    caplog.set_level(logging.DEBUG, logger="custom_components.svitlo_yeah.api.yasno")
    _serve(aioclient_mock, KYIV_CHAIN)

    assert await kyiv.resolve_address(KYIV_ADDRESS) == (AddressResult.FOUND, "53.1")

    # The log says which endpoint answered, and nothing of its query
    assert "streets answered 200" in caplog.text
    assert "houses answered 200" in caplog.text
    assert "group answered 200" in caplog.text
    for part in ("Сверстюка", quote("Сверстюка"), "query=", HOUSE_6A, "41362"):
        assert part not in caplog.text


async def test_log_of_a_failed_request_has_no_part_of_the_address(
    kyiv, aioclient_mock, caplog
):
    """The message of an aiohttp error holds the URL, so the log keeps only its type."""
    caplog.set_level(logging.DEBUG, logger="custom_components.svitlo_yeah.api.yasno")
    url = URL(_url("streets")).with_query({"query": "вул. Сверстюка Євгена"})
    request_info = aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    error = aiohttp.ClientResponseError(request_info, (), status=500)
    # The premise: the text of the error holds the address
    assert quote("Сверстюка") in str(error)
    aioclient_mock.get(_url("streets"), exc=error)

    assert await kyiv.search_streets("вул. Сверстюка Євгена") is None

    assert "streets: ClientResponseError" in caplog.text
    for part in ("Сверстюка", quote("Сверстюка"), "query="):
        assert part not in caplog.text
    # No traceback either: it would print the message of the error
    records = [
        _ for _ in caplog.records if _.name == "custom_components.svitlo_yeah.api.yasno"
    ]
    assert records
    assert all(_.exc_info is None for _ in records)


@pytest.mark.parametrize(
    ("extra", "has_cities"),
    [
        pytest.param({"hasCities": True}, True, id="with_cities"),
        pytest.param({"hasCities": False}, False, id="without_cities"),
        # A region that a coordinator stored in an older version has no such key
        pytest.param({}, False, id="no_key"),
        pytest.param({"hasCities": "true"}, False, id="text"),
        pytest.param({"hasCities": 1}, False, id="number"),
        pytest.param({"hasCities": None}, False, id="null"),
    ],
)
def test_region_has_cities_only_for_true(extra, has_cities):
    """The region has cities only when Yasno says true."""
    region = YasnoRegion.from_dict(
        {
            "id": 3,
            "value": "Дніпро",
            "dsos": [{"id": 301, "name": "ДнЕМ"}, {"id": 303, "name": "ЦЕК"}],
            **extra,
        }
    )

    assert region.has_cities is has_cities
    assert [_.id for _ in region.dsos] == [301, 303]


def test_region_without_the_flag_has_no_cities():
    """A region that is built by hand has no cities until it says so."""
    assert YasnoRegion(id=25, name="Київ").has_cities is False
