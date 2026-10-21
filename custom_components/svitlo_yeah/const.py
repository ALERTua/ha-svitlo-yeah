"""Constants for the Svitlo Yeah integration."""

from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "svitlo_yeah"
NAME: Final = "Svitlo Yeah | Світло Є"

# Configuration option
CONF_REGION: Final = "region"
CONF_PROVIDER: Final = "provider"
CONF_GROUP: Final = "group"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_ADDRESS_STR: Final = "address_str"
CONF_PROVIDER_TYPE: Final = "provider_type"
# The optional keys of a Yasno entry with an address. Each holds the text that Yasno
# writes, never an id, because Yasno changes its ids. A group entry has none of them.
# The city of the address, only in a region with cities, for example «м. Дніпро»
CONF_CITY: Final = "city"
# The street of the address, for example «вул. Сверстюка Євгена»
CONF_STREET: Final = "street"
# The house of the address, with its letter if it has one, for example «12Б»
CONF_HOUSE: Final = "house"

# Provider types
PROVIDER_TYPE_YASNO: Final = "yasno"
PROVIDER_TYPE_DTEK_JSON: Final = "dtek_json"
PROVIDER_TYPE_E_SVITLO: Final = "e-svitlo"
PROVIDER_TYPE_SOE: Final = "soe"

# Provider name simplification
PROVIDER_DTEK_FULL: Final = "ДТЕК КИЇВСЬКІ ЕЛЕКТРОМЕРЕЖІ"
PROVIDER_DTEK_SHORT: Final = "ДТЕК"

TZ_UA = ZoneInfo("Europe/Kyiv")

# Costants
UPDATE_INTERVAL: Final = 15
DTEK_FRESH_DATA_DAYS: Final = 2

# The schedules count the hours of one day; 23:59 stands for the end of a day
HOURS_IN_DAY: Final = 24
MINUTES_IN_DAY: Final = HOURS_IN_DAY * 60
LAST_HOUR: Final = 23
LAST_MINUTE: Final = 59

# API Endpoints
# The base of the address endpoints of Yasno: regions, cities, streets, houses, group
YASNO_ADDRESSES_ENDPOINT: Final = (
    "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/"
)
YASNO_REGIONS_ENDPOINT: Final = YASNO_ADDRESSES_ENDPOINT + "regions"
YASNO_PLANNED_OUTAGES_ENDPOINT: Final = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/{region_id}/dsos/{dso_id}/planned-outages"
# The Yasno page of each region, by the region id, as the page script of Yasno has them
YASNO_REGION_PAGES: Final[dict[int, str]] = {
    25: "https://static.yasno.ua/kyiv/outages",
    3: "https://static.yasno.ua/dnipro/outages",
}

# Yasno gives at most this many matches of one search of an address
YASNO_ADDRESS_MATCHES_CAP: Final = 20
# Yasno finds a street only from this many letters
YASNO_STREET_QUERY_MIN: Final = 3
# The most requests that one list of all houses of a street takes. Yasno gives at most
# YASNO_ADDRESS_MATCHES_CAP houses for one query, so the list asks one query for each
# digit, and a query that got the cap gets ten longer ones. A usual street needs 10
# requests (39 houses of Сверстюка), a long one needs more (133 houses of Велика
# Васильківська need 80). The limit ends a search that does not stop.
YASNO_HOUSE_LIST_REQUESTS_MAX: Final = 300

# API Block names
BLOCK_KEY_STATUS: Final = "status"

# Translation Keys
DEVICE_NAME_YASNO_TRANSLATION_KEY = "device_name_yasno"
DEVICE_NAME_DTEK_TRANSLATION_KEY = "device_name_dtek"
DEVICE_MANUFACTURER = NAME
DEVICE_NAME_E_SVITLO_TRANSLATION_KEY = "device_name_e_svitlo"
DEVICE_NAME_SOE_TRANSLATION_KEY = "device_name_soe"
PROVIDER_TO_DEVICE_NAME_MAP: Final = {
    PROVIDER_TYPE_YASNO: DEVICE_NAME_YASNO_TRANSLATION_KEY,
    PROVIDER_TYPE_DTEK_JSON: DEVICE_NAME_DTEK_TRANSLATION_KEY,
    PROVIDER_TYPE_E_SVITLO: DEVICE_NAME_E_SVITLO_TRANSLATION_KEY,
    PROVIDER_TYPE_SOE: DEVICE_NAME_SOE_TRANSLATION_KEY,
}


