"""Pytest configuration and fixtures."""

from datetime import timedelta

import pytest

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from tests.helpers import kyiv_midnight


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
    """Return the start of the current day in Kyiv, as the sources give it."""
    return kyiv_midnight()


@pytest.fixture(name="tomorrow")
def _tomorrow(today):
    """Return the start of the next day in Kyiv."""
    return today + timedelta(days=1)
