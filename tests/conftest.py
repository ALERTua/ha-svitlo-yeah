"""Pytest configuration and fixtures."""

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_utils


@pytest.fixture(name="today")
def _today():
    """Create an API instance."""
    return dt_utils.as_local(dt_utils.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


@pytest.fixture(name="tomorrow")
def _tomorrow(today):
    """Create an API instance."""
    return today + timedelta(days=1)
