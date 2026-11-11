"""The aroTHERM & GeniaAir (eBUS) integration."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CIRCUIT_BASS3,
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_ENABLE_SEND_HEX,
    DAY_SHORT_KEYS,
    DEFAULT_EBUSD_TCP_HOST,
    DEFAULT_EBUSD_TCP_PORT,
    DEFAULT_ENABLE_EBUSD_TCP,
    DEFAULT_ENABLE_SEND_HEX,
    DEFAULT_HOLIDAY_TEMP,
    DEPRECATED_UNIQUE_ID_SUFFIXES,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
    OUTDOOR_MODEL_SPECS,
    PLATFORMS,
    SERVICE_CANCEL_HOLIDAY_MODE,
    SERVICE_CANCEL_QUICK_VETO,
    SERVICE_DUMP_MQTT_VALUES,
    SERVICE_FORCE_DHW_BOOST,
    SERVICE_QUICK_VETO,
    SERVICE_READ_PARAMETER,
    SERVICE_RECORD_TOPIC_CHANGES,
    SERVICE_SEND_HEX_COMMAND,
    SERVICE_SET_HOLIDAY_MODE,
    SERVICE_SET_WEEKLY_TIMER,
    SERVICE_WRITE_PARAMETER,
    TIMER_CIRCUIT_PREFIXES,
    WEEKDAYS_LIST,
)
from .coordinator import SaunierGeniaCoordinator

_LOGGER = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"^(([01]?\d|2[0-3]):([0-5]\d)|24:00)$")

DAY_NAME_MAPPING: dict[str, str] = {
    # English canonical
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
    "weekdays": "Weekdays",
    "weekend": "Weekend",
    "all": "All",
    # Spanish localized
    "lunes": "Monday",
    "martes": "Tuesday",
    "miercoles": "Wednesday",
    "miércoles": "Wednesday",
    "jueves": "Thursday",
    "viernes": "Friday",
    "sabado": "Saturday",
    "sábado": "Saturday",
    "domingo": "Sunday",
    "laborables": "Weekdays",
    "lunes a viernes": "Weekdays",
    "entre semana": "Weekdays",
    "semana": "Weekdays",
    "fin de semana": "Weekend",
    "finde": "Weekend",
    "todos": "All",
    "toda la semana": "All",
    "lunes a domingo": "All",
}


def normalize_day_name(day_str: str) -> str:
    """Normalize day string (in English or Spanish) to canonical day name."""
    cleaned = day_str.strip().lower()
    canonical = DAY_NAME_MAPPING.get(cleaned)
    if canonical:
        return canonical
    for w in [*WEEKDAYS_LIST, "Weekdays", "Weekend", "All"]:
        if w.lower() == cleaned:
            return w
    raise HomeAssistantError(
        f"Invalid day '{day_str}'. Valid days are Monday to Sunday (or Lunes a Domingo), "
        "'Weekdays' ('Laborables'), 'Weekend' ('Fin de semana'), or 'All' ('Todos')."
    )


SET_WEEKLY_TIMER_SCHEMA = vol.Schema(
    {
        vol.Required("circuit_type"): vol.In(
            ["heating", "dhw", "cooling", "circulation"]
        ),
        vol.Required("day"): cv.string,
        vol.Optional("action", default="set"): vol.In(["set", "delete", "clear"]),
        vol.Optional("slot", default=1): vol.In([1, 2, 3]),
        vol.Optional("start_time"): cv.string,
        vol.Optional("end_time"): cv.string,
        vol.Optional("temp"): vol.All(vol.Coerce(float), vol.Range(min=5.0, max=80.0)),
        vol.Optional("reset_remaining", default=False): cv.boolean,
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

QUICK_VETO_SCHEMA = vol.Schema(
    {
        vol.Optional("temperature"): vol.All(
            vol.Coerce(float), vol.Range(min=10.0, max=30.0)
        ),
        vol.Optional("duration"): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=12.0)
        ),
    }
)

CANCEL_QUICK_VETO_SCHEMA = vol.Schema({})

DUMP_MQTT_VALUES_SCHEMA = vol.Schema(
    {
        vol.Optional("circuit"): cv.string,
        vol.Optional("anonymize", default=True): cv.boolean,
    }
)

RECORD_TOPIC_CHANGES_SCHEMA = vol.Schema(
    {
        vol.Optional("duration", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=120)
        ),
        vol.Optional("circuit"): cv.string,
        vol.Optional("anonymize", default=True): cv.boolean,
    }
)

SEND_HEX_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("command"): cv.string,
        vol.Optional("host"): cv.string,
        vol.Optional("port"): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Optional("timeout", default=5.0): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=30.0)
        ),
    }
)

READ_PARAMETER_SCHEMA = vol.Schema(
    {
        vol.Required("circuit"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("force", default=False): cv.boolean,
        vol.Optional("timeout", default=5.0): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=30.0)
        ),
    }
)

WRITE_PARAMETER_SCHEMA = vol.Schema(
    {
        vol.Required("circuit"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("value"): vol.Any(cv.string, int, float, bool),
    }
)


def _parse_hhmm(time_str: str, is_end: bool = False) -> tuple[int, int]:
    """Validate and parse 'HH:MM' into (hour, minute) integers."""
    raw = time_str.strip()
    match = TIME_PATTERN.match(raw)
    if not match:
        raise HomeAssistantError(
            f"Invalid time format '{time_str}'. Must be 'HH:MM' (00:00 to 24:00)."
        )
    parts = raw.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    if hour == 24:
        if minute != 0:
            raise HomeAssistantError(
                f"Invalid time format '{time_str}'. 24:00 must have 00 minutes."
            )
        if not is_end:
            raise HomeAssistantError(
                "Start time cannot be '24:00'. Day must start between '00:00' and '23:59'."
            )
    return hour, minute


def _time_to_minutes(
    hour: int, minute: int, is_end: bool = False, start_minutes: int = 0
) -> int:
    """Convert hour and minute into minutes from 00:00 (0 to 1440)."""
    if is_end and (hour == 24 or (hour == 0 and minute == 0 and start_minutes > 0)):
        return 1440
    return hour * 60 + minute


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
        elif (
            reg_entry.entity_id.endswith("_consigna_confort_calefaccion_zona_1_dia")
            or reg_entry.entity_id.endswith("_consigna_dia_zona_1")
            or reg_entry.entity_id.endswith("_zone_1_comfort_heating_setpoint_day")
            or reg_entry.entity_id.endswith("_zone_1_day_comfort_setpoint")
            or reg_entry.entity_id.endswith("_zone_1_day_setpoint")
        ):
            _LOGGER.info(
                "Purging legacy day setpoint entity %s (Z1DayTemp replaced by Z1CoolingManualTemp)",
                reg_entry.entity_id,
            )
            ent_reg.async_remove(reg_entry.entity_id)


def _async_migrate_legacy_device_names(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate legacy Spanish device registry names to English for existing installations."""
    dev_reg = dr.async_get(hass)
    translations_map = {
        " (Unidad Exterior)": " (Outdoor Unit)",
        " (Regulador Climático)": " (Climate Controller)",
        " (Interfaz Hidráulica)": " (Hydraulic Interface)",
        " (Termostato Inalámbrico)": " (Wireless Thermostat)",
    }
    for device_entry in list(
        dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    ):
        if device_entry.name_by_user is not None or not device_entry.name:
            continue
        new_name = device_entry.name
        for es_suffix, en_suffix in translations_map.items():
            if es_suffix in new_name:
                new_name = new_name.replace(es_suffix, en_suffix)
        if new_name != device_entry.name:
            _LOGGER.info(
                "Migrating device name '%s' -> '%s' (device_id=%s)",
                device_entry.name,
                new_name,
                device_entry.id,
            )
            dev_reg.async_update_device(device_entry.id, name=new_name)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Saunier Duval GeniaAir Max ES & MiPro Sense from a config entry."""
    # 1. Initialize and connect the centralized eBUSd MQTT coordinator
    coordinator = SaunierGeniaCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 2. Clean up deprecated b5 16 entities before forwarding platform setups
    _async_cleanup_deprecated_entities(hass, entry)
    _async_migrate_legacy_device_names(hass, entry)
    _async_sync_tcp_diagnostic_entities(hass, entry, reload_on_change=False)

    # 3. Pre-register parent outdoor device in device registry so child devices can use via_device_id
    dev_reg = dr.async_get(hass)
    outdoor_id = f"{entry.entry_id}_{DEVICE_OUTDOOR_UNIT}"
    outdoor_model = coordinator.outdoor_model
    outdoor_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, outdoor_id)},
        name=f"{outdoor_model} (Outdoor Unit)",
        manufacturer=coordinator.manufacturer,
        model=OUTDOOR_MODEL_SPECS.get(outdoor_model, outdoor_model),
        sw_version=coordinator.get_device_sw_version(DEVICE_OUTDOOR_UNIT),
        hw_version=coordinator.get_device_hw_version(DEVICE_OUTDOOR_UNIT),
        serial_number=coordinator.get_device_serial_number(DEVICE_OUTDOOR_UNIT),
    )
    coordinator.set_outdoor_device_id(outdoor_device.id)

    # 4. Forward entry setup to all supported platforms (sensor, climate, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 5. Listen for options updates (e.g. DHW boost temp, cooling bypass toggle)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 6. Register custom integration services (timers, DHW boost)
    _async_register_services(hass)
    return True


def _async_sync_tcp_diagnostic_entities(
    hass: HomeAssistant, entry: ConfigEntry, reload_on_change: bool = True
) -> None:
    """Enable or disable TCP diagnostic entities based on enable_ebusd_tcp option."""
    is_tcp_enabled = bool(
        entry.options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP)
    )
    ent_reg = er.async_get(hass)
    tcp_suffixes = (
        "_global_symbol_rate_value",
        "_global_reconnects_value",
        "_global_masters_value",
        "_global_arbitration_latency_value",
        "_global_missing_csv_devices_value",
        "_ebusd_symbol_rate",
        "_ebusd_reconnects",
        "_ebusd_masters",
        "_ebusd_arbitration_latency",
        "_ebusd_missing_csv_devices",
        "_button_ebusd_reload_csv",
        "_button_ebusd_restart_scan",
    )
    entities_to_update: list[
        tuple[er.RegistryEntry, er.RegistryEntryDisabler | None]
    ] = []
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if any(reg_entry.unique_id.endswith(sfx) for sfx in tcp_suffixes):
            if is_tcp_enabled and reg_entry.disabled:
                entities_to_update.append((reg_entry, None))
            elif not is_tcp_enabled and not reg_entry.disabled:
                entities_to_update.append(
                    (reg_entry, er.RegistryEntryDisabler.INTEGRATION)
                )

    if entities_to_update:
        for reg_entry, disabled_by in entities_to_update:
            ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=disabled_by)
        if reload_on_change:
            hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update in real time."""
    coordinator: SaunierGeniaCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        coordinator.async_update_options()

    _async_sync_tcp_diagnostic_entities(hass, entry, reload_on_change=True)


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
            hass.services.async_remove(DOMAIN, SERVICE_QUICK_VETO)
            hass.services.async_remove(DOMAIN, SERVICE_CANCEL_QUICK_VETO)
            hass.services.async_remove(DOMAIN, SERVICE_DUMP_MQTT_VALUES)
            hass.services.async_remove(DOMAIN, SERVICE_RECORD_TOPIC_CHANGES)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_HEX_COMMAND)
            hass.services.async_remove(DOMAIN, SERVICE_READ_PARAMETER)
            hass.services.async_remove(DOMAIN, SERVICE_WRITE_PARAMETER)

    return unload_ok


