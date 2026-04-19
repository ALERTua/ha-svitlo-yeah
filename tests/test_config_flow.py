"""Tests for the DTEK JSON stale-data path in the config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.svitlo_yeah.config_flow import IntegrationConfigFlow
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    PROVIDER_TYPE_DTEK_JSON,
)

TEST_PROVIDER_KEY = "kyiv_region"
TEST_GROUPS = ["1.1", "1.2"]


@pytest.fixture(name="flow")
def _flow():
    """Build a config flow with result helpers stubbed to return dicts."""
    flow = IntegrationConfigFlow()
    flow.data = {
        CONF_PROVIDER: TEST_PROVIDER_KEY,
        CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    }
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


def _dtek_api_mock(*, success: bool, is_stale: bool, groups: list[str]):
    """Build a MagicMock standing in for DtekAPIJson with configured state."""
    api = MagicMock()
    api.fetch_data = AsyncMock(return_value=(success, is_stale))
    api.get_dtek_region_groups = MagicMock(return_value=groups)
    return api


class TestStaleConfirmRouting:
    """async_step_group should route to stale_confirm only when needed."""

    async def test_stale_shows_confirm_step(self, flow):
        """Stale DTEK data triggers the stale_confirm form."""
        api = _dtek_api_mock(success=True, is_stale=True, groups=TEST_GROUPS)

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
        api = _dtek_api_mock(success=True, is_stale=False, groups=TEST_GROUPS)

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_group()

        assert result["type"] == "form"
        assert result["step_id"] == "group"

    async def test_empty_data_aborts(self, flow):
        """With no usable data, the flow aborts as before."""
        api = _dtek_api_mock(success=False, is_stale=False, groups=[])

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
        """Acknowledging sets the flow flag and re-enters group step."""
        api = _dtek_api_mock(success=True, is_stale=True, groups=TEST_GROUPS)

        with patch(
            "custom_components.svitlo_yeah.config_flow.DtekAPIJson",
            return_value=api,
        ):
            result = await flow.async_step_stale_confirm({"acknowledge": True})

        # After acknowledgement, async_step_group is re-entered and
        # because _stale_ack is set it must NOT bounce back to stale_confirm
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
