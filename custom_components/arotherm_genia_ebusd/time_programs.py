"""Weekly time program read/write service handlers (b5 55 protocol).

Implements ``read_time_program`` and ``write_time_program`` response services
following the shared contract used by Home Assistant schedule cards such as
``citoki/ebusd-time-program`` (``source: arotherm_genia_ebusd``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from time import monotonic as _monotonic_time
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CIRCUIT_BASS3,
    CIRCUIT_GLOBAL,
    DAY_SHORT_KEYS,
    DOMAIN,
    WEEKDAYS_LIST,
)
from .coordinator import SaunierGeniaCoordinator

_LOGGER = logging.getLogger(__name__)

MAX_SLOTS_PER_DAY = 3
TIME_GRID_MINUTES = 10
WRITE_PACING_SECONDS = 0.6
READBACK_SETTLE_SECONDS = 0.5
READBACK_STEP_DELAY_SECONDS = 0.3
BUS_READ_TIMEOUT_SECONDS = 4.0
TEMP_MATCH_TOLERANCE_C = 0.15

_HHMM_RE = re.compile(r"^(([01]?\d|2[0-3]):([0-5]\d)|24:00)$")
_DAY_LOWER_TO_CANONICAL: dict[str, str] = {day.lower(): day for day in WEEKDAYS_LIST}


@dataclass(frozen=True, kw_only=True)
class TimeProgramSpec:
    """Metadata describing a supported b5 55 weekly time program."""

    program: str
    circuit_type: str
    has_temperature: bool
    write_noop_temp: bool = False
    temp_field: str | None = None
    min_temp: float | None = None
    max_temp: float | None = None
    default_temp: float = 20.0
    aliases: tuple[str, ...] = ()


TIME_PROGRAM_SPECS: tuple[TimeProgramSpec, ...] = (
    TimeProgramSpec(
        program="Z1Timer",
        circuit_type="heating",
        has_temperature=True,
        temp_field="temp",
        min_temp=5.0,
        max_temp=30.0,
        default_temp=20.0,
        aliases=("z1", "heating"),
    ),
    TimeProgramSpec(
        program="HwcTimer",
        circuit_type="dhw",
        # HwcTimer uses a single shared DHW setpoint (HwcTempDesired) rather than
        # per-slot temperatures; writing '-' (0xFFFF) updates time slots without
        # mutating HwcTempDesired (matching VR940 / MiGo Link behavior).
        has_temperature=False,
        write_noop_temp=True,
        aliases=("hwc", "dhw"),
    ),
    TimeProgramSpec(
        program="CoolingTimer",
        circuit_type="cooling",
        has_temperature=True,
        temp_field="cooling_temp",
        min_temp=15.0,
        max_temp=30.0,
        default_temp=22.0,
        aliases=("cooling",),
    ),
    TimeProgramSpec(
        program="CirculationTimer",
        circuit_type="circulation",
        has_temperature=False,
        aliases=("cc", "circulation"),
    ),
    TimeProgramSpec(
        program="SilentTimer",
        circuit_type="silent",
        has_temperature=False,
        aliases=("silent",),
    ),
)

_PROGRAM_LOOKUP: dict[str, TimeProgramSpec] = {}
for _spec in TIME_PROGRAM_SPECS:
    _PROGRAM_LOOKUP[_spec.program.lower()] = _spec
    for _alias in _spec.aliases:
        _PROGRAM_LOOKUP[_alias.lower()] = _spec


@dataclass(frozen=True, kw_only=True)
class ParsedTimeSlot:
    """Validated 10-minute-grid time slot ready for b5 55 encoding."""

    from_hour: int
    from_min: int
    to_hour: int
    to_min: int
    temperature: float | None = None

    @property
    def start_minutes(self) -> int:
        """Start time in minutes since 00:00."""
        return self.from_hour * 60 + self.from_min

    @property
    def end_minutes(self) -> int:
        """End time in minutes since 00:00 (up to 1440)."""
        return self.to_hour * 60 + self.to_min

    @property
    def start_str(self) -> str:
        """Format start time as HH:MM."""
        return f"{self.from_hour:02d}:{self.from_min:02d}"

    @property
    def end_str(self) -> str:
        """Format end time as HH:MM (24:00 for end-of-day midnight)."""
        if self.end_minutes == 1440:
            return "24:00"
        return f"{self.to_hour:02d}:{self.to_min:02d}"

    def to_response_dict(self, *, include_temperature: bool) -> dict[str, Any]:
        """Serialize slot into the service response format."""
        result: dict[str, Any] = {"start": self.start_str, "end": self.end_str}
        if include_temperature and self.temperature is not None:
            result["temperature"] = round(self.temperature, 1)
        return result


TIME_PROGRAM_SLOT_SCHEMA = vol.Schema(
    {
        vol.Required("start"): cv.string,
        vol.Required("end"): cv.string,
        vol.Optional("temperature"): vol.Any(None, vol.Coerce(float)),
    }
)

READ_TIME_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required("program"): cv.string,
        vol.Optional("entry_id"): vol.Any(None, cv.string),
    }
)

WRITE_TIME_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required("program"): cv.string,
        vol.Required("days"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("slots"): [TIME_PROGRAM_SLOT_SCHEMA],
        vol.Optional("entry_id"): vol.Any(None, cv.string),
    }
)


def resolve_time_program_spec(raw_program: str) -> TimeProgramSpec:
    """Resolve a program identifier or raise the standard unsupported-program error."""
    cleaned = str(raw_program).strip()
    spec = _PROGRAM_LOOKUP.get(cleaned.lower())
    if spec is None:
        raise HomeAssistantError(
            f"Program '{cleaned}' is not available on this controller."
        )
    return spec


def _resolve_coordinator(
    hass: HomeAssistant, entry_id: str | None
) -> SaunierGeniaCoordinator:
    """Select the target coordinator by entry_id or prefer an operational one."""
    coordinators: dict[str, SaunierGeniaCoordinator] = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError(f"No configured instances of {DOMAIN} found.")

    if entry_id is not None and str(entry_id).strip():
        clean_id = str(entry_id).strip()
        coordinator = coordinators.get(clean_id)
        if coordinator is None:
            raise HomeAssistantError(
                f"Config entry '{clean_id}' not found for {DOMAIN}."
            )
        return coordinator

    return next(
        (c for c in coordinators.values() if c.is_ebus_operational),
        next(iter(coordinators.values())),
    )


def _get_default_program_temp(
    coordinator: SaunierGeniaCoordinator, spec: TimeProgramSpec
) -> float:
    """Return active circuit setpoint for a temperature-bearing program."""
    candidates: tuple[str, ...]
    if spec.circuit_type == "dhw":
        candidates = ("HwcTempDesired",)
    elif spec.circuit_type == "heating":
        candidates = ("Z1ManualTemp",)
    elif spec.circuit_type == "cooling":
        candidates = ("Z1CoolingManualTemp", "Z1CoolingTempDesired")
    else:
        return spec.default_temp

    for msg_name in candidates:
        msg = coordinator.get_message(CIRCUIT_BASS3, msg_name) or {}
        raw = msg.get("temp", msg.get("value"))
        if raw is not None:
            try:
                val = float(raw)
                if spec.min_temp is not None:
                    val = max(spec.min_temp, val)
                if spec.max_temp is not None:
                    val = min(spec.max_temp, val)
                return round(val, 1)
            except (TypeError, ValueError):
                continue
    return spec.default_temp


def _parse_hhmm_grid(raw_time: str, *, is_end: bool) -> tuple[int, int]:
    """Parse HH:MM and validate that it lies on the 10-minute hardware grid."""
    text = str(raw_time).strip()
    if not _HHMM_RE.match(text):
        raise HomeAssistantError(
            f"Invalid time '{raw_time}'. Expected 'HH:MM' between '00:00' and '24:00'."
        )
    hour_s, min_s = text.split(":")
    hour, minute = int(hour_s), int(min_s)
    if hour == 24:
        if minute != 0:
            raise HomeAssistantError(
                f"Invalid time '{raw_time}'. Midnight end must be '24:00'."
            )
        if not is_end:
            raise HomeAssistantError("Start time cannot be '24:00'.")
    if minute % TIME_GRID_MINUTES != 0:
        raise HomeAssistantError(
            f"Time '{raw_time}' must be on the {TIME_GRID_MINUTES}-minute grid."
        )
    return hour, minute


def _normalize_end_hhmm(
    from_h: int, from_m: int, to_h: int, to_m: int
) -> tuple[int, int]:
    """Normalize hardware 00:00 midnight end sentinel (when start > 00:00) to 24:00."""
    if to_h == 24 or (to_h == 0 and to_m == 0 and (from_h * 60 + from_m) > 0):
        return 24, 0
    return to_h, to_m


def _parse_slot_from_message(
    msg: dict[str, Any] | None, spec: TimeProgramSpec
) -> ParsedTimeSlot | None:
    """Decode a cached/fetched b5 55 timer slot message into a ParsedTimeSlot."""
    if not msg:
        return None
    raw_fh = msg.get("from_hour")
    raw_fm = msg.get("from_min")
    raw_th = msg.get("to_hour")
    raw_tm = msg.get("to_min")
    if raw_fh is None or raw_fm is None or raw_th is None or raw_tm is None:
        return None
    try:
        fh, fm, raw_th_i, raw_tm_i = (
            int(raw_fh),
            int(raw_fm),
            int(raw_th),
            int(raw_tm),
        )
    except (TypeError, ValueError):
        return None

    th, tm = _normalize_end_hhmm(fh, fm, raw_th_i, raw_tm_i)
    if (
        (fh == 0 and fm == 0 and th == 0 and tm == 0)
        or not (0 <= fh < 24 and 0 <= fm < 60)
        or not (0 <= th <= 24 and 0 <= tm < 60)
        or (th == 24 and tm != 0)
    ):
        return None
    if (th * 60 + tm) <= (fh * 60 + fm):
        return None

    temp_val: float | None = None
    if spec.has_temperature:
        raw_temp = msg.get(spec.temp_field) if spec.temp_field else None
        if raw_temp is None:
            raw_temp = msg.get("temp", msg.get("cooling_temp"))
        if raw_temp is not None:
            try:
                temp_val = round(float(raw_temp), 1)
            except (TypeError, ValueError):
                temp_val = None

    return ParsedTimeSlot(
        from_hour=fh,
        from_min=fm,
        to_hour=th,
        to_min=tm,
        temperature=temp_val,
    )


def _parse_slot_count(
    slots_msg: dict[str, Any] | None, day_canonical: str
) -> int | None:
    """Extract the 0..3 active slot count for a weekday from <prefix>_Slots."""
    if not slots_msg:
        return None
    raw = slots_msg.get(DAY_SHORT_KEYS[day_canonical])
    if raw is None or isinstance(raw, bool):
        return None
    try:
        count = int(float(raw)) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        return None
    return count if 0 <= count <= MAX_SLOTS_PER_DAY else None


def _slot_message_name(prefix: str, day_canonical: str, slot_index: int) -> str:
    """Build the eBUSd message name for a 1-based slot index."""
    suffix = "" if slot_index == 1 else f"_Slot{slot_index}"
    return f"{prefix}_{day_canonical}{suffix}"


def _is_bus_explicitly_offline(coordinator: SaunierGeniaCoordinator) -> bool:
    """Return True if eBUSd explicitly reports offline signal/running or silence timeout."""
    signal_offline = any(
        (coordinator.get_str(CIRCUIT_GLOBAL, m) or "").lower()
        in ("false", "0", "no", "off")
        for m in ("signal", "running")
    )
    if signal_offline:
        return True
    return (
        not coordinator.is_ebus_operational
        and getattr(coordinator, "_last_telemetry_time", None) is not None
    )


async def _async_force_read_controller_message(
    coordinator: SaunierGeniaCoordinator,
    msg_name: str,
    *,
    timeout: float = BUS_READ_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Actively query a controller message via MQTT /get and await the fresh reply."""
    if not hasattr(coordinator, "async_request_get"):
        return coordinator.get_message(CIRCUIT_BASS3, msg_name)

    target_circuit = coordinator.resolve_circuit(CIRCUIT_BASS3)
    event = asyncio.Event()

    @callback
    def _on_update() -> None:
        event.set()

    unsub_target = coordinator.async_add_listener(target_circuit, msg_name, _on_update)
    unsub_base = (
        coordinator.async_add_listener(CIRCUIT_BASS3, msg_name, _on_update)
        if target_circuit.lower() != CIRCUIT_BASS3.lower()
        else None
    )

    req_mono = _monotonic_time()
    try:
        await coordinator.async_request_get(CIRCUIT_BASS3, msg_name)
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except (TimeoutError, Exception) as err:  # noqa: BLE001
        _LOGGER.debug(
            "Timed out or failed reading %s/%s from eBUS: %s",
            target_circuit,
            msg_name,
            err,
        )
        return None
    finally:
        unsub_target()
        if unsub_base is not None:
            unsub_base()

    recent_err = coordinator.get_recent_error(
        target_circuit, msg_name, since_mono=req_mono
    ) or coordinator.get_recent_error(CIRCUIT_BASS3, msg_name, since_mono=req_mono)
    if recent_err is not None:
        _LOGGER.debug(
            "eBUSd returned error while reading %s/%s: %s",
            target_circuit,
            msg_name,
            recent_err,
        )
        return None

    msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
    if msg is None or coordinator._is_ebusd_err_msg(msg):
        return None
    return msg


