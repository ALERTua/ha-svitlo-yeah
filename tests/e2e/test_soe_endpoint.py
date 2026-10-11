"""End-to-end test against the real schedule of SOE (real network access)."""

import re
from unittest.mock import MagicMock, patch

import aiohttp

from custom_components.svitlo_yeah.api.soe import SoeClient

GROUP_FORMAT = re.compile(r"^[1-6]\.[12]$")


async def test_schedule_real_endpoint():
    """
    The site of SOE lists the 12 sub-queues in the format that the integration knows.

    A change of the path or of the fields would keep each SOE entry on its last
    answer, and a new entry could not pick a sub-queue. Only the real site shows it.
    """
    session = aiohttp.ClientSession()
    try:
        with patch(
            "custom_components.svitlo_yeah.api.soe.async_get_clientsession",
            return_value=session,
        ):
            client = SoeClient(MagicMock())
            assert await client.fetch_data() is True, "the site gave no usable answer"

            groups = client.get_groups()
            assert len(groups) == 12, groups
            assert [g for g in groups if not GROUP_FORMAT.match(g)] == []
            for group in groups:
                client.group = group
                assert client.get_updated_on() is not None, group
    finally:
        await session.close()
