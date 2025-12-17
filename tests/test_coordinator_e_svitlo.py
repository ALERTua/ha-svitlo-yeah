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
        password="pass",  # noqa: S106
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


def test_provider_name_with_address(coordinator):
    """Test provider_name returns address."""
    assert coordinator.provider_name == "Test Addr"


def test_provider_name_fallback(coordinator, mock_entry):
    """Test provider_name fallback."""
    mock_entry.data = {}
    assert coordinator.provider_name == "E-Svitlo (user)"
