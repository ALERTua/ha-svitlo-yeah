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
HOUSE_6E = "6\N{CYRILLIC CAPITAL LETTER IE}"

# The measured chain of Київ (region 25, DSO 902): street, house, group
KYIV_KEY = "yasnoprovider_25_902"
KYIV_STREET = {"id": 1647, "value": "вул. Сверстюка Євгена"}
KYIV_HOUSE = {"id": 41362, "value": HOUSE_6A}
KYIV_CHAIN = {
    "streets": {"json": [KYIV_STREET]},
    "houses": {"json": [KYIV_HOUSE]},
    "group": {"json": {"group": 53, "subgroup": 1}},
}

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
# The requests that the flow sends for an address with a city, in order
DNIPRO_ORDER = ["cities", "streets", "houses", "group"]

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
]

# What Yasno answers for an id that it does not know
ENTRY_NOT_FOUND = {
    "code": "EntryNotFound",
    "detail": "Street 644 not found in Region 3 and Dso 301",
}

ADDRESS_PAGE_URL = "https://static.yasno.ua/kyiv/outages"
ADDRESS_PATH = URL(YASNO_ADDRESSES_ENDPOINT).path

# The English text of the option that searches again, for each level
SEARCH_AGAIN_EN = {
    CONF_CITY: "My city is not in the list, search again",
    CONF_STREET: "My street is not in the list, search again",
    CONF_HOUSE: "My house is not in the list, search again",
}

# The lists of several matches. The names of the other matches are made up, and the
# matches of the measured chains are among them.
STREET_MATCHES = [
    {"id": 9001, "value": "вул. Перша Тестова"},
    KYIV_STREET,
    {"id": 9002, "value": "вул. Друга Тестова"},
]
HOUSE_MATCHES = [
    {"id": 41360, "value": "6"},
    KYIV_HOUSE,
    {"id": 41363, "value": "6\N{CYRILLIC CAPITAL LETTER BE}"},
]
CITY_MATCHES = [
    DNIPRO_CITY,
    {"id": 7, "value": "м. Тестове"},
    {"id": 8, "value": "м. Інше Тестове"},
]
MATCHES = {
    CONF_CITY: CITY_MATCHES,
    CONF_STREET: STREET_MATCHES,
    CONF_HOUSE: HOUSE_MATCHES,
}
LEVELS = [CONF_CITY, CONF_STREET, CONF_HOUSE]


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
    """Return the endpoints of the address requests, in order."""
    return [path for path, _ in _address_requests(mock)]


async def _configure(hass, result: dict, user_input: dict | None) -> dict:
    """Submit the form or the menu of a flow result."""
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _select_options(result: dict, field: str) -> list:
    """Return the options of a select field in a form result."""
    return result["data_schema"].schema[field].config["options"]


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
    """Submit the address form of Київ, with the texts of the measured chain."""
    texts = {CONF_STREET: "сверст", CONF_HOUSE: HOUSE_6A} | typed
    return await _configure(hass, result, texts)


async def _submit_dnipro(hass, result: dict, **typed: str) -> dict:
    """Submit the address form of Дніпро, with the texts of the measured chain."""
    texts = {
        CONF_CITY: DNIPRO_CITY["value"],
        CONF_STREET: "вул. Шевченка",
        CONF_HOUSE: DNIPRO_HOUSE["value"],
    } | typed
    return await _configure(hass, result, texts)


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
        typed = {CONF_CITY: text, CONF_STREET: "вул. Шевченка", CONF_HOUSE: "1"}
        return await _configure(hass, result, typed), typed
    result = await _kyiv_form(hass, aioclient_mock, **{f"{level}s": matches})
    typed = {CONF_STREET: "сверст", CONF_HOUSE: HOUSE_6A} | {level: text}
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

    async def test_address_form_of_a_region_without_cities(self, hass, aioclient_mock):
        """Київ has no cities: the form has the street and the house."""
        result = await _kyiv_form(hass, aioclient_mock)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert _fields(result) == [CONF_STREET, CONF_HOUSE]
        assert not result["errors"]
        assert result["description_placeholders"] == {"url": ADDRESS_PAGE_URL}
        # Each field is required, and the form has no text from an earlier try
        for key in result["data_schema"].schema:
            assert isinstance(key, vol.Required)
            assert _suggested(result, key.schema) is None
        assert _asked(aioclient_mock) == []

    async def test_address_form_of_a_region_with_cities(self, hass, aioclient_mock):
        """Дніпро has cities: the city comes before the street."""
        result = await _dnipro_form(hass, aioclient_mock)

        assert result["step_id"] == "address"
        assert _fields(result) == [CONF_CITY, CONF_STREET, CONF_HOUSE]
        assert result["description_placeholders"] == {"url": ADDRESS_PAGE_URL}


