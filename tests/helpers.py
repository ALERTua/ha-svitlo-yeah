"""Shared helpers that fake the aiohttp responses of the provider sources."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientError

from custom_components.svitlo_yeah.const import (
    CONF_ACCOUNT_ID,
    CONF_ADDRESS_STR,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DTEK_PROVIDER_URLS,
    E_SVITLO_SUMY_BASE_URL,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
    TZ_UA,
    YASNO_PLANNED_OUTAGES_ENDPOINT,
    YASNO_REGIONS_ENDPOINT,
)

if TYPE_CHECKING:
    from custom_components.svitlo_yeah.api.dtek.json import DtekAPIJson

# One entry of each provider, and the URLs that its source answers on.
# aioclient_mock serves them in the tests that set up a real entry.

KYIV_REGION_URLS = DTEK_PROVIDER_URLS["kyiv_region"]
DTEK_KYIV_REGION_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_DTEK_JSON,
    CONF_PROVIDER: "kyiv_region",
    CONF_GROUP: "1.1",
}

YASNO_KYIV_1_1 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_YASNO,
    CONF_REGION: 25,
    CONF_PROVIDER: 902,
    CONF_GROUP: "1.1",
}
YASNO_PLANNED_URL = YASNO_PLANNED_OUTAGES_ENDPOINT.format(region_id=25, dso_id=902)
YASNO_KYIV = {
    "id": 25,
    "value": "Київ",
    "dsos": [{"id": 902, "name": "ПРАТ «ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ»"}],
}

E_SVITLO_ACCOUNT_101 = {
    CONF_PROVIDER_TYPE: PROVIDER_TYPE_E_SVITLO,
    CONF_PROVIDER: "sumy",
    "username": "user",
    "password": "secret",
    CONF_ACCOUNT_ID: "101",
    CONF_ADDRESS_STR: "Суми, вул. Перша, 1",
}
E_SVITLO_LOGIN_URL = E_SVITLO_SUMY_BASE_URL + "api_main/login_api.json"
E_SVITLO_ACCOUNTS_URL = E_SVITLO_SUMY_BASE_URL + "api_main_reg/short_list_ls_api.json"
E_SVITLO_DETAILS_URL = E_SVITLO_SUMY_BASE_URL + "/api_main_reg/all_details_ls_api.json"
E_SVITLO_DISCONNECTIONS_URL = (
    E_SVITLO_SUMY_BASE_URL + "api_main/get_user_disconnections_image_api.json"
)


def kyiv_midnight() -> datetime:
    """Return the start of the current day in Kyiv: the sources give their days so."""
    return datetime.now(TZ_UA).replace(hour=0, minute=0, second=0, microsecond=0)


def fact_with_an_outage_today(update: datetime) -> dict:
    """Build a DTEK fact schedule in which group 1.1 has no power all day today."""
    today = int(kyiv_midnight().timestamp())
    day = {"GPV1.1": {str(hour): "no" for hour in range(1, 25)}, "GPV1.2": {}}
    return {
        "data": {str(today): day},
        "update": update.strftime("%d.%m.%Y %H:%M"),
        "today": today,
    }


def yasno_outage_all_day_today() -> dict:
    """Build a Yasno answer with a planned outage for group 1.1 all day today."""
    today = kyiv_midnight()
    return {
        "1.1": {
            "today": {
                "slots": [{"start": 0, "end": 1440, "type": "Definite"}],
                "date": today.isoformat(),
                "status": "ScheduleApplies",
            },
            "updatedOn": today.isoformat(),
        }
    }


def e_svitlo_outage_all_day_today() -> dict:
    """Build an E-Svitlo answer with an outage all day today, updated at 10:00."""
    today = datetime.now(TZ_UA)
    return {
        "data": {
            "date_today": today.strftime("%d.%m.%Y"),
            "lst_time_disc": [{"start_time": "00:00", "end_time": "23:59"}],
            "last_update": f"Оновлено: {today:%d.%m.%Y} 10:00",
        }
    }


def dtek_answers(aioclient_mock, fact: dict | None = None) -> None:
    """Serve the DTEK feeds with this fact schedule, or fail each request without it."""
    for url in KYIV_REGION_URLS:
        if fact is None:
            aioclient_mock.get(url, exc=ClientError())
        else:
            aioclient_mock.get(url, json={"fact": fact, "preset": {}})


def yasno_answers(aioclient_mock, *, answer: bool) -> None:
    """Serve the Yasno planned outages, or fail the request."""
    aioclient_mock.get(YASNO_REGIONS_ENDPOINT, json=[YASNO_KYIV])
    if answer:
        aioclient_mock.get(YASNO_PLANNED_URL, json=yasno_outage_all_day_today())
    else:
        aioclient_mock.get(YASNO_PLANNED_URL, exc=ClientError())


def e_svitlo_answers(aioclient_mock, *, answer: bool) -> None:
    """Serve the E-Svitlo login and disconnections, or fail the disconnections."""
    aioclient_mock.post(E_SVITLO_LOGIN_URL, json={"data": {"login": True}})
    aioclient_mock.post(E_SVITLO_DETAILS_URL, json={"data": {"lst_cherga": ["4.1"]}})
    if answer:
        aioclient_mock.post(
            E_SVITLO_DISCONNECTIONS_URL, json=e_svitlo_outage_all_day_today()
        )
    else:
        aioclient_mock.post(E_SVITLO_DISCONNECTIONS_URL, exc=ClientError())


# For each provider: the entry data, and a function that makes its source
# answer with an outage all day today, or fail
PROVIDERS = {
    "dtek": (
        DTEK_KYIV_REGION_1_1,
        lambda mock, *, answer: dtek_answers(
            mock, fact_with_an_outage_today(datetime.now(UTC)) if answer else None
        ),
    ),
    "yasno": (
        YASNO_KYIV_1_1,
        lambda mock, *, answer: yasno_answers(mock, answer=answer),
    ),
    "e_svitlo": (
        E_SVITLO_ACCOUNT_101,
        lambda mock, *, answer: e_svitlo_answers(mock, answer=answer),
    ),
}


def make_response(payload: dict | list | None = None, *, raise_error: bool = False):
    """
    Build a mocked aiohttp response that yields `payload`.

    DTEK JSON sources read the payload with ``.text()``, and Yasno reads it with
    ``.json()``, so the response answers both.
    """
    resp = AsyncMock()
    if raise_error:
        resp.raise_for_status = MagicMock(side_effect=Exception("Connection failed"))
    else:
        resp.raise_for_status = MagicMock()
    resp.text = AsyncMock(
        return_value=json.dumps(payload) if payload is not None else ""
    )
    resp.json = AsyncMock(return_value=payload)
    return resp


def get_cm(response):
    """Wrap a response in an async context manager (as ``session.get`` returns)."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def set_session_responses(api: DtekAPIJson, responses: list) -> None:
    """Configure ``api.session.get`` so each URL fetch yields the next response."""
    api.session.get = MagicMock(side_effect=[get_cm(r) for r in responses])


def fake_session(routes: dict[str, dict | list]) -> MagicMock:
    """
    Build a session whose ``get(url)`` answers with ``routes[url]``.

    A URL that is not in ``routes`` raises KeyError. A caller that does not
    catch it fails the test. ``DtekAPIJson.fetch_data`` catches each error of
    a source, so for DTEK a missing route becomes ``FetchResult.UNAVAILABLE``.
    """
    session = MagicMock()
    session.get = MagicMock(
        side_effect=lambda url, **_: get_cm(make_response(routes[url]))
    )
    return session
