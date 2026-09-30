"""Tests for the config flow: the DTEK JSON stale-data path and the full setup."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.data_entry_flow import AbortFlow

from custom_components.svitlo_yeah.api.dtek.base import FetchResult
from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.config_flow import IntegrationConfigFlow
from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DTEK_PROVIDER_URLS,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)
from tests.helpers import fake_session

TEST_PROVIDER_KEY = "kyiv_region"
TEST_GROUPS = ["1.1", "1.2"]


def _stub_results(flow: IntegrationConfigFlow) -> IntegrationConfigFlow:
    """Stub the result helpers to return plain dicts, with no current entries."""
    flow._async_current_entries = MagicMock(return_value=[])
    flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda **kwargs: {"type": "abort", **kwargs}
    )
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
    )
    return flow


@pytest.fixture(name="flow")
def _flow():
    """Build a config flow with result helpers stubbed to return dicts."""
    flow = _stub_results(IntegrationConfigFlow())
    flow.data = {
        CONF_PROVIDER: TEST_PROVIDER_KEY,
        CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    }
    return flow


def _dtek_api_mock(*, result: FetchResult, groups: list[str]):
    """Build a MagicMock standing in for DtekAPIJson with configured state."""
    api = MagicMock()
    api.fetch_data = AsyncMock(return_value=result)
    api.get_dtek_region_groups = MagicMock(return_value=groups)
    api.get_dtek_region_group_labels = MagicMock(return_value={})
    return api


class TestStaleConfirmRouting:
    """async_step_group should route to stale_confirm only when needed."""

    async def test_stale_shows_confirm_step(self, flow):
        """Stale DTEK data triggers the stale_confirm form."""
        api = _dtek_api_mock(result=FetchResult.STALE, groups=TEST_GROUPS)

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_group()

        api.fetch_data.assert_awaited_once_with(allow_stale_data=True)
        assert result["type"] == "form"
        assert result["step_id"] == "stale_confirm"

    async def test_fresh_skips_stale_confirm(self, flow):
        """Fresh DTEK data routes directly to the group selection form."""
        api = _dtek_api_mock(result=FetchResult.FRESH, groups=TEST_GROUPS)

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_group()

        assert result["type"] == "form"
        assert result["step_id"] == "group"

    async def test_unavailable_data_aborts(self, flow):
        """With no source that answered, the flow aborts as unavailable."""
        api = _dtek_api_mock(result=FetchResult.UNAVAILABLE, groups=[])

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_group()

        assert result["type"] == "abort"
        assert result["reason"] == "dtek_json_unavailable"

    @pytest.mark.parametrize("fetch_result", [FetchResult.FRESH, FetchResult.STALE])
    async def test_data_without_groups_aborts_as_empty(self, flow, fetch_result):
        """A source that answered without groups is not a connection problem."""
        api = _dtek_api_mock(result=fetch_result, groups=[])

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_group()

        assert result["type"] == "abort"
        assert result["reason"] == "dtek_json_empty_data"

    async def test_stale_confirm_unchecked_re_renders_form(self, flow):
        """Submitting the form without the checkbox re-shows it."""
        result = await flow.async_step_stale_confirm({"acknowledge": False})

        assert result["type"] == "form"
        assert result["step_id"] == "stale_confirm"
        assert "_stale_ack" not in flow.data

    async def test_stale_confirm_checked_proceeds_to_group(self, flow):
        """Acknowledging sets the flow flag and re-enters the group step."""
        api = _dtek_api_mock(result=FetchResult.STALE, groups=TEST_GROUPS)

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_stale_confirm({"acknowledge": True})

        # _stale_ack is set, so the re-entered group step must NOT bounce back
        assert result["type"] == "form"
        assert result["step_id"] == "group"
        assert flow.data.get("_stale_ack") is True


class TestStaleAckNotPersisted:
    """The _stale_ack flag must not leak into the created config entry."""

    async def test_stale_ack_stripped_on_entry_creation(self, flow):
        """Finalizing the group step pops the flow-local _stale_ack flag."""
        flow.data["_stale_ack"] = True

        result = await flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "create_entry"
        assert "_stale_ack" not in result["data"]
        assert result["data"][CONF_GROUP] == "1.1"


KYIV_REGION_URL = DTEK_PROVIDER_URLS["kyiv_region"][0]
KYIV_REGION_KEY = "dtekjsonprovider_kyiv_region"
KYIV_GROUPS = [f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2)]

YASNO_REGION_ID = 25
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
]


def _kyiv_region_feed(*, with_preset: bool) -> dict:
    """Mirror kyiv-region.json while DTEK publishes no outages: an empty fact."""
    feed = {"fact": {"data": [], "update": "19.02.2026 15:04", "today": 1790715600}}
    if with_preset:
        feed["preset"] = {
            "data": {f"GPV{group}": {"1": {"1": "yes"}} for group in KYIV_GROUPS}
        }
    return feed


@contextmanager
def _serve(routes: dict):
    """Answer each provider HTTP request of the flow from ``routes``."""
    session = fake_session(routes)
    with (
        patch(
            "custom_components.svitlo_yeah.api.dtek.json.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.svitlo_yeah.api.yasno.async_get_clientsession",
            return_value=session,
        ),
    ):
        yield


def _select_options(result: dict, field: str) -> list:
    """Return the options of a select field in a form result."""
    return result["data_schema"].schema[field].config["options"]


def _default(result: dict, field: str):
    """Return the default value of a field in a form result."""
    return next(k for k in result["data_schema"].schema if k == field).default()


@pytest.fixture(name="new_flow")
def _new_flow(monkeypatch):
    """Build a config flow at its first step, with an empty Yasno region cache."""
    monkeypatch.setattr(YasnoApi, "_regions", None)
    flow = _stub_results(IntegrationConfigFlow())
    flow.hass = MagicMock()
    return flow


class TestSetupWithRealProviderApis:
    """Walk the whole config flow with the real provider APIs and fake HTTP."""

    async def test_dtek_kyiv_region_with_empty_fact_schedule(self, new_flow):
        """An empty fact schedule still offers the preset groups after consent."""
        routes = {
            YASNO_REGIONS_ENDPOINT: YASNO_REGIONS,
            KYIV_REGION_URL: _kyiv_region_feed(with_preset=True),
        }
        with _serve(routes):
            result = await new_flow.async_step_user()
            providers = [o["value"] for o in _select_options(result, CONF_PROVIDER)]
            assert KYIV_REGION_KEY in providers

            result = await new_flow.async_step_user({CONF_PROVIDER: KYIV_REGION_KEY})
            assert result["step_id"] == "stale_confirm"

            result = await new_flow.async_step_stale_confirm({"acknowledge": True})
            assert result["step_id"] == "group"
            assert _select_options(result, CONF_GROUP) == KYIV_GROUPS

            result = await new_flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "create_entry"
        assert result["data"] == {
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
            CONF_PROVIDER: "kyiv_region",
            CONF_GROUP: "1.1",
        }

    async def test_dtek_dnipro_labels_the_cek_groups(self, new_flow):
        """A group that the source names without its number gets a label."""
        feed = {
            "fact": {"data": [], "update": "19.02.2026 15:04", "today": 1790715600},
            "preset": {
                "data": {
                    "GPV1.1": {"1": {"1": "yes"}},
                    "GPV1001.1": {"1": {"1": "yes"}},
                },
                "sch_names": {"GPV1.1": "Черга 1.1", "GPV1001.1": "ЦЕК 1.1"},
            },
        }
        routes = {
            YASNO_REGIONS_ENDPOINT: YASNO_REGIONS,
            DTEK_PROVIDER_URLS["dnipro"][0]: feed,
        }
        with _serve(routes):
            await new_flow.async_step_user()
            await new_flow.async_step_user({CONF_PROVIDER: "dtekjsonprovider_dnipro"})
            result = await new_flow.async_step_stale_confirm({"acknowledge": True})
            assert _select_options(result, CONF_GROUP) == [
                {"value": "1.1", "label": "1.1"},
                {"value": "1001.1", "label": "ЦЕК 1.1 (1001.1)"},
            ]

            result = await new_flow.async_step_group({CONF_GROUP: "1001.1"})

        assert result["data"][CONF_GROUP] == "1001.1"

    async def test_dtek_source_without_groups_aborts(self, new_flow):
        """An empty fact schedule without a preset schedule has no groups."""
        routes = {
            YASNO_REGIONS_ENDPOINT: YASNO_REGIONS,
            KYIV_REGION_URL: _kyiv_region_feed(with_preset=False),
        }
        with _serve(routes):
            await new_flow.async_step_user()
            result = await new_flow.async_step_user({CONF_PROVIDER: KYIV_REGION_KEY})

        assert result["type"] == "abort"
        assert result["reason"] == "dtek_json_empty_data"

    async def test_yasno_kyiv(self, new_flow):
        """Yasno offers the groups of its planned outages and stores the region."""
        routes = {
            YASNO_REGIONS_ENDPOINT: YASNO_REGIONS,
            YASNO_PLANNED_URL: {"1.1": {}, "1.2": {}},
        }
        with _serve(routes):
            result = await new_flow.async_step_user()
            providers = [o["value"] for o in _select_options(result, CONF_PROVIDER)]
            assert YASNO_KEY in providers

            result = await new_flow.async_step_user({CONF_PROVIDER: YASNO_KEY})
            assert result["step_id"] == "group"
            assert _select_options(result, CONF_GROUP) == ["1.1", "1.2"]

            result = await new_flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "create_entry"
        assert result["data"] == {
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
            CONF_PROVIDER: YASNO_DSO_ID,
            CONF_REGION: YASNO_REGION_ID,
            CONF_GROUP: "1.1",
        }

    async def test_yasno_without_groups_aborts(self, new_flow):
        """Yasno planned outages without groups stop the flow."""
        routes = {YASNO_REGIONS_ENDPOINT: YASNO_REGIONS, YASNO_PLANNED_URL: {}}
        with _serve(routes):
            await new_flow.async_step_user()
            result = await new_flow.async_step_user({CONF_PROVIDER: YASNO_KEY})

        assert result["type"] == "abort"
        assert result["reason"] == "yasno_connection_error"


def _reconfigure_flow(data: dict) -> IntegrationConfigFlow:
    """
    Build a reconfigure flow for an entry with the given data.

    The flow starts with the entry data, as async_step_reconfigure leaves it,
    so a test can call async_step_group directly.
    """
    flow = _stub_results(IntegrationConfigFlow())
    flow.data = dict(data)
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_RECONFIGURE, "entry_id": "test_entry"}
    entry = MagicMock()
    entry.data = data
    entry.options = {}
    flow._get_reconfigure_entry = MagicMock(return_value=entry)
    flow.async_update_and_abort = MagicMock(
        side_effect=lambda entry, **kwargs: {"type": "abort", "entry": entry, **kwargs}
    )
    return flow


class TestReconfigureGroup:
    """Reconfigure lets the user pick another group for an existing entry."""

    async def test_dtek_kyiv_region(self):
        """The group form preselects the current group and saves the new one."""
        flow = _reconfigure_flow(
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
                CONF_PROVIDER: "kyiv_region",
                CONF_GROUP: "1.1",
            }
        )
        routes = {KYIV_REGION_URL: _kyiv_region_feed(with_preset=True)}
        with _serve(routes):
            result = await flow.async_step_reconfigure()
            assert result["step_id"] == "stale_confirm"

            result = await flow.async_step_stale_confirm({"acknowledge": True})
            assert result["step_id"] == "group"
            assert _select_options(result, CONF_GROUP) == KYIV_GROUPS
            assert _default(result, CONF_GROUP) == "1.1"

            result = await flow.async_step_group({CONF_GROUP: "2.2"})

        flow.async_update_and_abort.assert_called_once_with(
            flow._get_reconfigure_entry(),
            data_updates={CONF_GROUP: "2.2"},
            reason="reconfigure_successful",
        )
        flow.async_create_entry.assert_not_called()

    async def test_yasno_group_that_the_source_lacks(self, monkeypatch):
        """A group that the source lacks is not preselected."""
        monkeypatch.setattr(YasnoApi, "_regions", None)
        flow = _reconfigure_flow(
            {
                CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
                CONF_PROVIDER: YASNO_DSO_ID,
                CONF_REGION: YASNO_REGION_ID,
                CONF_GROUP: "1.2",
            }
        )
        routes = {YASNO_PLANNED_URL: {"1.1": {}, "3.1": {}}}
        with _serve(routes):
            result = await flow.async_step_reconfigure()
            assert result["step_id"] == "group"
            assert _select_options(result, CONF_GROUP) == ["1.1", "3.1"]
            assert _default(result, CONF_GROUP) is None

            result = await flow.async_step_group({CONF_GROUP: "3.1"})

        flow.async_update_and_abort.assert_called_once_with(
            flow._get_reconfigure_entry(),
            data_updates={CONF_GROUP: "3.1"},
            reason="reconfigure_successful",
        )

    async def test_e_svitlo_stops_at_once(self):
        """E-Svitlo takes the group from the account, so reconfigure stops."""
        flow = _reconfigure_flow(
            {CONF_PROVIDER_TYPE: PROVIDER_TYPE_E_SVITLO, CONF_ACCOUNT_ID: "1"}
        )

        result = await flow.async_step_reconfigure()

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_e_svitlo"
        flow.async_update_and_abort.assert_not_called()


def _existing_entry(entry_id: str, data: dict) -> MagicMock:
    """Build a current config entry with the given data and no options."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = data
    entry.options = {}
    return entry