class TestFoundAddress:
    """An address that Yasno knows gives an entry with its group and its names."""

    async def test_kyiv_street_and_house_create_the_entry(self, hass, aioclient_mock):
        """One street that is not exact and one house go on without a question."""
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result)

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
        base = {"regionId": "25", "dsoId": "902"}
        assert _address_requests(aioclient_mock) == [
            ("streets", base | {"query": "сверст"}),
            ("houses", base | {"streetId": "1647", "query": HOUSE_6A}),
            ("group", base | {"streetId": "1647", "houseId": "41362"}),
        ]

    async def test_three_letters_of_the_street_are_enough(self, hass, aioclient_mock):
        """The street text has the least length that Yasno searches."""
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result, street=" све ")

        assert result["type"] is FlowResultType.CREATE_ENTRY

    async def test_latin_letter_of_the_house_goes_out_as_cyrillic(
        self, hass, aioclient_mock
    ):
        """Yasno does not find a Latin A in a house, so the search gets a Cyrillic A."""
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result, house=HOUSE_6A_LATIN)

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert _address_requests(aioclient_mock)[1] == (
            "houses",
            {
                "regionId": "25",
                "dsoId": "902",
                "streetId": "1647",
                "query": HOUSE_6A,
            },
        )
        # The entry keeps the name that Yasno wrote
        assert result["data"][CONF_HOUSE] == HOUSE_6A

    async def test_dnipro_city_street_and_house_create_the_entry(
        self, hass, aioclient_mock
    ):
        """In a region with cities, the entry has the city, and each request has it."""
        result = await _dnipro_form(hass, aioclient_mock)

        result = await _submit_dnipro(hass, result)

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
        base = {"regionId": "3", "dsoId": "301"}
        with_city = base | {"cityId": "6"}
        assert _address_requests(aioclient_mock) == [
            ("cities", base | {"query": "м. Дніпро"}),
            ("streets", with_city | {"query": "вул. Шевченка"}),
            ("houses", with_city | {"streetId": "644", "query": "1"}),
            ("group", with_city | {"streetId": "644", "houseId": "190821"}),
        ]

    async def test_group_of_an_existing_entry_aborts(self, hass, aioclient_mock):
        """An address with the group of an entry gives no second entry."""
        data = {**YASNO_KYIV_1_1, CONF_GROUP: "53.1"}
        existing = MockConfigEntry(domain=DOMAIN, data=data)
        existing.add_to_hass(hass)
        result = await _kyiv_form(hass, aioclient_mock)

        result = await _submit_kyiv(hass, result)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert hass.config_entries.async_entries(DOMAIN) == [existing]
        assert existing.data == data


