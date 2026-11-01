"""The aroTHERM & GeniaAir (eBUS) integration."""

from __future__ import annotations

import asyncio
import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CIRCUIT_BASS3,
    DEFAULT_HOLIDAY_TEMP,
    DEPRECATED_UNIQUE_ID_SUFFIXES,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
    OUTDOOR_MODEL_SPECS,
    PLATFORMS,
    SERVICE_CANCEL_HOLIDAY_MODE,
    SERVICE_FORCE_DHW_BOOST,
    SERVICE_SET_HOLIDAY_MODE,
    SERVICE_SET_WEEKLY_TIMER,
    TIMER_CIRCUIT_PREFIXES,
    WEEKDAYS_LIST,
)
from .coordinator import SaunierGeniaCoordinator

_LOGGER = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

SET_WEEKLY_TIMER_SCHEMA = vol.Schema(
    {
        vol.Required("circuit_type"): vol.In(
            ["heating", "dhw", "cooling", "circulation"]
        ),
        vol.Required("day"): vol.In([*WEEKDAYS_LIST, "Weekdays", "All"]),
        vol.Optional("slot", default=1): vol.In([1, 2, 3]),
        vol.Required("start_time"): cv.string,
        vol.Required("end_time"): cv.string,
    }
)

FORCE_DHW_BOOST_SCHEMA = vol.Schema(
    {
        vol.Optional("boost_temp"): vol.All(
            vol.Coerce(float), vol.Range(min=40.0, max=68.0)
        ),
    }
)

SET_HOLIDAY_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature", default=DEFAULT_HOLIDAY_TEMP): vol.All(
            vol.Coerce(float), vol.Range(min=5.0, max=24.0)
        ),
        vol.Optional("start_date"): cv.string,
        vol.Optional("start_time"): cv.string,
        vol.Optional("end_date"): cv.string,
        vol.Optional("end_time"): cv.string,
    }
)

CANCEL_HOLIDAY_MODE_SCHEMA = vol.Schema({})


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    """Validate and parse 'HH:MM' into (hour, minute) integers."""
    match = TIME_PATTERN.match(time_str.strip())
    if not match:
        raise HomeAssistantError(
            f"Invalid time format '{time_str}'. Must be 'HH:MM' (00:00 to 23:59)."
        )
    return int(match.group(1)), int(match.group(2))


