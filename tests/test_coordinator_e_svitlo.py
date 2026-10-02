"""Tests for E-Svitlo Coordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.coordinator.e_svitlo import ESvitloCoordinator
from custom_components.svitlo_yeah.models import ESvitloProvider


@pytest.fixture
def mock_hass():
    """Mock HomeAssistant."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_entry():
    """Mock ConfigEntry."""
    entry = MagicMock()
    entry.data = {
        "address_str": "Test Addr",
        "account_id": "123",
        "username": "user",
        "password": "pass",
    }
    return entry


@pytest.fixture
def mock_provider():
    """Mock Provider."""
    return ESvitloProvider(
        user_name="user",
        password="pass",
        region_name="Sumy",
        account_id="123",
    )


@pytest.fixture
def coordinator(mock_hass, mock_entry):
    """Create coordinator with mocked client."""
    with patch(
        "custom_components.svitlo_yeah.coordinator.e_svitlo.ESvitloClient"
    ) as mock_client_cls:
        client_instance = mock_client_cls.return_value
        client_instance.get_updated_on.return_value = dt_utils.now()

        coord = ESvitloCoordinator(mock_hass, mock_entry)
        coord.client = client_instance
        # Mock base class method that requires complex hass setup
        coord.async_fetch_translations = AsyncMock()
        return coord


@pytest.mark.asyncio
async def test_update_failure(coordinator):
    """Test data update failure."""
    coordinator.translations = {}
    coordinator.client.get_disconnections = AsyncMock(return_value=None)

    # helper for async update
    await coordinator._async_update_data()
    # Should not raise, just log warning
    assert coordinator.data is None  # Or whatever default is, since update failed


@pytest.mark.parametrize("with_address", [True, False], ids=["address", "no_address"])
def test_provider_name_has_no_account(coordinator, mock_entry, with_address):
    """Neither the address nor the username of the account names the provider."""
    if not with_address:
        del mock_entry.data["address_str"]
    assert coordinator.provider_name == "E-Svitlo"


def test_region_name_in_the_language_of_the_server(coordinator):
    """The region has its translated name, and its key until the texts come."""
    assert coordinator.region_name == "sumy"
    coordinator.translations = {"component.svitlo_yeah.common.sumy": "Суми"}
    assert coordinator.region_name == "Суми"
