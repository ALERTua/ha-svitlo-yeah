"""HTML-based DTEK API implementation using original website scraping."""

from __future__ import annotations

import logging

import aiohttp

from ...const import DEBUG, DTEK_ENDPOINT, DTEK_HEADERS
from .base import DtekAPIBase, _debug_data, _extract_data

LOGGER = logging.getLogger(__name__)


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