def common_translation_key(name: str) -> str:
    """Return the key of a text of the common section, for example a region name."""
    return f"component.{DOMAIN}.common.{name}"


TRANSLATION_KEY_EVENT_PLANNED_OUTAGE: Final = common_translation_key(
    "event_name_planned_outage"
)
TRANSLATION_KEY_EVENT_SCHEDULED_OUTAGE: Final = common_translation_key(
    "event_name_scheduled_outage"
)
TRANSLATION_KEY_EVENT_EMERGENCY_OUTAGE: Final = common_translation_key(
    "event_name_emergency_outage"
)
# Repair issues: the translation key, and the prefix of the issue id
ISSUE_GROUP_NOT_LISTED: Final = "group_not_listed"
ISSUE_ADDRESS_NOT_FOUND: Final = "address_not_found"

# E-Svitlo Constants
# The site of the personal cabinet, which the login forms name
E_SVITLO_URL: Final = "https://sm.e-svitlo.com.ua/"
E_SVITLO_SUMY_BASE_URL: Final = (
    "https://sm.e-svitlo.com.ua/ip_cabinet/restfull_api/improvise/"
)
E_SVITLO_ERROR_NOT_LOGGED_IN: Final = "Ви не увійшли до кабінету"

# SOE (Sumyoblenergo) Constants
# The page of the hourly schedules, where a user finds the sub-queue of an address
SOE_SITE_URL: Final = "https://www.soe.com.ua/consumers/shutdowns?tab=hourly-schedules"
# The answer that this page reads: each sub-queue with its outages of today
SOE_SCHEDULE_URL: Final = (
    "https://www.soe.com.ua/api/vidkluchenya/get_all_data_disconnections_api"
)


EVENT_DATA_CHANGED: Final = f"{DOMAIN}_data_changed"
# The check of an address gave the entry a new group. Also the prefix of the id of
# its notification, one for each entry.
EVENT_GROUP_CHANGED: Final = f"{DOMAIN}_group_changed"
TRANSLATION_KEY_GROUP_CHANGED_TITLE: Final = common_translation_key(
    "group_changed_title"
)
TRANSLATION_KEY_GROUP_CHANGED_MESSAGE: Final = common_translation_key(
    "group_changed_message"
)

DTEK_PROVIDER_URLS: dict[str, list[str]] = {
    "kyiv_region": [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/kyiv-region.json",
    ],
    "dnipro": [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/dnipro.json",
    ],
    "odesa": [
        "https://github.com/Baskerville42/outage-data-ua/raw/main/data/odesa.json",
    ],
    "khmelnytskyi": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Khmelnytskoblenerho.json",
    ],
    "ivano_frankivsk": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Prykarpattiaoblenerho.json",
    ],
    "uzhhorod": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Zakarpattiaoblenerho.json",
    ],
    "lviv": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Lvivoblenerho.json",
    ],
    "ternopil": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Ternopiloblenerho.json",
    ],
    "chernihiv": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Chernihivoblenergo.json",
    ],
    "zaporizhzhia": [
        "https://github.com/milkmann/gpv-zoe-zaporizhzhia/raw/main/data/Zaporizhzhiaoblenergo.json",
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Zaporizhzhiaoblenergo.json",
    ],
    "vinnytsia": [
        "https://github.com/olnet93/gpv-voe-vinnytsia/raw/main/data/Vinnytsiaoblenerho.json",
        "https://github.com/vn-progr/gpv-voe-vinnytsia/raw/main/data/Vinnytsiaoblenerho.json",
    ],
    "zhytomyr": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Zhytomyroblenergo.json",
    ],
    "poltava": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Poltavaoblenergo.json",
    ],
    "rivne": [
        "https://github.com/yaroslav2901/OE_OUTAGE_DATA/raw/main/data/Rivneoblenergo.json",
    ],
}
