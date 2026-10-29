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

from .const import (
    CIRCUIT_BASS3,
    DOMAIN,
    PLATFORMS,
    SERVICE_FORCE_DHW_BOOST,
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


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    """Validate and parse 'HH:MM' into (hour, minute) integers."""
    match = TIME_PATTERN.match(time_str.strip())
    if not match:
        raise HomeAssistantError(
            f"Invalid time format '{time_str}'. Must be 'HH:MM' (00:00 to 23:59)."
        )
    return int(match.group(1)), int(match.group(2))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Saunier Duval GeniaAir Max ES & MiPro Sense from a config entry."""
    # 1. Initialize and connect the centralized eBUSd MQTT coordinator
    coordinator = SaunierGeniaCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 2. Forward entry setup to all supported platforms (sensor, climate, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 3. Listen for options updates (e.g. DHW boost temp, cooling bypass toggle)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 4. Register custom integration services (timers, DHW boost)
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
