"""Config flow for Svitlo Yeah integration."""

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api.dtek.json import DtekAPIJson
from .api.e_svitlo import ESvitloClient
from .api.yasno import YASNO_REGIONS_ENDPOINT, YasnoApi
from .const import (
    CONF_ACCOUNT_ID,
    CONF_ADDRESS_STR,
    CONF_GROUP,
    CONF_PROVIDER,
    CONF_PROVIDER_TYPE,
    CONF_REGION,
    DOMAIN,
    DTEK_PROVIDER_URLS,
    NAME,
    PROVIDER_TYPE_DTEK_JSON,
    PROVIDER_TYPE_E_SVITLO,
    PROVIDER_TYPE_YASNO,
)
from .models.providers import (
    BaseProvider,
    DTEKJsonProvider,
    ESvitloProvider,
    YasnoProvider,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import YasnoRegion


LOGGER = logging.getLogger(__name__)


def get_config_value(
    entry: ConfigEntry | None,
    key: str,
    default: Any = None,
) -> Any:
    """Get a value from the config entry or default."""
    if entry is not None:
        return entry.options.get(key, entry.data.get(key, default))
    return default


class IntegrationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Svitlo Yeah."""

    def __init__(self) -> None:
        """Initialize config flow."""
        self.api_yasno = YasnoApi()
        self.available_providers: dict[str, BaseProvider] = {}
        self.data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step: select provider."""
        if user_input is not None:
            LOGGER.debug("async_step_user: User input: %s", user_input)
            provider_key = user_input[CONF_PROVIDER]
            selected_provider = self.available_providers.get(provider_key)
            if not selected_provider:
                msg = "Invalid provider selection"
                raise ValueError(msg)

            self.data[CONF_PROVIDER_TYPE] = selected_provider.provider_type
            self.data[CONF_PROVIDER] = selected_provider.provider_id
            if selected_provider.provider_type == PROVIDER_TYPE_YASNO:
                self.data[CONF_REGION] = selected_provider.region_id
            elif selected_provider.provider_type == PROVIDER_TYPE_E_SVITLO:
                # For E-Svitlo, go to auth step first
                # noinspection PyTypeChecker
                return await self.async_step_esvitlo_auth()

            # noinspection PyTypeChecker
            return await self.async_step_group()

        LOGGER.debug("async_step_user: No User input yet")
        await self.api_yasno.fetch_yasno_regions()
        yasno_regions: list[YasnoRegion] = self.api_yasno.regions  # ty:ignore[invalid-assignment]
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

        all_providers = yasno_providers + dtek_providers + [e_svitlo_provider]
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
                vol.Required(
                    CONF_PROVIDER,
                    default=get_config_value(None, CONF_PROVIDER),
                ): SelectSelector(
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

    async def async_step_group(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: select group."""
        if user_input is not None:
            LOGGER.debug("async_step_group: User input: %s", user_input)
            self.data.update(user_input)  # add group to the config

            LOGGER.info("async_step_group: Done. Creating entry from %s", self.data)
            # noinspection PyTypeChecker
            return self.async_create_entry(title=NAME, data=self.data)

        LOGGER.debug("async_step_user: No User input yet")

        region_id = self.data.get(CONF_REGION)
        provider_id = self.data[CONF_PROVIDER]
        provider_type = self.data[CONF_PROVIDER_TYPE]

        groups = []
        errors: dict[str, str] | None = None
        description_placeholders: Mapping[str, str] | None = None
        if provider_type == PROVIDER_TYPE_YASNO:
            if region_id and provider_id:
                temp_api = YasnoApi(
                    region_id=region_id,
                    provider_id=provider_id,
                )
                await temp_api.fetch_planned_outage_data()
                groups = temp_api.get_yasno_groups()
                if not groups:
                    description_placeholders = {"url": YASNO_REGIONS_ENDPOINT}
                    # noinspection PyTypeChecker
                    return self.async_abort(
                        reason="yasno_connection_error",
                        description_placeholders=description_placeholders,
                    )

        elif provider_type == PROVIDER_TYPE_DTEK_JSON and provider_id:
            urls = DTEK_PROVIDER_URLS.get(provider_id, [])
            if urls:
                temp_api = DtekAPIJson(urls=urls, group=None)
                await temp_api.fetch_data()
                groups = temp_api.get_dtek_region_groups()
                if not groups:
                    description_placeholders = {
                        "urls": urls[0] if len(urls) == 1 else urls
                    }  # ty:ignore[invalid-assignment]
                    # noinspection PyTypeChecker
                    return self.async_abort(
                        reason="dtek_json_empty_data",
                        description_placeholders=description_placeholders,
                    )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_GROUP,
                    default=get_config_value(None, CONF_GROUP),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=groups,
                        translation_key="group",
                    ),
                ),
            },
        )
        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="group",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_esvitlo_auth(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle authentication step for E-Svitlo."""
        errors = {}

        if user_input is not None:
            LOGGER.debug("async_step_esvitlo_auth: User input received")

            # Validate credentials by attempting login
            provider = ESvitloProvider(
                user_name=user_input["username"],
                password=user_input["password"],
            )

            client = ESvitloClient(self.hass, provider)

            if await client.login():
                # Authentication successful, store credentials and proceed
                self.data["username"] = user_input["username"]
                self.data["password"] = user_input["password"]

                # Proceed to account/group selection
                # noinspection PyTypeChecker
                return await self.async_step_esvitlo_account()

            errors["base"] = "invalid_auth"

        # Show authentication form
        data_schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
            }
        )

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="esvitlo_auth", data_schema=data_schema, errors=errors
        )

    async def async_step_esvitlo_account(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle account/group selection for E-Svitlo."""
        if user_input is not None:
            self.data[CONF_ACCOUNT_ID] = user_input[CONF_ACCOUNT_ID]

            # To store the address string, we need to find it again
            # from the account list
            # Re-instantiate client to fetch accounts
            provider = ESvitloProvider(
                user_name=self.data["username"],
                password=self.data["password"],
            )
            client = ESvitloClient(self.hass, provider)
            accounts = await client.get_accounts() or []

            # Find selected account
            selected_acc = next(
                (
                    a
                    for a in accounts
                    if str(a.get("a")) == str(user_input[CONF_ACCOUNT_ID])
                ),
                None,
            )

            if selected_acc:
                self.data[CONF_ADDRESS_STR] = selected_acc.get("address")

            # noinspection PyTypeChecker
            return self.async_create_entry(title=NAME, data=self.data)

        # We already have credentials in self.data from previous step
        provider = ESvitloProvider(
            user_name=self.data["username"],
            password=self.data["password"],
        )
        client = ESvitloClient(self.hass, provider)

        accounts = await client.get_accounts()
        if not accounts:
            # If no accounts found or error, abort or show error
            # noinspection PyTypeChecker
            return self.async_abort(reason="no_accounts_found")

        # Create options mapping: { account_id: "Address (LS)" }
        options = {}
        for acc in accounts:
            label = f"{acc.get('address')} ({acc.get('ls')})"
            # account_id is 'a' field
            val = acc.get("a")
            options[val] = label

        if not options:
            # noinspection PyTypeChecker
            return self.async_abort(reason="no_accounts_found")

        # noinspection PyTypeChecker
        return self.async_show_form(
            step_id="esvitlo_account",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCOUNT_ID, default=next(iter(options.keys()))
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