def _get_active_slot_count(
    coordinator: SaunierGeniaCoordinator, prefix: str, day_name: str
) -> int | None:
    """Return the number of active slots for a day from <prefix>_Slots, or None."""
    slots_msg = coordinator.get_message(CIRCUIT_BASS3, f"{prefix}_Slots") or {}
    raw = slots_msg.get(DAY_SHORT_KEYS[day_name])
    if raw is None:
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if 0 <= count <= 3 else None


def _collect_upper_slots(
    coordinator: SaunierGeniaCoordinator,
    prefix: str,
    day_name: str,
    slot: int,
    active_count: int | None,
) -> list[tuple[int, str]]:
    """Snapshot payloads of active slots above `slot` so they can be restored."""
    if active_count is None or active_count <= slot:
        return []
    upper: list[tuple[int, str]] = []
    for upper_slot in range(slot + 1, active_count + 1):
        suffix = "" if upper_slot == 1 else f"_Slot{upper_slot}"
        msg = coordinator.get_message(CIRCUIT_BASS3, f"{prefix}_{day_name}{suffix}")
        fields = (
            [msg.get(k) for k in ("from_hour", "from_min", "to_hour", "to_min")]
            if msg
            else []
        )
        if not fields or any(v is None for v in fields):
            raise HomeAssistantError(
                f"Cannot safely modify slot {slot} on {day_name}: current data of "
                f"slot {upper_slot} is unknown, rewriting would erase it. "
                "Wait for the schedule to be read from the bus and retry."
            )
        try:
            hh1, mm1, hh2, mm2 = (int(v) for v in fields if v is not None)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"Invalid stored data for slot {upper_slot} on {day_name}."
            ) from err
        upper.append((upper_slot, f"{hh1};{mm1};{hh2};{mm2}"))
    return upper


