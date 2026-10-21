"""Tests for the address flow of Yasno: the menu, the forms, the selects, the errors."""

import logging
from datetime import UTC, datetime
from unittest.mock import patch

import probatio as vol
import pytest
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.svitlo_yeah.const import (
    CONF_CITY,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    CONF_STREET,
    DOMAIN,
    PROVIDER_TYPE_YASNO,
    YASNO_ADDRESSES_ENDPOINT,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import (
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
    dtek_answers,
    fact_with_an_outage_today,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

LOGGER_NAME = "custom_components.svitlo_yeah"

# Yasno writes the number of a house with a Cyrillic letter
HOUSE_6A = "6\N{CYRILLIC CAPITAL LETTER A}"
HOUSE_6A_LATIN = "6A"
# The kind of a village is one letter, and ruff reads it as the Latin letter
VILLAGE = "\N{CYRILLIC SMALL LETTER ES}"
HOUSE_6B = "6\N{CYRILLIC CAPITAL LETTER BE}"

# The measured chain of Київ (region 25, DSO 902): street, houses, group. Yasno gives
# the houses of a street in its own order, and the other houses are made up.
KYIV_KEY = "yasnoprovider_25_902"
KYIV_STREET = {"id": 1647, "value": "вул. Сверстюка Євгена"}
KYIV_HOUSE = {"id": 41362, "value": HOUSE_6A}
KYIV_HOUSES = [
    {"id": 41370, "value": "10"},
    KYIV_HOUSE,
    {"id": 41350, "value": "2"},
    {"id": 41363, "value": HOUSE_6B},
    {"id": 41360, "value": "6"},
]
# The houses in the natural order: the dropdown of the house step lists them so
KYIV_HOUSES_SORTED = [
    {"id": 41350, "value": "2"},
    {"id": 41360, "value": "6"},
    KYIV_HOUSE,
    {"id": 41363, "value": HOUSE_6B},
    {"id": 41370, "value": "10"},
]
KYIV_CHAIN = {
    "streets": {"json": [KYIV_STREET]},
    "houses": {"json": KYIV_HOUSES},
    "group": {"json": {"group": 53, "subgroup": 1}},
}
KYIV_PLACE = "Київ, вул. Сверстюка Євгена"

# The measured chain of Дніпро (region 3, DSO 301, ДнЕМ): the city comes first.
# Yasno writes the name of the street with a space at the end.
DNIPRO_KEY = "yasnoprovider_3_301"
DNIPRO_PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=3, dso_id=301)
DNIPRO_CITY = {"id": 6, "value": "м. Дніпро"}
DNIPRO_STREET = {"id": 644, "value": "вул. Шевченка "}
DNIPRO_HOUSE = {"id": 190821, "value": "1"}
DNIPRO_CHAIN = {
    "cities": {"json": [DNIPRO_CITY]},
    "streets": {"json": [DNIPRO_STREET]},
    "houses": {"json": [DNIPRO_HOUSE]},
    "group": {"json": {"group": 3, "subgroup": 1}},
}
# The requests that the flow sends for an address with a city, in order. The
# houses of the street are one entry: they take ten requests, one for each digit.
DNIPRO_ORDER = ["cities", "streets", "houses", "group"]
# The queries of the ten requests that list the houses of a street
LIST_QUERIES = list("0123456789")

# A region that Yasno could add later, with no page of its own in the integration.
# Its name and its ids are made up.
OTHER_KEY = "yasnoprovider_99_999"
OTHER_PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=99, dso_id=999)

REGIONS = [
    {
        "id": 25,
        "value": "Київ",
        "hasCities": False,
        "dsos": [{"id": 902, "name": "ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»"}],
    },
    {
        "id": 3,
        "value": "Дніпро",
        "hasCities": True,
        "dsos": [{"id": 301, "name": "ДнЕМ"}, {"id": 303, "name": "ЦЕК"}],
    },
    {
        "id": 99,
        "value": "Тестове місто",
        "hasCities": False,
        "dsos": [{"id": 999, "name": "Тестовий оператор"}],
    },
]

# What Yasno answers for an id that it does not know
ENTRY_NOT_FOUND = {
    "code": "EntryNotFound",
    "detail": "Street 644 not found in Region 3 and Dso 301",
}

# The Yasno page that a form names for the region of Київ and of Дніпро
KYIV_PAGE_URL = "https://static.yasno.ua/kyiv/outages"
DNIPRO_PAGE_URL = "https://static.yasno.ua/dnipro/outages"
# The page of the group form of a DTEK provider: only Yasno has a page for each region
DTEK_PAGE_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"
ADDRESS_PATH = URL(YASNO_ADDRESSES_ENDPOINT).path

# The English text of the option that searches again, for each select. It is the
# label that the frontend shows when the language of the user has no text for it.
SEARCH_AGAIN_EN = {
    CONF_CITY: "My city is not in the list, search again",
    CONF_STREET: "My street is not in the list, search again",
    CONF_HOUSE: "This is not my street, search again",
}
# The translation key of each select: it gives the option the text of the language
TRANSLATION_KEYS = {
    CONF_CITY: "city_match",
    CONF_STREET: "street_match",
    CONF_HOUSE: "house_match",
}

# The lists of several matches. The names of the other matches are made up, and the
# matches of the measured chains are among them.
STREET_MATCHES = [
    {"id": 9001, "value": "вул. Перша Тестова"},
    KYIV_STREET,
    {"id": 9002, "value": "вул. Друга Тестова"},
]
CITY_MATCHES = [
    DNIPRO_CITY,
    {"id": 7, "value": "м. Тестове"},
    {"id": 8, "value": "м. Інше Тестове"},
]
MATCHES = {CONF_CITY: CITY_MATCHES, CONF_STREET: STREET_MATCHES}
LEVELS = [CONF_CITY, CONF_STREET]

# The reply that Yasno gives for the group, the errors of the house form, and the
# placeholders of its text. The group of the schedule check is in each case.
GROUP_ERRORS = [
    pytest.param(
        {"group": {"status": 404, "json": ENTRY_NOT_FOUND}},
        {"house": "house_not_found"},
        {},
        id="group_of_an_unknown_house",
    ),
    pytest.param(
        {"group": {"exc": ClientError()}},
        {"base": "yasno_no_answer"},
        {},
        id="group_without_an_answer",
    ),
    pytest.param(
        {"planned": {"exc": ClientError()}},
        {"base": "yasno_no_answer"},
        {},
        id="schedule_without_a_connection",
    ),
    pytest.param(
        {"planned": {"status": 500}},
        {"base": "yasno_no_answer"},
        {},
        id="schedule_server_error",
    ),
    pytest.param(
        {"planned": {"json": []}},
        {"base": "yasno_no_answer"},
        {},
        id="schedule_of_another_shape",
    ),
    pytest.param(
        {"planned": {"json": {"1.1": {}, "2.1": {}}}},
        {"base": "address_group_not_listed"},
        {"group": "53.1"},
        id="group_that_the_schedule_does_not_list",
    ),
]
# The same cases, without the placeholders of the text
GROUP_ERROR_REPLIES = [pytest.param(*_.values[:2], id=_.id) for _ in GROUP_ERRORS]


