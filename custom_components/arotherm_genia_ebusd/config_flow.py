"""Config flow and Options flow for Saunier Duval & Vaillant Heat Pumps (eBUSd)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
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
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_ENABLE_SCHEDULE_CALENDARS,
    CONF_ENABLE_SEND_HEX,
    CONF_FALLBACK_POLL_INTERVAL,
    CONF_FORCE_DHW_BOOST,
    CONF_HAS_MIGO_LINK,
    CONF_HAS_VR70,
    CONF_HAS_WIRELESS_ROOM_UNIT,
    CONF_INDOOR_MODEL,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    CONF_OUTDOOR_MODEL,
    CONF_PREREQUISITES_CONFIRMED,
    CSV_INSTALL_ONE_LINER,
    DEFAULT_AUTO_COOLING_LOCK_BYPASS,
    DEFAULT_EBUSD_TCP_HOST,
    DEFAULT_EBUSD_TCP_PORT,
    DEFAULT_ENABLE_EBUSD_TCP,
    DEFAULT_ENABLE_SCHEDULE_CALENDARS,
    DEFAULT_ENABLE_SEND_HEX,
    DEFAULT_FALLBACK_POLL_INTERVAL,
    DEFAULT_FORCE_DHW_BOOST,
    DEFAULT_HAS_MIGO_LINK,
    DEFAULT_HAS_VR70,
    DEFAULT_HAS_WIRELESS_ROOM_UNIT,
    DEFAULT_INDOOR_MODEL_SAUNIER,
    DEFAULT_INDOOR_MODEL_VAILLANT,
    DEFAULT_MANUFACTURER,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_OUTDOOR_MODEL_SAUNIER,
    DEFAULT_OUTDOOR_MODEL_VAILLANT,
    DOMAIN,
    INDOOR_MODELS_BY_MANUFACTURER,
    INDOOR_MODELS_SAUNIER,
    MANUFACTURER_VAILLANT,
    MANUFACTURERS,
    OUTDOOR_MODELS_BY_MANUFACTURER,
    OUTDOOR_MODELS_SAUNIER,
    SECTION_ADVANCED_OPTIONS,
)
from .ebusd_tcp import (
    LOOPBACK_HOSTS,
    EbusdBusHardware,
    async_probe_ebusd_bus_hardware,
    async_probe_ebusd_tcp,
)


class SaunierGeniaConfigFlow(ConfigFlow, domain=DOMAIN):  # pyright: ignore[reportCallIssue, reportGeneralTypeIssues]
    """Handle a config flow for Saunier Duval & Vaillant Heat Pumps (eBUSd)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._mqtt_prefix: str = DEFAULT_MQTT_PREFIX
        self._manufacturer: str = DEFAULT_MANUFACTURER
        self._models_data: dict[str, Any] = {}
        self._tcp_detected_endpoint: tuple[str, int] | None = None
        self._tcp_initial_enabled: bool = False
        self._tcp_initial_host: str = ""
        self._tcp_initial_port: int = DEFAULT_EBUSD_TCP_PORT
        self._tcp_last_rendered_enabled: bool = False
        self._tcp_last_rendered_host: str = ""
        self._bus_hardware_probed: bool = False
        self._bus_hardware: EbusdBusHardware | None = None

    async def _async_detect_bus_hardware_once(
        self,
        configured_host: str | None = None,
        port: int = DEFAULT_EBUSD_TCP_PORT,
    ) -> EbusdBusHardware | None:
        """Probe eBUSd `info` at most once per flow to pre-fill hardware toggles."""
        if self._bus_hardware_probed:
            return self._bus_hardware
        self._bus_hardware_probed = True
        if getattr(self, "hass", None) is None:
            return None
        self._bus_hardware = await async_probe_ebusd_bus_hardware(
            self.hass,
            configured_host=configured_host,
            port=port,
        )
        return self._bus_hardware

    @staticmethod
    def _build_ebusd_tcp_schema(
        enable_default: bool,
        host_default: str,
        port_default: int,
    ) -> vol.Schema:
        """Build the optional eBUSd TCP configuration schema."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_EBUSD_TCP,
                    default=enable_default,
                ): BooleanSelector(),
                vol.Optional(
                    CONF_EBUSD_TCP_HOST,
                    default=host_default,
                ): TextSelector(),
                vol.Optional(
                    CONF_EBUSD_TCP_PORT,
                    default=port_default,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=65535,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    async def _async_prepare_ebusd_tcp_defaults(
        self,
        existing_options: dict[str, Any] | None = None,
    ) -> tuple[bool, str, int]:
        """Compute defaults for the eBUSd TCP step, probing add-ons/local daemon when appropriate."""
        options = existing_options or {}
        adv_options = options.get(SECTION_ADVANCED_OPTIONS, {})
        if not isinstance(adv_options, dict):
            adv_options = {}

        tcp_explicitly_configured = (
            CONF_ENABLE_EBUSD_TCP in options or CONF_ENABLE_EBUSD_TCP in adv_options
        )
        enable_default = bool(
            options.get(
                CONF_ENABLE_EBUSD_TCP,
                adv_options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP),
            )
        )
        raw_host = str(
            options.get(
                CONF_EBUSD_TCP_HOST,
                adv_options.get(CONF_EBUSD_TCP_HOST, ""),
            )
            or ""
        ).strip()
        port_default = int(
            options.get(
                CONF_EBUSD_TCP_PORT,
                adv_options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT),
            )
            or DEFAULT_EBUSD_TCP_PORT
        )

        self._tcp_initial_enabled = enable_default
        self._tcp_initial_host = raw_host
        self._tcp_initial_port = port_default
        self._tcp_detected_endpoint = None

        host_default = raw_host
        if (
            existing_options is None
            and self._bus_hardware is not None
            and self._bus_hardware.endpoint is not None
        ):
            detected_host, detected_port = self._bus_hardware.endpoint
            self._tcp_detected_endpoint = (detected_host, detected_port)
            host_default = detected_host
            port_default = detected_port
            enable_default = True
        elif getattr(self, "hass", None) is not None and (
            existing_options is None
            or (not enable_default and not tcp_explicitly_configured)
            or raw_host in ("", *LOOPBACK_HOSTS)
        ):
            detected = await async_probe_ebusd_tcp(
                self.hass,
                configured_host=raw_host or None,
                port=port_default,
            )
            if detected is not None:
                detected_host, detected_port = detected
                self._tcp_detected_endpoint = (detected_host, detected_port)
                host_default = detected_host
                port_default = detected_port
                if existing_options is None or not tcp_explicitly_configured:
                    enable_default = True

        self._tcp_last_rendered_enabled = enable_default
        self._tcp_last_rendered_host = host_default
        return enable_default, host_default, port_default

    async def _async_validate_ebusd_tcp_input(
        self,
        user_input: dict[str, Any],
        *,
        is_reconfigure: bool,
    ) -> tuple[dict[str, str], bool, str, int]:
        """Validate optional eBUSd TCP settings and verify connectivity when enabled."""
        errors: dict[str, str] = {}
        enable_tcp = bool(user_input.get(CONF_ENABLE_EBUSD_TCP, False))
        host = str(user_input.get(CONF_EBUSD_TCP_HOST) or "").strip()
        port = int(user_input.get(CONF_EBUSD_TCP_PORT) or DEFAULT_EBUSD_TCP_PORT)

        # If the step opened disabled with an empty host and the user typed a host
        # without flipping the switch, treat that as wanting TCP enabled.
        if (
            not enable_tcp
            and host
            and not self._tcp_last_rendered_enabled
            and not self._tcp_last_rendered_host
        ):
            enable_tcp = True

        if enable_tcp:
            if not host:
                errors[CONF_EBUSD_TCP_HOST] = "invalid_ebusd_tcp_host"
            else:
                already_verified = self._tcp_detected_endpoint == (host, port)
                unchanged_existing = (
                    is_reconfigure
                    and self._tcp_initial_enabled
                    and host == self._tcp_initial_host
                    and port == self._tcp_initial_port
                )
                if (
                    getattr(self, "hass", None) is not None
                    and not already_verified
                    and not unchanged_existing
                ):
                    probed = await async_probe_ebusd_tcp(
                        self.hass,
                        configured_host=host,
                        port=port,
                    )
                    if probed is None:
                        errors["base"] = "cannot_connect_ebusd_tcp"
                    else:
                        host, port = probed
                        self._tcp_detected_endpoint = (host, port)

        self._tcp_last_rendered_enabled = enable_tcp
        self._tcp_last_rendered_host = host
        return errors, enable_tcp, host, port

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Require confirmation of eBUSd CSV and add-on prerequisites."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_PREREQUISITES_CONFIRMED):
                return await self.async_step_mqtt()
            errors[CONF_PREREQUISITES_CONFIRMED] = "prerequisites_not_confirmed"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PREREQUISITES_CONFIRMED, default=False
                ): BooleanSelector(),
            }
        )

        lang = (
            getattr(
                getattr(getattr(self, "hass", None), "config", None), "language", ""
            )
            if getattr(self, "hass", None) is not None
            else ""
        )
        guide_url = (
            "https://github.com/R91g/arotherm-genia-ebusd/blob/main/docs/installation_es.md#2-desplegar-los-archivos-csv-de-ebusd"
            if isinstance(lang, str) and lang.lower().startswith("es")
            else "https://github.com/R91g/arotherm-genia-ebusd/blob/main/docs/installation.md#2-deploy-the-ebusd-csv-configuration"
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "csv_url": "https://github.com/R91g/arotherm-genia-ebusd/tree/main/ebusd-configuration",
                "guide_url": guide_url,
                "install_cmd": CSV_INSTALL_ONE_LINER,
            },
        )

    async def async_step_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Configure MQTT prefix and select equipment manufacturer."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mqtt_prefix = (
                str(user_input.get(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX))
                .strip()
                .rstrip("/")
            )

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

        detected_hw = await self._async_detect_bus_hardware_once()
        default_manufacturer = (
            detected_hw.manufacturer
            if detected_hw is not None and detected_hw.manufacturer in MANUFACTURERS
            else DEFAULT_MANUFACTURER
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MQTT_PREFIX, default=DEFAULT_MQTT_PREFIX
                ): TextSelector(),
                vol.Required(
                    CONF_MANUFACTURER, default=default_manufacturer
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MANUFACTURERS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="mqtt",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_models(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Select specific hardware models based on chosen manufacturer."""
        if user_input is not None:
            self._models_data = {
                CONF_OUTDOOR_MODEL: user_input[CONF_OUTDOOR_MODEL],
                CONF_INDOOR_MODEL: user_input[CONF_INDOOR_MODEL],
                CONF_HAS_WIRELESS_ROOM_UNIT: user_input[CONF_HAS_WIRELESS_ROOM_UNIT],
                CONF_HAS_MIGO_LINK: user_input[CONF_HAS_MIGO_LINK],
                CONF_HAS_VR70: bool(user_input.get(CONF_HAS_VR70, DEFAULT_HAS_VR70)),
            }
            return await self.async_step_ebusd_tcp()

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

        detected_hw = await self._async_detect_bus_hardware_once()
        default_wireless = (
            detected_hw.has_wireless_room_unit
            if detected_hw is not None
            and detected_hw.has_wireless_room_unit is not None
            else DEFAULT_HAS_WIRELESS_ROOM_UNIT
        )
        default_migo_link = (
            detected_hw.has_migo_link
            if detected_hw is not None and detected_hw.has_migo_link is not None
            else DEFAULT_HAS_MIGO_LINK
        )
        default_vr70 = (
            detected_hw.has_vr70
            if detected_hw is not None and detected_hw.has_vr70 is not None
            else DEFAULT_HAS_VR70
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
                vol.Required(CONF_INDOOR_MODEL, default=default_indoor): SelectSelector(
                    SelectSelectorConfig(
                        options=indoor_models,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_HAS_WIRELESS_ROOM_UNIT,
                    default=default_wireless,
                ): BooleanSelector(),
                vol.Required(
                    CONF_HAS_MIGO_LINK,
                    default=default_migo_link,
                ): BooleanSelector(),
                vol.Required(
                    CONF_HAS_VR70,
                    default=default_vr70,
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="models",
            data_schema=schema,
        )

    async def async_step_ebusd_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: Optional eBUSd TCP configuration with add-on auto-detection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            (
                errors,
                enable_tcp,
                host,
                port,
            ) = await self._async_validate_ebusd_tcp_input(
                user_input, is_reconfigure=False
            )
            if not errors:
                entry_data = {
                    CONF_MQTT_PREFIX: self._mqtt_prefix,
                    CONF_MANUFACTURER: self._manufacturer,
                    **self._models_data,
                }
                title = f"{self._manufacturer} {self._models_data[CONF_OUTDOOR_MODEL]} ({self._mqtt_prefix})"
                options: dict[str, Any] = {
                    CONF_FORCE_DHW_BOOST: DEFAULT_FORCE_DHW_BOOST,
                    CONF_AUTO_COOLING_LOCK_BYPASS: DEFAULT_AUTO_COOLING_LOCK_BYPASS,
                    CONF_FALLBACK_POLL_INTERVAL: DEFAULT_FALLBACK_POLL_INTERVAL,
                    CONF_ENABLE_EBUSD_TCP: enable_tcp,
                }
                if host:
                    options[CONF_EBUSD_TCP_HOST] = host
                    options[CONF_EBUSD_TCP_PORT] = port
                return self.async_create_entry(
                    title=title,
                    data=entry_data,
                    options=options,
                )
            enable_default, host_default, port_default = enable_tcp, host, port
        else:
            (
                enable_default,
                host_default,
                port_default,
            ) = await self._async_prepare_ebusd_tcp_defaults()

        return self.async_show_form(
            step_id="ebusd_tcp",
            data_schema=self._build_ebusd_tcp_schema(
                enable_default, host_default, port_default
            ),
            errors=errors,
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
            self._models_data = {
                CONF_OUTDOOR_MODEL: user_input[CONF_OUTDOOR_MODEL],
                CONF_INDOOR_MODEL: user_input[CONF_INDOOR_MODEL],
                CONF_HAS_WIRELESS_ROOM_UNIT: user_input[CONF_HAS_WIRELESS_ROOM_UNIT],
                CONF_HAS_MIGO_LINK: user_input[CONF_HAS_MIGO_LINK],
                CONF_HAS_VR70: bool(
                    user_input.get(
                        CONF_HAS_VR70,
                        entry.data.get(CONF_HAS_VR70, DEFAULT_HAS_VR70),
                    )
                ),
            }
            return await self.async_step_reconfigure_ebusd_tcp()

        outdoor_models = OUTDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, OUTDOOR_MODELS_SAUNIER
        )
        indoor_models = INDOOR_MODELS_BY_MANUFACTURER.get(
            self._manufacturer, INDOOR_MODELS_SAUNIER
        )

        default_outdoor = entry.data.get(CONF_OUTDOOR_MODEL)
        if default_outdoor and default_outdoor.endswith(" (Legacy)"):
            stripped = default_outdoor.replace(" (Legacy)", "")
            if stripped in outdoor_models:
                default_outdoor = stripped
        if default_outdoor not in outdoor_models:
            default_outdoor = outdoor_models[0]

        default_indoor = entry.data.get(CONF_INDOOR_MODEL)
        if (
            default_indoor == "Módulo Hidráulico HE 9-7 W"
            and "Hydraulic Module HE 9-7 W" in indoor_models
        ):
            default_indoor = "Hydraulic Module HE 9-7 W"
        if default_indoor not in indoor_models:
            default_indoor = indoor_models[0]

        if CONF_HAS_VR70 in entry.data:
            default_vr70 = bool(entry.data[CONF_HAS_VR70])
        else:
            existing_host = (
                str(entry.options.get(CONF_EBUSD_TCP_HOST) or "").strip() or None
            )
            existing_port = int(
                entry.options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT)
                or DEFAULT_EBUSD_TCP_PORT
            )
            detected_hw = await self._async_detect_bus_hardware_once(
                configured_host=existing_host,
                port=existing_port,
            )
            default_vr70 = (
                detected_hw.has_vr70
                if detected_hw is not None and detected_hw.has_vr70 is not None
                else DEFAULT_HAS_VR70
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
                vol.Required(CONF_INDOOR_MODEL, default=default_indoor): SelectSelector(
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
                    default=entry.data.get(CONF_HAS_MIGO_LINK, DEFAULT_HAS_MIGO_LINK),
                ): BooleanSelector(),
                vol.Required(
                    CONF_HAS_VR70,
                    default=default_vr70,
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="reconfigure_models",
            data_schema=schema,
        )

    async def async_step_reconfigure_ebusd_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration step 3: Optional eBUSd TCP settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            (
                errors,
                enable_tcp,
                host,
                port,
            ) = await self._async_validate_ebusd_tcp_input(
                user_input, is_reconfigure=True
            )
            if not errors:
                new_data = {
                    **entry.data,
                    CONF_MANUFACTURER: self._manufacturer,
                    **self._models_data,
                }
                title = f"{self._manufacturer} {self._models_data[CONF_OUTDOOR_MODEL]} ({self._mqtt_prefix})"
                new_options = dict(entry.options)
                if SECTION_ADVANCED_OPTIONS in new_options and isinstance(
                    new_options[SECTION_ADVANCED_OPTIONS], dict
                ):
                    nested = new_options.pop(SECTION_ADVANCED_OPTIONS)
                    for key, value in nested.items():
                        new_options.setdefault(key, value)
                new_options[CONF_ENABLE_EBUSD_TCP] = enable_tcp
                if host:
                    new_options[CONF_EBUSD_TCP_HOST] = host
                    new_options[CONF_EBUSD_TCP_PORT] = port
                elif not enable_tcp:
                    new_options.pop(CONF_EBUSD_TCP_HOST, None)
                    new_options[CONF_EBUSD_TCP_PORT] = port

                return self.async_update_reload_and_abort(
                    entry,
                    title=title,
                    data=new_data,
                    options=new_options,
                )
            enable_default, host_default, port_default = enable_tcp, host, port
        else:
            (
                enable_default,
                host_default,
                port_default,
            ) = await self._async_prepare_ebusd_tcp_defaults(dict(entry.options))

        return self.async_show_form(
            step_id="reconfigure_ebusd_tcp",
            data_schema=self._build_ebusd_tcp_schema(
                enable_default, host_default, port_default
            ),
            errors=errors,
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
            if SECTION_ADVANCED_OPTIONS in user_input and isinstance(
                user_input[SECTION_ADVANCED_OPTIONS], dict
            ):
                user_input.update(user_input.pop(SECTION_ADVANCED_OPTIONS))

            if CONF_EBUSD_TCP_HOST in user_input:
                user_input[CONF_EBUSD_TCP_HOST] = (
                    str(user_input[CONF_EBUSD_TCP_HOST]).strip()
                    or DEFAULT_EBUSD_TCP_HOST
                )
            if CONF_EBUSD_TCP_PORT in user_input:
                user_input[CONF_EBUSD_TCP_PORT] = int(user_input[CONF_EBUSD_TCP_PORT])
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        adv_options = options.get(SECTION_ADVANCED_OPTIONS, {})
        if not isinstance(adv_options, dict):
            adv_options = {}

        tcp_explicitly_configured = (
            CONF_ENABLE_EBUSD_TCP in options or CONF_ENABLE_EBUSD_TCP in adv_options
        )
        enable_tcp_default = bool(
            options.get(
                CONF_ENABLE_EBUSD_TCP,
                adv_options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP),
            )
        )
        tcp_host_default = str(
            options.get(
                CONF_EBUSD_TCP_HOST,
                adv_options.get(CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST),
            )
        ).strip()
        tcp_port_default = int(
            options.get(
                CONF_EBUSD_TCP_PORT,
                adv_options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT),
            )
        )
        if getattr(self, "hass", None) is not None and (
            (not enable_tcp_default and not tcp_explicitly_configured)
            or tcp_host_default in ("", *LOOPBACK_HOSTS)
        ):
            detected = await async_probe_ebusd_tcp(
                self.hass,
                configured_host=tcp_host_default,
                port=tcp_port_default,
            )
            if detected is not None:
                detected_host, detected_port = detected
                tcp_host_default = detected_host
                tcp_port_default = detected_port
                if not tcp_explicitly_configured:
                    enable_tcp_default = True
        send_hex_default = bool(
            options.get(
                CONF_ENABLE_SEND_HEX,
                adv_options.get(CONF_ENABLE_SEND_HEX, DEFAULT_ENABLE_SEND_HEX),
            )
        )

        advanced_schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_EBUSD_TCP,
                    default=enable_tcp_default,
                ): BooleanSelector(),
                vol.Required(
                    CONF_EBUSD_TCP_HOST,
                    default=tcp_host_default,
                ): TextSelector(),
                vol.Required(
                    CONF_EBUSD_TCP_PORT,
                    default=tcp_port_default,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=65535,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_SEND_HEX,
                    default=send_hex_default,
                ): BooleanSelector(),
            }
        )

        section_fn = getattr(data_entry_flow, "section", None)
        base_schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_FORCE_DHW_BOOST,
                default=options.get(CONF_FORCE_DHW_BOOST, DEFAULT_FORCE_DHW_BOOST),
            ): BooleanSelector(),
            vol.Required(
                CONF_AUTO_COOLING_LOCK_BYPASS,
                default=options.get(
                    CONF_AUTO_COOLING_LOCK_BYPASS,
                    DEFAULT_AUTO_COOLING_LOCK_BYPASS,
                ),
            ): BooleanSelector(),
            vol.Required(
                CONF_ENABLE_SCHEDULE_CALENDARS,
                default=options.get(
                    CONF_ENABLE_SCHEDULE_CALENDARS,
                    DEFAULT_ENABLE_SCHEDULE_CALENDARS,
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

        if section_fn is not None:
            base_schema_dict[vol.Required(SECTION_ADVANCED_OPTIONS)] = section_fn(
                advanced_schema,
                {"collapsed": not enable_tcp_default},
            )
        else:
            base_schema_dict.update(advanced_schema.schema)

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(base_schema_dict)
        )
