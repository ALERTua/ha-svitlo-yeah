"""Config flow for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING, Any, override

import probatio as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.translation import async_get_translations

from .api.dtek.base import FetchResult
from .api.dtek.json import DtekAPIJson
from .api.e_svitlo import ESvitloClient, LoginResult
from .api.soe import SoeClient
from .api.yasno import (
    YASNO_REGIONS_ENDPOINT,
    AddressResult,
    YasnoApi,
    cyrillic_look_alikes,
    exact_matches,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_ADDRESS_STR,
    CONF_CITY,
    CONF_GROUP,
    CONF_HOUSE,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    CONF_STREET,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    E_SVITLO_URL,
    NAME,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_SOE,
    PROVIDER_TYPE_YASNO,
    SOE_SITE_URL,
    TZ_UA,
    YASNO_STREET_QUERY_MIN,
    common_translation_key,
)
from .models.providers import (
    BaseProvider,
    DTEKJsonProvider,
    ESvitloProvider,
    SoeProvider,
    YasnoProvider,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import YasnoAddressItem

LOGGER = logging.getLogger(__name__)

# The checkbox of the form that accepts outdated DTEK data
CONF_ACKNOWLEDGE = "acknowledge"

# The page where a user finds the group, for the text under the group field
GROUP_PAGE_URLS: dict[str, str] = {
    PROVIDER_TYPE_YASNO: "https://static.yasno.ua/kyiv/outages",
    PROVIDER_TYPE_DTEK_JSON: "https://www.dtek-krem.com.ua/ua/shutdowns",
    PROVIDER_TYPE_SOE: SOE_SITE_URL,
}

# The keys of an entry that name the address of a person, so no log line shows them
ADDRESS_KEYS = (CONF_CITY, CONF_STREET, CONF_HOUSE)

# The option that ends a select of matches and shows the address form again
SEARCH_AGAIN = "search_again"

# For each level of an address: the key of its "search again" text in the common
# section of the translations, and the English text for a language file without it
SEARCH_AGAIN_TEXTS: dict[str, tuple[str, str]] = {
    CONF_CITY: ("search_again_city", "My city is not in the list, search again"),
    CONF_STREET: ("search_again_street", "My street is not in the list, search again"),
    CONF_HOUSE: ("search_again_house", "My house is not in the list, search again"),
}

# The error under the field of a level, when Yasno knows no such text
NOT_FOUND_ERRORS: dict[str, str] = {
    CONF_CITY: "city_not_found",
    CONF_STREET: "street_not_found",
    CONF_HOUSE: "house_not_found",
}


def _without_address(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return the data without the address, for a log line."""
    return {key: value for key, value in data.items() if key not in ADDRESS_KEYS}


def _esvitlo_login_schema() -> vol.Schema:
    """
    Return the E-Svitlo login form.

    The autocomplete values let a password manager fill in the form.
    """
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
        }
    )


class IntegrationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svitlo Yeah."""

    # Each change of the entry data shape needs a new VERSION and async_migrate_entry
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.available_providers: dict[str, BaseProvider] = {}
        self.data: dict[str, Any] = {}
        # Whether the user accepted the outdated DTEK data in this flow
        self._stale_ack = False
        # The update time of the outdated DTEK data, which the warning shows
        self._stale_updated = ""
        # One E-Svitlo client opens one session for the whole flow
        self._client: ESvitloClient | None = None
        # The E-Svitlo accounts that the account form offers
        self._accounts: list[dict] = []
        # Whether the Yasno region of the flow has cities, which the address form asks
        self._has_cities = False
        # The texts that the user typed in the address form, for each field
        self._typed: dict[str, str] = {}
        # The match that the flow took or the user chose, for each level of the address
        self._chosen: dict[str, YasnoAddressItem] = {}
        # The matches of the select that is shown, so a chosen value maps to its match
        self._matches: list[YasnoAddressItem] = []

    def _e_svitlo_client(self, username: str, password: str) -> ESvitloClient:
        """Return the E-Svitlo client of the flow, with this login."""
        if self._client is None:
            self._client = ESvitloClient(
                self.hass, ESvitloProvider(user_name=username, password=password)
            )
        elif (self._client.user_name, self._client.pwd) != (username, password):
            self._client.use_login(username, password)
        return self._client

    @override
    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step: select provider."""
        if user_input is not None:
            LOGGER.debug("async_step_user: User input: %s", user_input)
            # The select of the form accepts only the keys of available_providers
            selected_provider = self.available_providers[user_input[CONF_PROVIDER]]

            self.data[CONF_PROVIDER_TYPE] = selected_provider.provider_type
            self.data[CONF_PROVIDER] = selected_provider.provider_id
            if selected_provider.provider_type == PROVIDER_TYPE_YASNO:
                self.data[CONF_REGION] = selected_provider.region_id
                # The user finds the schedule by an address, or knows the group
                # noinspection PyTypeChecker
                return await self.async_step_yasno_method()
            if selected_provider.provider_type == PROVIDER_TYPE_E_SVITLO:
                # For E-Svitlo, go to auth step first
                # noinspection PyTypeChecker
                return await self.async_step_esvitlo_auth()

            # noinspection PyTypeChecker
            return await self.async_step_group()

        LOGGER.debug("async_step_user: No User input yet")
        api_yasno = YasnoApi(self.hass)
        await api_yasno.fetch_yasno_regions()
        yasno_regions = api_yasno.regions or []
        LOGGER.debug("async_step_user: yasno_regions: %s", yasno_regions)
        yasno_providers: list[YasnoProvider] = []
        if yasno_regions:
            for region in yasno_regions:
                yasno_providers.extend(region.dsos)
        else:
            LOGGER.debug(
                "Failed to fetch Yasno regions. Check internet or report issue"
            )
            # Continue with DTEK only

        # Create DTEKJsonProvider instances for each available provider key
        dtek_providers = [DTEKJsonProvider(region_name=_) for _ in DTEK_PROVIDER_URLS]

        e_svitlo_provider = ESvitloProvider(user_name="sumy", password="")

        all_providers = [
            *yasno_providers,
            *dtek_providers,
            e_svitlo_provider,
            SoeProvider(),
        ]
        self.available_providers = {_.unique_key: _ for _ in all_providers}

        provider_options = [
            SelectOptionDict(
                label=_.translation_key,
                value=_.unique_key,
            )
            for _ in self.available_providers.values()
        ]

        data_schema = vol.Schema(
            {
                # default=None keeps the frontend from picking a provider for the user
                vol.Required(CONF_PROVIDER, default=None): SelectSelector(
                    SelectSelectorConfig(
                        options=provider_options,
                        translation_key="provider",
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=False,
                    ),
                ),
            },
        )

        # noinspection PyTypeChecker
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def _async_entry_title(self, data: Mapping[str, Any]) -> str:
        """
        Return the device name in the language of the server, as the entry title.

        Thus the entries differ on the page of the integration. An E-Svitlo title
        has no address, because the debug log shows the title.
        """
        names = await async_get_translations(
            self.hass, self.hass.config.language, "common", [DOMAIN]
        )
        provider_type = data.get(CONF_PROVIDER_TYPE)
        provider_id = data.get(CONF_PROVIDER)
        provider_name = names.get(
            common_translation_key(str(provider_id)), str(provider_id)
        )
        if provider_type == PROVIDER_TYPE_E_SVITLO:
            return f"{provider_name} E-Svitlo"
        if provider_type == PROVIDER_TYPE_SOE:
            provider_name = f"{provider_name} {SoeProvider().short_name}"
        if provider_type == PROVIDER_TYPE_YASNO:
            api = YasnoApi(self.hass)
            # The regions come from the class cache, if a flow or an entry got them
            await api.fetch_yasno_regions()
            region_id = data.get(CONF_REGION)
            region = api.get_region_by_id(region_id) if region_id else None
            dsos = region.dsos if region else []
            provider = next((_ for _ in dsos if _.provider_id == provider_id), None)
            if region is None or provider is None:
                # Without the Yasno regions the title has no names to show
                return NAME
            provider_name = f"{region.name} {provider.short_name}"
        return f"{provider_name} {data.get(CONF_GROUP)}"

    async def _async_save_group(self, user_input: dict) -> ConfigFlowResult:
        """
        Create the entry with the chosen group, or give the group to the entry.

        The input is the group, and for an address also the names of the address.
        """
        LOGGER.debug("async_step_group: User input: %s", _without_address(user_input))
        self.data.update(user_input)  # add group to the config

        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            if self.data[CONF_GROUP] == entry.data.get(CONF_GROUP):
                # noinspection PyTypeChecker
                return self.async_abort(reason="reconfigure_unchanged")

        # One entry for each provider and group: a second one only repeats it
        self._async_abort_entries_match(
            {
                key: self.data[key]
                for key in (
                    CONF_PROVIDER_TYPE,
                    CONF_REGION,
                    CONF_PROVIDER,
                    CONF_GROUP,
                )
                if key in self.data
            }
        )

        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            # A title of the user stays, a title of the integration follows the group
            title = entry.title
            if title in (NAME, await self._async_entry_title(entry.data)):
                title = await self._async_entry_title(self.data)
            # The update listener reloads it, and the reason keeps the integration text
            # noinspection PyTypeChecker
            return self.async_update_and_abort(
                entry,
                title=title,
                data_updates={CONF_GROUP: self.data[CONF_GROUP]},
                reason="reconfigure_successful",
            )

        LOGGER.debug(
            "async_step_group: Done. Creating entry from %s",
            _without_address(self.data),
        )
        # noinspection PyTypeChecker
        return self.async_create_entry(
            title=await self._async_entry_title(self.data), data=self.data
        )

    async def async_step_yasno_method(
        self,
        user_input: dict | None = None,  # noqa: ARG002  # the flow manager passes it
    ) -> ConfigFlowResult:
        """Let the user find the Yasno schedule by an address, or by a group."""
        # noinspection PyTypeChecker
        return self.async_show_menu(
            step_id="yasno_method", menu_options=["address", "group"]
        )

    def _address_schema(self) -> vol.Schema:
        """Return the address form: the city comes first, in a region with cities."""
        text = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        fields = {}
        if self._has_cities:
            fields[vol.Required(CONF_CITY)] = text
        fields[vol.Required(CONF_STREET)] = text
        fields[vol.Required(CONF_HOUSE)] = text
        return vol.Schema(fields)

    def _show_address_form(
        self,
        errors: dict[str, str] | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show the address form, with the typed texts as the suggested values."""
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="address",
            data_schema=self.add_suggested_values_to_schema(
                self._address_schema(), self._typed
            ),
            errors=errors,
            description_placeholders={
                "url": GROUP_PAGE_URLS[PROVIDER_TYPE_YASNO],
                **(placeholders or {}),
            },
        )

    async def _async_search_again_label(self, field: str) -> str:
        """Return the text of the option that searches again, for a level."""
        names = await async_get_translations(
            self.hass, self.hass.config.language, "common", [DOMAIN]
        )
        key, english = SEARCH_AGAIN_TEXTS[field]
        return names.get(common_translation_key(key), english)

    async def _async_show_pick_form(self, field: str) -> ConfigFlowResult:
        """
        Show a select of the matches of a level, and the option to search again.

        An exact match is preselected. Without one, no option is, because the
        frontend would take the first option for the user.
        """
        exact = exact_matches(self._matches, self._typed[field])
        options = [
            SelectOptionDict(value=str(item.id), label=item.value)
            for item in self._matches
        ]
        options.append(
            SelectOptionDict(
                value=SEARCH_AGAIN, label=await self._async_search_again_label(field)
            )
        )
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id=f"pick_{field}",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        field, default=str(exact[0].id) if len(exact) == 1 else None
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    ),
                }
            ),
            description_placeholders={
                "count": str(len(self._matches)),
                "query": self._typed[field].strip(),
            },
        )

    async def _async_take_match(
        self, field: str, items: list[YasnoAddressItem] | None
    ) -> ConfigFlowResult | None:
        """
        Take the one match of a search, or give the form that its answer needs.

        None means that the flow took the match and goes on to the next level.
        """
        errors: dict[str, str] = {}
        if items is None:
            errors["base"] = "yasno_no_answer"
        elif not items:
            errors[field] = NOT_FOUND_ERRORS[field]
        elif len(items) > 1:
            self._matches = items
            return await self._async_show_pick_form(field)
        else:
            self._chosen[field] = items[0]
            return None
        return self._show_address_form(errors)

    async def _async_search_address(self) -> ConfigFlowResult:
        """Search each level that has no match yet, and then ask for the group."""
        api = YasnoApi(
            self.hass,
            region_id=self.data[CONF_REGION],
            provider_id=self.data[CONF_PROVIDER],
        )
        if self._has_cities and CONF_CITY not in self._chosen:
            items = await api.search_cities(self._typed[CONF_CITY])
            if (step := await self._async_take_match(CONF_CITY, items)) is not None:
                return step
        city = self._chosen.get(CONF_CITY)
        city_id = city.id if city else None

        if CONF_STREET not in self._chosen:
            items = await api.search_streets(self._typed[CONF_STREET], city_id)
            if (step := await self._async_take_match(CONF_STREET, items)) is not None:
                return step
        street = self._chosen[CONF_STREET]

        if CONF_HOUSE not in self._chosen:
            # Yasno does not find a house that has a Latin letter in its number
            house_query = cyrillic_look_alikes(self._typed[CONF_HOUSE])
            items = await api.search_houses(street.id, house_query, city_id)
            if (step := await self._async_take_match(CONF_HOUSE, items)) is not None:
                return step
        # noinspection PyTypeChecker
        return await self._async_finish_address(api)

    async def _async_finish_address(self, api: YasnoApi) -> ConfigFlowResult:
        """Ask for the group of the chosen house, and save it with the address."""
        city = self._chosen.get(CONF_CITY)
        street = self._chosen[CONF_STREET]
        house = self._chosen[CONF_HOUSE]
        result, group = await api.get_address_group(
            street.id, house.id, city.id if city else None
        )
        errors: dict[str, str] = {}
        if result is AddressResult.NOT_FOUND:
            # Yasno knows the house as a match, but not as an address
            errors[CONF_HOUSE] = NOT_FOUND_ERRORS[CONF_HOUSE]
        elif group is None or not await api.fetch_planned_outage_data():
            errors["base"] = "yasno_no_answer"
        elif group not in api.get_yasno_groups():
            errors["base"] = "address_group_not_listed"
            return self._show_address_form(errors, {"group": group})
        else:
            # The names that Yasno wrote go into the entry, never its ids
            address = {CONF_STREET: street.value, CONF_HOUSE: house.value}
            if city:
                address[CONF_CITY] = city.value
            return await self._async_save_group({CONF_GROUP: group, **address})
        return self._show_address_form(errors)

    async def async_step_address(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Ask for the address, and search it at Yasno."""
        api = YasnoApi(self.hass)
        # The regions come from the class cache, if the provider step got them
        await api.fetch_yasno_regions()
        region = api.get_region_by_id(self.data[CONF_REGION])
        self._has_cities = region is not None and region.has_cities

        if user_input is None:
            return self._show_address_form()

        # The texts come back as the suggested values after an error or a new search
        self._typed = dict(user_input)
        self._chosen = {}
        errors: dict[str, str] = {}
        if len(self._typed[CONF_STREET].strip()) < YASNO_STREET_QUERY_MIN:
            errors[CONF_STREET] = "street_too_short"
            return self._show_address_form(errors)
        return await self._async_search_address()

    async def _async_pick(
        self, field: str, user_input: dict | None
    ) -> ConfigFlowResult:
        """Take the match that the user chose, or show the address form again."""
        if user_input is None:
            return await self._async_show_pick_form(field)
        if user_input[field] == SEARCH_AGAIN:
            return self._show_address_form()
        # The schema of the form that was shown accepts only the offered values
        self._chosen[field] = next(
            item for item in self._matches if str(item.id) == user_input[field]
        )
        return await self._async_search_address()

    async def async_step_pick_city(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the city among the matches of Yasno."""
        return await self._async_pick(CONF_CITY, user_input)

    async def async_step_pick_street(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the street among the matches of Yasno."""
        return await self._async_pick(CONF_STREET, user_input)

    async def async_step_pick_house(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the house among the matches of Yasno."""
        return await self._async_pick(CONF_HOUSE, user_input)

    async def async_step_group(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: select group."""
        if user_input is not None:
            return await self._async_save_group(user_input)

        LOGGER.debug("async_step_user: No User input yet")

        region_id = self.data.get(CONF_REGION)
        provider_id = self.data[CONF_PROVIDER]
        provider_type = self.data[CONF_PROVIDER_TYPE]

        groups = []
        group_labels: dict[str, str] = {}
        if provider_type == PROVIDER_TYPE_YASNO:
            if region_id and provider_id:
                temp_api = YasnoApi(
                    self.hass,
                    region_id=region_id,
                    provider_id=provider_id,
                )
                await temp_api.fetch_planned_outage_data()
                groups = temp_api.get_yasno_groups()
                if not groups:
                    # noinspection PyTypeChecker
                    return self.async_abort(
                        reason="yasno_connection_error",
                        description_placeholders={"url": YASNO_REGIONS_ENDPOINT},
                    )

        elif provider_type == PROVIDER_TYPE_DTEK_JSON and provider_id:
            urls = DTEK_PROVIDER_URLS.get(provider_id, [])
            if urls:
                temp_api = DtekAPIJson(self.hass, urls=urls, group=None)
                result = await temp_api.fetch_data(allow_stale_data=True)
                groups = temp_api.get_dtek_region_groups()
                if result is FetchResult.UNAVAILABLE or not groups:
                    # noinspection PyTypeChecker
                    return self.async_abort(
                        reason=(
                            "dtek_json_unavailable"
                            if result is FetchResult.UNAVAILABLE
                            else "dtek_json_empty_data"
                        ),
                        # One source on each line of the text
                        description_placeholders={"urls": "\n".join(urls)},
                    )
                if result is FetchResult.STALE and not self._stale_ack:
                    # The source gives the update time in Kyiv, so the warning does too
                    updated = temp_api.get_updated_on()
                    self._stale_updated = (
                        updated.astimezone(TZ_UA).strftime("%d.%m.%Y %H:%M")
                        if updated
                        else ""
                    )
                    # noinspection PyTypeChecker
                    return await self.async_step_stale_confirm()
                group_labels = temp_api.get_dtek_region_group_labels()

        elif provider_type == PROVIDER_TYPE_SOE:
            soe_api = SoeClient(self.hass)
            await soe_api.fetch_data()
            groups = soe_api.get_groups()
            if not groups:
                # noinspection PyTypeChecker
                return self.async_abort(
                    reason="soe_unavailable",
                    description_placeholders={"url": SOE_SITE_URL},
                )

        # A select takes plain values or labeled options, not a mix of both
        group_options: list[str] | list[SelectOptionDict] = groups
        if group_labels:
            group_options = [
                SelectOptionDict(value=group, label=group_labels.get(group, group))
                for group in groups
            ]

        # On reconfigure, preselect the current group while the source lists it
        current_group = self.data.get(CONF_GROUP)
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_GROUP,
                    default=current_group if current_group in groups else None,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=group_options,
                        translation_key="group",
                    ),
                ),
            },
        )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="group",
            data_schema=data_schema,
            description_placeholders={"url": GROUP_PAGE_URLS[provider_type]},
        )

    async def async_step_reconfigure(
        self,
        user_input: dict | None = None,  # noqa: ARG002  # the flow manager passes it
    ) -> ConfigFlowResult:
        """Let the user pick another group for an existing entry."""
        entry = self._get_reconfigure_entry()
        self.data = dict(entry.data)
        if self.data.get(CONF_PROVIDER_TYPE) == PROVIDER_TYPE_E_SVITLO:
            # E-Svitlo takes the group from the account, so it has no group list
            # noinspection PyTypeChecker
            return self.async_abort(reason="reconfigure_e_svitlo")
        # noinspection PyTypeChecker
        return await self.async_step_group()

    async def async_step_stale_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Warn about stale DTEK JSON data and require acknowledgement."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_ACKNOWLEDGE):
                self._stale_ack = True
                # noinspection PyTypeChecker
                return await self.async_step_group()
            errors[CONF_ACKNOWLEDGE] = "acknowledge_required"

        data_schema = vol.Schema(
            {vol.Required(CONF_ACKNOWLEDGE, default=False): bool},
        )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="stale_confirm",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"updated": self._stale_updated},
        )

    async def async_step_esvitlo_auth(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle authentication step for E-Svitlo."""
        errors = {}

        if user_input is not None:
            LOGGER.debug("async_step_esvitlo_auth: User input received")

            # Validate credentials by attempting login
            client = self._e_svitlo_client(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            login = await client.try_login()

            if login is LoginResult.OK:
                # Authentication successful, store credentials and proceed
                self.data[CONF_USERNAME] = user_input[CONF_USERNAME]
                self.data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

                # Proceed to account/group selection
                # noinspection PyTypeChecker
                return await self.async_step_esvitlo_account()

            errors["base"] = (
                "invalid_auth" if login is LoginResult.REJECTED else "cannot_connect"
            )

        # Show authentication form
        data_schema = _esvitlo_login_schema()

        # After an error, keep the typed username; the password is never sent back
        if user_input is not None:
            data_schema = self.add_suggested_values_to_schema(
                data_schema, {CONF_USERNAME: user_input[CONF_USERNAME]}
            )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="esvitlo_auth",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"esvitlo_url": E_SVITLO_URL},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002  # the flow manager passes it
    ) -> ConfigFlowResult:
        """Ask for the E-Svitlo login again, after the server refused it."""
        # noinspection PyTypeChecker
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Check the new E-Svitlo login, and keep it in the entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            client = self._e_svitlo_client(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            login = await client.try_login()
            accounts = await client.get_accounts() if login is LoginResult.OK else None
            account_id = entry.data.get(CONF_ACCOUNT_ID)
            if login is LoginResult.REJECTED:
                errors["base"] = "invalid_auth"
            elif accounts is None:
                errors["base"] = "cannot_connect"
            elif account_id is not None and all(
                str(a.get("a")) != str(account_id) for a in accounts
            ):
                # Another login must not swap the account of the entry
                # noinspection PyTypeChecker
                return self.async_abort(reason="wrong_account")
            else:
                # Only a changed login reloads, through the listener, as in Reconfigure
                # noinspection PyTypeChecker
                return self.async_update_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    reason="reauth_successful",
                )

        # The username of the entry, or the typed one; the password is never sent back
        username = (user_input or entry.data).get(CONF_USERNAME)
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _esvitlo_login_schema(), {CONF_USERNAME: username}
            ),
            errors=errors,
            description_placeholders={"esvitlo_url": E_SVITLO_URL},
        )

    async def async_step_esvitlo_account(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle account/group selection for E-Svitlo."""
        if user_input is not None:
            self.data[CONF_ACCOUNT_ID] = user_input[CONF_ACCOUNT_ID]

            # One entry for each E-Svitlo account: a second one only repeats it
            self._async_abort_entries_match(
                {
                    key: self.data[key]
                    for key in (CONF_PROVIDER_TYPE, CONF_PROVIDER, CONF_ACCOUNT_ID)
                }
            )

            # The address comes from the accounts that the form offered
            selected_acc = next(
                (
                    a
                    for a in self._accounts
                    if str(a.get("a")) == str(user_input[CONF_ACCOUNT_ID])
                ),
                None,
            )

            if selected_acc:
                self.data[CONF_ADDRESS_STR] = selected_acc.get("address")

            # noinspection PyTypeChecker
            return self.async_create_entry(
                title=await self._async_entry_title(self.data), data=self.data
            )

        # The client of the login step is still logged in
        client = self._e_svitlo_client(
            self.data[CONF_USERNAME], self.data[CONF_PASSWORD]
        )
        accounts = await client.get_accounts()
        if accounts is None:
            # The server gave no list of accounts: a network or a server error
            # noinspection PyTypeChecker
            return self.async_abort(reason="e_svitlo_connection_error")
        if not accounts:
            # noinspection PyTypeChecker
            return self.async_abort(reason="no_accounts_found")
        self._accounts = accounts

        # Create options mapping: { account_id: "Address (LS)" }
        options = {}
        for acc in accounts:
            label = f"{acc.get('address')} ({acc.get('ls')})"
            # account_id is 'a' field
            val = acc.get("a")
            options[val] = label

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="esvitlo_account",
            data_schema=vol.Schema(
                {
                    # The frontend sends the default, so it is a value of the options
                    vol.Required(
                        CONF_ACCOUNT_ID, default=str(next(iter(options)))
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=str(k), label=v)
                                for k, v in options.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
