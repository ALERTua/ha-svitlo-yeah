"""Tests for the config flow on a real Home Assistant (the hass fixture)."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_ADDRESS_STR,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    NAME,
    PROVIDER_TYPE_E_SVITLO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    E_SVITLO_ACCOUNT_101,
    E_SVITLO_ACCOUNTS_URL,
    E_SVITLO_LOGIN_URL,
    YASNO_KYIV_1_1,
    YASNO_PLANNED_URL,
)

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "empty_yasno_region_cache"
)

KYIV_REGION_URL = DTEK_PROVIDER_URLS["kyiv_region"][0]
KYIV_REGION_KEY = "dtekjsonprovider_kyiv_region"
KYIV_GROUPS = [f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2)]

YASNO_REGION_ID = 25
YASNO_OTHER_REGION_ID = 3
YASNO_DSO_ID = 902
YASNO_KEY = f"yasnoprovider_{YASNO_REGION_ID}_{YASNO_DSO_ID}"
YASNO_REGIONS = [
    {
        "hasCities": False,
        "dsos": [{"id": YASNO_DSO_ID, "name": "ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»"}],
        "id": YASNO_REGION_ID,
        "value": "Київ",
    },
    {
        "hasCities": False,
        "dsos": [{"id": YASNO_DSO_ID, "name": "ДТЕК"}],
        "id": YASNO_OTHER_REGION_ID,
        "value": "Дніпро",
    },
]

E_SVITLO_KEY = "esvitloprovider_sumy"
# The login forms name the site of the personal cabinet
E_SVITLO_SITE = "https://sm.e-svitlo.com.ua/"
E_SVITLO_CREDENTIALS = {
    key: E_SVITLO_ACCOUNT_101[key] for key in (CONF_USERNAME, CONF_PASSWORD)
}
E_SVITLO_NEW_LOGIN = {**E_SVITLO_CREDENTIALS, CONF_PASSWORD: "new secret"}
E_SVITLO_ACCOUNTS = [
    {"a": 101, "address": "Суми, вул. Перша, 1", "ls": "5001"},
    {"a": 102, "address": "Суми, вул. Друга, 2", "ls": "5002"},
]


def _dtek_feed(
    *,
    fresh: bool,
    fact_groups: tuple[str, ...] | list[str] = (),
    preset_groups: tuple[str, ...] | list[str] = (),
    sch_names: dict[str, str] | None = None,
) -> dict:
    """
    Build a DTEK JSON feed with the given groups.

    A feed without fact groups mirrors kyiv-region.json while DTEK publishes
    no outages: ``"data": []``.
    """
    update = (
        datetime.now(UTC).strftime("%d.%m.%Y %H:%M") if fresh else "19.02.2026 15:04"
    )
    day = {f"GPV{group}": {"1": "yes"} for group in fact_groups}
    feed = {
        "fact": {
            "data": {"1790715600": day} if day else [],
            "update": update,
            "today": 1790715600,
        }
    }
    if preset_groups:
        feed["preset"] = {
            "data": {f"GPV{group}": {"1": {"1": "yes"}} for group in preset_groups}
        }
    if sch_names:
        feed["preset"]["sch_names"] = {
            f"GPV{group}": name for group, name in sch_names.items()
        }
    return feed


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


def _add_entry(hass, data: dict) -> MockConfigEntry:
    """Add a config entry of this integration with the given data."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def _no_entry_setup():
    """Create the entries without their setup: these tests cover the flow only."""
    with patch("custom_components.svitlo_yeah.async_setup_entry", return_value=True):
        yield


