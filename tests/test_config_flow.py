"""Tests for the config flow on a real Home Assistant (the hass fixture)."""

from datetime import UTC, datetime
from unittest.mock import patch

import probatio as vol
import pytest
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    NAME,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import (
    DTEK_KYIV_REGION_1_1,
    REMOVED_PROVIDER_ENTRIES,
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


async def _choose_group_method(hass, result: dict) -> dict:
    """Choose «By group» in the menu that a Yasno provider shows."""
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "yasno_method"
    return await _configure(hass, result, {"next_step_id": "group"})


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
        # The text under the field links the page of this provider only
        assert result["description_placeholders"] == {
            "url": "https://www.dtek-krem.com.ua/ua/shutdowns"
        }

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

    # Both formats that the freshness check reads must also give the shown time
    @pytest.mark.parametrize(
        "update",
        ["19.02.2026 15:04", "15:04 19.02.2026"],
        ids=["date_first", "time_first"],
    )
    async def test_stale_confirm_shows_the_update_time(
        self, hass, aioclient_mock, update
    ):
        """The warning shows when the source last updated, also after an error."""
        feed = _dtek_feed(fresh=False, preset_groups=KYIV_GROUPS)
        feed["fact"]["update"] = update
        aioclient_mock.get(KYIV_REGION_URL, json=feed)

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})

        # The hass fixture runs in US/Pacific, and the source gives the Kyiv time
        assert result["description_placeholders"] == {"updated": "19.02.2026 15:04"}

        result = await _configure(hass, result, {"acknowledge": False})

        assert result["description_placeholders"] == {"updated": "19.02.2026 15:04"}


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
        result = await _choose_group_method(hass, result)
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == ["1.1", "1.2"]
        assert result["description_placeholders"] == {
            "url": "https://static.yasno.ua/kyiv/outages"
        }

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
        result = await _choose_group_method(hass, result)

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
        result = await _choose_group_method(hass, result)

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
        result = await _choose_group_method(hass, result)
        assert result["step_id"] == "group"
        assert _select_options(result, CONF_GROUP) == ["1.1", "3.1"]
        assert _default(result, CONF_GROUP) is None

        result = await _configure(hass, result, {CONF_GROUP: "3.1"})

        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_GROUP] == "3.1"

    @pytest.mark.parametrize(
        ("data", "provider"),
        list(REMOVED_PROVIDER_ENTRIES.values()),
        ids=list(REMOVED_PROVIDER_ENTRIES),
    )
    async def test_entry_of_a_removed_provider_stops_at_once(
        self, hass, aioclient_mock, data, provider
    ):
        """
        Reconfigure of an entry of a removed provider stops, and names the provider.

        The entry keeps its data, and the flow asks no source.
        """
        entry = _add_entry(hass, data)

        result = await entry.start_reconfigure_flow(hass)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "provider_removed"
        assert result["description_placeholders"] == {
            "provider": provider,
            "integration": "Svitlo Yeah!",
        }
        assert entry.data == data
        assert aioclient_mock.call_count == 0

    @pytest.mark.parametrize("provider_type", ["other", None], ids=["other", "none"])
    async def test_entry_of_an_unknown_provider_type_stops_at_once(
        self, hass, aioclient_mock, provider_type
    ):
        """Reconfigure of an entry of an unknown provider type stops, and names it."""
        data = {**YASNO_KYIV_1_1, CONF_PROVIDER_TYPE: provider_type}
        entry = _add_entry(hass, data)

        result = await entry.start_reconfigure_flow(hass)

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "unknown_provider_type"
        assert result["description_placeholders"] == {
            "provider_type": str(provider_type)
        }
        assert entry.data == data
        assert aioclient_mock.call_count == 0


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
        result = await _choose_group_method(hass, result)
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
        result = await _choose_group_method(hass, result)
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
