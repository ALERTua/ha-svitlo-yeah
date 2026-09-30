"""Tests for the config flow on a real Home Assistant (the hass fixture)."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)

KYIV_REGION_URL = DTEK_PROVIDER_URLS["kyiv_region"][0]
KYIV_REGION_KEY = "dtekjsonprovider_kyiv_region"
KYIV_GROUPS = [f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2)]

YASNO_REGION_ID = 25
YASNO_OTHER_REGION_ID = 3
YASNO_DSO_ID = 902
YASNO_KEY = f"yasnoprovider_{YASNO_REGION_ID}_{YASNO_DSO_ID}"
YASNO_PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(
    region_id=YASNO_REGION_ID, dso_id=YASNO_DSO_ID
)
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

DTEK_KYIV_REGION_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    CONF_PROVIDER: "kyiv_region",
    CONF_GROUP: "1.1",
}
YASNO_KYIV_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
    CONF_PROVIDER: YASNO_DSO_ID,
    CONF_REGION: YASNO_REGION_ID,
    CONF_GROUP: "1.1",
}


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


def _add_entry(hass, data: dict) -> MockConfigEntry:
    """Add a config entry of this integration with the given data."""
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def _no_entry_setup():
    """Create the entries without their setup: these tests cover the flow only."""
    with patch("custom_components.svitlo_yeah.async_setup_entry", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _empty_yasno_region_cache(monkeypatch):
    """Make each flow fetch the Yasno regions again."""
    monkeypatch.setattr(YasnoApi, "_regions", None)


async def _start_flow(hass, aioclient_mock) -> dict:
    """Start a new flow at the provider form, with the Yasno regions served."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=YASNO_REGIONS)
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _configure(hass, result: dict, user_input: dict) -> dict:
    """Submit the form of a flow result."""
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


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

    async def test_stale_confirm_unchecked_re_renders_form(self, hass, aioclient_mock):
        """Submitting the form without the checkbox re-shows it."""
        aioclient_mock.get(
            KYIV_REGION_URL, json=_dtek_feed(fresh=False, preset_groups=KYIV_GROUPS)
        )

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: KYIV_REGION_KEY})
        result = await _configure(hass, result, {"acknowledge": False})

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "stale_confirm"


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

    async def test_yasno_without_groups_aborts(self, hass, aioclient_mock):
        """Yasno planned outages without groups stop the flow."""
        aioclient_mock.get(YASNO_PLANNED_URL, json={})

        result = await _start_flow(hass, aioclient_mock)
        result = await _configure(hass, result, {CONF_PROVIDER: YASNO_KEY})

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "yasno_connection_error"

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