class TestSeveralMatches:
    """Several matches of a level give a select, and a select can search again."""

    # The level, the typed text of the level, and the id of the match that the form
    # preselects: an exact match is preselected, and without one no option is
    @pytest.mark.parametrize(
        ("level", "text", "preselected"),
        [
            pytest.param(CONF_CITY, "м. Дніпро", "6", id="city_exact"),
            pytest.param(CONF_CITY, "дніпр", None, id="city_not_exact"),
            pytest.param(
                CONF_STREET, "вул. Сверстюка Євгена", "1647", id="street_exact"
            ),
            pytest.param(CONF_STREET, "сверст", None, id="street_not_exact"),
            pytest.param(CONF_HOUSE, HOUSE_6A_LATIN, "41362", id="house_exact"),
            pytest.param(CONF_HOUSE, "6", "41360", id="house_short_text_exact"),
            pytest.param(CONF_HOUSE, HOUSE_6E, None, id="house_not_exact"),
        ],
    )
    async def test_select_of_the_matches(
        self, hass, aioclient_mock, level, text, preselected
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
        assert result["data_schema"].schema[level].config["mode"] == "list"
        # Without an exact match the default is empty, as in the provider form:
        # a field with no default at all gets its first option from the frontend
        assert _default(result, level) == preselected
        assert result["description_placeholders"] == {
            "count": "3",
            "query": text,
        }

    # The level, the text that gives several matches, the id of the chosen match, the
    # key that the group request holds for the level, and the requests after the select
    @pytest.mark.parametrize(
        ("level", "text", "chosen", "key", "next_requests"),
        [
            pytest.param(
                CONF_CITY,
                "дніпр",
                7,
                "cityId",
                ["streets", "houses", "group"],
                id="city",
            ),
            pytest.param(
                CONF_STREET,
                "сверст",
                9002,
                "streetId",
                ["houses", "group"],
                id="street",
            ),
            pytest.param(CONF_HOUSE, "6", 41363, "houseId", ["group"], id="house"),
        ],
    )
    async def test_chosen_match_goes_on_to_the_next_level(
        self, hass, aioclient_mock, level, text, chosen, key, next_requests
    ):
        """The flow goes on with the chosen match, not with the first one."""
        result, _ = await _open_pick(hass, aioclient_mock, level, text)
        asked = len(_address_requests(aioclient_mock))

        result = await _configure(hass, result, {level: str(chosen)})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        (match,) = (item for item in MATCHES[level] if item["id"] == chosen)
        assert result["data"][level] == match["value"]
        # The select ends the search of its level, and the next levels follow
        later = _address_requests(aioclient_mock)[asked:]
        assert [path for path, _ in later] == next_requests
        assert later[-1][1][key] == str(chosen)
        if level == CONF_CITY:
            assert [query["cityId"] for _, query in later] == ["7", "7", "7"]

    @pytest.mark.parametrize(
        ("level", "text"),
        [(CONF_CITY, "дніпр"), (CONF_STREET, "сверст"), (CONF_HOUSE, "6")],
        ids=LEVELS,
    )
    async def test_search_again_shows_the_address_form_with_the_typed_texts(
        self, hass, aioclient_mock, level, text
    ):
        """«Search again» asks no more, and gives back the form with what was typed."""
        result, typed = await _open_pick(hass, aioclient_mock, level, text)
        asked = _asked(aioclient_mock)

        result = await _configure(hass, result, {level: "search_again"})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert not result["errors"]
        assert result["description_placeholders"] == {"url": ADDRESS_PAGE_URL}
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

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_STREET] == "вул. Сверстюка Євгена"
        assert _asked(aioclient_mock) == ["streets", "houses", "group"]

    async def test_label_is_in_the_language_of_the_server(self, hass, aioclient_mock):
        """The option that searches again has its text from the common translations."""
        hass.config.language = "uk"

        result, _ = await _open_pick(hass, aioclient_mock, CONF_STREET, "сверст")

        assert _select_options(result, CONF_STREET)[-1] == {
            "value": "search_again",
            "label": "Моєї вулиці немає, шукати знову",
        }

    async def test_label_falls_back_to_english(self, hass, aioclient_mock):
        """A language file without the text gives the English text."""
        with patch(
            "custom_components.svitlo_yeah.config_flow.async_get_translations",
            return_value={},
        ):
            result, _ = await _open_pick(hass, aioclient_mock, CONF_HOUSE, "6")

        assert _select_options(result, CONF_HOUSE)[-1] == {
            "value": "search_again",
            "label": SEARCH_AGAIN_EN[CONF_HOUSE],
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
        """The exact city is preselected, and the whole path holds its id."""
        result, _ = await _open_pick(hass, aioclient_mock, CONF_CITY, "м. Дніпро")

        result = await _configure(
            hass, result, {CONF_CITY: _default(result, CONF_CITY)}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_CITY] == "м. Дніпро"
        assert result["data"][CONF_GROUP] == "3.1"
        requests = _address_requests(aioclient_mock)
        assert [path for path, _ in requests] == DNIPRO_ORDER
        assert [query.get("cityId") for _, query in requests] == [None, "6", "6", "6"]


class TestErrors:
    """An error keeps the address form, with the typed texts as suggested values."""

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
        assert _suggested(result, CONF_HOUSE) == "1"

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
                CONF_HOUSE,
                "house_not_found",
                ["cities", "streets", "houses"],
                id="house_without_matches",
            ),
            pytest.param(
                {"group": {"status": 404, "json": ENTRY_NOT_FOUND}},
                CONF_HOUSE,
                "house_not_found",
                DNIPRO_ORDER,
                id="house_that_the_group_does_not_know",
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
        assert _suggested(result, CONF_HOUSE) == "1"

    @pytest.mark.parametrize("level", DNIPRO_ORDER)
    @pytest.mark.parametrize(
        "reply",
        [{"exc": ClientError()}, {"exc": TimeoutError()}, {"status": 500}],
        ids=["no_connection", "timeout", "server_error"],
    )
    async def test_no_answer_of_a_level(self, hass, aioclient_mock, level, reply):
        """No answer at a level says nothing about the address."""
        result = await _dnipro_form(hass, aioclient_mock, **{level: reply})

        result = await _submit_dnipro(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert result["errors"] == {"base": "yasno_no_answer"}
        assert _asked(aioclient_mock) == DNIPRO_ORDER[: DNIPRO_ORDER.index(level) + 1]
        assert _suggested(result, CONF_HOUSE) == "1"

    @pytest.mark.parametrize(
        "planned",
        [{"exc": ClientError()}, {"status": 500}, {"json": []}],
        ids=["no_connection", "server_error", "another_shape"],
    )
    async def test_no_answer_with_the_schedule(self, hass, aioclient_mock, planned):
        """The group is known, but the schedule gives no answer."""
        result = await _kyiv_form(hass, aioclient_mock, planned=planned)

        result = await _submit_kyiv(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "yasno_no_answer"}
        assert _suggested(result, CONF_STREET) == "сверст"
        assert hass.config_entries.async_entries(DOMAIN) == []

    async def test_group_that_the_schedule_does_not_list(self, hass, aioclient_mock):
        """Yasno gives a group that its schedule lacks: the error names the group."""
        result = await _kyiv_form(
            hass, aioclient_mock, planned={"json": {"1.1": {}, "2.1": {}}}
        )

        result = await _submit_kyiv(hass, result)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "address"
        assert result["errors"] == {"base": "address_group_not_listed"}
        assert result["description_placeholders"] == {
            "url": ADDRESS_PAGE_URL,
            "group": "53.1",
        }
        assert _suggested(result, CONF_STREET) == "сверст"
        assert _suggested(result, CONF_HOUSE) == HOUSE_6A
        assert hass.config_entries.async_entries(DOMAIN) == []

    async def test_next_submit_after_an_error_starts_over(self, hass, aioclient_mock):
        """A match that the user chose before an error does not stay in the next try."""
        result = await _kyiv_form(
            hass, aioclient_mock, streets={"json": STREET_MATCHES}, houses={"json": []}
        )
        result = await _submit_kyiv(hass, result)
        result = await _configure(hass, result, {CONF_STREET: "9001"})
        assert result["errors"] == {"house": "house_not_found"}
        aioclient_mock.clear_requests()
        _serve_kyiv(aioclient_mock, streets={"json": STREET_MATCHES})

        result = await _submit_kyiv(hass, result)

        # The street is searched again and asked again, not taken from the first try
        assert result["step_id"] == "pick_street"
        assert _asked(aioclient_mock) == ["streets"]
        result = await _configure(hass, result, {CONF_STREET: "1647"})
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
            result = await _kyiv_form(
                hass, aioclient_mock, streets={"json": STREET_MATCHES}
            )
            result = await _submit_kyiv(hass, result, house=HOUSE_6A_LATIN)
            result = await _configure(hass, result, {CONF_STREET: "1647"})
        else:
            result = await _dnipro_form(
                hass, aioclient_mock, cities={"json": CITY_MATCHES}
            )
            result = await _submit_dnipro(hass, result, city="дніпр", street="шевч")
            result = await _configure(hass, result, {CONF_CITY: "6"})
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