def upper_slots_to_writes(
    prefix: str, day_name: str, upper_slots: list[tuple[int, str]]
) -> list[tuple[str, str]]:
    """Convert snapshotted upper slots into ordered (message, payload) writes."""
    return [(f"{prefix}_{day_name}_Slot{n}", data) for n, data in upper_slots]


def _get_default_circuit_temp(
    coordinator: SaunierGeniaCoordinator, circuit_type: str
) -> float:
    """Return default or active target temperature for a timer circuit."""
    if circuit_type == "dhw":
        msg = coordinator.get_message(CIRCUIT_BASS3, "HwcTempDesired") or {}
        raw = msg.get("temp", msg.get("value"))
        if raw is not None:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
        return 50.0
    if circuit_type == "heating":
        msg = coordinator.get_message(CIRCUIT_BASS3, "Z1ManualTemp") or {}
        raw = msg.get("temp", msg.get("value"))
        if raw is not None:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
        return 20.0
    if circuit_type == "cooling":
        msg = coordinator.get_message(CIRCUIT_BASS3, "Z1CoolingManualTemp") or {}
        raw = msg.get("temp", msg.get("value"))
        if raw is None:
            msg = coordinator.get_message(CIRCUIT_BASS3, "Z1CoolingTempDesired") or {}
            raw = msg.get("temp", msg.get("value"))
        if raw is not None:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass
        return 22.0
    # Circulation uses 20.0 as standard dummy temperature setpoint in eBUS telegrams
    return 20.0


async def _async_collect_day_writes(
    coordinator: SaunierGeniaCoordinator,
    prefix: str,
    day_name: str,
    new_total: int,
    target_slot: int,
    target_from_h: int,
    target_from_m: int,
    target_to_h: int,
    target_to_m: int,
    target_temp: float,
    default_temp: float,
) -> list[tuple[str, str]]:
    """Generate ordered (message, payload) writes for all active slots of day_name.

    In the b5 55 a6 protocol, all active slots for a given day must be written
    with total_slots equal to new_total and include the target temperature setpoint.
    """
    writes: list[tuple[str, str]] = []
    for s_idx in range(1, new_total + 1):
        suffix = "" if s_idx == 1 else f"_Slot{s_idx}"
        msg_name = f"{prefix}_{day_name}{suffix}"
        if s_idx == target_slot:
            fh = target_from_h
            fm = target_from_m
            th = target_to_h
            tm = target_to_m
            slot_temp = target_temp
        else:
            msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
            fields = (
                [msg.get(k) for k in ("from_hour", "from_min", "to_hour", "to_min")]
                if msg
                else []
            )
            if (not fields or any(v is None for v in fields)) and hasattr(
                coordinator, "async_request_get"
            ):
                with contextlib.suppress(Exception):
                    await coordinator.async_request_get(CIRCUIT_BASS3, msg_name)
                    for _ in range(10):
                        await asyncio.sleep(0.05)
                        msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
                        fields = (
                            [
                                msg.get(k)
                                for k in (
                                    "from_hour",
                                    "from_min",
                                    "to_hour",
                                    "to_min",
                                )
                            ]
                            if msg
                            else []
                        )
                        if fields and not any(v is None for v in fields):
                            break
            if not fields or any(v is None for v in fields):
                raise HomeAssistantError(
                    f"Cannot safely modify slot {target_slot} on {day_name}: current data of "
                    f"slot {s_idx} is unknown, rewriting would erase it. "
                    "Wait for the schedule to be read from the bus and retry."
                )
            try:
                raw_fh, raw_fm, raw_th, raw_tm = (
                    int(v) for v in fields if v is not None
                )
            except (TypeError, ValueError) as err:
                raise HomeAssistantError(
                    f"Invalid stored data for slot {s_idx} on {day_name}."
                ) from err
            fh = raw_fh
            fm = raw_fm
            th = (
                24
                if (raw_th == 24 or (raw_th == 0 and raw_tm == 0 and raw_fh > 0))
                else raw_th
            )
            tm = 0 if th == 24 else raw_tm
            raw_temp = msg.get("temp", msg.get("cooling_temp")) if msg else None
            try:
                slot_temp = float(raw_temp) if raw_temp is not None else default_temp
            except (ValueError, TypeError):
                slot_temp = default_temp

        if prefix == "CirculationTimer":
            payload = f"{new_total};{fh};{fm};{th};{tm}"
        else:
            payload = f"{new_total};{fh};{fm};{th};{tm};{slot_temp:.1f}"
        writes.append((msg_name, payload))
    return writes