DTEK_KYIV_REGION_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    CONF_PROVIDER: TEST_PROVIDER_KEY,
    CONF_GROUP: "1.1",
}
YASNO_KYIV_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
    CONF_PROVIDER: YASNO_DSO_ID,
    CONF_REGION: YASNO_REGION_ID,
    CONF_GROUP: "1.1",
}


class TestDuplicateGroup:
    """The integration keeps one entry for each provider and group."""

    async def test_same_provider_and_group_aborts(self, flow):
        """A second entry for the same DTEK provider and group aborts."""
        flow._async_current_entries.return_value = [
            _existing_entry("other", DTEK_KYIV_REGION_1_1)
        ]

        with pytest.raises(AbortFlow) as err:
            await flow.async_step_group({CONF_GROUP: "1.1"})

        assert err.value.reason == "already_configured"

    async def test_other_group_creates_the_entry(self, flow):
        """Another group of the same provider is a new entry."""
        flow._async_current_entries.return_value = [
            _existing_entry("other", DTEK_KYIV_REGION_1_1)
        ]

        result = await flow.async_step_group({CONF_GROUP: "1.2"})

        assert result["type"] == "create_entry"

    async def test_same_group_of_another_dtek_provider_creates_the_entry(self, flow):
        """The same group of another DTEK provider is a new entry."""
        flow._async_current_entries.return_value = [
            _existing_entry("other", {**DTEK_KYIV_REGION_1_1, CONF_PROVIDER: "odesa"})
        ]

        result = await flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "create_entry"

    async def test_yasno_group_of_another_region_creates_the_entry(self, flow):
        """The same Yasno group in another region is a new entry."""
        flow.data = {**YASNO_KYIV_1_1, CONF_REGION: 3}
        flow.data.pop(CONF_GROUP)
        flow._async_current_entries.return_value = [
            _existing_entry("other", YASNO_KYIV_1_1)
        ]

        result = await flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "create_entry"

    async def test_reconfigure_to_the_group_of_another_entry_aborts(self):
        """Reconfigure does not move an entry onto the group of another entry."""
        flow = _reconfigure_flow({**DTEK_KYIV_REGION_1_1, CONF_GROUP: "2.2"})
        flow._async_current_entries.return_value = [
            _existing_entry("other", DTEK_KYIV_REGION_1_1)
        ]

        with pytest.raises(AbortFlow) as err:
            await flow.async_step_group({CONF_GROUP: "1.1"})

        assert err.value.reason == "already_configured"
        flow.async_update_and_abort.assert_not_called()

    async def test_reconfigure_to_its_own_group_changes_nothing(self):
        """Reconfigure to the current group of the entry changes nothing."""
        flow = _reconfigure_flow(DTEK_KYIV_REGION_1_1)
        flow._async_current_entries.return_value = [
            _existing_entry("test_entry", DTEK_KYIV_REGION_1_1)
        ]

        result = await flow.async_step_group({CONF_GROUP: "1.1"})

        assert result["type"] == "abort"
        assert result["reason"] == "reconfigure_unchanged"
        flow.async_update_and_abort.assert_not_called()
