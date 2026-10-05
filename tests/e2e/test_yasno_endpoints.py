"""End-to-end tests against the real Yasno API (real network access)."""

import datetime
import re
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.util import dt as dt_utils

from custom_components.svitlo_yeah.api.yasno import YasnoApi

GROUP_FORMAT = re.compile(r"^\d+\.\d+$")


async def test_planned_outages_real_endpoints(monkeypatch):
    """
    Each Yasno provider lists its groups in the format that the integration knows.

    A change of the Yasno format would make is_group_listed False for each
    entry: each Yasno user would get a false repair issue and an Electricity
    sensor with no value. Only the real API shows such a change.
    """
    monkeypatch.setattr(YasnoApi, "_regions", None)
    session = aiohttp.ClientSession()
    try:
        with patch(
            "custom_components.svitlo_yeah.api.yasno.async_get_clientsession",
            return_value=session,
        ):
            await YasnoApi(MagicMock()).fetch_yasno_regions()
            regions = YasnoApi._regions
            assert regions, "the Yasno API gave no regions"

            start = dt_utils.now()
            end = start + datetime.timedelta(days=2)
            providers_with_groups = 0
            for region in regions:
                for provider in region.dsos:
                    api = YasnoApi(
                        MagicMock(), region_id=region.id, provider_id=provider.id
                    )
                    await api.fetch_planned_outage_data()
                    groups = api.get_yasno_groups()
                    if not groups:
                        continue
                    providers_with_groups += 1

                    name = f"{region.name} / {provider.name}"
                    wrong = [g for g in groups if not GROUP_FORMAT.match(g)]
                    assert not wrong, f"{name}: groups in an unknown format {wrong}"
                    for group in groups:
                        api.group = group
                        assert api.is_group_listed() is True, f"{name}: {group}"
                        for event in api.get_events(start, end):
                            if event.all_day:
                                # An emergency day is an all-day event with dates.
                                assert not isinstance(event.start, datetime.datetime), (
                                    f"{name} {group}: all-day event with a time"
                                )
                            else:
                                assert event.start.tzinfo, (
                                    f"{name} {group}: naive start"
                                )
                            assert event.start < event.end, f"{name} {group}"
    finally:
        await session.close()

    if not providers_with_groups:
        pytest.skip("no Yasno provider lists groups now")
