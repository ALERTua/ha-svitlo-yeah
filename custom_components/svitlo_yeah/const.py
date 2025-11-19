"""Constants for the Svitlo Yeah integration."""

from typing import Final

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
PROVIDER_TYPE_DTEK_HTML: Final = "dtek_html"

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
DTEK_ENDPOINT: Final = "https://www.dtek-krem.com.ua/ua/shutdowns"
YASNO_REGIONS_ENDPOINT: Final = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/regions"
)
YASNO_PLANNED_OUTAGES_ENDPOINT: Final = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"
DTEK_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk,en-US;q=0.8,en;q=0.5,ru;q=0.3",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://www.google.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101"
    " Firefox/144.0",
}

# API Block names
BLOCK_KEY_STATUS: Final = "status"

# Translation Keys
DEVICE_NAME_YASNO_TRANSLATION_KEY = "device_name_yasno"
DEVICE_NAME_DTEK_TRANSLATION_KEY = "device_name_dtek"
DEVICE_MANUFACTURER = NAME
PROVIDER_TO_DEVICE_NAME_MAP: Final = {
    PROVIDER_TYPE_YASNO: DEVICE_NAME_YASNO_TRANSLATION_KEY,
    PROVIDER_TYPE_DTEK_JSON: DEVICE_NAME_DTEK_TRANSLATION_KEY,
    PROVIDER_TYPE_DTEK_HTML: DEVICE_NAME_DTEK_TRANSLATION_KEY,
}
TRANSLATION_KEY_PROVIDER_DTEK: Final = "provider_name_dtek"
TRANSLATION_KEY_EVENT_PLANNED_OUTAGE: Final = (
    "component.svitlo_yeah.coordinator.event_name_planned_outage"
)
TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE: Final = (
    "component.svitlo_yeah.coordinator.event_name_emergency_outage"
)

# Events
EVENT_DATA_CHANGED: Final = f"{DOMAIN}_data_changed"
