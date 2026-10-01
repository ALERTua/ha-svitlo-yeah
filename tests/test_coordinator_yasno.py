"""The Yasno coordinator on a real Home Assistant (the hass fixture)."""

import pytest
from aiohttp import ClientConnectionError
from homeassistant.util import dt as dt_utils
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.svitlo_yeah.api.yasno import YasnoApi
from custom_components.svitlo_yeah.const import (
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    EVENT_DATA_CHANGED,
    PROVIDER_TYPE_YASNO,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
)
from custom_components.svitlo_yeah.coordinator.yasno import YasnoCoordinator
from custom_components.svitlo_yeah.models import ConnectivityState, YasnoRegion

PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=25, dso_id=902)


def _outage_all_day_today() -> dict:
    """Build a Yasno answer with a planned outage for group 1.2 all day today."""
    today = dt_utils.as_local(dt_utils.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return {
        "1.2": {
            "today": {
                "slots": [{"start": 0, "end": 1440, "type": "Definite"}],
                "date": today.isoformat(),
                "status": "ScheduleApplies",
            },
            "updatedOn": today.isoformat(),
        }
    }


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture(name="coordinator")
def _coordinator(hass, monkeypatch):
    """Build a Yasno coordinator for Kyiv, group 1.2, with the regions cached."""
    monkeypatch.setattr(
        YasnoApi,
        "_regions",
        [
            YasnoRegion.from_dict(
                {"id": 25, "value": "Київ", "dsos": [{"id": 902, "name": "ДТЕК"}]}
            )
        ],
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
            CONF_REGION: 25,
            CONF_PROVIDER: 902,
            CONF_GROUP: "1.2",
        },
    )
    entry.add_to_hass(hass)
    return YasnoCoordinator(hass, entry)


@pytest.mark.parametrize(
    "error", [ClientConnectionError(), TimeoutError()], ids=["connection", "timeout"]
)
async def test_failed_request_keeps_the_schedule(
    hass, aioclient_mock, coordinator, error
):
    """A failed request leaves the running outage and fires no change event."""
    aioclient_mock.get(PLANNED_URL, json=_outage_all_day_today())
    await coordinator._async_update_data()
    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE

    changes = async_capture_events(hass, EVENT_DATA_CHANGED)
    aioclient_mock.clear_requests()
    aioclient_mock.get(PLANNED_URL, exc=error)
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert coordinator.current_state == ConnectivityState.STATE_PLANNED_OUTAGE
    assert changes == []
