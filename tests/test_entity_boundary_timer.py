"""Tests for boundary-timer lifecycle on entity removal."""

from unittest.mock import MagicMock

import pytest

from custom_components.svitlo_yeah.calendar import PlannedOutagesCalendar


@pytest.mark.asyncio
async def test_boundary_timer_cancelled_on_remove():
    """The scheduled boundary callback must be cancelled when the entity is removed."""
    entity = object.__new__(PlannedOutagesCalendar)
    unsubscribe = MagicMock()
    entity._unsubscribe_boundary = unsubscribe

    await entity.async_will_remove_from_hass()

    unsubscribe.assert_called_once()
    assert entity._unsubscribe_boundary is None