@pytest.fixture(autouse=True)
def _no_entry_setup():
    """Create the entries without their setup: these tests cover the flow only."""
    with patch("custom_components.svitlo_yeah.async_setup_entry", return_value=True):
        yield


def _serve(
    mock,
    chain: dict[str, dict],
    planned_url: str,
    planned: dict,
    changes: dict[str, dict],
) -> None:
    """Serve the chain of an address and the schedule, with other replies at some."""
    for path, reply in (chain | changes).items():
        mock.get(YASNO_ADDRESSES_ENDPOINT + path, **reply)
    mock.get(planned_url, **planned)


def _serve_kyiv(mock, *, planned: dict | None = None, **changes: dict) -> None:
    """Serve Київ: group 53.1 is in the schedule, unless `planned` says otherwise."""
    planned = planned or {"json": {"53.1": {}, "1.1": {}}}
    _serve(mock, KYIV_CHAIN, YASNO_PLANNED_URL, planned, changes)


def _serve_dnipro(mock, *, planned: dict | None = None, **changes: dict) -> None:
    """Serve Дніпро: group 3.1 is in the schedule, unless `planned` says otherwise."""
    planned = planned or {"json": {"3.1": {}, "1.1": {}}}
    _serve(mock, DNIPRO_CHAIN, DNIPRO_PLANNED_URL, planned, changes)


def _houses_by_query(by_query: dict[str, dict], default: dict) -> dict:
    """
    Return the reply of the houses endpoint that answers each query by its text.

    A request with a query that has no registered answer gets an error from the
    mock, so the reply holds the answer for the other queries too. The ten queries
    that list the houses get the default.
    """

    async def side_effect(method, url, _data):
        reply = by_query.get(url.query["query"], default)
        return AiohttpClientMockResponse(method, url, **reply)

    return {"side_effect": side_effect}


def _address_requests(mock) -> list[tuple[str, dict[str, str]]]:
    """Return the endpoint and the query of each address request, in order."""
    requests = [
        (url.path.rsplit("/", 1)[-1], dict(url.query))
        for _, url, _, _ in mock.mock_calls
        if url.path.startswith(ADDRESS_PATH)
    ]
    # The regions are not an address request
    return [_ for _ in requests if _[0] != "regions"]


def _asked(mock) -> list[str]:
    """
    Return the endpoints of the address requests, in order.

    The ten requests that list the houses of a street show as one «houses».
    """
    requests = _address_requests(mock)
    asked = []
    index = 0
    while index < len(requests):
        path, _ = requests[index]
        asked.append(path)
        listed = [query.get("query") for _, query in requests[index : index + 10]]
        index += 10 if path == "houses" and listed == LIST_QUERIES else 1
    return asked


def _house_searches(mock) -> list[dict[str, str]]:
    """Return the query of each request that searched houses, without the list."""
    return [
        query
        for path, query in _address_requests(mock)
        if path == "houses" and query["query"] not in LIST_QUERIES
    ]


async def _configure(hass, result: dict, user_input: dict | None) -> dict:
    """Submit the form or the menu of a flow result."""
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _config(result: dict, field: str) -> dict:
    """Return the config of the selector of a field in a form result."""
    return result["data_schema"].schema[field].config


def _select_options(result: dict, field: str) -> list:
    """Return the options of a select field in a form result."""
    return _config(result, field)["options"]


def _options_of(houses: list[dict]) -> list[dict]:
    """
    Return the options that the dropdown of the houses has for these houses.

    The value of an option is the number of its house, the same as its label.
    """
    return [{"value": _["value"], "label": _["value"]} for _ in houses]


def _default(result: dict, field: str):
    """Return the default value of a field in a form result."""
    return next(k for k in result["data_schema"].schema if k == field).default()


def _suggested(result: dict, field: str):
    """Return the suggested value of a field in a form result, or None."""
    key = next(k for k in result["data_schema"].schema if k == field)
    return (key.description or {}).get("suggested_value")


def _fields(result: dict) -> list[str]:
    """Return the names of the fields of a form result, in order."""
    return [key.schema for key in result["data_schema"].schema]


