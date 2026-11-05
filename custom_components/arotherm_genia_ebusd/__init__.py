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
    DAY_SHORT_KEYS,
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

TIME_PATTERN = re.compile(r"^(([01]?\d|2[0-3]):([0-5]\d)|24:00)$")

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


def _time_to_minutes(hour: int, minute: int, is_end: bool = False) -> int:
    """Convert hour and minute into minutes from 00:00 (0 to 1440)."""
    if is_end and (hour == 24 or (hour == 0 and minute == 0)):
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

            from_h, from_m = _parse_hhmm(start_time, is_end=False)
            to_h, to_m = _parse_hhmm(end_time, is_end=True)

            from_minutes = _time_to_minutes(from_h, from_m, is_end=False)
            to_minutes = _time_to_minutes(to_h, to_m, is_end=True)

            if from_minutes >= to_minutes:
                raise HomeAssistantError(
                    f"Start time '{start_time}' must be earlier than end time '{end_time}'. "
                    "Time slots cannot cross midnight into the next day."
                )

            # Wire encoding: if end is midnight (1440 minutes), write hour 24
            wire_to_h = 24 if to_minutes == 1440 else to_h
            wire_to_m = 0 if to_minutes == 1440 else to_m

            prefix = TIMER_CIRCUIT_PREFIXES[circuit_type]
            slot_suffix = "" if slot == 1 else f"_Slot{slot}"
            payload = f"{from_h};{from_m};{wire_to_h};{wire_to_m}"

            if day_selection == "Weekdays":
                target_days = WEEKDAYS_LIST[:5]
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
                    # Validate every target day BEFORE writing anything, so a rejected
                    # request never leaves the schedule half-modified.
                    plans: list[tuple[str, list[tuple[int, str]], int]] = []
                    for day_name in target_days:
                        active_count = _get_active_slot_count(
                            coordinator, prefix, day_name
                        )
                        if active_count is None:
                            raise HomeAssistantError(
                                f"Cannot modify schedule for {day_name}: active slot count "
                                f"({prefix}_Slots) is not known yet. Wait for eBUS telemetry "
                                "or read the schedule first."
                            )
                        if slot > active_count + 1:
                            raise HomeAssistantError(
                                f"Cannot write slot {slot} on {day_name}: only "
                                f"{active_count} slot(s) are currently active. "
                                f"Fill slot {active_count + 1} first."
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
                            active_count=active_count,
                        )

                        upper_slots = _collect_upper_slots(
                            coordinator, prefix, day_name, slot, active_count
                        )
                        new_total = max(active_count, slot)
                        plans.append((day_name, upper_slots, new_total))

                    # Physical eBUS bus runs at 2400 baud (~240 bytes/s) with hardware collision
                    # arbitration. Consecutive writes require pacing (~600 ms) to prevent
                    # bus arbitration collisions with MiPro Sense or buffer overflows.
                    first_write = True
                    for day_name, upper_slots, new_total in plans:
                        try:
                            # The b5 55 write command carries a hardcoded total_slots byte equal to
                            # the slot index, so writing slot N truncates the day to N slots.
                            # Rewrite the previously active upper slots (ascending) with their
                            # current data afterwards to restore the correct total_slots.
                            writes: list[tuple[str, str]] = [
                                (f"{prefix}_{day_name}{slot_suffix}", payload),
                                *upper_slots_to_writes(prefix, day_name, upper_slots),
                            ]
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
