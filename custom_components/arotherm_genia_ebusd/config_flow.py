"""Config flow and Options flow for Saunier Duval & Vaillant Heat Pumps (eBUSd)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_AUTO_COOLING_LOCK_BYPASS,
    CONF_FALLBACK_POLL_INTERVAL,
    CONF_FORCE_DHW_BOOST,
    CONF_HAS_MIGO_LINK,
    CONF_HAS_WIRELESS_ROOM_UNIT,
    CONF_INDOOR_MODEL,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    CONF_OUTDOOR_MODEL,
    DEFAULT_AUTO_COOLING_LOCK_BYPASS,
    DEFAULT_FALLBACK_POLL_INTERVAL,
    DEFAULT_FORCE_DHW_BOOST,
    DEFAULT_HAS_MIGO_LINK,
    DEFAULT_HAS_WIRELESS_ROOM_UNIT,
    DEFAULT_INDOOR_MODEL,
    DEFAULT_INDOOR_MODEL_SAUNIER,
    DEFAULT_INDOOR_MODEL_VAILLANT,
    DEFAULT_MANUFACTURER,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_OUTDOOR_MODEL,
    DEFAULT_OUTDOOR_MODEL_SAUNIER,
    DEFAULT_OUTDOOR_MODEL_VAILLANT,
    DOMAIN,
    INDOOR_MODELS_BY_MANUFACTURER,
    INDOOR_MODELS_SAUNIER,
    MANUFACTURERS,
    MANUFACTURER_VAILLANT,
    OUTDOOR_MODELS_BY_MANUFACTURER,
    OUTDOOR_MODELS_SAUNIER,
)


class SaunierGeniaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Saunier Duval & Vaillant Heat Pumps (eBUSd)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._mqtt_prefix: str = DEFAULT_MQTT_PREFIX
        self._manufacturer: str = DEFAULT_MANUFACTURER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Configure MQTT prefix and select equipment manufacturer."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mqtt_prefix = str(
                user_input.get(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX)
            ).strip().rstrip("/")

            if not mqtt_prefix:
                errors[CONF_MQTT_PREFIX] = "invalid_mqtt_prefix"
            elif "mqtt" not in self.hass.config.components:
                errors["base"] = "mqtt_not_configured"
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{mqtt_prefix}")
                self._abort_if_unique_id_configured()

                self._mqtt_prefix = mqtt_prefix
                self._manufacturer = str(
                    user_input.get(CONF_MANUFACTURER, DEFAULT_MANUFACTURER)
                )
                return await self.async_step_models()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MQTT_PREFIX, default=DEFAULT_MQTT_PREFIX
                ): TextSelector(),
                vol.Required(
                    CONF_MANUFACTURER, default=DEFAULT_MANUFACTURER
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MANUFACTURERS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_models(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Select specific hardware models based on chosen manufacturer."""
        if user_input is not None:
            entry_data = {
                CONF_MQTT_PREFIX: self._mqtt_prefix,
                CONF_MANUFACTURER: self._manufacturer,
                CONF_OUTDOOR_MODEL: user_input[CONF_OUTDOOR_MODEL],
                CONF_INDOOR_MODEL: user_input[CONF_INDOOR_MODEL],
                CONF_HAS_WIRELESS_ROOM_UNIT: user_input[CONF_HAS_WIRELESS_ROOM_UNIT],
                CONF_HAS_MIGO_LINK: user_input[CONF_HAS_MIGO_LINK],
            }
            title = f"{self._manufacturer} {user_input[CONF_OUTDOOR_MODEL]} ({self._mqtt_prefix})"
            return self.async_create_entry(
                title=title,
                data=entry_data,
                options={
                    CONF_FORCE_DHW_BOOST: DEFAULT_FORCE_DHW_BOOST,
                    CONF_AUTO_COOLING_LOCK_BYPASS: DEFAULT_AUTO_COOLING_LOCK_BYPASS,
                    CONF_FALLBACK_POLL_INTERVAL: DEFAULT_FALLBACK_POLL_INTERVAL,
                },
            )

        is_vaillant = self._manufacturer == MANUFACTURER_VAILLANT
        outdoor_models = OUTDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, OUTDOOR_MODELS_SAUNIER
        )
        indoor_models = INDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, INDOOR_MODELS_SAUNIER
        )
        default_outdoor = (
            DEFAULT_OUTDOOR_MODEL_VAILLANT
            if is_vaillant
            else DEFAULT_OUTDOOR_MODEL_SAUNIER
        )
        default_indoor = (
            DEFAULT_INDOOR_MODEL_VAILLANT
            if is_vaillant
            else DEFAULT_INDOOR_MODEL_SAUNIER
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OUTDOOR_MODEL, default=default_outdoor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=outdoor_models,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_INDOOR_MODEL, default=default_indoor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=indoor_models,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_HAS_WIRELESS_ROOM_UNIT,
                    default=DEFAULT_HAS_WIRELESS_ROOM_UNIT,
                ): BooleanSelector(),
                vol.Required(
                    CONF_HAS_MIGO_LINK,
                    default=DEFAULT_HAS_MIGO_LINK,
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="models",
            data_schema=schema,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration step 1: Select manufacturer."""
        entry = self._get_reconfigure_entry()
        self._mqtt_prefix = str(entry.data.get(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX))

        if user_input is not None:
            self._manufacturer = str(
                user_input.get(CONF_MANUFACTURER, DEFAULT_MANUFACTURER)
            )
            return await self.async_step_reconfigure_models()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MANUFACTURER,
                    default=entry.data.get(CONF_MANUFACTURER, DEFAULT_MANUFACTURER),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MANUFACTURERS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
        )

    async def async_step_reconfigure_models(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration step 2: Select equipment models."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            new_data = {
                **entry.data,
                CONF_MANUFACTURER: self._manufacturer,
                CONF_OUTDOOR_MODEL: user_input[CONF_OUTDOOR_MODEL],
                CONF_INDOOR_MODEL: user_input[CONF_INDOOR_MODEL],
                CONF_HAS_WIRELESS_ROOM_UNIT: user_input[CONF_HAS_WIRELESS_ROOM_UNIT],
                CONF_HAS_MIGO_LINK: user_input[CONF_HAS_MIGO_LINK],
            }
            title = f"{self._manufacturer} {user_input[CONF_OUTDOOR_MODEL]} ({self._mqtt_prefix})"
            return self.async_update_reload_and_abort(
                entry,
                title=title,
                data=new_data,
            )

        outdoor_models = OUTDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, OUTDOOR_MODELS_SAUNIER
        )
        indoor_models = INDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, INDOOR_MODELS_SAUNIER
        )

        default_outdoor = entry.data.get(CONF_OUTDOOR_MODEL)
        if default_outdoor not in outdoor_models:
            default_outdoor = outdoor_models[0]
        default_indoor = entry.data.get(CONF_INDOOR_MODEL)
        if default_indoor not in indoor_models:
            default_indoor = indoor_models[0]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OUTDOOR_MODEL, default=default_outdoor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=outdoor_models,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_INDOOR_MODEL, default=default_indoor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=indoor_models,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_HAS_WIRELESS_ROOM_UNIT,
                    default=entry.data.get(
                        CONF_HAS_WIRELESS_ROOM_UNIT, DEFAULT_HAS_WIRELESS_ROOM_UNIT
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_HAS_MIGO_LINK,
                    default=entry.data.get(
                        CONF_HAS_MIGO_LINK, DEFAULT_HAS_MIGO_LINK
                    ),
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_models",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SaunierGeniaOptionsFlowHandler:
        """Get the options flow for this handler."""
        return SaunierGeniaOptionsFlowHandler()


class SaunierGeniaOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Saunier Duval & Vaillant Heat Pumps (eBUSd)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options in real time."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FORCE_DHW_BOOST,
                    default=options.get(
                        CONF_FORCE_DHW_BOOST, DEFAULT_FORCE_DHW_BOOST
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_AUTO_COOLING_LOCK_BYPASS,
                    default=options.get(
                        CONF_AUTO_COOLING_LOCK_BYPASS,
                        DEFAULT_AUTO_COOLING_LOCK_BYPASS,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_FALLBACK_POLL_INTERVAL,
                    default=options.get(
                        CONF_FALLBACK_POLL_INTERVAL,
                        DEFAULT_FALLBACK_POLL_INTERVAL,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=3600,
                        step=10,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