async def _start_flow(hass, aioclient_mock) -> dict:
    """Start a new flow at the provider form, with the Yasno regions served."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=YASNO_REGIONS)
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _configure(hass, result: dict, user_input: dict) -> dict:
    """Submit the form of a flow result."""
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def _start_e_svitlo_flow(hass, aioclient_mock) -> dict:
    """Start a new flow at the E-Svitlo login form."""
    result = await _start_flow(hass, aioclient_mock)
    result = await _configure(hass, result, {CONF_PROVIDER: E_SVITLO_KEY})
    assert result["step_id"] == "esvitlo_auth"
    assert result["description_placeholders"]["esvitlo_url"] == E_SVITLO_SITE
    return result


def _serve_e_svitlo(aioclient_mock) -> None:
    """Accept the E-Svitlo login and list two accounts of the user."""
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(
        E_SVITLO_ACCOUNTS_URL, json={"data": {"lst_ls": E_SVITLO_ACCOUNTS}}
    )


async def test_provider_form_preselects_no_provider(hass, aioclient_mock):
    """
    The provider field has an empty default, so the user picks the provider.

    Without a default, the frontend selects the first option of a required select.
    """
    result = await _start_flow(hass, aioclient_mock)

    key = next(k for k in result["data_schema"].schema if k == CONF_PROVIDER)
    assert key.default is not vol.UNDEFINED
    assert _default(result, CONF_PROVIDER) is None


class TestStaleConfirmRouting:
    """The group step asks for consent only while the DTEK data is stale."""

    async def test_fresh_skips_stale_confirm(self, hass, aioclient_mock):
        """Fresh DTEK data routes directly to the group selection form."""
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=True, fact_groups=("1.1", "1.2"))
        )

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == ["1.1", "1.2"]

    async def test_unavailable_data_aborts(self, hass, aioclient_mock):
        """With no source that answered, the flow aborts as unavailable."""
        aioclient_mock.get(KYIV_REGION_URL, exc=ClientError())

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "dtek_json_unavailable"
        assert result["description_placeholders"] == {"urls": KYIV_REGION_URL}

    async def test_unavailable_sources_go_one_on_each_line(self, hass, aioclient_mock):
        """The abort text names each source of a provider on its own line."""
        urls = DTEK_PROVIDER_URLS["vinnytsia"]
        for url in urls:
            aioclient_mock.get(url, exc=ClientError())

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(
            hass, result, {CONF_PROVIDER: "dtekjsonprovider_vinnytsia"}
        )

        assert len(urls) > 1
        assert result["description_placeholders"] == {"urls": "\n".join(urls)}

    @pytest.mark.parametrize("fresh", [True, False], ids=["fresh", "stale"])
    async def test_data_without_groups_aborts_as_empty(
        self, hass, aioclient_mock, fresh
    ):
        """A source that answered without groups is not a connection problem."""
        aioclient_mock.get(KYIV_REGION_URL, json=_dtek_feed(fresh=fresh))

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "dtek_json_empty_data"

    async def test_stale_confirm_unchecked_shows_an_error(self, hass, aioclient_mock):
        """The form without the checkbox comes back with an error at the checkbox."""
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=False, preset_groups=KYIV_GROUPS)
        )

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})
        result = await _configure(hass, result, {"acknowledge": False})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "stale_confirm"
        assert result["errors"] == {"acknowledge": "acknowledge_required"}

        result = await _configure(hass, result, {"acknowledge": True})

        assert result["step_id"] == "group"


class TestSetupWithRealProviderApis:
    """Walk the whole config flow with the real provider APIs and fake HTTP."""

    async def test_dtek_kyiv_region_with_empty_fact_schedule(
        self, hass, aioclient_mock
    ):
        """An empty fact schedule still offers the preset groups after consent."""
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=False, preset_groups=KYIV_GROUPS)
        )

        result = await _start_flow(hass, aioclient_mock)
        providers = [o["value"] for o in _select_options(result, CONF_PROVIDER)]
        assert KYIV_REGION_KEY in providers

        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})
        assert result["step_id"] == "stale_confirm"

        result = await _configure(hass, result, {"acknowledge": True})
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == KYIV_GROUPS

        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        # The consent is a flag of the flow, so the entry data does not keep it.
        assert result["data"] == DTEK_KYIV_REGION_1_1
        assert hass.config_entries.async_entries(DOMAIN)[0].data == DTEK_KYIV_REGION_1_1
        assert result["title"] == "Kyiv Oblast 1.1"

    async def test_dtek_dnipro_labels_the_cek_groups(self, hass, aioclient_mock):
        """A group that the source names without its number gets a label."""
        feed = _dtek_feed(
            fresh=False,
            preset_groups=("1.1", "1001.1"),
            sch_names={"1.1": "Черга 1.1", "1001.1": "ЦЕК 1.1"},
        )
        aioclient_mock.get(DTEK_PROVIDER_URLS["dnipro"][0], json=feed)

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(
            hass, result, {CONF_PROVIDER: "dtekjsonprovider_dnipro"}
        )
        result = await _configure(hass, result, {"acknowledge": True})
        assert _select_options(result, CONF_GROUP) == [
            {"value": "1.1", "label": "1.1"},
            {"value": "1001.1", "label": "ЦЕК 1.1 (1001.1)"},
        ]

        result = await _configure(hass, result, {CONF_GROUP: "1001.1"})

        assert result["data"][CONF_GROUP] == "1001.1"

    async def test_yasno_kyiv(self, hass, aioclient_mock):
        """Yasno offers the groups of its planned outages and stores the region."""
        aioclient_mock.get(YASNO_PLANNED_URL, json={"1.1": {}, "1.2": {}})

        result = await _start_flow(hass, aioclient_mock)
        providers = [o["value"] for o in _select_options(result, CONF_PROVIDER)]
        assert YASNO_KEY in providers

        result = await _configure(hass, result, {CONF_PROVIDER: YASNO_KEY})
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == ["1.1", "1.2"]

        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == YASNO_KYIV_1_1
        # The long DTEK name of the source becomes «ДТЕК», as in the device name
        assert result["title"] == "Київ ДТЕК 1.1"

    async def test_yasno_without_groups_aborts(self, hass, aioclient_mock):
        """Yasno planned outages without groups stop the flow."""
        aioclient_mock.get(YASNO_PLANNED_URL, json={})

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: YASNO_KEY})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "yasno_connection_error"

    async def test_unknown_provider_is_refused_by_the_form(self, hass, aioclient_mock):
        """The provider select accepts only the providers that the form offers."""
        result = await _start_flow(hass, aioclient_mock)

        with pytest.raises(InvalidData):
            await _configure(hass, result, {CONF_PROVIDER: "dtekjsonprovider_nowhere"})

    async def test_yasno_regions_timeout_offers_dtek(self, hass, aioclient_mock):
        """While the Yasno regions time out, the other providers stay available."""
        aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=TimeoutError())

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

        assert result["type"] is FlowResultType.FORM
        providers = [o["value"] for o in _select_options(result, CONF_PROVIDER)]
        assert KYIV_REGION_KEY in providers
        assert YASNO_KEY not in providers

    async def test_yasno_groups_timeout_aborts(self, hass, aioclient_mock):
        """Planned outages that time out stop the flow like a connection error."""
        aioclient_mock.get(YASNO_PLANNED_URL, exc=TimeoutError())

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: YASNO_KEY})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "yasno_connection_error"


class TestReconfigureGroup:
    """Reconfigure lets the user pick another group for an existing entry."""

    async def test_dtek_kyiv_region(self, hass, aioclient_mock):
        """The group form preselects the current group and saves the new one."""
        entry = _add_entry(hass, DTEK_KYIV_REGION_1_1)
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=False, preset_groups=KYIV_GROUPS)
        )

        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "stale_confirm"

        result = await _configure(hass, result, {"acknowledge": True})
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == KYIV_GROUPS
        assert _default(result, CONF_GROUP) == "1.1"

        result = await _configure(hass, result, {CONF_GROUP: "2.2"})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data == {**DTEK_KYIV_REGION_1_1, CONF_GROUP: "2.2"}
        assert hass.config_entries.async_entries(DOMAIN) == [entry]

    async def test_yasno_group_that_the_source_lacks(self, hass, aioclient_mock):
        """A group that the source lacks is not preselected."""
        entry = _add_entry(hass, {**YASNO_KYIV_1_1, CONF_GROUP: "1.2"})
        aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=YASNO_REGIONS)
        aioclient_mock.get(YASNO_PLANNED_URL, json={"1.1": {}, "3.1": {}})

        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == ["1.1", "3.1"]
        assert _default(result, CONF_GROUP) is None

        result = await _configure(hass, result, {CONF_GROUP: "3.1"})

        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_GROUP] == "3.1"

    async def test_e_svitlo_stops_at_once(self, hass):
        """E-Svitlo takes the group from the account, so reconfigure stops."""
        data = {CONF_PROVIDER_TYPE: PROVIDER_TYPE_E_SVITLO, CONF_ACCOUNT_ID: "1"}
        entry = _add_entry(hass, data)

        result = await entry.start_reconfigure_flow(hass)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_e_svitlo"
        assert entry.data == data


class TestEntryTitle:
    """The title of an entry names its provider and group, as the device name does."""

    async def test_title_in_the_language_of_the_server(self, hass, aioclient_mock):
        """The provider name in the title comes in the language of the server."""
        hass.config.language = "uk"
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=True, fact_groups=("1.1",))
        )

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})
        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["title"] == "Київська Область 1.1"

    @pytest.mark.parametrize(
        ("title", "new_title"),
        [
            ("Kyiv Oblast 1.1", "Kyiv Oblast 2.2"),
            (NAME, "Kyiv Oblast 2.2"),
            ("Дача", "Дача"),
        ],
        ids=["title_of_the_integration", "title_of_earlier_versions", "own_title"],
    )
    async def test_reconfigure_keeps_a_title_of_the_user(
        self, hass, aioclient_mock, title, new_title
    ):
        """Reconfigure moves a title of the integration to the new group."""
        entry = MockConfigEntry(domain=DOMAIN, data=DTEK_KYIV_REGION_1_1, title=title)
        entry.add_to_hass(hass)
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=True, fact_groups=("1.1", "2.2"))
        )

        result = await entry.start_reconfigure_flow(hass)
        result = await _configure(hass, result, {CONF_GROUP: "2.2"})

        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_GROUP] == "2.2"
        assert entry.title == new_title

    async def test_yasno_title_without_the_regions(self, hass, aioclient_mock):
        """Without the Yasno regions the integration has no names: the title stays."""
        entry = MockConfigEntry(
            domain=DOMAIN, data={**YASNO_KYIV_1_1, CONF_GROUP: "1.2"}, title="Мій дім"
        )
        entry.add_to_hass(hass)
        aioclient_mock.get(YASNO_REGIONS_ENDPOINT, exc=ClientError())
        aioclient_mock.get(YASNO_PLANNED_URL, json={"1.1": {}, "3.1": {}})

        result = await entry.start_reconfigure_flow(hass)
        result = await _configure(hass, result, {CONF_GROUP: "3.1"})

        assert result["reason"] == "reconfigure_successful"
        assert entry.title == "Мій дім"


class TestDuplicateGroup:
    """The integration keeps one entry for each provider and group."""

    @pytest.fixture(autouse=True)
    def _fresh_kyiv_region_feed(self, aioclient_mock):
        """Serve a fresh Kyiv region feed, so that no consent step comes."""
        aioclient_mock.get(
            KYIV_REGION_URL,
            json=_dtek_feed(fresh=True, fact_groups=("1.1", "1.2", "2.2")),
        )

    async def _add_kyiv_region_group(self, hass, aioclient_mock, group: str) -> dict:
        """Walk a new flow for the Kyiv region feed to the given group."""
        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})
        return await _configure(hass, result, {CONF_GROUP: group})

    async def test_same_provider_and_group_aborts(self, hass, aioclient_mock):
        """A second entry for the same DTEK provider and group aborts."""
        _add_entry(hass, DTEK_KYIV_REGION_1_1)

        result = await self._add_kyiv_region_group(hass, aioclient_mock, "1.1")

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_other_group_creates_the_entry(self, hass, aioclient_mock):
        """Another group of the same provider is a new entry."""
        _add_entry(hass, DTEK_KYIV_REGION_1_1)

        result = await self._add_kyiv_region_group(hass, aioclient_mock, "1.2")

        assert result["type"] is FlowResultType.CREATE_ENTRY

    async def test_same_group_of_another_dtek_provider_creates_the_entry(
        self, hass, aioclient_mock
    ):
        """The same group of another DTEK provider is a new entry."""
        _add_entry(hass, {**DTEK_KYIV_REGION_1_1, CONF_PROVIDER: "odesa"})

        result = await self._add_kyiv_region_group(hass, aioclient_mock, "1.1")

        assert result["type"] is FlowResultType.CREATE_ENTRY

    async def test_yasno_group_of_another_region_creates_the_entry(
        self, hass, aioclient_mock
    ):
        """The same Yasno group in another region is a new entry."""
        _add_entry(hass, YASNO_KYIV_1_1)
        aioclient_mock.get(
            YASNO_PLANNED_OUTAGES_ENDPOINT.format(
                region_id=YASNO_OTHER_REGION_ID, dso_id=YASNO_DSO_ID
            ),
            json={"1.1": {}},
        )

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(
            hass,
            result,
            {CONF_PROVIDER: f"yasnoprovider_{YASNO_OTHER_REGION_ID}_{YASNO_DSO_ID}"},
        )
        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_REGION] == YASNO_OTHER_REGION_ID

    async def test_reconfigure_to_the_group_of_another_entry_aborts(self, hass):
        """Reconfigure does not move an entry onto the group of another entry."""
        entry = _add_entry(hass, {**DTEK_KYIV_REGION_1_1, CONF_GROUP: "2.2"})
        _add_entry(hass, DTEK_KYIV_REGION_1_1)

        result = await entry.start_reconfigure_flow(hass)
        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert entry.data[CONF_GROUP] == "2.2"

    async def test_reconfigure_to_its_own_group_changes_nothing(self, hass):
        """Reconfigure to the current group of the entry changes nothing."""
        entry = _add_entry(hass, DTEK_KYIV_REGION_1_1)

        result = await entry.start_reconfigure_flow(hass)
        result = await _configure(hass, result, {CONF_GROUP: "1.1"})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_unchanged"
        assert entry.data == DTEK_KYIV_REGION_1_1


class TestDuplicateESvitloAccount:
    """The integration keeps one entry for each E-Svitlo account."""

    @pytest.fixture(autouse=True)
    def _e_svitlo_answers(self, aioclient_mock):
        """Accept the login and list two accounts of the user."""
        _serve_e_svitlo(aioclient_mock)

    async def _add_account(self, hass, aioclient_mock, account_id: str) -> dict:
        """Walk a new E-Svitlo flow to the given account."""
        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)
        assert result["step_id"] == "esvitlo_account"
        return await _configure(hass, result, {CONF_ACCOUNT_ID: account_id})

    async def test_same_account_aborts(self, hass, aioclient_mock):
        """A second entry for the same account aborts."""
        _add_entry(hass, E_SVITLO_ACCOUNT_101)

        result = await self._add_account(hass, aioclient_mock, "101")

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    async def test_other_account_creates_the_entry(self, hass, aioclient_mock):
        """Another account of the same user is a new entry with its address."""
        _add_entry(hass, E_SVITLO_ACCOUNT_101)

        result = await self._add_account(hass, aioclient_mock, "102")

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            **E_SVITLO_ACCOUNT_101,
            CONF_ACCOUNT_ID: "102",
            CONF_ADDRESS_STR: "Суми, вул. Друга, 2",
        }
        # The address is personal data, and the debug log shows the title
        assert result["title"] == "Sumy E-Svitlo"


class TestESvitloLoginForm:
    """The E-Svitlo login form helps the browser and a password manager."""

    async def test_fields_have_their_types_and_autocomplete(self, hass, aioclient_mock):
        """The password field is masked, and both fields name their autocomplete."""
        result = await _start_e_svitlo_flow(hass, aioclient_mock)

        schema = result["data_schema"].schema
        username, password = (
            schema[field].config for field in ("username", "password")
        )
        assert (username["type"], username["autocomplete"]) == ("text", "username")
        assert (password["type"], password["autocomplete"]) == (
            "password",
            "current-password",
        )

    @pytest.mark.parametrize(
        "answer",
        [{"json": {"data": {"login": False}}}, {"exc": ClientError()}],
        ids=["invalid_auth", "cannot_connect"],
    )
    async def test_error_keeps_the_username(self, hass, aioclient_mock, answer):
        """After an error, the form keeps the typed username, but not the password."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, **answer)
        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        assert _suggested(result, "username") is None

        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["step_id"] == "esvitlo_auth"
        assert result["errors"]
        assert _suggested(result, "username") == E_SVITLO_CREDENTIALS["username"]
        assert _suggested(result, "password") is None


