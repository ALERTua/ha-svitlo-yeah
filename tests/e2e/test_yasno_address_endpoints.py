"""End-to-end tests of the address search of Yasno, with public addresses."""

import re
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from custom_components.svitlo_yeah.api.yasno import (
    AddressResult,
    YasnoApi,
    exact_matches,
)
from custom_components.svitlo_yeah.models import YasnoAddress

GROUP_FORMAT = re.compile(r"^\d+\.\d+$")

# Public addresses: a building on a central street, never the address of a person.
# Yasno can move a house to another group, so the tests check the shape of the
# answers, not a fixed group.
ADDRESSES = [
    pytest.param(25, 902, YasnoAddress(street="вул. Хрещатик", house="36"), id="kyiv"),
    pytest.param(
        3,
        301,
        YasnoAddress(street="вул. Грушевського Михайла", house="1", city="м. Дніпро"),
        id="dnipro_with_a_city",
    ),
]


@pytest.fixture
async def real_session(monkeypatch):
    """Give the Yasno client a real session, and an empty cache of the regions."""
    monkeypatch.setattr(YasnoApi, "_regions", None)
    session = aiohttp.ClientSession()
    try:
        with patch(
            "custom_components.svitlo_yeah.api.yasno.async_get_clientsession",
            return_value=session,
        ):
            yield session
    finally:
        await session.close()


@pytest.mark.usefixtures("real_session")
@pytest.mark.parametrize(("region_id", "provider_id", "address"), ADDRESSES)
async def test_public_address_gives_a_listed_group(region_id, provider_id, address):
    """
    The names of a public address give a group that the schedule of Yasno lists.

    The weekly check of each entry with an address asks the same requests. A change
    of their answers would give each such entry Unknown or Not found, and then a
    false repair issue. Only the real API shows such a change.
    """
    api = YasnoApi(MagicMock(), region_id=region_id, provider_id=provider_id)

    result, group = await api.resolve_address(address)

    assert result is AddressResult.FOUND, result
    assert group is not None
    assert GROUP_FORMAT.match(group), group
    assert await api.fetch_planned_outage_data()
    assert group in api.get_yasno_groups()


@pytest.mark.usefixtures("real_session")
@pytest.mark.parametrize(("region_id", "provider_id", "address"), ADDRESSES)
async def test_houses_of_a_public_street_have_its_house(
    region_id, provider_id, address
):
    """
    The list of all houses of the street, which the config flow shows, has the house.

    The flow asks one query for each digit, because Yasno gives at most 20 houses
    for one query. A change of that limit or of the search would hide houses.
    """
    api = YasnoApi(MagicMock(), region_id=region_id, provider_id=provider_id)
    city_id = None
    if address.city is not None:
        cities = exact_matches(
            await api.search_cities(address.city) or [], address.city
        )
        assert len(cities) == 1, cities
        city_id = cities[0].id
    streets = exact_matches(
        await api.search_streets(address.street, city_id) or [], address.street
    )
    assert len(streets) == 1, streets

    houses = await api.all_houses(streets[0].id, city_id)

    assert houses
    assert address.house in [house.value for house in houses]


@pytest.mark.usefixtures("real_session")
async def test_house_that_the_street_lacks_is_not_found():
    """A number that the street lacks is Not found, so it counts toward the repair."""
    api = YasnoApi(MagicMock(), region_id=25, provider_id=902)

    result, group = await api.resolve_address(
        YasnoAddress(street="вул. Хрещатик", house="9999")
    )

    assert result is AddressResult.NOT_FOUND
    assert group is None