def validate_days(raw_days: list[str]) -> list[str]:
    """Validate and deduplicate requested weekday names (canonical capitalized)."""
    if not raw_days:
        raise HomeAssistantError("Parameter 'days' must contain at least one weekday.")
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_days:
        key = str(raw).strip().lower()
        canonical = _DAY_LOWER_TO_CANONICAL.get(key)
        if canonical is None:
            raise HomeAssistantError(
                f"Invalid weekday '{raw}'. Expected one of: "
                + ", ".join(d.lower() for d in WEEKDAYS_LIST)
                + "."
            )
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def validate_slots(
    raw_slots: list[dict[str, Any]],
    spec: TimeProgramSpec,
    default_temp: float,
) -> list[ParsedTimeSlot]:
    """Validate 0..3 slots on the 10-minute grid with no overlaps."""
    if len(raw_slots) > MAX_SLOTS_PER_DAY:
        raise HomeAssistantError(
            f"Too many slots ({len(raw_slots)}): at most {MAX_SLOTS_PER_DAY} slots per day are supported."
        )

    parsed: list[ParsedTimeSlot] = []
    for idx, item in enumerate(raw_slots, start=1):
        fh, fm = _parse_hhmm_grid(item["start"], is_end=False)
        raw_th, raw_tm = _parse_hhmm_grid(item["end"], is_end=True)
        th, tm = _normalize_end_hhmm(fh, fm, raw_th, raw_tm)

        start_min = fh * 60 + fm
        end_min = th * 60 + tm
        if start_min >= end_min:
            raise HomeAssistantError(
                f"Slot {idx} start time '{item['start']}' must be earlier than end time '{item['end']}'."
            )

        slot_temp: float | None = None
        if spec.has_temperature:
            raw_temp = item.get("temperature")
            temp_val = default_temp if raw_temp is None else round(float(raw_temp), 1)
            if (spec.min_temp is not None and temp_val < spec.min_temp) or (
                spec.max_temp is not None and temp_val > spec.max_temp
            ):
                raise HomeAssistantError(
                    f"Slot {idx} temperature {temp_val} °C is out of range for {spec.program} "
                    f"({spec.min_temp:.1f} to {spec.max_temp:.1f} °C)."
                )
            slot_temp = temp_val

        parsed.append(
            ParsedTimeSlot(
                from_hour=fh,
                from_min=fm,
                to_hour=th,
                to_min=tm,
                temperature=slot_temp,
            )
        )

    parsed.sort(key=lambda s: (s.start_minutes, s.end_minutes))
    for i in range(len(parsed) - 1):
        prev_slot = parsed[i]
        next_slot = parsed[i + 1]
        if next_slot.start_minutes < prev_slot.end_minutes:
            raise HomeAssistantError(
                f"Time slots overlap: {prev_slot.start_str}-{prev_slot.end_str} "
                f"and {next_slot.start_str}-{next_slot.end_str}."
            )

    return parsed