async def _async_hydrate_day_schedule(
    coordinator: SaunierGeniaCoordinator,
    prefix: str,
    day_name: str,
    active_count: int,
    exclude_slot: int | None = None,
    timeout: float = 2.0,
) -> None:
    """Read all active slots for day_name from physical bus via MQTT if not already cached."""
    if not hasattr(coordinator, "async_request_get"):
        return
    for s_idx in range(1, active_count + 1):
        if s_idx == exclude_slot:
            continue
        suffix = "" if s_idx == 1 else f"_Slot{s_idx}"
        msg_name = f"{prefix}_{day_name}{suffix}"
        msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
        fields = (
            [msg.get(k) for k in ("from_hour", "from_min", "to_hour", "to_min")]
            if msg
            else []
        )
        if not fields or any(v is None for v in fields):
            with contextlib.suppress(Exception):
                await coordinator.async_request_get(CIRCUIT_BASS3, msg_name)
                for _ in range(int(timeout / 0.1)):
                    await asyncio.sleep(0.1)
                    msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
                    fields = (
                        [
                            msg.get(k)
                            for k in (
                                "from_hour",
                                "from_min",
                                "to_hour",
                                "to_min",
                            )
                        ]
                        if msg
                        else []
                    )
                    if fields and not any(v is None for v in fields):
                        break


def _validate_daily_schedule(
    coordinator: SaunierGeniaCoordinator,
    prefix: str,
    day_name: str,
    slot: int,
    from_minutes: int,
    to_minutes: int,
    start_time_str: str,
    end_time_str: str,
    active_count: int,
) -> None:
    """Validate that all slots for `day_name` are in chronological order without overlapping."""
    day_total = max(active_count, slot)
    slots_map: dict[int, tuple[int, int, str, str]] = {}
    slots_map[slot] = (from_minutes, to_minutes, start_time_str, end_time_str)

    for s_idx in range(1, day_total + 1):
        if s_idx == slot:
            continue
        suffix = "" if s_idx == 1 else f"_Slot{s_idx}"
        msg = coordinator.get_message(CIRCUIT_BASS3, f"{prefix}_{day_name}{suffix}")
        fields = (
            [msg.get(k) for k in ("from_hour", "from_min", "to_hour", "to_min")]
            if msg
            else []
        )
        if not fields or any(v is None for v in fields):
            raise HomeAssistantError(
                f"Cannot safely modify slot {slot} on {day_name}: current data of slot {s_idx} "
                "is unknown. Wait for eBUS telemetry before modifying the schedule."
            )
        try:
            h1, m1, h2, m2 = (int(v) for v in fields if v is not None)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"Invalid stored data for slot {s_idx} on {day_name}."
            ) from err

        s_start = h1 * 60 + m1
        s_end = (
            1440
            if (h2 == 24 or (h2 == 0 and m2 == 0 and s_start > 0))
            else (h2 * 60 + m2)
        )
        end_display = "24:00" if s_end == 1440 else f"{h2:02d}:{m2:02d}"
        slots_map[s_idx] = (s_start, s_end, f"{h1:02d}:{m1:02d}", end_display)

    sorted_slots = sorted(slots_map.items(), key=lambda item: item[0])
    for i in range(len(sorted_slots) - 1):
        idx_a, (_start_a, end_a, str_start_a, str_end_a) = sorted_slots[i]
        idx_b, (start_b, _end_b, str_start_b, str_end_b) = sorted_slots[i + 1]

        if start_b < end_a:
            raise HomeAssistantError(
                f"Slot {idx_b} ({str_start_b} - {str_end_b}) overlaps with "
                f"slot {idx_a} ({str_start_a} - {str_end_a}) on {day_name}. "
                "Slots must be in chronological order without overlapping."
            )


SERIAL_PATTERN = re.compile(r"^[0-9A-Za-z]{20,32}$")


def _anonymize_value(val: Any, key_name: str = "") -> Any:
    """Recursively mask sensitive serial numbers and hardware identifiers."""
    if isinstance(val, str):
        val_stripped = val.strip()
        if SERIAL_PATTERN.match(val_stripped):
            if len(val_stripped) > 16:
                return f"{val_stripped[:12]}{'*' * (len(val_stripped) - 16)}{val_stripped[-4:]}"
            return (
                f"{val_stripped[:4]}{'*' * (len(val_stripped) - 8)}{val_stripped[-4:]}"
            )
        if any(s in key_name.lower() for s in ("serial", "barcode", "ident")):
            if len(val_stripped) > 8:
                return f"{val_stripped[:4]}{'*' * (len(val_stripped) - 8)}{val_stripped[-4:]}"
            return "****"
        return val
    if isinstance(val, dict):
        return {k: _anonymize_value(v, str(k)) for k, v in val.items()}
    if isinstance(val, list):
        return [_anonymize_value(item, key_name) for item in val]
    return val


