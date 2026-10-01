"""Pytest configuration and fixtures."""

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.yasno import YasnoApi


@pytest.fixture
def empty_yasno_region_cache(monkeypatch):
    """
    Make each Yasno setup or flow fetch the regions again.

    YasnoApi keeps the regions in a class attribute, so without this fixture
    one test gets the regions that another test served.
    """
    monkeypatch.setattr(YasnoApi, "_regions", None)


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