def _async_cleanup_deprecated_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove obsolete entity registry entries from earlier b5 16 definitions."""
    ent_reg = er.async_get(hass)
    deprecated_uids = {
        f"{entry.entry_id}_{suffix}" for suffix in DEPRECATED_UNIQUE_ID_SUFFIXES
    }
    for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        if reg_entry.unique_id in deprecated_uids:
            _LOGGER.info(
                "Removing deprecated entity %s (unique_id=%s)",
                reg_entry.entity_id,
                reg_entry.unique_id,
            )
            ent_reg.async_remove(reg_entry.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Saunier Duval GeniaAir Max ES & MiPro Sense from a config entry."""
    # 1. Initialize and connect the centralized eBUSd MQTT coordinator
    coordinator = SaunierGeniaCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 2. Clean up deprecated b5 16 entities before forwarding platform setups
    _async_cleanup_deprecated_entities(hass, entry)

    # 3. Pre-register parent outdoor device in device registry so child devices can use via_device_id
    dev_reg = dr.async_get(hass)
    outdoor_id = f"{entry.entry_id}_{DEVICE_OUTDOOR_UNIT}"
    outdoor_model = coordinator.outdoor_model
    outdoor_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, outdoor_id)},
        name=f"{outdoor_model} (Unidad Exterior)",
        manufacturer=coordinator.manufacturer,
        model=OUTDOOR_MODEL_SPECS.get(outdoor_model, outdoor_model),
        sw_version=coordinator.get_device_sw_version(DEVICE_OUTDOOR_UNIT),
        hw_version=coordinator.get_device_hw_version(DEVICE_OUTDOOR_UNIT),
        serial_number=coordinator.get_device_serial_number(DEVICE_OUTDOOR_UNIT),
    )
    coordinator.set_outdoor_device_id(outdoor_device.id)

    # 4. Forward entry setup to all supported platforms (sensor, climate, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 4. Listen for options updates (e.g. DHW boost temp, cooling bypass toggle)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 5. Register custom integration services (timers, DHW boost)
    _async_register_services(hass)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update in real time."""
    coordinator: SaunierGeniaCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        coordinator.async_update_options()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SaunierGeniaCoordinator | None = hass.data.get(DOMAIN, {}).pop(
            entry.entry_id, None
        )
        if coordinator is not None:
            await coordinator.async_unload()

        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SET_WEEKLY_TIMER)
            hass.services.async_remove(DOMAIN, SERVICE_FORCE_DHW_BOOST)
            hass.services.async_remove(DOMAIN, SERVICE_SET_HOLIDAY_MODE)
            hass.services.async_remove(DOMAIN, SERVICE_CANCEL_HOLIDAY_MODE)

    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    """Register custom domain services for weekly schedule timers and forced DHW boost."""
    if not hass.services.has_service(DOMAIN, SERVICE_SET_WEEKLY_TIMER):

        async def _async_handle_set_weekly_timer(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.set_weekly_timer service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            circuit_type: str = call.data["circuit_type"]
            day_selection: str = call.data["day"]
            slot: int = int(call.data.get("slot", 1))
            start_time: str = call.data["start_time"]
            end_time: str = call.data["end_time"]

            from_h, from_m = _parse_hhmm(start_time)
            to_h, to_m = _parse_hhmm(end_time)

            prefix = TIMER_CIRCUIT_PREFIXES[circuit_type]
            slot_suffix = "" if slot == 1 else f"_Slot{slot}"
            payload = f"{from_h};{from_m};{to_h};{to_m}"

            if day_selection == "Weekdays":
                target_days = WEEKDAYS_LIST[:5]
            elif day_selection == "All":
                target_days = WEEKDAYS_LIST
            else:
                target_days = [day_selection]

            for coordinator in coordinators.values():
                for idx, day_name in enumerate(target_days):
                    message = f"{prefix}_{day_name}{slot_suffix}"
                    await coordinator.async_write_parameter(
                        CIRCUIT_BASS3, message, payload
                    )
                    # Physical eBUS bus runs at 2400 baud (~240 bytes/s) with hardware collision
                    # arbitration. Consecutive multi-message writes require pacing (~600 ms)
                    # to prevent bus arbitration collisions with MiPro Sense or buffer overflows.
                    if idx < len(target_days) - 1:
                        await asyncio.sleep(0.6)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_WEEKLY_TIMER,
            _async_handle_set_weekly_timer,
            schema=SET_WEEKLY_TIMER_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_DHW_BOOST):

        async def _async_handle_force_dhw_boost(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.force_dhw_boost service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            boost_temp: float | None = call.data.get("boost_temp")
            for coordinator in coordinators.values():
                await coordinator.async_trigger_dhw_boost(
                    override_boost_temp=boost_temp
                )

        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_DHW_BOOST,
            _async_handle_force_dhw_boost,
            schema=FORCE_DHW_BOOST_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_HOLIDAY_MODE):

        async def _async_handle_set_holiday_mode(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.set_holiday_mode service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            temp: float = float(call.data.get("temperature", DEFAULT_HOLIDAY_TEMP))
            start_date: str | None = call.data.get("start_date")
            start_time: str | None = call.data.get("start_time")
            end_date: str | None = call.data.get("end_date")
            end_time: str | None = call.data.get("end_time")

            for coordinator in coordinators.values():
                await coordinator.async_activate_holiday_mode(
                    temp=temp,
                    start_date=start_date,
                    start_time=start_time,
                    end_date=end_date,
                    end_time=end_time,
                )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_HOLIDAY_MODE,
            _async_handle_set_holiday_mode,
            schema=SET_HOLIDAY_MODE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CANCEL_HOLIDAY_MODE):

        async def _async_handle_cancel_holiday_mode(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.cancel_holiday_mode service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            for coordinator in coordinators.values():
                await coordinator.async_cancel_holiday_mode()

        hass.services.async_register(
            DOMAIN,
            SERVICE_CANCEL_HOLIDAY_MODE,
            _async_handle_cancel_holiday_mode,
            schema=CANCEL_HOLIDAY_MODE_SCHEMA,
        )