def _slots_match(
    actual: ParsedTimeSlot, expected: ParsedTimeSlot, spec: TimeProgramSpec
) -> bool:
    """Return True if a read-back slot matches the written slot."""
    if actual.start_minutes != expected.start_minutes:
        return False
    if actual.end_minutes != expected.end_minutes:
        return False
    if spec.has_temperature:
        if actual.temperature is None or expected.temperature is None:
            return False
        if abs(actual.temperature - expected.temperature) > TEMP_MATCH_TOLERANCE_C:
            return False
    return True


async def async_handle_read_time_program(
    hass: HomeAssistant,
    program: str,
    *,
    entry_id: str | None = None,
) -> ServiceResponse:
    """Handle arotherm_genia_ebusd.read_time_program service call."""
    spec = resolve_time_program_spec(program)
    coordinator = _resolve_coordinator(hass, entry_id)

    slots_msg_name = f"{spec.program}_Slots"
    slots_msg = coordinator.get_message(CIRCUIT_BASS3, slots_msg_name)
    if slots_msg is None or coordinator._is_ebusd_err_msg(slots_msg):
        if _is_bus_explicitly_offline(coordinator):
            raise HomeAssistantError(
                "Cannot read time program: eBUS communication is not operational."
            )
        slots_msg = await _async_force_read_controller_message(
            coordinator, slots_msg_name
        )
        if slots_msg is None:
            raise HomeAssistantError(
                f"Failed to read active slot counts ({slots_msg_name}) from controller."
            )

    days_result: dict[str, list[dict[str, Any]]] = {}
    incomplete_days: list[str] = []
    bus_fetches = 0

    for day_canonical in WEEKDAYS_LIST:
        day_lower = day_canonical.lower()
        count = _parse_slot_count(slots_msg, day_canonical)
        if count is None:
            days_result[day_lower] = []
            incomplete_days.append(day_lower)
            continue
        if count == 0:
            days_result[day_lower] = []
            continue

        day_slots: list[dict[str, Any]] = []
        day_incomplete = False
        for slot_idx in range(1, count + 1):
            msg_name = _slot_message_name(spec.program, day_canonical, slot_idx)
            msg = coordinator.get_message(CIRCUIT_BASS3, msg_name)
            parsed = (
                _parse_slot_from_message(msg, spec)
                if msg is not None and not coordinator._is_ebusd_err_msg(msg)
                else None
            )
            if parsed is None and not _is_bus_explicitly_offline(coordinator):
                if bus_fetches > 0:
                    await asyncio.sleep(READBACK_STEP_DELAY_SECONDS)
                bus_fetches += 1
                fetched = await _async_force_read_controller_message(
                    coordinator, msg_name
                )
                parsed = _parse_slot_from_message(fetched, spec)

            if parsed is None:
                day_incomplete = True
            else:
                day_slots.append(
                    parsed.to_response_dict(include_temperature=spec.has_temperature)
                )

        days_result[day_lower] = day_slots
        if day_incomplete:
            incomplete_days.append(day_lower)

    response: dict[str, Any] = {
        "program": spec.program,
        "circuit": coordinator.active_controller_circuit,
        "temperature": spec.has_temperature,
        "days": days_result,
    }
    if incomplete_days:
        response["incomplete"] = incomplete_days
    return response