def _async_register_services(hass: HomeAssistant) -> None:
    """Register custom domain services for weekly schedule timers and forced DHW boost."""
    if not hass.services.has_service(DOMAIN, SERVICE_SET_WEEKLY_TIMER):

        async def _async_handle_set_weekly_timer(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.set_weekly_timer service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            circuit_type: str = call.data["circuit_type"]
            raw_day: str = call.data["day"]
            day_selection = normalize_day_name(raw_day)
            action: str = str(call.data.get("action", "set")).strip().lower()
            slot: int = int(call.data.get("slot", 1))
            start_time_raw: str | None = call.data.get("start_time")
            end_time_raw: str | None = call.data.get("end_time")
            temp_input: float | None = call.data.get("temp")
            reset_remaining: bool = bool(call.data.get("reset_remaining", False))

            if action == "set":
                if not start_time_raw or not end_time_raw:
                    raise HomeAssistantError(
                        "Parameters 'start_time' and 'end_time' are required when action is 'set'."
                    )
                start_time = start_time_raw.strip()
                end_time = end_time_raw.strip()
                from_h, from_m = _parse_hhmm(start_time, is_end=False)
                to_h, to_m = _parse_hhmm(end_time, is_end=True)

                from_minutes = _time_to_minutes(from_h, from_m, is_end=False)
                to_minutes = _time_to_minutes(
                    to_h, to_m, is_end=True, start_minutes=from_minutes
                )

                if from_minutes >= to_minutes:
                    if from_minutes == 0 and to_minutes == 0:
                        raise HomeAssistantError(
                            "Start time '00:00' cannot be equal to end time '00:00'. "
                            "To program a full 24-hour day (all day), set end_time to '24:00'. "
                            "To delete this slot or clear the day, set action to 'delete' or 'clear'."
                        )
                    if from_minutes == to_minutes:
                        raise HomeAssistantError(
                            f"Start time '{start_time}' cannot be equal to end time '{end_time}'. "
                            "To delete this slot or clear the day, set action to 'delete' or 'clear'."
                        )
                    raise HomeAssistantError(
                        f"Start time '{start_time}' must be earlier than end time '{end_time}'. "
                        "Time slots cannot cross midnight into the next day."
                    )

                # Wire encoding: if end is midnight (1440 minutes), write hour 24
                wire_to_h = 24 if to_minutes == 1440 else to_h
                wire_to_m = 0 if to_minutes == 1440 else to_m
            else:
                start_time = ""
                end_time = ""
                from_h = from_m = wire_to_h = wire_to_m = 0
                from_minutes = to_minutes = 0

            prefix = TIMER_CIRCUIT_PREFIXES[circuit_type]

            if day_selection == "Weekdays":
                target_days = WEEKDAYS_LIST[:5]
            elif day_selection == "Weekend":
                target_days = WEEKDAYS_LIST[5:]
            elif day_selection == "All":
                target_days = WEEKDAYS_LIST
            else:
                target_days = [day_selection]

            for coordinator in coordinators.values():
                if not coordinator.is_ebus_operational:
                    raise HomeAssistantError(
                        "Cannot execute service: eBUS communication is not operational."
                    )

                async with coordinator.timer_write_lock:
                    default_temp = _get_default_circuit_temp(coordinator, circuit_type)
                    target_temp = (
                        float(temp_input) if temp_input is not None else default_temp
                    )

                    # Validate every target day BEFORE writing anything, so a rejected
                    # request never leaves the schedule half-modified.
                    plans: list[tuple[str, int, list[tuple[str, str]]]] = []
                    for day_name in target_days:
                        if action == "clear":
                            clear_payload = (
                                "0;0;0;0;0"
                                if prefix == "CirculationTimer"
                                else f"0;0;0;0;0;{default_temp:.1f}"
                            )
                            writes = [(f"{prefix}_{day_name}", clear_payload)]
                            plans.append((day_name, 0, writes))
                            continue

                        active_count = _get_active_slot_count(
                            coordinator, prefix, day_name
                        )
                        if (
                            active_count is None
                            and reset_remaining
                            and slot == 1
                            and action == "set"
                        ):
                            # Explicit single slot overwrite requested: no prior slot state needed
                            active_count = 1

                        if active_count is None and hasattr(
                            coordinator, "async_request_get"
                        ):
                            with contextlib.suppress(Exception):
                                await coordinator.async_request_get(
                                    CIRCUIT_BASS3, f"{prefix}_Slots"
                                )
                                for _ in range(25):
                                    await asyncio.sleep(0.1)
                                    active_count = _get_active_slot_count(
                                        coordinator, prefix, day_name
                                    )
                                    if active_count is not None:
                                        break

                        if active_count is None:
                            raise HomeAssistantError(
                                f"Cannot modify schedule for {day_name}: active slot count "
                                f"({prefix}_Slots) is not known yet. Wait for eBUS telemetry, "
                                "or pass 'reset_remaining: true' with slot 1 to overwrite the schedule without waiting."
                            )

                        if action == "delete":
                            empty_payload = (
                                "0;0;0;0;0"
                                if prefix == "CirculationTimer"
                                else f"0;0;0;0;0;{default_temp:.1f}"
                            )
                            if active_count == 0 or slot > active_count:
                                # Day is already empty or slot does not exist: clear to 0 safely
                                writes = [(f"{prefix}_{day_name}", empty_payload)]
                                plans.append((day_name, 0, writes))
                                continue

                            # Hydrate all active slots of this day to preserve remaining ones
                            await _async_hydrate_day_schedule(
                                coordinator=coordinator,
                                prefix=prefix,
                                day_name=day_name,
                                active_count=active_count,
                                exclude_slot=None,
                            )

                            if active_count <= 1:
                                # Deleting the only active slot clears the day to 0 slots
                                writes = [(f"{prefix}_{day_name}", empty_payload)]
                                plans.append((day_name, 0, writes))
                            else:
                                remaining_slots: list[
                                    tuple[int, int, int, int, float]
                                ] = []
                                for s_idx in range(1, active_count + 1):
                                    if s_idx == slot:
                                        continue
                                    suffix = "" if s_idx == 1 else f"_Slot{s_idx}"
                                    msg = (
                                        coordinator.get_message(
                                            CIRCUIT_BASS3,
                                            f"{prefix}_{day_name}{suffix}",
                                        )
                                        or {}
                                    )
                                    try:
                                        fh = int(msg.get("from_hour", 0))
                                        fm = int(msg.get("from_min", 0))
                                        th = int(msg.get("to_hour", 0))
                                        tm = int(msg.get("to_min", 0))
                                        raw_t = msg.get("temp", msg.get("cooling_temp"))
                                        st = (
                                            float(raw_t)
                                            if raw_t is not None
                                            else default_temp
                                        )
                                    except (TypeError, ValueError):
                                        fh = fm = th = tm = 0
                                        st = default_temp
                                    remaining_slots.append((fh, fm, th, tm, st))

                                new_total = len(remaining_slots)
                                writes = []
                                for new_idx, (
                                    fh,
                                    fm,
                                    th,
                                    tm,
                                    st,
                                ) in enumerate(remaining_slots, 1):
                                    suffix = "" if new_idx == 1 else f"_Slot{new_idx}"
                                    payload = (
                                        f"{new_total};{fh};{fm};{th};{tm}"
                                        if prefix == "CirculationTimer"
                                        else f"{new_total};{fh};{fm};{th};{tm};{st:.1f}"
                                    )
                                    writes.append(
                                        (
                                            f"{prefix}_{day_name}{suffix}",
                                            payload,
                                        )
                                    )
                                plans.append((day_name, new_total, writes))
                            continue

                        # action == "set"
                        if slot > active_count + 1:
                            raise HomeAssistantError(
                                f"Cannot write slot {slot} on {day_name}: only "
                                f"{active_count} slot(s) are currently active. "
                                f"Fill slot {active_count + 1} first."
                            )

                        new_total = slot if reset_remaining else max(active_count, slot)

                        if not (reset_remaining and slot == 1):
                            await _async_hydrate_day_schedule(
                                coordinator=coordinator,
                                prefix=prefix,
                                day_name=day_name,
                                active_count=active_count,
                                exclude_slot=slot,
                            )

                        _validate_daily_schedule(
                            coordinator=coordinator,
                            prefix=prefix,
                            day_name=day_name,
                            slot=slot,
                            from_minutes=from_minutes,
                            to_minutes=to_minutes,
                            start_time_str=start_time,
                            end_time_str=end_time,
                            active_count=new_total if reset_remaining else active_count,
                        )

                        writes = await _async_collect_day_writes(
                            coordinator=coordinator,
                            prefix=prefix,
                            day_name=day_name,
                            new_total=new_total,
                            target_slot=slot,
                            target_from_h=from_h,
                            target_from_m=from_m,
                            target_to_h=wire_to_h,
                            target_to_m=wire_to_m,
                            target_temp=target_temp,
                            default_temp=default_temp,
                        )
                        plans.append((day_name, new_total, writes))

                    # Physical eBUS bus runs at 2400 baud (~240 bytes/s) with hardware collision
                    # arbitration. Consecutive writes require pacing (~600 ms) to prevent
                    # bus arbitration collisions with MiPro Sense or buffer overflows.
                    first_write = True
                    for day_name, new_total, writes in plans:
                        try:
                            # In b5 55 a6 protocol, all active slots for a day carry total_slots = new_total
                            for message, msg_payload in writes:
                                if not first_write:
                                    await asyncio.sleep(0.6)
                                first_write = False
                                await coordinator.async_write_parameter(
                                    CIRCUIT_BASS3, message, msg_payload
                                )
                            # Update optimistic counter only after the full day's cascade finishes cleanly
                            coordinator.async_set_optimistic_active_slots(
                                prefix, day_name, new_total
                            )
                        except Exception as err:
                            _LOGGER.error(
                                "Failed while writing schedule cascade for %s on %s: %s. "
                                "Invalidating cached active slot count for safety.",
                                prefix,
                                day_name,
                                err,
                            )
                            coordinator.async_invalidate_active_slots(prefix, day_name)
                            raise HomeAssistantError(
                                f"Failed to complete weekly timer write cascade on {day_name}: {err}. "
                                "Cached slot count has been invalidated for safety."
                            ) from err

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
                if not coordinator.is_ebus_operational:
                    raise HomeAssistantError(
                        "Cannot execute service: eBUS communication is not operational."
                    )
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
                if not coordinator.is_ebus_operational:
                    raise HomeAssistantError(
                        "Cannot execute service: eBUS communication is not operational."
                    )
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
                if not coordinator.is_ebus_operational:
                    raise HomeAssistantError(
                        "Cannot execute service: eBUS communication is not operational."
                    )
                await coordinator.async_cancel_holiday_mode()

        hass.services.async_register(
            DOMAIN,
            SERVICE_CANCEL_HOLIDAY_MODE,
            _async_handle_cancel_holiday_mode,
            schema=CANCEL_HOLIDAY_MODE_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_QUICK_VETO):

        async def _async_handle_quick_veto(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.quick_veto service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            temperature: float | None = call.data.get("temperature")
            duration: float | None = call.data.get("duration")

            for coordinator in coordinators.values():
                if coordinator.is_cooling_active():
                    await coordinator.async_set_cooling_quick_veto(
                        temperature=temperature,
                        duration=duration,
                    )
                else:
                    await coordinator.async_set_quick_veto(
                        temperature=temperature,
                        duration=duration,
                    )

        hass.services.async_register(
            DOMAIN,
            SERVICE_QUICK_VETO,
            _async_handle_quick_veto,
            schema=QUICK_VETO_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CANCEL_QUICK_VETO):

        async def _async_handle_cancel_quick_veto(call: ServiceCall) -> None:
            """Handle arotherm_genia_ebusd.cancel_quick_veto service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            for coordinator in coordinators.values():
                if coordinator.cooling_quick_veto_active:
                    await coordinator.async_cancel_cooling_quick_veto(restore=True)
                else:
                    await coordinator.async_cancel_quick_veto()

        hass.services.async_register(
            DOMAIN,
            SERVICE_CANCEL_QUICK_VETO,
            _async_handle_cancel_quick_veto,
            schema=CANCEL_QUICK_VETO_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_DUMP_MQTT_VALUES):

        async def _async_handle_dump_mqtt_values(
            call: ServiceCall,
        ) -> ServiceResponse:
            """Handle arotherm_genia_ebusd.dump_mqtt_values service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            target_circuit: str | None = call.data.get("circuit")
            anonymize: bool = bool(call.data.get("anonymize", True))
            results: dict[str, Any] = {}

            for idx, (entry_id, coordinator) in enumerate(coordinators.items(), 1):
                bus_state: dict[str, dict[str, Any]] = {}
                for (circuit, msg_name), values in coordinator._state.items():
                    if target_circuit and target_circuit.lower() not in circuit.lower():
                        continue
                    payload = _anonymize_value(values) if anonymize else values
                    bus_state.setdefault(circuit, {})[msg_name] = payload

                safe_entry_id = (
                    (
                        f"anonymized_entry_{idx}"
                        if len(coordinators) > 1
                        else "anonymized_entry_id"
                    )
                    if anonymize
                    else entry_id
                )

                results[safe_entry_id] = {
                    "domain": DOMAIN,
                    "entry_id": safe_entry_id,
                    "anonymized": anonymize,
                    "mqtt_prefix": coordinator.mqtt_prefix,
                    "is_ebus_operational": coordinator.is_ebus_operational,
                    "outdoor_model": coordinator.outdoor_model,
                    "indoor_model": coordinator.indoor_model,
                    "active_outdoor_circuit": coordinator.active_outdoor_circuit,
                    "active_controller_circuit": coordinator.active_controller_circuit,
                    "cached_messages_count": sum(
                        len(msgs) for msgs in bus_state.values()
                    ),
                    "values": bus_state,
                }

            if len(results) == 1:
                return next(iter(results.values()))
            return results

        hass.services.async_register(
            DOMAIN,
            SERVICE_DUMP_MQTT_VALUES,
            _async_handle_dump_mqtt_values,
            schema=DUMP_MQTT_VALUES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RECORD_TOPIC_CHANGES):

        async def _async_handle_record_topic_changes(
            call: ServiceCall,
        ) -> ServiceResponse:
            """Handle arotherm_genia_ebusd.record_topic_changes service call."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

            duration: int = int(call.data.get("duration", 30))
            target_circuit: str | None = call.data.get("circuit")
            anonymize: bool = bool(call.data.get("anonymize", True))

            records: list[dict[str, Any]] = []

            @callback
            def _on_record_message(msg: mqtt.ReceiveMessage) -> None:
                topic = msg.topic
                if target_circuit and target_circuit.lower() not in topic.lower():
                    return

                raw_payload = msg.payload
                payload_str = (
                    raw_payload
                    if isinstance(raw_payload, str)
                    else raw_payload.decode("utf-8", errors="replace")
                )
                try:
                    payload_data = json.loads(payload_str)
                except (json.JSONDecodeError, ValueError):
                    payload_data = payload_str

                if anonymize:
                    payload_data = _anonymize_value(payload_data, key_name=topic)

                records.append(
                    {
                        "timestamp": dt_util.utcnow().isoformat(),
                        "topic": topic,
                        "payload": payload_data,
                        "retained": bool(msg.retain),
                        "qos": msg.qos,
                    }
                )

            prefixes = list({coord.mqtt_prefix for coord in coordinators.values()})
            unsubs: list[Callable[[], None]] = []
            try:
                for prefix in prefixes:
                    unsub = await mqtt.async_subscribe(
                        hass, f"{prefix}/#", _on_record_message, qos=0
                    )
                    unsubs.append(unsub)
                await asyncio.sleep(duration)
            except Exception as err:
                raise HomeAssistantError(f"Error recording MQTT topics: {err}") from err
            finally:
                for unsub in unsubs:
                    unsub()

            return {
                "duration_seconds": duration,
                "anonymized": anonymize,
                "mqtt_prefixes": prefixes if len(prefixes) > 1 else prefixes[0],
                "circuit_filter": target_circuit,
                "message_count": len(records),
                "records": records,
            }

        hass.services.async_register(
            DOMAIN,
            SERVICE_RECORD_TOPIC_CHANGES,
            _async_handle_record_topic_changes,
            schema=RECORD_TOPIC_CHANGES_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_HEX_COMMAND):

        async def _async_handle_send_hex_command(
            call: ServiceCall,
        ) -> ServiceResponse:
            """Handle arotherm_genia_ebusd.send_hex_command service call via TCP socket."""
            entries = hass.config_entries.async_entries(DOMAIN)
            is_hex_enabled = any(
                entry.options.get(CONF_ENABLE_SEND_HEX, DEFAULT_ENABLE_SEND_HEX)
                for entry in entries
            )
            if not is_hex_enabled:
                raise HomeAssistantError(
                    "The send_hex_command service is disabled for security reasons. "
                    "To enable it, navigate to Settings > Devices & Services > "
                    "aroTHERM & GeniaAir (eBUS) > Configure and enable 'send_hex_command'."
                )

            command_raw = str(call.data["command"]).strip().replace(" ", "")
            if not command_raw or not all(
                c in "0123456789abcdefABCDEF" for c in command_raw
            ):
                raise HomeAssistantError(
                    f"Invalid hexadecimal command '{call.data['command']}'. "
                    "Must contain only valid hexadecimal characters."
                )

            active_entry = next(
                (
                    e
                    for e in entries
                    if e.options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP)
                ),
                entries[0] if entries else None,
            )
            default_host = (
                str(
                    active_entry.options.get(
                        CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST
                    )
                ).strip()
                if active_entry
                else DEFAULT_EBUSD_TCP_HOST
            )
            default_port = (
                int(
                    active_entry.options.get(
                        CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT
                    )
                )
                if active_entry
                else DEFAULT_EBUSD_TCP_PORT
            )

            host = str(call.data.get("host") or default_host).strip()
            port = int(call.data.get("port") or default_port)
            timeout = float(call.data.get("timeout", 5.0))

            reader: asyncio.StreamReader | None = None
            writer: asyncio.StreamWriter | None = None
            try:
                try:
                    connect_coro = asyncio.open_connection(host, port)
                    reader, writer = await asyncio.wait_for(
                        connect_coro, timeout=timeout
                    )
                except (TimeoutError, OSError):
                    if host in ("127.0.0.1", "localhost"):
                        fallback_hosts = ("b4d7ad18-ebusd", "local-ebusd", "ebusd")
                        connected = False
                        for fb_host in fallback_hosts:
                            try:
                                connect_coro = asyncio.open_connection(fb_host, port)
                                reader, writer = await asyncio.wait_for(
                                    connect_coro, timeout=timeout
                                )
                                host = fb_host
                                connected = True
                                break
                            except (TimeoutError, OSError):
                                continue
                        if not connected:
                            raise
                    else:
                        raise
                if reader is None or writer is None:
                    raise HomeAssistantError(
                        f"Could not connect to eBUSd TCP daemon at {host}:{port}"
                    )
                writer.write(f"hex {command_raw}\n".encode("ascii"))
                await writer.drain()

                read_coro = reader.readline()
                raw_response = await asyncio.wait_for(read_coro, timeout=timeout)
                response_str = raw_response.decode("ascii", errors="replace").strip()
            except TimeoutError as err:
                raise HomeAssistantError(
                    f"Timeout ({timeout}s) connecting to or reading from eBUSd daemon at {host}:{port}"
                ) from err
            except OSError as err:
                raise HomeAssistantError(
                    f"Could not connect to eBUSd TCP daemon at {host}:{port}: {err}. "
                    "Please verify that eBUSd is reachable and that its TCP port (8888) is open."
                ) from err
            finally:
                if writer is not None:
                    writer.close()
                    with contextlib.suppress(OSError):
                        await writer.wait_closed()

            is_error = response_str.startswith("ERR:")
            return {
                "command": command_raw,
                "response": response_str,
                "success": not is_error,
                "host": host,
                "port": port,
            }

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_HEX_COMMAND,
            _async_handle_send_hex_command,
            schema=SEND_HEX_COMMAND_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_READ_PARAMETER):

        async def _async_handle_read_parameter(
            call: ServiceCall,
        ) -> ServiceResponse:
            """Handle arotherm_genia_ebusd.read_parameter service call via MQTT."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")
            coordinator = next(iter(coordinators.values()))

            circuit = str(call.data["circuit"]).strip()
            name = str(call.data["name"]).strip()
            force = bool(call.data.get("force", False))
            timeout = float(call.data.get("timeout", 5.0))

            if not circuit or not name:
                raise HomeAssistantError(
                    "Both 'circuit' and 'name' parameters must be non-empty strings."
                )

            target_circuit = coordinator.resolve_circuit(circuit)

            # Return immediately from cache if force is False and data is already cached
            if not force:
                cached_msg = coordinator.get_message(
                    target_circuit, name
                ) or coordinator.get_message(circuit, name)
                if cached_msg is not None:
                    return {
                        "circuit": circuit,
                        "target_circuit": target_circuit,
                        "name": name,
                        "value": cached_msg,
                        "cached": True,
                    }

            # Set up notification event for the response
            event = asyncio.Event()

            def _on_update() -> None:
                event.set()

            unsub_target = coordinator.async_add_listener(
                target_circuit, name, _on_update
            )
            unsub_circuit = (
                coordinator.async_add_listener(circuit, name, _on_update)
                if circuit.lower() != target_circuit.lower()
                else None
            )

            try:
                await coordinator.async_request_get(circuit, name)
                try:
                    await asyncio.wait_for(event.wait(), timeout=timeout)
                except TimeoutError as err:
                    raise HomeAssistantError(
                        f"Timeout waiting for eBUSd MQTT response on '{target_circuit}/{name}' after {timeout}s"
                    ) from err
            finally:
                unsub_target()
                if unsub_circuit is not None:
                    unsub_circuit()

            value = coordinator.get_message(
                target_circuit, name
            ) or coordinator.get_message(circuit, name)
            return {
                "circuit": circuit,
                "target_circuit": target_circuit,
                "name": name,
                "value": value,
                "cached": False,
            }

        hass.services.async_register(
            DOMAIN,
            SERVICE_READ_PARAMETER,
            _async_handle_read_parameter,
            schema=READ_PARAMETER_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_PARAMETER):

        async def _async_handle_write_parameter(
            call: ServiceCall,
        ) -> ServiceResponse:
            """Handle arotherm_genia_ebusd.write_parameter service call via MQTT."""
            coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
            if not coordinators:
                raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")
            coordinator = next(iter(coordinators.values()))

            circuit = str(call.data["circuit"]).strip()
            name = str(call.data["name"]).strip()
            value = call.data["value"]

            if not circuit or not name:
                raise HomeAssistantError(
                    "Both 'circuit' and 'name' parameters must be non-empty strings."
                )

            target_circuit = coordinator.resolve_circuit(circuit)
            topic = f"{coordinator.mqtt_prefix}/{target_circuit}/{name}/set"

            try:
                await coordinator.async_write_parameter(circuit, name, value)
            except Exception as err:
                raise HomeAssistantError(
                    f"Failed to publish write parameter to '{topic}': {err}"
                ) from err

            return {
                "status": "success",
                "circuit": circuit,
                "target_circuit": target_circuit,
                "name": name,
                "value": str(value),
                "topic": topic,
            }

        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_PARAMETER,
            _async_handle_write_parameter,
            schema=WRITE_PARAMETER_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