async def _open_menu(hass, aioclient_mock, key: str) -> dict:
    """Start a new flow, and pick a provider: a Yasno provider gives the menu."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=REGIONS)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await _configure(hass, result, {CONF_PROVIDER: key})


async def _open_address_form(hass, aioclient_mock, key: str) -> dict:
    """Start a new flow of a Yasno provider, and choose «By address» in the menu."""
    result = await _open_menu(hass, aioclient_mock, key)
    assert result["type"] is FlowResultType.MENU
    return await _configure(hass, result, {"next_step_id": "address"})


async def _kyiv_form(hass, aioclient_mock, **changes: dict) -> dict:
    """Serve Київ, and open its address form."""
    _serve_kyiv(aioclient_mock, **changes)
    return await _open_address_form(hass, aioclient_mock, KYIV_KEY)


async def _dnipro_form(hass, aioclient_mock, **changes: dict) -> dict:
    """Serve Дніпро, and open its address form."""
    _serve_dnipro(aioclient_mock, **changes)
    return await _open_address_form(hass, aioclient_mock, DNIPRO_KEY)


async def _submit_kyiv(hass, result: dict, **typed: str) -> dict:
    """Submit the address form of Київ, with the text of the measured chain."""
    return await _configure(hass, result, {CONF_STREET: "сверст"} | typed)


async def _submit_dnipro(hass, result: dict, **typed: str) -> dict:
    """Submit the address form of Дніпро, with the texts of the measured chain."""
    texts = {
        CONF_CITY: DNIPRO_CITY["value"],
        CONF_STREET: "вул. Шевченка",
    } | typed
    return await _configure(hass, result, texts)


async def _kyiv_house_form(hass, aioclient_mock, **changes: dict) -> dict:
    """Serve Київ, and walk the address form to the dropdown of the houses."""
    result = await _kyiv_form(hass, aioclient_mock, **changes)
    result = await _submit_kyiv(hass, result)
    assert result["step_id"] == "house"
    return result


async def _dnipro_house_form(hass, aioclient_mock, **changes: dict) -> dict:
    """Serve Дніпро, and walk the address form to the dropdown of the houses."""
    result = await _dnipro_form(hass, aioclient_mock, **changes)
    result = await _submit_dnipro(hass, result)
    assert result["step_id"] == "house"
    return result


async def _kyiv_twin_house_form(hass, aioclient_mock) -> dict:
    """
    Serve Київ with a second house of the number of KYIV_HOUSE, and show its dropdown.

    The twin comes last in the answer of Yasno, so the house of the measured chain
    is the first listed house of that number. The search of Yasno for that number
    knows only this house: a request for it would show in the requests.
    """
    twin = {"id": 41999, "value": HOUSE_6A}
    houses = _houses_by_query(
        {HOUSE_6A: {"json": [KYIV_HOUSE]}}, {"json": [*KYIV_HOUSES, twin]}
    )
    return await _kyiv_house_form(hass, aioclient_mock, houses=houses)


async def _open_pick(
    hass, aioclient_mock, level: str, text: str
) -> tuple[dict, dict[str, str]]:
    """
    Walk the address form to the select of a level, where Yasno has many matches.

    The text is what the user types at that level. Return the select, and the
    texts that the user typed in the form.
    """
    matches = {"json": MATCHES[level]}
    if level == CONF_CITY:
        result = await _dnipro_form(hass, aioclient_mock, cities=matches)
        typed = {CONF_CITY: text, CONF_STREET: "вул. Шевченка"}
        return await _configure(hass, result, typed), typed
    result = await _kyiv_form(hass, aioclient_mock, streets=matches)
    typed = {CONF_STREET: text}
    return await _configure(hass, result, typed), typed


class TestMenu:
    """A Yasno provider asks how to find the schedule: by an address, or by a group."""

    async def test_yasno_provider_shows_the_menu(self, hass, aioclient_mock):
        """The menu offers the address first, then the group."""
        result = await _open_menu(hass, aioclient_mock, KYIV_KEY)

        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "yasno_method"
        assert result["menu_options"] == ["address", "group"]

    async def test_dtek_provider_shows_no_menu(self, hass, aioclient_mock):
        """A DTEK provider goes straight to its group form."""
        dtek_answers(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))

        result = await _open_menu(hass, aioclient_mock, "dtekjsonprovider_kyiv_region")

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "group"

    async def test_group_option_shows_the_group_form(self, hass, aioclient_mock):
        """«By group» is the group form of the other providers, with no search."""
        _serve_kyiv(aioclient_mock)
        result = await _open_menu(hass, aioclient_mock, KYIV_KEY)

        result = await _configure(hass, result, {"next_step_id": "group"})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "group"
        assert _asked(aioclient_mock) == []

    async def test_entry_of_a_group_has_no_description(self, hass, aioclient_mock):
        """The text «Found the address» is for an address: a group has none."""
        _serve_kyiv(aioclient_mock)
        result = await _open_menu(hass, aioclient_mock, KYIV_KEY)
        result = await _configure(hass, result, {"next_step_id": "group"})

        result = await _configure(hass, result, {CONF_GROUP: "53.1"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_GROUP] == "53.1"
        assert result["description"] is None
        assert result["description_placeholders"] is None

    async def test_address_form_of_a_region_without_cities(self, hass, aioclient_mock):
        """Київ has no cities: the form has the street only, and no house."""
        result = await _kyiv_form(hass, aioclient_mock)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert _fields(result) == [CONF_STREET]
        assert not result["errors"]
        assert result["description_placeholders"] == {"url": KYIV_PAGE_URL}
        # Each field is required, and the form has no text from an earlier try
        for key in result["data_schema"].schema:
            assert isinstance(key, vol.Required)
            assert _suggested(result, key.schema) is None
        assert _asked(aioclient_mock) == []

    async def test_address_form_of_a_region_with_cities(self, hass, aioclient_mock):
        """Дніпро has cities: the city comes before the street."""
        result = await _dnipro_form(hass, aioclient_mock)

        assert result["step_id"] == "address"
        assert _fields(result) == [CONF_CITY, CONF_STREET]
        assert result["description_placeholders"] == {"url": DNIPRO_PAGE_URL}


class TestRegionPage:
    """A Yasno form names the Yasno page of its region, and a DTEK form its own page."""

    # The provider and the page of its region. A region with no page of its own gets
    # the page of Київ.
    @pytest.mark.parametrize(
        ("key", "page"),
        [
            pytest.param(KYIV_KEY, KYIV_PAGE_URL, id="kyiv"),
            pytest.param(DNIPRO_KEY, DNIPRO_PAGE_URL, id="dnipro"),
            pytest.param(OTHER_KEY, KYIV_PAGE_URL, id="another_region"),
        ],
    )
    async def test_address_form_names_the_page_of_its_region(
        self, hass, aioclient_mock, key, page
    ):
        """The text under the address form names the page of the region of Yasno."""
        result = await _open_address_form(hass, aioclient_mock, key)

        assert result["step_id"] == "address"
        assert result["description_placeholders"] == {"url": page}
        assert _asked(aioclient_mock) == []

    # The provider, the schedule that its group form asks for, and the region page
    @pytest.mark.parametrize(
        ("key", "planned_url", "page"),
        [
            pytest.param(KYIV_KEY, YASNO_PLANNED_URL, KYIV_PAGE_URL, id="kyiv"),
            pytest.param(DNIPRO_KEY, DNIPRO_PLANNED_URL, DNIPRO_PAGE_URL, id="dnipro"),
            pytest.param(
                OTHER_KEY, OTHER_PLANNED_URL, KYIV_PAGE_URL, id="another_region"
            ),
        ],
    )
    async def test_group_form_names_the_page_of_its_region(
        self, hass, aioclient_mock, key, planned_url, page
    ):
        """The text under the group form of Yasno names the page of its region."""
        aioclient_mock.get(planned_url, json={"1.1": {}})
        result = await _open_menu(hass, aioclient_mock, key)

        result = await _configure(hass, result, {"next_step_id": "group"})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "group"
        assert result["description_placeholders"] == {"url": page}

    async def test_group_form_of_a_dtek_provider_names_the_page_of_dtek(
        self, hass, aioclient_mock
    ):
        """The page of a region is for Yasno only: DTEK keeps its own page."""
        dtek_answers(aioclient_mock, fact_with_an_outage_today(datetime.now(UTC)))

        result = await _open_menu(hass, aioclient_mock, "dtekjsonprovider_kyiv_region")

        assert result["step_id"] == "group"
        assert result["description_placeholders"] == {"url": DTEK_PAGE_URL}

    async def test_address_form_after_an_error_names_the_page_of_its_region(
        self, hass, aioclient_mock
    ):
        """The form that shows an error names the page of the region too."""
        result = await _dnipro_form(hass, aioclient_mock)

        result = await _submit_dnipro(hass, result, street="св")

        assert result["errors"] == {"street": "street_too_short"}
        assert result["description_placeholders"] == {"url": DNIPRO_PAGE_URL}


class TestFoundAddress:
    """An address that Yasno knows gives an entry with its group and its names."""

    async def test_one_street_goes_to_the_house_step(self, hass, aioclient_mock):
        """A street that the text does not name, but the only match, is taken."""
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "house"
        # The text names the address that the houses belong to
        assert result["description_placeholders"] == {
            "place": KYIV_PLACE,
            "count": "5",
        }
        base = {"regionId": "25", "dsoId": "902"}
        assert _address_requests(aioclient_mock) == [
            ("streets", base | {"query": "сверст"}),
            *(
                ("houses", base | {"streetId": "1647", "query": digit})
                for digit in LIST_QUERIES
            ),
        ]

    async def test_kyiv_house_creates_the_entry(self, hass, aioclient_mock):
        """The chosen house gives the group, and the entry shows the address."""
        result = await _kyiv_house_form(hass, aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
            CONF_PROVIDER: 902,
            CONF_REGION: 25,
            CONF_GROUP: "53.1",
            CONF_STREET: "вул. Сверстюка Євгена",
            CONF_HOUSE: HOUSE_6A,
        }
        (entry,) = hass.config_entries.async_entries(DOMAIN)
        assert entry.data == result["data"]
        # The title is the one of a group entry, without the address
        assert result["title"] == "Київ ДТЕК 53.1"
        # The dialog of the new entry shows the address and the group
        assert result["description"] == "address"
        assert result["description_placeholders"] == {
            "address": f"{KYIV_PLACE}, {HOUSE_6A}",
            "group": "53.1",
        }
        base = {"regionId": "25", "dsoId": "902"}
        assert _asked(aioclient_mock) == ["streets", "houses", "group"]
        assert _address_requests(aioclient_mock)[-1] == (
            "group",
            base | {"streetId": "1647", "houseId": "41362"},
        )

    async def test_three_letters_of_the_street_are_enough(self, hass, aioclient_mock):
        """The street text has the least length that Yasno searches."""
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result, street=" све ")

        assert result["step_id"] == "house"

    @pytest.mark.parametrize("typed", ["Хрещатик", "вул. Хрещатик", "ВУЛ.  хрещатик "])
    async def test_typed_street_that_one_match_names_is_taken(
        self, hass, aioclient_mock, typed
    ):
        """The text names one of several matches, with its kind or without: no list."""
        streets = [
            {"id": 948, "value": "вул. Набережно-Хрещатицька"},
            {"id": 947, "value": "вул. Хрещатик"},
        ]
        result = await _kyiv_form(hass, aioclient_mock, streets={"json": streets})

        result = await _submit_kyiv(hass, result, street=typed)

        assert result["step_id"] == "house"
        assert result["description_placeholders"]["place"] == "Київ, вул. Хрещатик"
        assert _address_requests(aioclient_mock)[1][1]["streetId"] == "947"

    async def test_dnipro_city_street_and_house_create_the_entry(
        self, hass, aioclient_mock
    ):
        """In a region with cities, the entry has the city, and each request has it."""
        result = await _dnipro_house_form(hass, aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: DNIPRO_HOUSE["value"]})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
            CONF_PROVIDER: 301,
            CONF_REGION: 3,
            CONF_GROUP: "3.1",
            CONF_CITY: "м. Дніпро",
            # The names go in as Yasno writes them: the street has a space at the end
            CONF_STREET: "вул. Шевченка ",
            CONF_HOUSE: "1",
        }
        assert result["title"] == "Дніпро ДнЕМ 3.1"
        assert result["description"] == "address"
        assert result["description_placeholders"] == {
            "address": "Дніпро, м. Дніпро, вул. Шевченка, 1",
            "group": "3.1",
        }
        assert _asked(aioclient_mock) == DNIPRO_ORDER
        base = {"regionId": "3", "dsoId": "301"}
        with_city = base | {"cityId": "6"}
        requests = _address_requests(aioclient_mock)
        assert requests[0] == ("cities", base | {"query": "м. Дніпро"})
        assert requests[1] == ("streets", with_city | {"query": "вул. Шевченка"})
        assert requests[2:-1] == [
            ("houses", with_city | {"streetId": "644", "query": digit})
            for digit in LIST_QUERIES
        ]
        assert requests[-1] == (
            "group",
            with_city | {"streetId": "644", "houseId": "190821"},
        )

    async def test_address_text_without_the_region_name(self, hass, aioclient_mock):
        """Without the region in the cache, the address starts with the street."""
        result = await _kyiv_form(hass, aioclient_mock)

        with patch(
            "custom_components.svitlo_yeah.config_flow.YasnoApi.get_region_by_id",
            return_value=None,
        ):
            result = await _submit_kyiv(hass, result)

        assert result["step_id"] == "house"
        assert result["description_placeholders"]["place"] == "вул. Сверстюка Євгена"

    async def test_typed_city_without_its_kind_is_taken(self, hass, aioclient_mock):
        """«Дніпро» names «м. Дніпро» and not the village «Дніпрове»: no list."""
        cities = {"json": [DNIPRO_CITY, {"id": 9, "value": f"{VILLAGE}. Дніпрове"}]}
        result = await _dnipro_form(hass, aioclient_mock, cities=cities)

        result = await _submit_dnipro(hass, result, city="Дніпро")

        assert result["step_id"] == "house"
        # The name of the street has a space at the end, and the text has none
        assert result["description_placeholders"]["place"] == (
            "Дніпро, м. Дніпро, вул. Шевченка"
        )
        assert _asked(aioclient_mock) == ["cities", "streets", "houses"]

    async def test_group_of_an_existing_entry_aborts(self, hass, aioclient_mock):
        """An address with the group of an entry gives no second entry."""
        data = {**YASNO_KYIV_1_1, CONF_GROUP: "53.1"}
        existing = MockConfigEntry(domain=DOMAIN, data=data)
        existing.add_to_hass(hass)
        result = await _kyiv_house_form(hass, aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert hass.config_entries.async_entries(DOMAIN) == [existing]
        assert existing.data == data


class TestSeveralMatches:
    """Several matches of a level give a select, and a select can search again."""

    # The level, the typed text of the level, and the place that the select names
    @pytest.mark.parametrize(
        ("level", "text", "place"),
        [
            pytest.param(CONF_CITY, "дніпр", "Дніпро", id="city"),
            pytest.param(CONF_STREET, "сверст", "Київ", id="street"),
        ],
    )
    async def test_select_of_the_matches(
        self, hass, aioclient_mock, level, text, place
    ):
        """The select lists the matches in the order of Yasno, then «search again»."""
        result, _ = await _open_pick(hass, aioclient_mock, level, text)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == f"pick_{level}"
        assert _fields(result) == [level]
        assert _select_options(result, level) == [
            *({"value": str(_["id"]), "label": _["value"]} for _ in MATCHES[level]),
            {"value": "search_again", "label": SEARCH_AGAIN_EN[level]},
        ]
        assert _config(result, level)["mode"] == "list"
        # No option is preselected, as in the provider form: a field with no default
        # at all gets its first option from the frontend
        assert _default(result, level) is None
        assert result["description_placeholders"] == {
            "place": place,
            "count": "3",
            "query": text,
        }

    async def test_two_matches_with_the_typed_name_give_a_select(
        self, hass, aioclient_mock
    ):
        """«Тестова» names a street and a lane: the user chooses which one."""
        streets = [
            {"id": 9001, "value": "вул. Тестова"},
            {"id": 9002, "value": "пров. Тестова"},
            {"id": 9003, "value": "вул. Інша"},
        ]
        result = await _kyiv_form(hass, aioclient_mock, streets={"json": streets})

        result = await _submit_kyiv(hass, result, street="Тестова")

        assert result["step_id"] == "pick_street"
        assert result["description_placeholders"]["count"] == "3"

    async def test_street_select_names_the_city_too(self, hass, aioclient_mock):
        """After the city, the select of the streets names the region and the city."""
        result = await _dnipro_form(
            hass, aioclient_mock, streets={"json": STREET_MATCHES}
        )

        result = await _submit_dnipro(hass, result)

        assert result["step_id"] == "pick_street"
        assert result["description_placeholders"] == {
            "place": "Дніпро, м. Дніпро",
            "count": "3",
            "query": "вул. Шевченка",
        }

    # The level, the text that gives several matches, the id of the chosen match, the
    # place that the house step names, and the requests after the select
    @pytest.mark.parametrize(
        ("level", "text", "chosen", "place", "next_requests"),
        [
            pytest.param(
                CONF_CITY,
                "дніпр",
                7,
                "Дніпро, м. Тестове, вул. Шевченка",
                ["streets", "houses"],
                id="city",
            ),
            pytest.param(
                CONF_STREET,
                "сверст",
                9002,
                "Київ, вул. Друга Тестова",
                ["houses"],
                id="street",
            ),
        ],
    )
    async def test_chosen_match_goes_on_to_the_next_level(
        self, hass, aioclient_mock, level, text, chosen, place, next_requests
    ):
        """The flow goes on with the chosen match, not with the first one."""
        result, _ = await _open_pick(hass, aioclient_mock, level, text)
        asked = len(_address_requests(aioclient_mock))

        result = await _configure(hass, result, {level: str(chosen)})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "house"
        assert result["description_placeholders"]["place"] == place
        # The select ends the search of its level, and the next levels follow
        later = _address_requests(aioclient_mock)[asked:]
        assert _asked(aioclient_mock)[-len(next_requests) :] == next_requests
        if level == CONF_CITY:
            assert {query["cityId"] for _, query in later} == {"7"}
        else:
            assert {query["streetId"] for _, query in later} == {"9002"}

    # The level, the text of the level, and the page of the region of the address
    @pytest.mark.parametrize(
        ("level", "text", "page"),
        [
            (CONF_CITY, "дніпр", DNIPRO_PAGE_URL),
            (CONF_STREET, "сверст", KYIV_PAGE_URL),
        ],
        ids=LEVELS,
    )
    async def test_search_again_shows_the_address_form_with_the_typed_texts(
        self, hass, aioclient_mock, level, text, page
    ):
        """«Search again» asks no more, and gives back the form with what was typed."""
        result, typed = await _open_pick(hass, aioclient_mock, level, text)
        asked = _asked(aioclient_mock)

        result = await _configure(hass, result, {level: "search_again"})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert not result["errors"]
        assert result["description_placeholders"] == {"url": page}
        assert _asked(aioclient_mock) == asked
        assert _fields(result) == list(typed)
        assert {_: _suggested(result, _) for _ in typed} == typed

    async def test_search_again_then_a_new_text_searches_again(
        self, hass, aioclient_mock
    ):
        """After «search again» the next submit starts the searches over."""
        result, _ = await _open_pick(hass, aioclient_mock, CONF_STREET, "вул")
        result = await _configure(hass, result, {CONF_STREET: "search_again"})
        aioclient_mock.clear_requests()
        _serve_kyiv(aioclient_mock)

        result = await _submit_kyiv(hass, result)

        assert result["step_id"] == "house"
        assert result["description_placeholders"]["place"] == KYIV_PLACE
        assert _asked(aioclient_mock) == ["streets", "houses"]

    @pytest.mark.parametrize(
        ("level", "text"),
        [(CONF_CITY, "дніпр"), (CONF_STREET, "сверст")],
        ids=LEVELS,
    )
    async def test_select_has_its_translation_key(
        self, hass, aioclient_mock, level, text
    ):
        """The frontend gives «search again» its text by the translation key."""
        result, _ = await _open_pick(hass, aioclient_mock, level, text)

        assert _config(result, level)["translation_key"] == TRANSLATION_KEYS[level]

    @pytest.mark.parametrize(
        ("level", "text"),
        [(CONF_CITY, "дніпр"), (CONF_STREET, "сверст")],
        ids=LEVELS,
    )
    async def test_label_is_the_english_text_in_each_language(
        self, hass, aioclient_mock, level, text
    ):
        """The flow does not translate: the label is the English fallback."""
        hass.config.language = "uk"

        result, _ = await _open_pick(hass, aioclient_mock, level, text)

        assert _select_options(result, level)[-1] == {
            "value": "search_again",
            "label": SEARCH_AGAIN_EN[level],
        }

    async def test_select_without_an_input_shows_itself_again(
        self, hass, aioclient_mock
    ):
        """A call without an input chooses nothing: the same select comes back."""
        result, _ = await _open_pick(hass, aioclient_mock, CONF_STREET, "сверст")

        again = await _configure(hass, result, None)

        assert again["step_id"] == "pick_street"
        assert _select_options(again, CONF_STREET) == _select_options(
            result, CONF_STREET
        )
        assert again["description_placeholders"] == result["description_placeholders"]

    async def test_value_that_the_select_does_not_offer_is_refused(
        self, hass, aioclient_mock
    ):
        """The select takes only the options that it shows."""
        result, _ = await _open_pick(hass, aioclient_mock, CONF_STREET, "сверст")

        with pytest.raises(InvalidData):
            await _configure(hass, result, {CONF_STREET: "1647000"})

    async def test_dnipro_city_from_a_select_goes_to_the_entry(
        self, hass, aioclient_mock
    ):
        """The city from a select gives the id to each next request, up to the entry."""
        result, _ = await _open_pick(hass, aioclient_mock, CONF_CITY, "дніпр")

        result = await _configure(hass, result, {CONF_CITY: "6"})
        result = await _configure(hass, result, {CONF_HOUSE: DNIPRO_HOUSE["value"]})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_CITY] == "м. Дніпро"
        assert result["data"][CONF_GROUP] == "3.1"
        requests = _address_requests(aioclient_mock)
        assert _asked(aioclient_mock) == DNIPRO_ORDER
        assert [query.get("cityId") for _, query in requests] == [None] + ["6"] * (
            len(requests) - 1
        )


class TestHouseStep:
    """The house step lists all houses of the street, and takes a typed number too."""

    async def test_dropdown_lists_the_houses_in_the_natural_order(
        self, hass, aioclient_mock
    ):
        """The dropdown has a search box, «search again», and the houses in order."""
        result = await _kyiv_house_form(hass, aioclient_mock)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "house"
        assert _fields(result) == [CONF_HOUSE]
        assert not result["errors"]
        config = _config(result, CONF_HOUSE)
        assert config["mode"] == "dropdown"
        # A typed number is a value too, and it gives the frontend its search box
        assert config["custom_value"] is True
        assert config["sort"] is False
        assert config["options"] == [
            {"value": "search_again", "label": SEARCH_AGAIN_EN[CONF_HOUSE]},
            *_options_of(KYIV_HOUSES_SORTED),
        ]
        # The frontend shows the value of the chosen option in the field, so the value
        # of each house is its number, and never its id
        numbers = [_["value"] for _ in KYIV_HOUSES_SORTED]
        assert [_["value"] for _ in config["options"][1:]] == numbers
        assert [_["label"] for _ in config["options"][1:]] == numbers
        # Without a default the frontend chooses nothing for the user, and the form has
        # no house from an earlier try
        assert _default(result, CONF_HOUSE) is None
        assert _suggested(result, CONF_HOUSE) is None
        assert result["description_placeholders"] == {
            "place": KYIV_PLACE,
            "count": "5",
        }

    async def test_search_again_option_comes_first_in_a_long_list(
        self, hass, aioclient_mock
    ):
        """A long list hides its last option, so «search again» comes first."""
        # Yasno gives the houses in its own order, and the dropdown sorts them
        houses = [{"id": 50000 + number, "value": str(number)} for number in (3, 1, 2)]
        houses += [
            {"id": 50000 + number, "value": str(number)} for number in range(40, 3, -1)
        ]

        result = await _kyiv_house_form(hass, aioclient_mock, houses={"json": houses})

        options = _select_options(result, CONF_HOUSE)
        assert result["description_placeholders"]["count"] == "40"
        assert len(options) == 41
        assert options[0] == {
            "value": "search_again",
            "label": SEARCH_AGAIN_EN[CONF_HOUSE],
        }
        assert [_["value"] for _ in options[1:]] == [str(_) for _ in range(1, 41)]
        assert [_["value"] for _ in options].count("search_again") == 1

    async def test_select_has_its_translation_key(self, hass, aioclient_mock):
        """The frontend gives «search again» its text by the translation key."""
        result = await _kyiv_house_form(hass, aioclient_mock)

        assert (
            _config(result, CONF_HOUSE)["translation_key"]
            == TRANSLATION_KEYS[CONF_HOUSE]
        )

    async def test_label_is_the_english_text_in_each_language(
        self, hass, aioclient_mock
    ):
        """The flow does not translate: the label is the English fallback."""
        hass.config.language = "uk"

        result = await _kyiv_house_form(hass, aioclient_mock)

        assert _select_options(result, CONF_HOUSE)[0] == {
            "value": "search_again",
            "label": SEARCH_AGAIN_EN[CONF_HOUSE],
        }

    async def test_houses_of_a_street_in_a_city_ask_with_the_city(
        self, hass, aioclient_mock
    ):
        """The street in a city lists its houses with the id of the city."""
        result = await _dnipro_house_form(hass, aioclient_mock)

        assert _select_options(result, CONF_HOUSE)[1:] == _options_of([DNIPRO_HOUSE])
        assert result["description_placeholders"] == {
            "place": "Дніпро, м. Дніпро, вул. Шевченка",
            "count": "1",
        }
        queries = [
            query
            for path, query in _address_requests(aioclient_mock)
            if path == "houses"
        ]
        assert len(queries) == len(LIST_QUERIES)
        assert {(_["cityId"], _["streetId"]) for _ in queries} == {("6", "644")}

    @pytest.mark.parametrize(
        "typed",
        [HOUSE_6A, HOUSE_6A_LATIN, f" {HOUSE_6A.lower()} "],
        ids=["cyrillic", "latin", "lower_case_and_spaces"],
    )
    async def test_typed_number_of_a_listed_house_needs_no_search(
        self, hass, aioclient_mock, typed
    ):
        """A typed number of one listed house is that house, with no new search."""
        result = await _kyiv_house_form(hass, aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: typed})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOUSE] == HOUSE_6A
        assert _asked(aioclient_mock) == ["streets", "houses", "group"]

    async def test_typed_number_that_the_list_lacks_goes_to_yasno(
        self, hass, aioclient_mock
    ):
        """A list can miss a house: a typed «6A» is searched with a Cyrillic letter."""
        listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
        houses = _houses_by_query({HOUSE_6A: {"json": [KYIV_HOUSE]}}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)
        labels = [_["label"] for _ in _select_options(result, CONF_HOUSE)]
        assert HOUSE_6A not in labels

        result = await _configure(hass, result, {CONF_HOUSE: HOUSE_6A_LATIN})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        # The entry keeps the name that Yasno wrote
        assert result["data"][CONF_HOUSE] == HOUSE_6A
        assert [_["query"] for _ in _house_searches(aioclient_mock)] == [HOUSE_6A]
        assert _house_searches(aioclient_mock)[0]["streetId"] == "1647"
        assert _asked(aioclient_mock) == ["streets", "houses", "houses", "group"]
        assert _address_requests(aioclient_mock)[-1][1]["houseId"] == "41362"

    async def test_two_listed_houses_with_one_number_give_one_option(
        self, hass, aioclient_mock
    ):
        """The dropdown has one option for a number, also when two houses have it."""
        result = await _kyiv_twin_house_form(hass, aioclient_mock)

        numbers = [_["value"] for _ in _select_options(result, CONF_HOUSE)[1:]]

        assert numbers == [_["value"] for _ in KYIV_HOUSES_SORTED]
        assert numbers.count(HOUSE_6A) == 1
        # The text counts the houses of the street, so it counts both twins
        assert result["description_placeholders"]["count"] == "6"

    async def test_number_of_two_listed_houses_takes_the_first_listed_one(
        self, hass, aioclient_mock
    ):
        """Two listed houses have the number: the first one is the house, no search."""
        result = await _kyiv_twin_house_form(hass, aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: HOUSE_6A})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOUSE] == HOUSE_6A
        # Yasno is not asked about the number: the list has it
        assert _house_searches(aioclient_mock) == []
        assert _asked(aioclient_mock) == ["streets", "houses", "group"]
        # The group is the one of the first listed house, not of its twin
        assert _address_requests(aioclient_mock)[-1][1]["houseId"] == "41362"

    async def test_typed_number_that_yasno_does_not_know(self, hass, aioclient_mock):
        """No match is an error under the field, and the same dropdown comes back."""
        listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
        houses = _houses_by_query({}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)

        again = await _configure(hass, result, {CONF_HOUSE: "99"})

        assert again["type"] is FlowResultType.FORM
        assert again["step_id"] == "house"
        assert again["errors"] == {"house": "house_not_found"}
        assert _select_options(again, CONF_HOUSE) == _select_options(result, CONF_HOUSE)
        assert again["description_placeholders"] == result["description_placeholders"]
        # The list is not asked again: the form shows the list that it has
        assert _asked(aioclient_mock) == ["streets", "houses", "houses"]
        assert [_["query"] for _ in _house_searches(aioclient_mock)] == ["99"]

    # The typed number, the query that Yasno gets for it, and the houses that it gives
    @pytest.mark.parametrize(
        ("typed", "query", "found"),
        [
            # Several houses hold the text, and none of them has this number
            pytest.param(
                "12",
                "12",
                [{"id": 41380, "value": "12-1"}, {"id": 41381, "value": "12Б"}],
                id="no_exact_match",
            ),
            # Two houses have the number: the number does not tell which one
            pytest.param(
                HOUSE_6A_LATIN,
                HOUSE_6A,
                [KYIV_HOUSE, {"id": 41999, "value": HOUSE_6A}],
                id="two_exact_matches",
            ),
        ],
    )
    async def test_typed_number_without_one_exact_match_is_not_found(
        self, hass, aioclient_mock, typed, query, found
    ):
        """Only one house with the typed number is a sure answer."""
        # The list has no house that holds the typed number
        listed = [{"id": 41350, "value": "2"}, {"id": 41370, "value": "10"}]
        houses = _houses_by_query({query: {"json": found}}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)

        again = await _configure(hass, result, {CONF_HOUSE: typed})

        assert again["step_id"] == "house"
        assert again["errors"] == {"house": "house_not_found"}
        assert [_["query"] for _ in _house_searches(aioclient_mock)] == [query]

    @pytest.mark.parametrize(
        "reply",
        [{"exc": ClientError()}, {"exc": TimeoutError()}, {"status": 500}],
        ids=["no_connection", "timeout", "server_error"],
    )
    async def test_typed_number_without_an_answer_of_yasno(
        self, hass, aioclient_mock, reply
    ):
        """No answer says nothing about the number: the error is on the form."""
        listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
        houses = _houses_by_query({HOUSE_6A: reply}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)

        again = await _configure(hass, result, {CONF_HOUSE: HOUSE_6A_LATIN})

        assert again["step_id"] == "house"
        assert again["errors"] == {"base": "yasno_no_answer"}
        assert _select_options(again, CONF_HOUSE) == _select_options(result, CONF_HOUSE)

    async def test_search_again_shows_the_address_form_with_the_typed_texts(
        self, hass, aioclient_mock
    ):
        """The option «not my street» asks no more, and gives back the typed texts."""
        result = await _kyiv_house_form(hass, aioclient_mock)
        asked = _asked(aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: "search_again"})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert not result["errors"]
        assert result["description_placeholders"] == {"url": KYIV_PAGE_URL}
        assert _asked(aioclient_mock) == asked
        assert _suggested(result, CONF_STREET) == "сверст"

    async def test_form_without_an_input_shows_the_list_again(
        self, hass, aioclient_mock
    ):
        """A call without an input chooses nothing, and asks for no new list."""
        result = await _kyiv_house_form(hass, aioclient_mock)
        asked = _asked(aioclient_mock)

        again = await _configure(hass, result, None)

        assert again["step_id"] == "house"
        assert _select_options(again, CONF_HOUSE) == _select_options(result, CONF_HOUSE)
        assert _asked(aioclient_mock) == asked

    @pytest.mark.parametrize(("changes", "errors", "extra"), GROUP_ERRORS)
    async def test_error_of_the_group_keeps_the_house_form(
        self, hass, aioclient_mock, changes, errors, extra
    ):
        """An error after the choice shows the dropdown again, for the street."""
        result = await _kyiv_house_form(hass, aioclient_mock, **changes)

        again = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})

        assert again["type"] is FlowResultType.FORM
        assert again["step_id"] == "house"
        assert again["errors"] == errors
        assert _select_options(again, CONF_HOUSE) == _select_options(result, CONF_HOUSE)
        # The text names the address of the street: the house is not accepted yet
        assert again["description_placeholders"] == {
            **result["description_placeholders"],
            **extra,
        }
        assert hass.config_entries.async_entries(DOMAIN) == []
        # The list of the houses is asked once
        assert _asked(aioclient_mock)[:3] == ["streets", "houses", "group"]

    @pytest.mark.parametrize(("changes", "errors"), GROUP_ERROR_REPLIES)
    async def test_error_of_the_group_suggests_the_chosen_house(
        self, hass, aioclient_mock, changes, errors
    ):
        """After an error of the group, the field shows the house that was chosen."""
        result = await _kyiv_house_form(hass, aioclient_mock, **changes)

        again = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})

        assert again["errors"] == errors
        assert _suggested(again, CONF_HOUSE) == HOUSE_6A

    async def test_typed_number_that_yasno_does_not_know_stays_in_the_field(
        self, hass, aioclient_mock
    ):
        """After «house not found», the field shows the number that the user typed."""
        listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
        houses = _houses_by_query({}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)

        again = await _configure(hass, result, {CONF_HOUSE: "99"})

        assert again["errors"] == {"house": "house_not_found"}
        assert _suggested(again, CONF_HOUSE) == "99"

    async def test_typed_number_without_an_answer_of_yasno_stays_in_the_field(
        self, hass, aioclient_mock
    ):
        """After no answer of the search, the field shows the number that was typed."""
        listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
        houses = _houses_by_query({HOUSE_6A: {"exc": ClientError()}}, {"json": listed})
        result = await _kyiv_house_form(hass, aioclient_mock, houses=houses)

        again = await _configure(hass, result, {CONF_HOUSE: HOUSE_6A_LATIN})

        assert again["errors"] == {"base": "yasno_no_answer"}
        assert _suggested(again, CONF_HOUSE) == HOUSE_6A_LATIN

    async def test_next_choice_after_an_error_goes_on(self, hass, aioclient_mock):
        """After the error of a group, a new choice of the same form makes the entry."""
        result = await _kyiv_house_form(
            hass, aioclient_mock, group={"status": 404, "json": ENTRY_NOT_FOUND}
        )
        result = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})
        assert result["errors"] == {"house": "house_not_found"}
        aioclient_mock.clear_requests()
        _serve_kyiv(aioclient_mock)

        result = await _configure(hass, result, {CONF_HOUSE: "2"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOUSE] == "2"
        assert result["description_placeholders"]["address"] == f"{KYIV_PLACE}, 2"
        assert _asked(aioclient_mock) == ["group"]


class TestButton:
    """The button of a form says Next while a form follows, and Submit at the last."""

    async def test_forms_before_the_house_say_next_and_the_house_form_does_not(
        self, hass, aioclient_mock
    ):
        """The address form and the pick forms are not the last step: a house comes."""
        result = await _dnipro_form(
            hass,
            aioclient_mock,
            cities={"json": CITY_MATCHES},
            streets={"json": STREET_MATCHES},
        )
        # The frontend shows Next only for a form with last_step set to False
        assert result["step_id"] == "address"
        assert result["last_step"] is False

        result = await _submit_dnipro(hass, result, city="дніпр")
        assert result["step_id"] == "pick_city"
        assert result["last_step"] is False

        result = await _configure(hass, result, {CONF_CITY: "6"})
        assert result["step_id"] == "pick_street"
        assert result["last_step"] is False

        result = await _configure(hass, result, {CONF_STREET: "9001"})
        assert result["step_id"] == "house"
        assert result["last_step"] is not False

        # The address form that «search again» shows has the same button
        result = await _configure(hass, result, {CONF_HOUSE: "search_again"})
        assert result["step_id"] == "address"
        assert result["last_step"] is False

        # The address form with an error has it too
        result = await _submit_dnipro(hass, result, street="св")
        assert result["errors"] == {"street": "street_too_short"}
        assert result["last_step"] is False


class TestErrors:
    """An error of a search keeps the address form, with the texts suggested."""

    @pytest.mark.parametrize("street", ["св", "  св  ", "   ", ""])
    async def test_short_street_asks_nothing(self, hass, aioclient_mock, street):
        """Fewer than three letters of the street give an error, and no request."""
        result = await _dnipro_form(hass, aioclient_mock)

        result = await _submit_dnipro(hass, result, street=street)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert result["errors"] == {"street": "street_too_short"}
        assert _address_requests(aioclient_mock) == []
        assert _suggested(result, CONF_CITY) == "м. Дніпро"
        assert _suggested(result, CONF_STREET) == street

    # The reply that Yasno gives, the field of the error, the error, and the requests
    # that the flow sends until then
    @pytest.mark.parametrize(
        ("changes", "field", "error", "asked"),
        [
            pytest.param(
                {"cities": {"json": []}},
                CONF_CITY,
                "city_not_found",
                ["cities"],
                id="city",
            ),
            pytest.param(
                {"streets": {"json": []}},
                CONF_STREET,
                "street_not_found",
                ["cities", "streets"],
                id="street",
            ),
            pytest.param(
                {"houses": {"json": []}},
                CONF_STREET,
                "street_without_houses",
                ["cities", "streets", "houses"],
                id="street_without_houses",
            ),
        ],
    )
    async def test_unknown_text(
        self, hass, aioclient_mock, changes, field, error, asked
    ):
        """Yasno does not know a text: the error is under the field of that level."""
        result = await _dnipro_form(hass, aioclient_mock, **changes)

        result = await _submit_dnipro(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert result["errors"] == {field: error}
        assert _asked(aioclient_mock) == asked
        assert _suggested(result, CONF_CITY) == "м. Дніпро"
        assert _suggested(result, CONF_STREET) == "вул. Шевченка"

    @pytest.mark.parametrize("level", ["cities", "streets", "houses"])
    @pytest.mark.parametrize(
        "reply",
        [{"exc": ClientError()}, {"exc": TimeoutError()}, {"status": 500}],
        ids=["no_connection", "timeout", "server_error"],
    )
    async def test_no_answer_of_a_level(self, hass, aioclient_mock, level, reply):
        """No answer at a level says nothing about the address, also for the houses."""
        result = await _dnipro_form(hass, aioclient_mock, **{level: reply})

        result = await _submit_dnipro(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert result["errors"] == {"base": "yasno_no_answer"}
        assert _asked(aioclient_mock) == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]
        assert _suggested(result, CONF_STREET) == "вул. Шевченка"

    async def test_one_house_query_without_an_answer_gives_no_list(
        self, hass, aioclient_mock
    ):
        """A list of the houses with a hole in it is no list: Yasno does not answer."""
        houses = _houses_by_query({"7": {"exc": ClientError()}}, {"json": KYIV_HOUSES})
        result = await _kyiv_form(hass, aioclient_mock, houses=houses)

        result = await _submit_kyiv(hass, result)

        assert result["step_id"] == "address"
        assert result["errors"] == {"base": "yasno_no_answer"}

    async def test_next_submit_after_an_error_starts_over(self, hass, aioclient_mock):
        """A match that the user chose before an error does not stay in the next try."""
        result = await _kyiv_form(
            hass, aioclient_mock, streets={"json": STREET_MATCHES}, houses={"json": []}
        )
        result = await _submit_kyiv(hass, result)
        result = await _configure(hass, result, {CONF_STREET: "9001"})
        assert result["step_id"] == "address"
        assert result["errors"] == {"street": "street_without_houses"}
        aioclient_mock.clear_requests()
        _serve_kyiv(aioclient_mock, streets={"json": STREET_MATCHES})

        result = await _submit_kyiv(hass, result)

        # The street is searched again and asked again, not taken from the first try
        assert result["step_id"] == "pick_street"
        assert _asked(aioclient_mock) == ["streets"]
        result = await _configure(hass, result, {CONF_STREET: "1647"})
        # The houses are asked again too, for the street of the new choice
        assert result["step_id"] == "house"
        assert result["description_placeholders"]["place"] == KYIV_PLACE
        assert _asked(aioclient_mock) == ["streets", "houses"]
        result = await _configure(hass, result, {CONF_HOUSE: KYIV_HOUSE["value"]})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_STREET] == "вул. Сверстюка Євгена"


class TestLog:
    """The address of a person stays out of the debug log."""

    # The group of the entry, and the texts that the log must not have
    @pytest.mark.parametrize(
        ("region", "group", "secrets"),
        [
            pytest.param(
                CONF_STREET,
                "53.1",
                ["Сверстюка", "сверст", HOUSE_6A, HOUSE_6A_LATIN],
                id="without_a_city",
            ),
            pytest.param(
                CONF_CITY,
                "3.1",
                ["м. Дніпро", "Шевченка", "шевч", "дніпр"],
                id="with_a_city",
            ),
        ],
    )
    async def test_no_log_line_has_the_address(
        self, hass, aioclient_mock, caplog, region, group, secrets
    ):
        """The typed texts, the names of Yasno and the entry data are not in the log."""
        caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
        if region == CONF_STREET:
            # The list lacks the house, so the typed Latin number goes to the search
            listed = [_ for _ in KYIV_HOUSES if _ != KYIV_HOUSE]
            houses = _houses_by_query(
                {HOUSE_6A: {"json": [KYIV_HOUSE]}}, {"json": listed}
            )
            result = await _kyiv_form(
                hass, aioclient_mock, streets={"json": STREET_MATCHES}, houses=houses
            )
            result = await _submit_kyiv(hass, result)
            result = await _configure(hass, result, {CONF_STREET: "1647"})
            result = await _configure(hass, result, {CONF_HOUSE: HOUSE_6A_LATIN})
        else:
            result = await _dnipro_form(
                hass, aioclient_mock, cities={"json": CITY_MATCHES}
            )
            result = await _submit_dnipro(hass, result, city="дніпр", street="шевч")
            result = await _configure(hass, result, {CONF_CITY: "6"})
            result = await _configure(hass, result, {CONF_HOUSE: DNIPRO_HOUSE["value"]})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        # The entry has the address, so the log could have shown it
        assert CONF_STREET in result["data"]

        log = "\n".join(
            _.getMessage() for _ in caplog.records if _.name.startswith(LOGGER_NAME)
        )
        # The log has the lines of the flow, with the group of the entry
        assert f"'{CONF_GROUP}': '{group}'" in log
        for secret in secrets:
            assert secret not in log