class TestESvitloConnection:
    """The E-Svitlo steps tell refused credentials from an unreachable server."""

    async def test_refused_login_shows_invalid_auth(self, hass, aioclient_mock):
        """Credentials that the server refuses keep the form with invalid_auth."""
        aioclient_mock.post(
            E_SVITLO_LOGIN_URL, json={"data": {"login": False}, "error": "refused"}
        )

        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "esvitlo_auth"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.parametrize(
        "answer",
        [{"exc": ClientError()}, {"exc": TimeoutError()}, {"status": 500}],
        ids=["client_error", "timeout", "http_500"],
    )
    async def test_unreachable_server_shows_cannot_connect(
        self, hass, aioclient_mock, answer
    ):
        """No answer of the server to the login keeps the form with cannot_connect."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, **answer)

        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "esvitlo_auth"
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_retry_after_a_network_error_reaches_the_account_step(
        self, hass, aioclient_mock
    ):
        """After a network error, the same form logs in on the next try."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, exc=ClientError())
        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)
        assert result["errors"] == {"base": "cannot_connect"}

        aioclient_mock.clear_requests()
        _serve_e_svitlo(aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "esvitlo_account"

    async def test_failed_accounts_request_aborts(self, hass, aioclient_mock):
        """A failed request for the accounts is a connection error, not no accounts."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
        aioclient_mock.post(E_SVITLO_ACCOUNTS_URL, exc=ClientError())

        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "e_svitlo_connection_error"

    async def test_user_without_accounts_aborts(self, hass, aioclient_mock):
        """A user whose list of accounts is empty gets no_accounts_found."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
        aioclient_mock.post(E_SVITLO_ACCOUNTS_URL, json={"data": {"lst_ls": []}})

        result = await _start_e_svitlo_flow(hass, aioclient_mock)
        result = await _configure(hass, result, E_SVITLO_CREDENTIALS)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "no_accounts_found"


class TestESvitloReauth:
    """After E-Svitlo refuses the login, the user enters the current one."""

    async def _start(self, hass) -> tuple[MockConfigEntry, dict]:
        """Add an E-Svitlo entry, and start its reauthentication."""
        entry = _add_entry(hass, E_SVITLO_ACCOUNT_101)
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        assert result["description_placeholders"]["esvitlo_url"] == E_SVITLO_SITE
        return entry, result

    async def test_form_suggests_the_username_of_the_entry(self, hass):
        """The form shows the username of the entry, and never its password."""
        _, result = await self._start(hass)

        assert _suggested(result, "username") == E_SVITLO_ACCOUNT_101["username"]
        assert _suggested(result, "password") is None

    async def test_current_login_updates_the_entry(self, hass, aioclient_mock):
        """A login that opens the account of the entry goes into the entry."""
        _serve_e_svitlo(aioclient_mock)
        entry, result = await self._start(hass)

        result = await _configure(hass, result, E_SVITLO_NEW_LOGIN)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data == {**E_SVITLO_ACCOUNT_101, **E_SVITLO_NEW_LOGIN}

    async def test_refused_login_shows_invalid_auth(self, hass, aioclient_mock):
        """A refused login keeps the form with invalid_auth and the typed username."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": False}})
        entry, result = await self._start(hass)

        result = await _configure(
            hass, result, {**E_SVITLO_NEW_LOGIN, "username": "u2"}
        )

        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_auth"}
        assert _suggested(result, "username") == "u2"
        assert _suggested(result, "password") is None
        assert entry.data == E_SVITLO_ACCOUNT_101

    @pytest.mark.parametrize(
        "accounts_answer",
        [None, {"exc": ClientError()}],
        ids=["login_unreachable", "accounts_unreachable"],
    )
    async def test_unreachable_server_shows_cannot_connect(
        self, hass, aioclient_mock, accounts_answer
    ):
        """No answer of the server at the login or the accounts gives cannot_connect."""
        if accounts_answer is None:
            aioclient_mock.post(E_SVITLO_LOGIN_URL, exc=ClientError())
        else:
            aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
            aioclient_mock.post(E_SVITLO_ACCOUNTS_URL, **accounts_answer)
        entry, result = await self._start(hass)

        result = await _configure(hass, result, E_SVITLO_NEW_LOGIN)

        assert result["errors"] == {"base": "cannot_connect"}
        assert entry.data == E_SVITLO_ACCOUNT_101

    async def test_login_without_the_account_aborts(self, hass, aioclient_mock):
        """A login that does not open the account of the entry changes nothing."""
        aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
        aioclient_mock.post(
            E_SVITLO_ACCOUNTS_URL, json={"data": {"lst_ls": [{"a": 202}]}}
        )
        entry, result = await self._start(hass)

        result = await _configure(hass, result, E_SVITLO_NEW_LOGIN)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "wrong_account"
        assert entry.data == E_SVITLO_ACCOUNT_101
