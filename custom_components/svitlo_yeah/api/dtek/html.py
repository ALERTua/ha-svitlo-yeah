"""HTML-based DTEK API implementation using original website scraping."""

from __future__ import annotations

import json
import logging
import re

import aiohttp

from ...const import DEBUG, DTEK_ENDPOINT, DTEK_HEADERS
from .base import DtekAPIBase, _debug_data

LOGGER = logging.getLogger(__name__)


def _extract_data(html: str) -> dict | None:
    """Extract data from HTML."""
    pattern = r"DisconSchedule\.fact\s*=\s*({.*?})</script>"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        LOGGER.error(
            "Could not find DisconSchedule.fact in HTML. "
            "This may indicate that the request is being filtered as bot "
            "or the service is down. If you are sure that the service is up, "
            "please create an issue."
        )
        return None

    try:
        data = match.group(1)
        return json.loads(data)
    except json.JSONDecodeError:
        LOGGER.exception("Failed to parse DisconSchedule.fact JSON")
        return None


class DtekAPIHtml(DtekAPIBase):
    """DTEK API for original HTML scraping."""

    async def fetch_data(self) -> None:
        """Original HTML scraping logic."""
        if DEBUG:
            self.data = _debug_data()
            return

        url = DTEK_ENDPOINT
        headers = DTEK_HEADERS
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)
                )
                response.raise_for_status()
                self.data = _extract_data(await response.text())
        except Exception:
            LOGGER.exception("Error fetching data from %s", url)
            self.data = None
