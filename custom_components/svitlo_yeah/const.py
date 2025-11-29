"""Constants for the Svitlo Yeah integration."""

from __future__ import annotations

from typing import Final

from .models.providers import DTEKJsonProvider

# Do not commit as True
DEBUG: Final = False

DOMAIN: Final = "svitlo_yeah"
NAME: Final = "Svitlo Yeah | Світло Є"

# Configuration option
CONF_REGION: Final = "region"
CONF_PROVIDER: Final = "provider"
CONF_GROUP: Final = "group"
CONF_PROVIDER_TYPE: Final = "provider_type"

# Provider types
PROVIDER_TYPE_YASNO: Final = "yasno"
PROVIDER_TYPE_DTEK_JSON: Final = "dtek_json"

# Provider name simplification
PROVIDER_DTEK_FULL: Final = "ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ"
PROVIDER_DTEK_SHORT: Final = "ДТЕК"

# Costants
if DEBUG:
    UPDATE_INTERVAL: Final = 1
else:
    UPDATE_INTERVAL: Final = 15
DTEK_FRESH_DATA_DAYS: Final = 2

# API Endpoints
YASNO_REGIONS_ENDPOINT: Final = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/regions"
)
YASNO_PLANNED_OUTAGES_ENDPOINT: Final = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"

# API Block names
BLOCK_KEY_STATUS: Final = "status"

# Translation Keys
DEVICE_NAME_YASNO_TRANSLATION_KEY = "device_name_yasno"
DEVICE_NAME_DTEK_TRANSLATION_KEY = "device_name_dtek"
DEVICE_MANUFACTURER = NAME
PROVIDER_TO_DEVICE_NAME_MAP: Final = {
    PROVIDER_TYPE_YASNO: DEVICE_NAME_YASNO_TRANSLATION_KEY,
    PROVIDER_TYPE_DTEK_JSON: DEVICE_NAME_DTEK_TRANSLATION_KEY,
}
TRANSLATION_KEY_EVENT_PLANNED_OUTAGE: Final = (
    "component.svitlo_yeah.common.event_name_planned_outage"
)
TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE: Final = (
    "component.svitlo_yeah.common.event_name_emergency_outage"
)

EVENT_DATA_CHANGED: Final = f"{DOMAIN}_data_changed"

DTEK_PROVIDER_URLS: dict[DTEKJsonProvider, list[str]] = {
    DTEKJsonProvider.KYIV_REGION: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/kyiv-region.json",
    ],
    DTEKJsonProvider.DNIPRO: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/dnipro.json",
    ],
    DTEKJsonProvider.ODESA: [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/odesa.json",
    ],
    DTEKJsonProvider.KHMELNYTSKYI: [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Khmelnytskoblenerho.json",
    ],
    DTEKJsonProvider.IVANO_FRANKIVSK: [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Prykarpattiaoblenerho.json",
    ],
    DTEKJsonProvider.UZHHOROD: [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Zakarpattiaoblenerho.json",
    ],
    DTEKJsonProvider.LVIV: [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Lvivoblenerho.json",
    ],
}