async def async_handle_write_time_program(
    hass: HomeAssistant,
    program: str,
    days: list[str],
    slots: list[dict[str, Any]],
    *,
    entry_id: str | None = None,
) -> ServiceResponse:
    """Handle arotherm_genia_ebusd.write_time_program service call with bus read-back."""
    spec = resolve_time_program_spec(program)
    target_days = validate_days(days)
    coordinator = _resolve_coordinator(hass, entry_id)

    default_temp = _get_default_program_temp(coordinator, spec)
    parsed_slots = validate_slots(slots, spec, default_temp)

    if not coordinator.is_ebus_operational:
        raise HomeAssistantError(
            "Cannot write time program: eBUS communication is not operational."
        )

    total_slots = len(parsed_slots)
    write_plans: list[tuple[str, list[tuple[str, str]]]] = []
    for day_canonical in target_days:
        if total_slots == 0:
            if spec.has_temperature:
                clear_payload = f"0;0;0;0;0;{default_temp:.1f}"
            elif spec.write_noop_temp:
                clear_payload = "0;0;0;0;0;-"
            else:
                clear_payload = "0;0;0;0;0"
            write_plans.append(
                (day_canonical, [(f"{spec.program}_{day_canonical}", clear_payload)])
            )
            continue

        day_writes: list[tuple[str, str]] = []
        for slot_idx, slot in enumerate(parsed_slots, start=1):
            msg_name = _slot_message_name(spec.program, day_canonical, slot_idx)
            wire_to_h = 24 if slot.end_minutes == 1440 else slot.to_hour
            wire_to_m = 0 if slot.end_minutes == 1440 else slot.to_min
            if spec.has_temperature:
                temp_val = (
                    slot.temperature if slot.temperature is not None else default_temp
                )
                payload = (
                    f"{total_slots};{slot.from_hour};{slot.from_min};"
                    f"{wire_to_h};{wire_to_m};{temp_val:.1f}"
                )
            elif spec.write_noop_temp:
                payload = (
                    f"{total_slots};{slot.from_hour};{slot.from_min};"
                    f"{wire_to_h};{wire_to_m};-"
                )
            else:
                payload = (
                    f"{total_slots};{slot.from_hour};{slot.from_min};"
                    f"{wire_to_h};{wire_to_m}"
                )
            day_writes.append((msg_name, payload))
        write_plans.append((day_canonical, day_writes))

    confirmed_days: dict[str, list[dict[str, Any]]] = {}

    async with coordinator.timer_write_lock:
        first_write = True
        for day_canonical, day_writes in write_plans:
            try:
                for msg_name, payload in day_writes:
                    if not first_write:
                        await asyncio.sleep(WRITE_PACING_SECONDS)
                    first_write = False
                    await coordinator.async_write_parameter(
                        CIRCUIT_BASS3, msg_name, payload
                    )
                coordinator.async_set_optimistic_active_slots(
                    spec.program, day_canonical, total_slots
                )
            except Exception as err:
                coordinator.async_invalidate_active_slots(spec.program, day_canonical)
                raise HomeAssistantError(
                    f"Failed writing {spec.program} for {day_canonical.lower()}: {err}"
                ) from err

        # Allow the controller to commit the b5 55 a6 write before reading back.
        await asyncio.sleep(READBACK_SETTLE_SECONDS)

        slots_msg_name = f"{spec.program}_Slots"
        readback_slots_msg = await _async_force_read_controller_message(
            coordinator, slots_msg_name
        )
        if readback_slots_msg is None:
            for day_canonical in target_days:
                coordinator.async_invalidate_active_slots(spec.program, day_canonical)
            raise HomeAssistantError(
                f"Write confirmation failed: could not read back {slots_msg_name} from controller."
            )

        for day_canonical in target_days:
            day_lower = day_canonical.lower()
            actual_count = _parse_slot_count(readback_slots_msg, day_canonical)
            if actual_count != total_slots:
                coordinator.async_invalidate_active_slots(spec.program, day_canonical)
                raise HomeAssistantError(
                    f"Write verification mismatch for {spec.program} on {day_lower}: "
                    f"expected {total_slots} active slot(s), controller reports {actual_count}."
                )

            if total_slots == 0:
                confirmed_days[day_lower] = []
                continue

            day_confirmed: list[dict[str, Any]] = []
            for slot_idx, expected_slot in enumerate(parsed_slots, start=1):
                await asyncio.sleep(READBACK_STEP_DELAY_SECONDS)
                msg_name = _slot_message_name(spec.program, day_canonical, slot_idx)
                fetched = await _async_force_read_controller_message(
                    coordinator, msg_name
                )
                actual_slot = _parse_slot_from_message(fetched, spec)
                if actual_slot is None or not _slots_match(
                    actual_slot, expected_slot, spec
                ):
                    with contextlib.suppress(Exception):
                        coordinator.async_invalidate_active_slots(
                            spec.program, day_canonical
                        )
                    raise HomeAssistantError(
                        f"Write verification mismatch for {spec.program} on {day_lower} "
                        f"slot {slot_idx}: expected {expected_slot.to_response_dict(include_temperature=spec.has_temperature)}, "
                        f"controller reports "
                        f"{actual_slot.to_response_dict(include_temperature=spec.has_temperature) if actual_slot else None}."
                    )
                day_confirmed.append(
                    actual_slot.to_response_dict(
                        include_temperature=spec.has_temperature
                    )
                )
            confirmed_days[day_lower] = day_confirmed

    return {
        "program": spec.program,
        "circuit": coordinator.active_controller_circuit,
        "days": confirmed_days,
    }
