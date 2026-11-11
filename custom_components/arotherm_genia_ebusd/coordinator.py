"""MQTT Coordinator, Hydration Queue, DHW Boost Manager, and Thermodynamic Calculator."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CALC_CIRCUIT,
    CALC_COOL_EER,
    CALC_DELTA_T,
    CALC_DHW_TOTAL_ENERGY,
    CALC_GLOBAL_EFFICIENCY,
    CALC_HC_COP,
    CALC_HEATING_TOTAL_ENERGY,
    CALC_HWC_COP,
    CALC_LIVE_COP,
    CALC_SYSTEM_TOTAL_ENERGY,
    CALC_THERMAL_POWER,
    CIRCUIT_BASS3,
    CIRCUIT_BASV3,
    CIRCUIT_BROADCAST,
    CIRCUIT_CTLV2,
    CIRCUIT_CTLV3,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMU,
    CIRCUIT_HMU00,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    CIRCUIT_VWZIO,
    CONF_AUTO_COOLING_LOCK_BYPASS,
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_FALLBACK_POLL_INTERVAL,
    CONF_FORCE_DHW_BOOST,
    CONF_HAS_MIGO_LINK,
    CONF_HAS_WIRELESS_ROOM_UNIT,
    CONF_INDOOR_MODEL,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    CONF_OUTDOOR_MODEL,
    CONTROLLER_CIRCUITS,
    DAY_SHORT_KEYS,
    DEFAULT_AUTO_COOLING_LOCK_BYPASS,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_COOLING_QUICK_VETO_BOOST_DELTA,
    DEFAULT_COOLING_TEMP,
    DEFAULT_CYLINDER_HYST,
    DEFAULT_DEVICE_VERSIONS,
    DEFAULT_EBUSD_TCP_HOST,
    DEFAULT_EBUSD_TCP_PORT,
    DEFAULT_ENABLE_EBUSD_TCP,
    DEFAULT_FALLBACK_POLL_INTERVAL,
    DEFAULT_FORCE_DHW_BOOST,
    DEFAULT_HAS_MIGO_LINK,
    DEFAULT_HAS_WIRELESS_ROOM_UNIT,
    DEFAULT_HOLIDAY_TEMP,
    DEFAULT_INDOOR_MODEL,
    DEFAULT_MANUFACTURER,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_OUTDOOR_MODEL,
    DEFAULT_QUICK_VETO_BOOST_DELTA,
    DEFAULT_QUICK_VETO_DURATION,
    DEVICE_OUTDOOR_UNIT,
    DHW_BOOST_HYST_MARGIN,
    DHW_BOOST_MAX_TIMEOUT_SECONDS,
    DOMAIN,
    EBUSD_TRAFFIC_TIMEOUT_SECONDS,
    ELECTRIC_POWER_STALE_TIMEOUT_SECONDS,
    ESSENTIAL_HYDRATION_MESSAGES,
    HMU_HW5103_HYDRATION_MESSAGES,
    HMUX0_CUSTOM_SIGNATURE_MESSAGES,
    HMUX0_EXCLUSIVE_MESSAGES,
    HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES,
    HOLIDAY_DEFAULT_END_TIME,
    HOLIDAY_INDEFINITE_END_DATE,
    HOLIDAY_RESET_DATE,
    HOLIDAY_RESET_TIME,
    HYDRATION_STEP_DELAY_SECONDS,
    INITIAL_HYDRATION_WAIT_SECONDS,
    ISSUE_MISSING_CUSTOM_CSV,
    ISSUE_MQTTJSON_NOT_ENABLED,
    ISSUE_NO_EBUSD_MQTT_TRAFFIC,
    ISSUE_OUTDATED_CONTROLLER_CSV,
    ISSUE_OUTDATED_HMU_CSV,
    ISSUE_OUTDATED_HMUX0_CSV,
    MANUFACTURER_VAILLANT,
    MESSAGE_ALIASES,
    OUTDOOR_CIRCUITS,
    SCAN_ADDRESS_TO_DEVICE_KEY,
    SCAN_TOPIC_CIRCUITS,
    SENTINEL_COOLING_THRESHOLD,
    SET_CONFIRMATION_DELAY_SECONDS,
    STATE_INACTIVE,
    STATE_OPEN_ENDED,
    UPSTREAM_DEFAULT_CSV_MESSAGES,
)
from .thermodynamics import (
    MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH,
    calculate_combined_efficiency,
    calculate_combined_mode_energy,
    calculate_delta_t,
    calculate_live_cop,
    calculate_period_cop,
    calculate_system_total_energy,
    calculate_thermal_power,
)

_LOGGER = logging.getLogger(__name__)

_OUTDOOR_THERMO_TRIGGER_NAMES: tuple[str, ...] = (
    "rundataflowtemp",
    "rundatareturntemp",
    "status01",
    "rundataflowrate",
    "rundataelectricpowerconsumption",
    "powerstatus",
    "energyyieldprecision",
    "hmustatuscode",
    "prenergyelectrichc",
    "prenergyelectrichwc",
    "prenergyelectriccool",
    "prenergythermalhc",
    "prenergythermalhwc",
    "prenergythermalcool",
    "yieldhc",
    "yieldhwc",
    "yieldcooling",
    "cophc",
    "cophwc",
    "copcooling",
    "totalenergyusage",
    "flowpressure",
)

# Inputs in outdoor units (hmux0/hmu), controller (15.*), and vwzio that trigger recalculation of thermodynamic & energy sensors
THERMO_TRIGGER_MESSAGES: frozenset[tuple[str, str]] = frozenset(
    {(c, msg) for c in OUTDOOR_CIRCUITS for msg in _OUTDOOR_THERMO_TRIGGER_NAMES}
    | {
        (c, msg)
        for c in CONTROLLER_CIRCUITS
        for msg in ("prenergysumhc", "prenergysumhwc")
    }
    | {
        (CIRCUIT_VWZIO, "powerstatus"),
        (CIRCUIT_VWZIO, "prenergyelectrichc"),
        (CIRCUIT_VWZIO, "prenergyelectrichwc"),
        (CIRCUIT_VWZIO, "prenergythermalhc"),
        (CIRCUIT_VWZIO, "prenergythermalhwc"),
    }
)

ACTIVE_COMPRESSOR_STATUSES: set[str] = {
    "heat_compressor_active",
    "hwc_compressor_active",
    "cool_compressor_active",
}


def parse_ebusd_payload(raw_payload: str) -> dict[str, Any]:
    """Parse an ebusd MQTT payload (with --mqttjson or plain text fallback).

    Rules from specification section 3.2:
    1. Attempt to parse raw_payload as JSON.
    2. If dict, extract v["value"] if isinstance(v, dict) and "value" in v, else v.
    3. If not valid JSON (or scalar JSON), return {"value": ...}.
    """
    stripped = raw_payload.strip()
    if not stripped:
        return {}

    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return {"value": stripped}

    if isinstance(parsed, dict):
        normalized: dict[str, Any] = {}
        for key, val in parsed.items():
            if isinstance(val, dict) and "value" in val:
                normalized[key] = val["value"]
            else:
                normalized[key] = val
        return normalized

    return {"value": parsed}


# Field layouts of multi-value write payloads ("a;b;c"). They mirror the field order of
# the 'w' lines in 15.bass3.csv and are used to apply the optimistic local update to the
# same named fields that ebusd publishes in its MQTT JSON (e.g. day/month/year).
DATE_WRITE_FIELDS: tuple[str, ...] = ("day", "month", "year")
TIME_WRITE_FIELDS: tuple[str, ...] = ("hours", "minutes", "seconds")
TIMER_WRITE_FIELDS: tuple[str, ...] = (
    "total_slots",
    "from_hour",
    "from_min",
    "to_hour",
    "to_min",
    "temp",
)


def _coerce_scalar(raw: Any) -> Any:
    """Convert a written payload token to int/float when numeric, else keep it as-is."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _multi_field_layout(
    message: str, current: dict[str, Any]
) -> tuple[str, ...] | None:
    """Return the ordered field names for a multi-value write of `message`."""
    if message in (
        "CoolingStartDate",
        "CoolingEndDate",
        "HolidayStartDate",
        "HolidayEndDate",
    ):
        return DATE_WRITE_FIELDS
    if message in ("HolidayStartTime", "HolidayEndTime"):
        return TIME_WRITE_FIELDS
    if "Timer_" in message and not message.endswith("_Slots"):
        return TIMER_WRITE_FIELDS
    # Generic fallback: reuse the field order already published by ebusd
    data_keys = tuple(k for k in current if k != "value")
    return data_keys or None


# Whitelist of writable parameters that have active read priority (r / r9) on eBUS.
# ONLY these parameters query physical bus hardware on confirmation /get.
# For all other writable parameters (passive 'u'), confirmation /get is NEVER sent,
# preventing eBUSd from echoing stale RAM cache over user input.
ACTIVE_READ_CONFIRMATION_MESSAGES: frozenset[tuple[str, str]] = frozenset(
    {
        (CIRCUIT_BASS3.lower(), "AdaptHeatCurve"),
        (CIRCUIT_BASS3.lower(), "AlternativePoint"),
        (CIRCUIT_BASS3.lower(), "BivalencePointHc"),
        (CIRCUIT_BASS3.lower(), "BivalencePointHwc"),
        (CIRCUIT_BASS3.lower(), "BufferChargeOffset"),
        (CIRCUIT_BASS3.lower(), "CoolingFlowTempDesiredMax"),
        (CIRCUIT_BASS3.lower(), "CoolingFlowTempDesiredMin"),
        (CIRCUIT_BASS3.lower(), "CylinderChargeHyst"),
        (CIRCUIT_BASS3.lower(), "CylinderChargeOffset"),
        (CIRCUIT_BASS3.lower(), "GlobalSystemOff"),
        (CIRCUIT_BASS3.lower(), "Hc1AutoOffMode"),
        (CIRCUIT_BASS3.lower(), "Hc1ExcessTemp"),
        (CIRCUIT_BASS3.lower(), "Hc1HeatCurve"),
        (CIRCUIT_BASS3.lower(), "Hc1MaxFlowTempDesired"),
        (CIRCUIT_BASS3.lower(), "Hc1MinFlowTempDesired"),
        (CIRCUIT_BASS3.lower(), "Hc1RoomTempSwitchOn"),
        (CIRCUIT_BASS3.lower(), "Hc1Status"),
        (CIRCUIT_BASS3.lower(), "Hc1SummerTempLimit"),
        (CIRCUIT_BASS3.lower(), "HwcLockTime"),
        (CIRCUIT_BASS3.lower(), "HwcMaxFlowTempDesired"),
        (CIRCUIT_BASS3.lower(), "HwcParallelLoading"),
        (CIRCUIT_BASS3.lower(), "MaxCylinderChargeTime"),
        (CIRCUIT_BASS3.lower(), "MaxRoomHumidity"),
        (CIRCUIT_BASS3.lower(), "PumpAdditionalTime"),
        (CIRCUIT_BASS3.lower(), "HolidayTemp"),
        (CIRCUIT_BASS3.lower(), "Z1ValveStatus"),
    }
)


class SaunierGeniaCoordinator:
    """Central MQTT state manager, hydration scheduler, and COP calculator.

    Architectural design:
    - Physical eBUS runs at a slow 2400 baud (~240 bytes/second) half-duplex with CSMA/CD.
      Therefore, this coordinator strictly avoids aggressive continuous polling and instead
      favors passive listening (`u` broadcast/update messages) whenever possible.
    - Active polling is reserved for high-precision diagnostic and configuration registers.
    - Write commands apply optimistic local cache updates to ensure immediate UI feedback,
      with paced delays between consecutive physical bus operations to avoid collisions.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry

        # State storage indexed by (circuit_lower, message_name)
        self._state: dict[tuple[str, str], dict[str, Any]] = {}
        # Timestamps of last received update indexed by (circuit_lower, message_lower)
        self._message_timestamps: dict[tuple[str, str], float] = {}
        # Case-insensitive index mapping (circuit_lower, message_lower) -> canonical message_name
        self._canonical_names: dict[tuple[str, str], str] = {}

        # Listeners indexed by (circuit_lower, message_lower)
        self._listeners: dict[tuple[str, str], list[Callable[[], None]]] = {}
        self._global_listeners: list[Callable[[], None]] = []

        # Subscriptions and background tasks cleanup callbacks
        self._mqtt_unsubs: list[CALLBACK_TYPE] = []
        self._hydration_timer_unsub: CALLBACK_TYPE | None = None
        self._fallback_poll_unsub: CALLBACK_TYPE | None = None
        self._ebusd_tcp_poll_unsub: CALLBACK_TYPE | None = None
        self._hydration_task: asyncio.Task[None] | None = None
        self._pending_get_unsubs: dict[tuple[str, str], CALLBACK_TYPE] = {}

        # Thermodynamic calculation state
        self.last_active_cop: float | None = None

        # Smart Forced DHW Boost state
        self._saved_dhw_target_temp: float | None = None
        self._dhw_boost_goal_temp: float | None = None
        self._dhw_boost_active: bool = False
        self._dhw_boost_started_at: float = 0.0
        self._dhw_boost_seen_load: bool = False
        self._dhw_boost_timeout_unsub: CALLBACK_TYPE | None = None

        # Custom cooling season window state
        self._custom_cooling_start_date: str | None = None
        self._custom_cooling_end_date: str | None = None

        # Preselected / pending holiday mode parameters
        self._preselected_holiday_start_datetime: datetime | None = None
        self._preselected_holiday_end_datetime: datetime | None = None

        # Pre-veto operating mode memory (to restore 'off' when veto ends)
        self._pre_veto_opmode: str | None = None

        # Configured heating boost delta in °C (default +3.0 °C)
        self._quick_veto_boost_delta: float = DEFAULT_QUICK_VETO_BOOST_DELTA

        # Configured cooling boost delta in °C (default 2.0 °C) and cooling veto state
        self._cooling_quick_veto_boost_delta: float = (
            DEFAULT_COOLING_QUICK_VETO_BOOST_DELTA
        )
        self._cooling_veto_unsub: CALLBACK_TYPE | None = None
        self._cooling_veto_get_unsub: CALLBACK_TYPE | None = None
        self._cooling_veto_restore_unsub: CALLBACK_TYPE | None = None
        self._pre_cooling_veto_opmode: str | None = None
        self._pre_cooling_veto_temp: float | None = None
        self._cooling_veto_active_temp: float | None = None
        self._cooling_veto_end_time: datetime | None = None
        self._pending_cooling_veto_restore: bool = False
        self._cooling_veto_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_cooling_veto"
        )

        # Passive hardware and software version detection from ebusd scan.*
        self._device_versions: dict[str, dict[str, str | None]] = {
            k: dict(v) for k, v in DEFAULT_DEVICE_VERSIONS.items()
        }

        # Root outdoor device registry ID for child device topology (via_device_id)
        self._outdoor_device_id: str | None = None

        # Active controller circuit name ('basv3' for Vaillant, 'bass3' for Saunier Duval)
        self._active_controller_circuit: str = (
            CIRCUIT_BASV3
            if self.manufacturer == MANUFACTURER_VAILLANT
            else CIRCUIT_BASS3
        )

        # Active outdoor unit circuit name ('hmux0' or 'hmu')
        self._active_outdoor_circuit: str = CIRCUIT_HMUX0

        # Initial hydration state tracking
        self._initial_hydration_started: bool = False

        # Pending hydration queue for dynamic re-evaluation on circuit change
        self._pending_hydration: list[tuple[str, str]] = []

        # Active Home Assistant Repair issues (issue_registry)
        self._active_repair_issues: set[str] = set()

        # Silence watchdog and last telemetry timestamp
        self._last_telemetry_time: float | None = None
        self._watchdog_unsub: CALLBACK_TYPE | None = None

        # Lock to serialize multi-slot weekly timer operations and prevent bus collisions
        self.timer_write_lock: asyncio.Lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Configuration & Options Properties
    # -------------------------------------------------------------------------

    @property
    def mqtt_prefix(self) -> str:
        """Return configured MQTT topic prefix without trailing slash."""
        prefix = self.entry.data.get(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX)
        return str(prefix).strip().rstrip("/") or DEFAULT_MQTT_PREFIX

    @property
    def manufacturer(self) -> str:
        """Return configured manufacturer (Saunier Duval or Vaillant)."""
        return str(self.entry.data.get(CONF_MANUFACTURER, DEFAULT_MANUFACTURER))

    @property
    def outdoor_model(self) -> str:
        """Return configured outdoor heat pump model."""
        return str(self.entry.data.get(CONF_OUTDOOR_MODEL, DEFAULT_OUTDOOR_MODEL))

    @property
    def indoor_model(self) -> str:
        """Return configured indoor hydraulic interface model."""
        return str(self.entry.data.get(CONF_INDOOR_MODEL, DEFAULT_INDOOR_MODEL))

    @property
    def active_controller_circuit(self) -> str:
        """Return active eBUS circuit name for the system controller ('bass3', 'basv3', 'ctlv2', 'ctlv3')."""
        return self._active_controller_circuit

    @property
    def active_outdoor_circuit(self) -> str:
        """Return active eBUS circuit name for the outdoor heat pump ('hmux0' or 'hmu')."""
        return self._active_outdoor_circuit

    @property
    def has_wireless_room_unit(self) -> bool:
        """Return True if wireless room thermostat (04.netx3) is enabled."""
        return bool(
            self.entry.data.get(
                CONF_HAS_WIRELESS_ROOM_UNIT, DEFAULT_HAS_WIRELESS_ROOM_UNIT
            )
        )

    @property
    def has_migo_link(self) -> bool:
        """Return True if MiGo Link (f1) gateway is active on the eBUS."""
        return bool(self.entry.data.get(CONF_HAS_MIGO_LINK, DEFAULT_HAS_MIGO_LINK))

    @property
    def force_dhw_boost(self) -> bool:
        """Return True if Smart Forced DHW Boost algorithm is enabled."""
        return bool(
            self.entry.options.get(CONF_FORCE_DHW_BOOST, DEFAULT_FORCE_DHW_BOOST)
        )

    @property
    def auto_cooling_lock_bypass(self) -> bool:
        """Return True if Lock 1 (CoolingEndDate=01;01;99) opens automatically on COOL."""
        return bool(
            self.entry.options.get(
                CONF_AUTO_COOLING_LOCK_BYPASS, DEFAULT_AUTO_COOLING_LOCK_BYPASS
            )
        )

    @property
    def is_ebus_operational(self) -> bool:
        """Return True if eBUS communication is operational.

        1. If ebusd publishes 'global/signal' or 'global/running' and it is explicitly false/0/off/no, return False.
        2. If no telemetry has been received yet (_state is empty), return False.
        3. If communication silence timeout (EBUSD_TRAFFIC_TIMEOUT_SECONDS) is exceeded, return False.
        4. If state contains no telemetry from actual heating/heat pump circuits (only metadata like version), return False.
        5. Otherwise, return True.
        """
        for circuit_msg in ("signal", "running"):
            val = self.get_str(CIRCUIT_GLOBAL, circuit_msg)
            if val is not None and val.lower() in ("false", "0", "no", "off"):
                return False

        if not self._state:
            return False

        if (
            self._last_telemetry_time is not None
            and (time.monotonic() - self._last_telemetry_time)
            > EBUSD_TRAFFIC_TIMEOUT_SECONDS
        ):
            return False

        # Require actual equipment telemetry or explicit positive signal from ebusd
        has_equipment_telemetry = any(
            c in OUTDOOR_CIRCUITS
            or c in CONTROLLER_CIRCUITS
            or c
            in (
                CIRCUIT_VWZIO,
                CIRCUIT_NETX3,
                CIRCUIT_NETX3_ALT,
                CIRCUIT_BROADCAST,
            )
            for c, _ in self._state
        )
        if not has_equipment_telemetry:
            running_val = self.get_str(CIRCUIT_GLOBAL, "running")
            signal_val = self.get_str(CIRCUIT_GLOBAL, "signal")
            has_positive_daemon = (
                running_val is not None
                and running_val.lower() in ("true", "1", "yes", "on")
            ) or (
                signal_val is not None
                and signal_val.lower() in ("true", "1", "yes", "on")
            )
            if not has_positive_daemon:
                return False

        return True

    @property
    def fallback_poll_interval(self) -> int:
        """Return fallback poll interval in seconds when has_migo_link is False."""
        return int(
            self.entry.options.get(
                CONF_FALLBACK_POLL_INTERVAL, DEFAULT_FALLBACK_POLL_INTERVAL
            )
        )

    @property
    def is_ebusd_tcp_enabled(self) -> bool:
        """Return True if advanced eBUSd TCP connection is enabled."""
        return bool(
            self.entry.options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP)
        )

    @property
    def ebusd_tcp_host(self) -> str:
        """Return configured eBUSd TCP host."""
        return str(
            self.entry.options.get(CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST)
        ).strip()

    @property
    def ebusd_tcp_port(self) -> int:
        """Return configured eBUSd TCP port."""
        return int(self.entry.options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT))

    @property
    def outdoor_device_id(self) -> str | None:
        """Return the internal Home Assistant Device Registry ID for the outdoor unit."""
        if self._outdoor_device_id:
            return self._outdoor_device_id
        if not self.hass:
            return None
        from homeassistant.helpers import device_registry as dr

        dev_reg = dr.async_get(self.hass)
        entry_id = self.entry.entry_id
        outdoor_id = f"{entry_id}_{DEVICE_OUTDOOR_UNIT}"
        if hasattr(dev_reg, "async_get_device_by_identifier"):
            device = dev_reg.async_get_device_by_identifier((DOMAIN, outdoor_id))
        else:
            device = dev_reg.async_get_device(identifiers={(DOMAIN, outdoor_id)})
        if device:
            self._outdoor_device_id = device.id
            return device.id
        return None

    def set_outdoor_device_id(self, device_id: str | None) -> None:
        """Set the internal Device Registry ID for the outdoor unit."""
        self._outdoor_device_id = device_id

    @property
    def saved_dhw_target_temp(self) -> float | None:
        """Return original DHW target temperature saved before a forced boost."""
        return self._saved_dhw_target_temp

    @property
    def dhw_boost_forced_active(self) -> bool:
        """Return True if a forced DHW boost setpoint elevation is currently active."""
        return self._dhw_boost_active

    @property
    def custom_cooling_start_date(self) -> str | None:
        """Return custom cooling start date if configured."""
        return self._custom_cooling_start_date

    def set_custom_cooling_start_date(self, val: str | None) -> None:
        """Set custom cooling start date."""
        self._custom_cooling_start_date = val

    @property
    def custom_cooling_end_date(self) -> str | None:
        """Return custom cooling end date if configured."""
        return self._custom_cooling_end_date

    def set_custom_cooling_end_date(self, val: str | None) -> None:
        """Set custom cooling end date."""
        self._custom_cooling_end_date = val

    @property
    def has_custom_cooling_dates(self) -> bool:
        """Return True if user pre-set custom cooling start or end date."""
        return bool(self._custom_cooling_start_date or self._custom_cooling_end_date)

    @property
    def preselected_holiday_start_datetime(self) -> datetime | None:
        """Return preselected holiday start datetime."""
        return self._preselected_holiday_start_datetime

    @preselected_holiday_start_datetime.setter
    def preselected_holiday_start_datetime(self, val: datetime | None) -> None:
        self._preselected_holiday_start_datetime = val

    @property
    def preselected_holiday_end_datetime(self) -> datetime | None:
        """Return preselected holiday end datetime."""
        return self._preselected_holiday_end_datetime

    @preselected_holiday_end_datetime.setter
    def preselected_holiday_end_datetime(self, val: datetime | None) -> None:
        self._preselected_holiday_end_datetime = val

    @property
    def pre_veto_opmode(self) -> str | None:
        """Return operating mode before veto was triggered, if any."""
        return self._pre_veto_opmode

    @pre_veto_opmode.setter
    def pre_veto_opmode(self, val: str | None) -> None:
        self._pre_veto_opmode = val

    @property
    def quick_veto_boost_delta(self) -> float:
        """Return configured temperature elevation for quick veto boost."""
        return self._quick_veto_boost_delta

    @quick_veto_boost_delta.setter
    def quick_veto_boost_delta(self, val: float) -> None:
        self._quick_veto_boost_delta = max(0.5, min(10.0, round(float(val), 1)))

    @property
    def cooling_quick_veto_boost_delta(self) -> float:
        """Return configured temperature reduction for cooling quick veto boost."""
        return self._cooling_quick_veto_boost_delta

    @cooling_quick_veto_boost_delta.setter
    def cooling_quick_veto_boost_delta(self, val: float) -> None:
        self._cooling_quick_veto_boost_delta = max(0.5, min(5.0, round(float(val), 1)))

    @property
    def cooling_quick_veto_active(self) -> bool:
        """Return True if cooling quick veto is currently active."""
        if self._cooling_veto_end_time is None:
            return False
        return datetime.now() < self._cooling_veto_end_time

    @property
    def cooling_quick_veto_remaining_minutes(self) -> int | None:
        """Return remaining minutes of active cooling quick veto."""
        if not self.cooling_quick_veto_active or self._cooling_veto_end_time is None:
            return None
        diff = (self._cooling_veto_end_time - datetime.now()).total_seconds()
        return max(0, int(diff // 60))

    @property
    def cooling_quick_veto_target_temp(self) -> float | None:
        """Return active target temperature of cooling quick veto."""
        return self._cooling_veto_active_temp

    @property
    def pre_cooling_veto_opmode(self) -> str | None:
        """Return operating mode before cooling veto was triggered."""
        return self._pre_cooling_veto_opmode

    @property
    def pre_cooling_veto_temp(self) -> float | None:
        """Return target temperature before cooling veto was triggered."""
        return self._pre_cooling_veto_temp

    # -------------------------------------------------------------------------
    # Lifecycle Setup & Unload
    # -------------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to ebusd MQTT topics, load persisted veto state, and schedule initial hydration."""
        await self._async_restore_persisted_cooling_veto()

        prefix = self.mqtt_prefix
        circuits_to_subscribe = [
            *CONTROLLER_CIRCUITS,
            *OUTDOOR_CIRCUITS,
            CIRCUIT_VWZIO,
            CIRCUIT_NETX3,
            CIRCUIT_NETX3_ALT,
            "Broadcast",
            CIRCUIT_BROADCAST,
            CIRCUIT_GLOBAL,
        ]

        for circuit in circuits_to_subscribe:
            topic = f"{prefix}/{circuit}/#"
            unsub = await mqtt.async_subscribe(
                self.hass, topic, self._async_on_mqtt_message, qos=0
            )
            self._mqtt_unsubs.append(unsub)

        # Passive scan topics subscription for SW/HW and serial detection (/# matches root and subtopics)
        for scan_circuit in SCAN_TOPIC_CIRCUITS:
            unsub = await mqtt.async_subscribe(
                self.hass,
                f"{prefix}/{scan_circuit}/#",
                self._async_on_mqtt_message,
                qos=0,
            )
            self._mqtt_unsubs.append(unsub)

        _LOGGER.debug(
            "Subscribed to ebusd MQTT topics under prefix '%s'; scheduling initial hydration in %.1fs",
            prefix,
            INITIAL_HYDRATION_WAIT_SECONDS,
        )

        # Schedule initial staggered hydration after 5.0 seconds
        self._hydration_timer_unsub = async_call_later(
            self.hass,
            INITIAL_HYDRATION_WAIT_SECONDS,
            self._async_start_initial_hydration,
        )

        # Configure fallback polling timer ONLY if has_migo_link is False
        self.async_update_options()

        # Periodic watchdog to detect communication silence / ebusd disconnect
        self._watchdog_unsub = async_track_time_interval(
            self.hass,
            self._async_check_watchdog,
            timedelta(seconds=60),
        )

    @callback
    def _async_check_watchdog(self, _now: datetime) -> None:
        """Periodic watchdog checking for communication silence timeout."""
        if self._last_telemetry_time is None:
            return
        elapsed = time.monotonic() - self._last_telemetry_time
        if elapsed > EBUSD_TRAFFIC_TIMEOUT_SECONDS:
            self._async_notify_message_listeners(CIRCUIT_GLOBAL, "running")
            self._async_notify_message_listeners(CIRCUIT_GLOBAL, "signal")

    @callback
    def async_update_options(self) -> None:
        """Reconfigure runtime timers when OptionsFlow is updated."""
        if self._fallback_poll_unsub is not None:
            self._fallback_poll_unsub()
            self._fallback_poll_unsub = None

        if not self.has_migo_link:
            interval = max(60, self.fallback_poll_interval)
            _LOGGER.info(
                "MiGo Link (f1) disabled; enabling fallback MQTT /get polling every %ds",
                interval,
            )
            self._fallback_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_run_fallback_poll,
                timedelta(seconds=interval),
            )

        self._async_setup_ebusd_tcp_polling()

    async def async_unload(self) -> None:
        """Unsubscribe from MQTT and cancel all background tasks and timers."""
        for unsub in self._mqtt_unsubs:
            unsub()
        self._mqtt_unsubs.clear()

        if self._hydration_timer_unsub is not None:
            self._hydration_timer_unsub()
            self._hydration_timer_unsub = None

        if self._fallback_poll_unsub is not None:
            self._fallback_poll_unsub()
            self._fallback_poll_unsub = None

        if self._ebusd_tcp_poll_unsub is not None:
            self._ebusd_tcp_poll_unsub()
            self._ebusd_tcp_poll_unsub = None

        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None

        if self._cooling_veto_unsub is not None:
            self._cooling_veto_unsub()
            self._cooling_veto_unsub = None

        if self._cooling_veto_get_unsub is not None:
            self._cooling_veto_get_unsub()
            self._cooling_veto_get_unsub = None

        if self._cooling_veto_restore_unsub is not None:
            self._cooling_veto_restore_unsub()
            self._cooling_veto_restore_unsub = None

        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
            self._watchdog_unsub = None

        for unsub in self._pending_get_unsubs.values():
            unsub()
        self._pending_get_unsubs.clear()

        if self._hydration_task is not None and not self._hydration_task.done():
            self._hydration_task.cancel()
            self._hydration_task = None

    # -------------------------------------------------------------------------
    # MQTT Reception & Normalization
    # -------------------------------------------------------------------------

    @callback
    def _async_on_mqtt_message(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle incoming MQTT messages from ebusd."""
        topic = msg.topic
        if topic.endswith(("/get", "/set")):
            return

        prefix_with_slash = f"{self.mqtt_prefix}/"
        if not topic.startswith(prefix_with_slash):
            return

        self._last_telemetry_time = time.monotonic()

        rel_topic = topic[len(prefix_with_slash) :]
        parts = rel_topic.split("/")
        if not parts or not parts[0]:
            return

        circuit_raw = parts[0]
        circuit_lower = circuit_raw.lower()

        # Intercept scan messages for passive SW/HW and serial number detection
        if circuit_lower.startswith("scan."):
            self._async_set_repair_issue(ISSUE_NO_EBUSD_MQTT_TRAFFIC, active=False)
            self._async_handle_scan_message(parts, msg.payload)
            return

        if len(parts) < 2:
            return

        message_name = parts[1]

        # Ignore command suffixes if nested
        if message_name in ("get", "set") or parts[-1] in ("get", "set"):
            return

        raw_payload = (
            msg.payload.decode("utf-8", errors="replace")
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload)
        )

        parsed = parse_ebusd_payload(raw_payload)
        if not parsed:
            return

        circuit_key = circuit_raw.lower()
        msg_lower = message_name.lower()

        # If ebusd published a subfield topic <prefix>/<circuit>/<message>/<field>
        if len(parts) == 3:
            subfield = parts[2]
            sub_val = parsed.get("value", next(iter(parsed.values())))
            existing = dict(self._state.get((circuit_key, message_name), {}))
            existing[subfield] = sub_val
            parsed = existing

        now = time.time()
        self._canonical_names[(circuit_key, msg_lower)] = message_name
        self._state[(circuit_key, message_name)] = parsed
        self._message_timestamps[(circuit_key, msg_lower)] = now

        # Notify subscribers for this (circuit, message)
        self._async_notify_message_listeners(circuit_key, message_name)

        # Check if this message name has a canonical alias (e.g. flowtemp -> RunDataFlowTemp)
        canonical_alias = MESSAGE_ALIASES.get(msg_lower)
        alias_parsed: dict[str, Any] | None = None
        if canonical_alias and canonical_alias != message_name:
            alias_parsed = dict(parsed)
            if msg_lower == "powerconsumptionhmu":
                val = parsed.get("value", next(iter(parsed.values()), None))
                if val is not None:
                    try:
                        alias_parsed["power"] = float(val) * 1000.0
                    except (ValueError, TypeError):
                        pass
            self._canonical_names[(circuit_key, canonical_alias.lower())] = (
                canonical_alias
            )
            self._state[(circuit_key, canonical_alias)] = alias_parsed
            self._message_timestamps[(circuit_key, canonical_alias.lower())] = now
            self._async_notify_message_listeners(circuit_key, canonical_alias)

            # If passive schedule update carried total_slots, keep active slots in sync
            if "total_slots" in parsed and "_" in canonical_alias:
                try:
                    parts_msg = canonical_alias.split("_")
                    t_prefix = parts_msg[0]
                    t_day = parts_msg[1]
                    if t_day in DAY_SHORT_KEYS:
                        t_count = int(parsed["total_slots"])
                        self.async_set_optimistic_active_slots(t_prefix, t_day, t_count)
                except (ValueError, TypeError, IndexError):
                    pass

        # Dynamic aliasing for outdoor unit circuits (hmux0 <-> hmu)
        if circuit_key in OUTDOOR_CIRCUITS:
            old_outdoor = self._active_outdoor_circuit
            self._active_outdoor_circuit = circuit_key
            if old_outdoor != circuit_key:
                self._async_on_outdoor_circuit_changed(circuit_key)
            for alt_circuit in OUTDOOR_CIRCUITS:
                if alt_circuit != circuit_key:
                    self._canonical_names[(alt_circuit, msg_lower)] = message_name
                    self._state[(alt_circuit, message_name)] = parsed
                    self._message_timestamps[(alt_circuit, msg_lower)] = now
                    self._async_notify_message_listeners(alt_circuit, message_name)
                    if (
                        canonical_alias
                        and canonical_alias != message_name
                        and alias_parsed
                    ):
                        self._canonical_names[
                            (alt_circuit, canonical_alias.lower())
                        ] = canonical_alias
                        self._state[(alt_circuit, canonical_alias)] = alias_parsed
                        self._message_timestamps[
                            (alt_circuit, canonical_alias.lower())
                        ] = now
                        self._async_notify_message_listeners(
                            alt_circuit, canonical_alias
                        )

        # Dynamic aliasing for climate controller circuits (bass3 <-> basv3 <-> ctlv2 <-> ctlv3)
        if circuit_key in CONTROLLER_CIRCUITS:
            self._active_controller_circuit = circuit_key
            for alt_circuit in CONTROLLER_CIRCUITS:
                if alt_circuit != circuit_key:
                    self._canonical_names[(alt_circuit, msg_lower)] = message_name
                    self._state[(alt_circuit, message_name)] = parsed
                    self._message_timestamps[(alt_circuit, msg_lower)] = now
                    self._async_notify_message_listeners(alt_circuit, message_name)
                    if (
                        canonical_alias
                        and canonical_alias != message_name
                        and alias_parsed
                    ):
                        self._canonical_names[
                            (alt_circuit, canonical_alias.lower())
                        ] = canonical_alias
                        self._state[(alt_circuit, canonical_alias)] = alias_parsed
                        self._message_timestamps[
                            (alt_circuit, canonical_alias.lower())
                        ] = now
                        self._async_notify_message_listeners(
                            alt_circuit, canonical_alias
                        )

        # Trigger thermodynamic calculations if relevant outdoor unit or hydraulic module telemetry changed
        canonical_msg_lower = canonical_alias.lower() if canonical_alias else msg_lower
        if (circuit_key, msg_lower) in THERMO_TRIGGER_MESSAGES or (
            circuit_key,
            canonical_msg_lower,
        ) in THERMO_TRIGGER_MESSAGES:
            self._async_recalculate_thermodynamics()

        # Check DHW boost restoration conditions when bass3/basv3 HwcSFMode or HwcStorageTemp updates
        if circuit_key in CONTROLLER_CIRCUITS and message_name in (
            "HwcSFMode",
            "HwcStorageTemp",
            "HwcStatus",
        ):
            self._async_check_dhw_boost_restoration()

        # Check Quick Veto restoration conditions when controller Z1SFMode or Z1Status updates
        if circuit_key in CONTROLLER_CIRCUITS and message_name in (
            "Z1SFMode",
            "Z1Status",
        ):
            self._async_check_quick_veto_restoration()
            if message_name == "Z1Status":
                z1_status_val = (
                    self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
                ).lower()
                if z1_status_val == "holidayaway" and self.cooling_quick_veto_active:
                    self.hass.async_create_task(
                        self.async_cancel_cooling_quick_veto(restore=True)
                    )

        # If a persisted cooling quick veto expired while HA was offline, restore once eBUS becomes operational
        if (
            self._pending_cooling_veto_restore
            and self.is_ebus_operational
            and (circuit_key in CONTROLLER_CIRCUITS or circuit_key in OUTDOOR_CIRCUITS)
            and self._cooling_veto_restore_unsub is None
        ):

            @callback
            def _async_schedule_pending_cooling_restore(_now: datetime) -> None:
                self._cooling_veto_restore_unsub = None
                self.hass.async_create_task(
                    self._async_execute_pending_cooling_veto_restore()
                )

            self._cooling_veto_restore_unsub = async_call_later(
                self.hass, 1.5, _async_schedule_pending_cooling_restore
            )

        # Verify eBUSd CSV compatibility and manage Home Assistant Repair issues
        self._async_check_csv_compatibility_on_message(
            circuit_key, msg_lower, parsed, raw_payload
        )

    # -------------------------------------------------------------------------
    # Home Assistant Repairs (eBUSd CSV & MQTT Configuration Verification)
    # -------------------------------------------------------------------------

    @callback
    def _async_set_repair_issue(
        self,
        issue_id: str,
        active: bool,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Create or delete a Home Assistant Repair issue in the Issue Registry."""
        from homeassistant.helpers import issue_registry as ir

        if active:
            if issue_id in self._active_repair_issues:
                return
            self._active_repair_issues.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
                translation_placeholders=placeholders,
                learn_more_url="https://github.com/R91g/arotherm-genia-ebusd#step-1-deploy-optimized-ebusd-csv-configuration",
            )
        else:
            if issue_id in self._active_repair_issues:
                self._active_repair_issues.discard(issue_id)
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def _async_check_csv_compatibility_on_message(
        self,
        circuit_key: str,
        msg_lower: str,
        parsed: dict[str, Any],
        raw_payload: str = "",
    ) -> None:
        """Inspect incoming MQTT payloads to detect MQTT/CSV configuration issues."""
        # 0. Any message on <mqtt_prefix>/# proves the MQTT prefix is receiving traffic
        self._async_set_repair_issue(ISSUE_NO_EBUSD_MQTT_TRAFFIC, active=False)

        # 1. Detect missing --mqttjson flag when multi-field telemetry arrives as semicolon plain text
        if (
            circuit_key in (*OUTDOOR_CIRCUITS, *CONTROLLER_CIRCUITS, CIRCUIT_VWZIO)
            and raw_payload
        ):
            stripped = raw_payload.strip()
            if stripped.startswith("{"):
                self._async_set_repair_issue(ISSUE_MQTTJSON_NOT_ENABLED, active=False)
            elif ";" in stripped:
                self._async_set_repair_issue(ISSUE_MQTTJSON_NOT_ENABLED, active=True)

        # 2. Detect legacy vs modern 08.hmux0.csv via StateCompressor, RunDataFlowRate & CompressorSilentOperationLevel
        if circuit_key == CIRCUIT_HMUX0 and msg_lower == "statecompressor":
            if (
                isinstance(parsed, dict)
                and "comp_speed" in parsed
                and "flow_temp" not in parsed
            ):
                self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)
            elif isinstance(parsed, dict) and "flow_temp" in parsed:
                flow_msg = self.get_message(CIRCUIT_HMUX0, "RunDataFlowRate") or {}
                has_legacy_flow = (
                    isinstance(flow_msg, dict)
                    and "value" in flow_msg
                    and "flow_rate" not in flow_msg
                )
                silent_msg = self.get_message(
                    CIRCUIT_HMUX0, "CompressorSilentOperationLevel"
                )
                is_silent_err = isinstance(silent_msg, str) and silent_msg.startswith(
                    "ERR:"
                )
                if not has_legacy_flow and not is_silent_err:
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)

        if circuit_key == CIRCUIT_HMUX0 and msg_lower == "rundataflowrate":
            if isinstance(parsed, dict) and "flow_rate" in parsed:
                sc_msg = self.get_message(CIRCUIT_HMUX0, "StateCompressor") or {}
                has_legacy_sc = (
                    isinstance(sc_msg, dict)
                    and "comp_speed" in sc_msg
                    and "flow_temp" not in sc_msg
                )
                silent_msg = self.get_message(
                    CIRCUIT_HMUX0, "CompressorSilentOperationLevel"
                )
                is_silent_err = isinstance(silent_msg, str) and silent_msg.startswith(
                    "ERR:"
                )
                if not has_legacy_sc and not is_silent_err:
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)
            elif (
                isinstance(parsed, dict)
                and "value" in parsed
                and "flow_rate" not in parsed
                and raw_payload.strip().startswith("{")
            ):
                self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)

        if circuit_key == CIRCUIT_HMUX0 and msg_lower == "rundatanominalflowrate":
            sc_msg = self.get_message(CIRCUIT_HMUX0, "StateCompressor") or {}
            has_legacy_sc = (
                isinstance(sc_msg, dict)
                and "comp_speed" in sc_msg
                and "flow_temp" not in sc_msg
            )
            if not has_legacy_sc:
                self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)

        if (
            circuit_key == CIRCUIT_HMUX0
            and msg_lower == "compressorsilentoperationlevel"
        ):
            if raw_payload.strip().startswith("ERR:"):
                self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)
            elif not raw_payload.strip().startswith("ERR:"):
                sc_msg = self.get_message(CIRCUIT_HMUX0, "StateCompressor") or {}
                flow_msg = self.get_message(CIRCUIT_HMUX0, "RunDataFlowRate") or {}
                has_legacy_sc = (
                    isinstance(sc_msg, dict)
                    and "comp_speed" in sc_msg
                    and "flow_temp" not in sc_msg
                )
                has_legacy_flow = (
                    isinstance(flow_msg, dict)
                    and "value" in flow_msg
                    and "flow_rate" not in flow_msg
                )
                if not has_legacy_sc and not has_legacy_flow:
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)

        # 2a. Detect legacy/upstream vs custom 08.hmu.csv / 08.hmu.HW5103.csv
        if circuit_key in (CIRCUIT_HMU, CIRCUIT_HMU00):
            if msg_lower == "status01":
                if (
                    isinstance(parsed, dict)
                    and "temp_1" in parsed
                    and "flow_temp" not in parsed
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)
                elif isinstance(parsed, dict) and "flow_temp" in parsed:
                    silent_raw = str(
                        self.get_message(circuit_key, "CompressorSilentOperationLevel")
                        or ""
                    )
                    if not silent_raw.startswith("ERR:"):
                        self._async_set_repair_issue(
                            ISSUE_OUTDATED_HMU_CSV, active=False
                        )

            elif msg_lower in UPSTREAM_DEFAULT_CSV_MESSAGES:
                self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)

            elif msg_lower == "compressorsilentoperationlevel":
                if raw_payload.strip().startswith("ERR:"):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)
                elif not raw_payload.strip().startswith("ERR:"):
                    status_msg = self.get_message(circuit_key, "Status01") or {}
                    has_legacy_status = (
                        isinstance(status_msg, dict)
                        and "temp_1" in status_msg
                        and "flow_temp" not in status_msg
                    )
                    if not has_legacy_status:
                        self._async_set_repair_issue(
                            ISSUE_OUTDATED_HMU_CSV, active=False
                        )

        # 2b. Detect legacy vs modern controller CSVs (Z1HolidayTemp/Z1DayTemp vs HolidayTemp/Z1CoolingManualTemp/SilentTimer)
        if circuit_key in CONTROLLER_CIRCUITS:
            is_err = raw_payload.strip().startswith("ERR:")
            if (not is_err and msg_lower in ("z1holidaytemp", "z1daytemp")) or (
                is_err and msg_lower in ("silenttimer_slots", "z1coolingmanualtemp")
            ):
                self._async_set_repair_issue(ISSUE_OUTDATED_CONTROLLER_CSV, active=True)
            elif not is_err and (
                msg_lower in ("holidaytemp", "z1coolingmanualtemp", "silenttimer_slots")
                or (
                    msg_lower == "holidaystartdate"
                    and isinstance(parsed, dict)
                    and "year" in parsed
                )
            ):
                for c in CONTROLLER_CIRCUITS:
                    self._state.pop((c, "Z1HolidayTemp"), None)
                    self._state.pop((c, "z1holidaytemp"), None)
                    self._state.pop((c, "Z1DayTemp"), None)
                    self._state.pop((c, "z1daytemp"), None)
                    self._canonical_names.pop((c, "z1holidaytemp"), None)
                    self._canonical_names.pop((c, "z1daytemp"), None)
                self._async_set_repair_issue(
                    ISSUE_OUTDATED_CONTROLLER_CSV, active=False
                )

        # 3. Clear 'missing_custom_csv' once all required custom CSV circuits report telemetry
        if (
            circuit_key in (*OUTDOOR_CIRCUITS, *CONTROLLER_CIRCUITS, CIRCUIT_VWZIO)
            and self._has_all_required_csv_circuits()
        ):
            self._async_set_repair_issue(ISSUE_MISSING_CUSTOM_CSV, active=False)

        # 4. Detect default upstream ebusd.eu hmu.inc messages (when custom CSV is not loaded)
        if (
            circuit_key in OUTDOOR_CIRCUITS
            and msg_lower in UPSTREAM_DEFAULT_CSV_MESSAGES
            and not any(
                self.has_message(circuit_key, m)
                for m in HMUX0_CUSTOM_SIGNATURE_MESSAGES
            )
        ):
            self._async_set_repair_issue(ISSUE_MISSING_CUSTOM_CSV, active=True)

    def _has_all_required_csv_circuits(self) -> bool:
        """Return True if outdoor unit, controller, and vwzio have all reported telemetry."""
        has_custom_outdoor = any(
            self.has_message(c, m)
            for c in OUTDOOR_CIRCUITS
            for m in HMUX0_CUSTOM_SIGNATURE_MESSAGES
        )
        has_controller = any(c in CONTROLLER_CIRCUITS for c, _ in self._state)
        has_vwzio = any(c == CIRCUIT_VWZIO for c, _ in self._state)
        return has_custom_outdoor and has_controller and has_vwzio

    @callback
    def _async_verify_custom_csv_after_hydration(self) -> None:
        """Check after initial hydration whether eBUSd MQTT traffic and all custom CSVs are active."""
        if not self._state:
            self._async_set_repair_issue(
                ISSUE_NO_EBUSD_MQTT_TRAFFIC,
                active=True,
                placeholders={"mqtt_prefix": self.mqtt_prefix},
            )
            return

        self._async_set_repair_issue(ISSUE_NO_EBUSD_MQTT_TRAFFIC, active=False)

        signal_raw = (self.get_str(CIRCUIT_GLOBAL, "signal") or "").lower()
        has_bus_traffic = signal_raw in ("1", "true", "yes", "on") or any(
            c in OUTDOOR_CIRCUITS or c in CONTROLLER_CIRCUITS or c == CIRCUIT_VWZIO
            for c, _ in self._state
        )
        if not has_bus_traffic:
            return

        self._async_set_repair_issue(
            ISSUE_MISSING_CUSTOM_CSV,
            active=not self._has_all_required_csv_circuits(),
        )

    # -------------------------------------------------------------------------
    # Listener Subscription & Notification
    # -------------------------------------------------------------------------

    @callback
    def async_add_listener(
        self,
        circuit: str,
        message: str,
        update_callback: Callable[[], None],
    ) -> CALLBACK_TYPE:
        """Subscribe an entity callback to a specific (circuit, message) pair."""
        key = (circuit.lower(), message.lower())
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(update_callback)

        @callback
        def _remove() -> None:
            if key in self._listeners and update_callback in self._listeners[key]:
                self._listeners[key].remove(update_callback)

        return _remove

    @callback
    def _async_notify_message_listeners(self, circuit_key: str, message: str) -> None:
        """Notify all callbacks registered for (circuit_key, message)."""
        key = (circuit_key.lower(), message.lower())
        for cb in list(self._listeners.get(key, [])):
            cb()
        for cb in list(self._global_listeners):
            cb()

    # -------------------------------------------------------------------------
    # State Getters (Compatible with CSV field names & Blueprint aliases)
    # -------------------------------------------------------------------------

    def has_message(self, circuit: str, message: str) -> bool:
        """Return True if we have received data for (circuit, message)."""
        c_key = circuit.lower()
        m_lower = message.lower()
        canonical = self._canonical_names.get((c_key, m_lower), message)
        return (c_key, canonical) in self._state or (c_key, m_lower) in self._state

    def get_message(self, circuit: str, message: str) -> dict[str, Any] | None:
        """Return the full normalized dict for (circuit, message), or None."""
        c_key = self.resolve_circuit(circuit).lower()
        m_lower = message.lower()
        canonical = self._canonical_names.get((c_key, m_lower), message)
        res = self._state.get((c_key, canonical))
        if res is not None:
            return res
        if canonical != m_lower:
            res = self._state.get((c_key, m_lower))
            if res is not None:
                return res
        # Fallback to literal circuit if resolve_circuit changed it but data was keyed by literal
        lit_key = circuit.lower()
        if lit_key != c_key:
            canonical_lit = self._canonical_names.get((lit_key, m_lower), message)
            res = self._state.get((lit_key, canonical_lit))
            if res is not None:
                return res
            if canonical_lit != m_lower:
                res = self._state.get((lit_key, m_lower))
                if res is not None:
                    return res
        return None

    def get_field(
        self,
        circuit: str,
        message: str,
        field: str = "value",
        default: Any = None,
    ) -> Any:
        """Retrieve a field value from (circuit, message) with smart CSV fallbacks."""
        msg_data = self.get_message(circuit, message)
        if not msg_data:
            return default

        # 1. Exact field match
        if field in msg_data and msg_data[field] is not None:
            return msg_data[field]

        # 2. Fallback to 'value' or 'flow_rate' (standard single-field names in 15.bass3.csv & 08.hmux0.csv)
        for single_alias in ("value", "flow_rate"):
            if single_alias in msg_data and msg_data[single_alias] is not None:
                return msg_data[single_alias]

        # 3. Specific multi-field alias mappings between specification and CSVs
        if field in ("temp1", "flow_temp", "temp"):
            for alias in ("temp", "flow_temp", "temp1"):
                if alias in msg_data and msg_data[alias] is not None:
                    return msg_data[alias]
        elif field in ("return_temp", "temp_1"):
            for alias in ("temp_1", "return_temp"):
                if alias in msg_data and msg_data[alias] is not None:
                    return msg_data[alias]
        elif field in ("cooling_temp", "temp") and "cooling_temp" in msg_data:
            return msg_data["cooling_temp"]
        elif field in ("pumpstate", "status"):
            for alias in ("pumpstate", "status", "value"):
                if alias in msg_data and msg_data[alias] is not None:
                    return msg_data[alias]

        # 4. If the message has only 1 field in the JSON dict, return its value
        if len(msg_data) == 1:
            only_val = next(iter(msg_data.values()))
            if only_val is not None:
                return only_val

        return default

    def get_float(
        self,
        circuit: str,
        message: str,
        field: str = "value",
        default: float | None = None,
    ) -> float | None:
        """Retrieve a field value converted to float, or default if invalid/missing."""
        val = self.get_field(circuit, message, field)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_int(
        self,
        circuit: str,
        message: str,
        field: str = "value",
        default: int | None = None,
    ) -> int | None:
        """Retrieve a field value converted to int, or default if invalid/missing."""
        val = self.get_field(circuit, message, field)
        if val is None:
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def get_str(
        self,
        circuit: str,
        message: str,
        field: str = "value",
        default: str | None = None,
    ) -> str | None:
        """Retrieve a field value converted to string, or default if missing."""
        val = self.get_field(circuit, message, field)
        if val is None:
            return default
        return str(val).strip()

    def get_message_timestamp(self, circuit: str, message: str) -> float | None:
        """Return the Unix timestamp when (circuit, message) was last updated, or None."""
        c_key = self.resolve_circuit(circuit).lower()
        m_lower = message.lower()
        ts = self._message_timestamps.get((c_key, m_lower))
        if ts is not None:
            return ts
        canonical = MESSAGE_ALIASES.get(m_lower)
        if canonical:
            ts = self._message_timestamps.get((c_key, canonical.lower()))
            if ts is not None:
                return ts
        # Fallback to literal circuit if resolve_circuit changed it
        lit_key = circuit.lower()
        if lit_key != c_key:
            ts = self._message_timestamps.get((lit_key, m_lower))
            if ts is not None:
                return ts
            if canonical:
                ts = self._message_timestamps.get((lit_key, canonical.lower()))
                if ts is not None:
                    return ts
        return None

    def get_message_age(
        self, circuit: str, message: str, now: float | None = None
    ) -> float | None:
        """Return elapsed seconds since (circuit, message) was last updated, or None if never received."""
        ts = self.get_message_timestamp(circuit, message)
        if ts is None:
            return None
        current_time = now if now is not None else time.time()
        return max(0.0, current_time - ts)

    def get_instantaneous_electric_power(
        self, now: float | None = None
    ) -> float | None:
        """Return instantaneous electrical power consumption (W) with dynamic staleness fallback.

        Prioritizes RunDataElectricPowerConsumption (active high-frequency r1 poll) when fresh.
        If RunDataElectricPowerConsumption is stale (> 180 seconds without an update) and
        PowerStatus has fresher telemetry, dynamically falls back to PowerStatus.
        """
        circuits = tuple(
            dict.fromkeys([self._active_outdoor_circuit, CIRCUIT_HMUX0, CIRCUIT_HMU])
        )

        run_val: float | None = None
        run_age: float | None = None
        run_ts: float | None = None
        for circuit in circuits:
            val = self.get_float(circuit, "RunDataElectricPowerConsumption", "power")
            if val is not None:
                run_val = val
                run_age = self.get_message_age(
                    circuit, "RunDataElectricPowerConsumption", now=now
                )
                run_ts = self.get_message_timestamp(
                    circuit, "RunDataElectricPowerConsumption"
                )
                break

        ps_val: float | None = None
        ps_age: float | None = None
        ps_ts: float | None = None
        for circuit in circuits:
            val = self.get_float(circuit, "PowerStatus", "power")
            if val is not None:
                ps_val = val
                ps_age = self.get_message_age(circuit, "PowerStatus", now=now)
                ps_ts = self.get_message_timestamp(circuit, "PowerStatus")
                break

        if run_val is None:
            return ps_val
        if ps_val is None:
            return run_val

        # Both are present: check staleness
        is_run_stale = (
            run_age is not None and run_age > ELECTRIC_POWER_STALE_TIMEOUT_SECONDS
        )
        if not is_run_stale:
            return run_val

        # RunData is stale (> 180s). Fall back to PowerStatus if PowerStatus is newer or fresh.
        if (ps_ts is not None and run_ts is not None and ps_ts > run_ts) or (
            ps_age is not None and ps_age <= ELECTRIC_POWER_STALE_TIMEOUT_SECONDS
        ):
            return ps_val

        return run_val

    # -------------------------------------------------------------------------
    # MQTT Publishing (/set and /get) & Hydration Queue
    # -------------------------------------------------------------------------

    def resolve_circuit(self, circuit: str) -> str:
        """Resolve a logical circuit name or alias to the active physical eBUS circuit."""
        circuit_lower = circuit.lower()
        if (
            circuit_lower in CONTROLLER_CIRCUITS
            or circuit_lower in ("15", "controller")
            or circuit_lower.startswith("15.")
        ):
            return self._active_controller_circuit
        if (
            circuit_lower in OUTDOOR_CIRCUITS
            or circuit_lower in ("08", "outdoor", "heatpump")
            or circuit_lower.startswith("08.")
        ):
            return self._active_outdoor_circuit
        return circuit

    async def async_request_get(self, circuit: str, message: str) -> None:
        """Publish an empty payload to <mqtt_prefix>/<circuit>/<message>/get."""
        target_circuit = self.resolve_circuit(circuit)
        topic = f"{self.mqtt_prefix}/{target_circuit}/{message}/get"
        await mqtt.async_publish(self.hass, topic, "", qos=0, retain=False)

    async def async_write_parameter(
        self,
        circuit: str,
        message: str,
        value: Any,
    ) -> None:
        """Publish a write command to <mqtt_prefix>/<circuit>/<message>/set and schedule confirmation /get."""
        circuit_lower = circuit.lower()
        is_controller = circuit_lower in CONTROLLER_CIRCUITS
        is_outdoor = circuit_lower in OUTDOOR_CIRCUITS
        target_circuit = self.resolve_circuit(circuit)
        topic = f"{self.mqtt_prefix}/{target_circuit}/{message}/set"
        payload = str(value)
        _LOGGER.debug("Publishing eBUSd write: %s -> '%s'", topic, payload)

        # Optimistic local update so Home Assistant UI reflects the user's action immediately.
        # For passive 'u' messages this is the ONLY state refresh until MiGo Link (f1) or the
        # controller (10) polls the register again, so it must update the real field names.
        self._apply_optimistic_update(circuit, message, value)
        self._async_notify_message_listeners(circuit, message)
        if is_controller:
            for alt_circuit in CONTROLLER_CIRCUITS:
                if alt_circuit != circuit_lower:
                    self._apply_optimistic_update(alt_circuit, message, value)
                    self._async_notify_message_listeners(alt_circuit, message)
        elif is_outdoor:
            for alt_circuit in OUTDOOR_CIRCUITS:
                if alt_circuit != circuit_lower:
                    self._apply_optimistic_update(alt_circuit, message, value)
                    self._async_notify_message_listeners(alt_circuit, message)

        await mqtt.async_publish(self.hass, topic, payload, qos=0, retain=False)

        # Schedule confirmation /get ONLY for active read commands (r / r9 whitelist).
        # For all passive 'u' commands (setpoints, modes, timers, dates), NEVER send /get,
        # perfectly preserving the optimistic UI update without stale cache rebounds.
        check_circuit = CIRCUIT_BASS3.lower() if is_controller else circuit.lower()
        key = (check_circuit, message)
        if key in ACTIVE_READ_CONFIRMATION_MESSAGES:
            if key in self._pending_get_unsubs:
                self._pending_get_unsubs.pop(key)()

            @callback
            def _confirm_get(_now: datetime) -> None:
                self._pending_get_unsubs.pop(key, None)
                self.hass.async_create_task(self.async_request_get(circuit, message))

            self._pending_get_unsubs[key] = async_call_later(
                self.hass, SET_CONFIRMATION_DELAY_SECONDS, _confirm_get
            )

    def _apply_optimistic_update(self, circuit: str, message: str, value: Any) -> None:
        """Store a written value locally using the same field names ebusd publishes.

        - Multi-value payloads ("01;01;99", "6;0;22;0") are split and mapped to their
          named fields (day/month/year, from_hour/from_min/to_hour/to_min), keeping any
          extra read-only field (e.g. CoolingTimer cooling_temp) untouched.
        - Single values update the only published field if it is not named 'value'
          (e.g. 'temp'), otherwise the canonical 'value' field.
        """
        circuit_key = circuit.lower()
        msg_lower = message.lower()
        canonical = self._canonical_names.get((circuit_key, msg_lower), message)
        self._canonical_names[(circuit_key, msg_lower)] = canonical
        current = dict(self._state.get((circuit_key, canonical)) or {})

        if isinstance(value, str) and ";" in value:
            parts = [_coerce_scalar(part) for part in value.split(";")]
            layout = _multi_field_layout(canonical, current)
            if layout:
                if len(parts) == 4 and layout == TIMER_WRITE_FIELDS:
                    current.update(
                        zip(
                            ("from_hour", "from_min", "to_hour", "to_min"),
                            parts,
                            strict=False,
                        )
                    )
                else:
                    current.update(zip(layout, parts, strict=False))
                    if "CoolingTimer_" in canonical and "temp" in current:
                        current["cooling_temp"] = current["temp"]
            else:
                current["value"] = value.strip()
        else:
            scalar = _coerce_scalar(value)
            if len(current) == 1 and "value" not in current:
                current[next(iter(current))] = scalar
            else:
                current["value"] = scalar

        self._state[(circuit_key, canonical)] = current

    @callback
    def async_set_optimistic_active_slots(
        self, prefix: str, day_name: str, count: int
    ) -> None:
        """Update optimistic active slot count for a day across all controller circuits."""
        short_day = DAY_SHORT_KEYS.get(day_name)
        if not short_day:
            return
        msg_name = f"{prefix}_Slots"
        for circuit in CONTROLLER_CIRCUITS:
            state_key = (circuit, msg_name)
            existing = dict(self._state.get(state_key, {}))
            existing[short_day] = count
            self._state[state_key] = existing
            self._async_notify_message_listeners(circuit, msg_name)

    @callback
    def async_invalidate_active_slots(self, prefix: str, day_name: str) -> None:
        """Invalidate cached active slot count for a day across all controller circuits on write failure."""
        short_day = DAY_SHORT_KEYS.get(day_name)
        if not short_day:
            return
        msg_name = f"{prefix}_Slots"
        for circuit in CONTROLLER_CIRCUITS:
            state_key = (circuit, msg_name)
            if state_key in self._state:
                existing = dict(self._state[state_key])
                existing.pop(short_day, None)
                self._state[state_key] = existing
                self._async_notify_message_listeners(circuit, msg_name)

    @callback
    def _async_sync_hmux0_only_entities(self, is_split_hmu: bool) -> None:
        """Disable or re-enable HMUX0-exclusive per-mode electrical sensors in Entity Registry."""
        entry_id = getattr(self.entry, "entry_id", None)
        if not isinstance(entry_id, str) or not entry_id:
            return
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(self.hass)
        hmux0_uids = {
            f"{entry_id}_{suffix}" for suffix in HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES
        }
        for reg_entry in list(er.async_entries_for_config_entry(ent_reg, entry_id)):
            if getattr(reg_entry, "unique_id", None) not in hmux0_uids:
                continue
            if is_split_hmu and reg_entry.disabled_by is None:
                ent_reg.async_update_entity(
                    reg_entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                )
            elif (
                not is_split_hmu
                and reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
            ):
                ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)

    @callback
    def _async_on_outdoor_circuit_changed(self, new_circuit: str) -> None:
        """Handle outdoor circuit transition (e.g. late HMU detection)."""
        is_split_hmu = new_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00)
        self._async_sync_hmux0_only_entities(is_split_hmu)
        if is_split_hmu:
            # 1. Purge incompatible Monobloc b516 messages from pending queue
            self._pending_hydration = [
                (c, m)
                for (c, m) in self._pending_hydration
                if not (c in OUTDOOR_CIRCUITS and m in HMUX0_EXCLUSIVE_MESSAGES)
            ]
            # 2. Find missing HMU specific messages
            missing_hmu = [
                (c, m)
                for (c, m) in HMU_HW5103_HYDRATION_MESSAGES
                if not self.has_message(c, m) and (c, m) not in self._pending_hydration
            ]
            if missing_hmu:
                if self._hydration_task is not None and not self._hydration_task.done():
                    # Append missing HMU messages to currently running queue
                    self._pending_hydration.extend(missing_hmu)
                elif self._initial_hydration_started:
                    # Initial hydration already ran and finished; start a new queue for HMU
                    self._hydration_task = self.hass.async_create_background_task(
                        self._async_run_hydration_queue(missing_hmu),
                        name=f"{self.entry.domain}_hmu_late_hydration",
                    )
        if any((c, m.lower()) in THERMO_TRIGGER_MESSAGES for (c, m) in self._state):
            self._async_recalculate_thermodynamics()

    @callback
    def _async_start_initial_hydration(self, _now: datetime) -> None:
        """Start background task to hydrate missing messages after retained wait."""
        self._hydration_timer_unsub = None
        self._initial_hydration_started = True
        if self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00):
            missing: list[tuple[str, str]] = [
                (circuit, message)
                for circuit, message in ESSENTIAL_HYDRATION_MESSAGES
                if not (
                    circuit in OUTDOOR_CIRCUITS and message in HMUX0_EXCLUSIVE_MESSAGES
                )
                and not self.has_message(circuit, message)
            ]
            for circuit, message in HMU_HW5103_HYDRATION_MESSAGES:
                if not self.has_message(circuit, message):
                    missing.append((circuit, message))
        else:
            missing = [
                (circuit, message)
                for circuit, message in ESSENTIAL_HYDRATION_MESSAGES
                if not self.has_message(circuit, message)
            ]
        if self.has_wireless_room_unit and not self.has_message(
            CIRCUIT_NETX3, "RoomTempDial"
        ):
            missing.append((CIRCUIT_NETX3, "RoomTempDial"))

        if not missing:
            _LOGGER.debug(
                "All essential eBUSd messages already hydrated via retained MQTT payloads"
            )
            self._async_verify_custom_csv_after_hydration()
            return

        _LOGGER.info(
            "Starting staggered eBUSd initial hydration (/get) for %d missing messages (%.1fs step)",
            len(missing),
            HYDRATION_STEP_DELAY_SECONDS,
        )
        self._hydration_task = self.hass.async_create_background_task(
            self._async_run_hydration_queue(missing),
            name=f"{self.entry.domain}_initial_hydration",
        )

    async def _async_run_hydration_queue(self, messages: list[tuple[str, str]]) -> None:
        """Publish /get sequentially with 0.8s spacing to avoid eBUS collisions."""
        self._pending_hydration = list(messages)
        try:
            while self._pending_hydration:
                circuit, message = self._pending_hydration.pop(0)
                if self.has_message(circuit, message):
                    continue
                if (
                    self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00)
                    and circuit in OUTDOOR_CIRCUITS
                    and message in HMUX0_EXCLUSIVE_MESSAGES
                ):
                    continue
                await self.async_request_get(circuit, message)
                await asyncio.sleep(HYDRATION_STEP_DELAY_SECONDS)
        except asyncio.CancelledError:
            _LOGGER.debug("Initial eBUSd hydration task cancelled")
            raise
        finally:
            self._pending_hydration.clear()
        _LOGGER.info("Completed initial staggered eBUSd hydration queue")
        self._async_verify_custom_csv_after_hydration()

    async def _async_run_fallback_poll(self, _now: datetime) -> None:
        """Periodic fallback poll executed only when has_migo_link is False."""
        if self.has_migo_link:
            return
        if self._hydration_task is not None and not self._hydration_task.done():
            return
        # Poll core operational messages + live telemetry & energy counters with gentle spacing
        if self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00):
            fallback_energy_messages: list[tuple[str, str]] = [
                (CIRCUIT_HMU, "HMUStatusCode"),
                (CIRCUIT_HMU, "StateCompressor"),
                (CIRCUIT_HMU, "RunDataCompressorSpeed"),
                (CIRCUIT_HMU, "PowerStatus"),
                (CIRCUIT_HMU, "RunDataElectricPowerConsumption"),
                (CIRCUIT_HMU, "RunDataFlowRate"),
                (CIRCUIT_HMU, "RunDataFlowTemp"),
                (CIRCUIT_HMU, "RunDataReturnTemp"),
                (CIRCUIT_HMU, "YieldHc"),
                (CIRCUIT_HMU, "YieldHwc"),
                (CIRCUIT_HMU, "YieldCooling"),
                (CIRCUIT_HMU, "CopHc"),
                (CIRCUIT_HMU, "CopHwc"),
                (CIRCUIT_HMU, "CopCooling"),
                (CIRCUIT_HMU, "TotalEnergyUsage"),
                (CIRCUIT_HMU, "FlowPressure"),
                (CIRCUIT_HMU, "EnergyIntegral"),
                (CIRCUIT_HMU, "CompressorHours"),
                (CIRCUIT_HMU, "CompressorStarts"),
                (CIRCUIT_VWZIO, "PowerStatus"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
            ]
        else:
            fallback_energy_messages = [
                (CIRCUIT_HMUX0, "HMUStatusCode"),
                (CIRCUIT_HMUX0, "StateCompressor"),
                (CIRCUIT_HMUX0, "RunDataCompressorSpeed"),
                (CIRCUIT_HMUX0, "PowerStatus"),
                (CIRCUIT_HMUX0, "RunDataElectricPowerConsumption"),
                (CIRCUIT_HMUX0, "RunDataFlowRate"),
                (CIRCUIT_HMUX0, "RunDataFlowTemp"),
                (CIRCUIT_HMUX0, "RunDataReturnTemp"),
                (CIRCUIT_HMUX0, "PrEnergyElectricHc"),
                (CIRCUIT_HMUX0, "PrEnergyElectricHwc"),
                (CIRCUIT_HMUX0, "PrEnergyElectricCool"),
                (CIRCUIT_HMUX0, "PrEnergyThermalHc"),
                (CIRCUIT_HMUX0, "PrEnergyThermalHwc"),
                (CIRCUIT_HMUX0, "PrEnergyThermalCool"),
                (CIRCUIT_HMUX0, "PrEnergyEnvYieldHc"),
                (CIRCUIT_HMUX0, "PrEnergyEnvYieldHwc"),
                (CIRCUIT_VWZIO, "PowerStatus"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
            ]
        controller_hydration_messages = [
            item for item in ESSENTIAL_HYDRATION_MESSAGES if item[0] == CIRCUIT_BASS3
        ]
        core_messages = list(
            dict.fromkeys([*controller_hydration_messages, *fallback_energy_messages])
        )
        self._hydration_task = self.hass.async_create_background_task(
            self._async_force_poll_queue(core_messages),
            name=f"{self.entry.domain}_fallback_poll",
        )

    async def _async_force_poll_queue(self, messages: list[tuple[str, str]]) -> None:
        """Sequentially request /get on messages with 0.8s spacing."""
        for circuit, message in messages:
            await self.async_request_get(circuit, message)
            await asyncio.sleep(HYDRATION_STEP_DELAY_SECONDS)

    # -------------------------------------------------------------------------
    # Advanced eBUSd TCP Daemon Polling (Diagnostics & Info)
    # -------------------------------------------------------------------------

    @callback
    def _async_setup_ebusd_tcp_polling(self) -> None:
        """Set up or cancel periodic eBUSd TCP info polling based on options."""
        if self._ebusd_tcp_poll_unsub is not None:
            self._ebusd_tcp_poll_unsub()
            self._ebusd_tcp_poll_unsub = None

        if not self.is_ebusd_tcp_enabled:
            return

        _LOGGER.info(
            "Advanced eBUSd TCP connection enabled; polling info from %s:%s every 60s",
            self.ebusd_tcp_host,
            self.ebusd_tcp_port,
        )

        if self.hass:
            self.hass.async_create_background_task(
                self._async_fetch_ebusd_tcp_info(),
                name=f"{DOMAIN}_initial_tcp_info_{self.entry.entry_id}",
            )
            self._ebusd_tcp_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_run_ebusd_tcp_poll,
                timedelta(seconds=60),
            )

    async def _async_run_ebusd_tcp_poll(self, _now: datetime) -> None:
        """Periodic timer callback to fetch eBUSd TCP daemon info."""
        await self._async_fetch_ebusd_tcp_info()

    async def _async_open_tcp_connection(
        self, host: str, port: int, timeout: float = 3.0
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open TCP connection to eBUSd socket, falling back to HA add-on hostnames if localhost fails."""
        try:
            connect_coro = asyncio.open_connection(host, port)
            return await asyncio.wait_for(connect_coro, timeout=timeout)
        except (TimeoutError, OSError):
            if host in ("127.0.0.1", "localhost"):
                fallback_hosts = ("b4d7ad18-ebusd", "local-ebusd", "ebusd")
                for fb_host in fallback_hosts:
                    try:
                        connect_coro = asyncio.open_connection(fb_host, port)
                        reader, writer = await asyncio.wait_for(
                            connect_coro, timeout=timeout
                        )
                        _LOGGER.debug(
                            "Connected to eBUSd TCP socket via fallback host '%s:%s'",
                            fb_host,
                            port,
                        )
                        return reader, writer
                    except (TimeoutError, OSError):
                        continue
            raise

    async def _async_fetch_ebusd_tcp_info(self) -> None:
        """Fetch daemon health, metrics, and loaded CSV status directly from eBUSd TCP socket."""
        if not self.is_ebusd_tcp_enabled:
            return

        host = self.ebusd_tcp_host
        port = self.ebusd_tcp_port
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await self._async_open_tcp_connection(
                host, port, timeout=3.0
            )
            writer.write(b"info\n")
            await writer.drain()

            lines: list[str] = []
            while True:
                try:
                    line_bytes = await asyncio.wait_for(reader.readline(), timeout=3.0)
                except (TimeoutError, StopAsyncIteration):
                    break
                if not line_bytes:
                    break
                line = line_bytes.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                lines.append(line)
        except (TimeoutError, OSError) as err:
            _LOGGER.debug(
                "Unable to connect to eBUSd TCP socket at %s:%s for info: %s",
                host,
                port,
                err,
            )
            return
        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()

        if not lines:
            return

        missing_csv_devices: list[dict[str, str]] = []
        loaded_csv_devices: list[dict[str, str]] = []
        total_scanned = 0

        for line in lines:
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()

            if key == "version":
                self._state[(CIRCUIT_GLOBAL, "version")] = {"value": val}
                self._async_notify_message_listeners(CIRCUIT_GLOBAL, "version")
            elif key == "symbol rate":
                with contextlib.suppress(ValueError):
                    self._state[(CIRCUIT_GLOBAL, "symbol_rate")] = {"value": int(val)}
                    self._async_notify_message_listeners(CIRCUIT_GLOBAL, "symbol_rate")
            elif key == "reconnects":
                with contextlib.suppress(ValueError):
                    self._state[(CIRCUIT_GLOBAL, "reconnects")] = {"value": int(val)}
                    self._async_notify_message_listeners(CIRCUIT_GLOBAL, "reconnects")
            elif key == "masters":
                with contextlib.suppress(ValueError):
                    self._state[(CIRCUIT_GLOBAL, "masters")] = {"value": int(val)}
                    self._async_notify_message_listeners(CIRCUIT_GLOBAL, "masters")
            elif key in ("max arbitration micros", "arbitration micros"):
                with contextlib.suppress(ValueError):
                    micros = int(val)
                    ms = round(micros / 1000.0)
                    self._state[(CIRCUIT_GLOBAL, "arbitration_latency")] = {"value": ms}
                    self._async_notify_message_listeners(
                        CIRCUIT_GLOBAL, "arbitration_latency"
                    )
            elif key.startswith("address ") and 'scanned "' in val:
                total_scanned += 1
                addr = key.replace("address", "").strip()
                scanned_part = val.partition('scanned "')[2].partition('"')[0]
                fields = dict(
                    item.split("=", 1)
                    for item in scanned_part.split(";")
                    if "=" in item
                )
                dev_id = fields.get("ID", addr)
                sw_ver = fields.get("SW", "")
                hw_ver = fields.get("HW", "")
                if ', loaded "' in val:
                    csv_file = val.partition(', loaded "')[2].rstrip('"')
                    loaded_csv_devices.append(
                        {
                            "address": addr,
                            "id": dev_id,
                            "csv": csv_file,
                            "sw": sw_ver,
                            "hw": hw_ver,
                        }
                    )
                else:
                    missing_csv_devices.append(
                        {
                            "address": addr,
                            "id": dev_id,
                            "sw": sw_ver,
                            "hw": hw_ver,
                        }
                    )

        summary_val = (
            ", ".join(d["id"] for d in missing_csv_devices)
            if missing_csv_devices
            else "OK"
        )
        self._state[(CIRCUIT_GLOBAL, "missing_csv_devices")] = {
            "value": summary_val,
            "missing_count": len(missing_csv_devices),
            "missing_devices": [
                f"{d['id']} (addr: {d['address']}, SW: {d['sw']}, HW: {d['hw']})"
                for d in missing_csv_devices
            ],
            "loaded_devices": [
                f"{d['address']}: {d['id']} ({d['csv']})" for d in loaded_csv_devices
            ],
            "total_scanned": total_scanned,
        }
        self._async_notify_message_listeners(CIRCUIT_GLOBAL, "missing_csv_devices")

    async def async_ebusd_tcp_reload(self) -> str:
        """Send reload command to eBUSd via TCP socket to reload all CSV definition files."""
        res = await self._async_send_ebusd_tcp_command("reload\n")
        await self._async_fetch_ebusd_tcp_info()
        return res

    async def async_ebusd_tcp_scan(self) -> str:
        """Send scan config command to eBUSd via TCP socket to restart device scanning."""
        res = await self._async_send_ebusd_tcp_command("scan config\n")
        await self._async_fetch_ebusd_tcp_info()
        return res

    async def _async_send_ebusd_tcp_command(self, cmd: str) -> str:
        """Send a raw command string to eBUSd TCP socket and return its decoded response."""
        if not self.is_ebusd_tcp_enabled:
            raise HomeAssistantError(
                "eBUSd TCP connection is disabled in integration options."
            )

        host = self.ebusd_tcp_host
        port = self.ebusd_tcp_port
        try:
            reader, writer = await self._async_open_tcp_connection(
                host, port, timeout=5.0
            )
        except (TimeoutError, OSError) as err:
            _LOGGER.error(
                "Failed to connect to eBUSd TCP socket at %s:%s for command '%s': %s",
                host,
                port,
                cmd.strip(),
                err,
            )
            raise HomeAssistantError(
                f"Failed to connect to eBUSd daemon at {host}:{port}: {err}"
            ) from err

        try:
            writer.write(cmd.encode("ascii"))
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            resp = raw.decode("ascii", errors="replace").strip()
        except (TimeoutError, OSError) as err:
            _LOGGER.error(
                "Error communicating with eBUSd TCP socket at %s:%s for command '%s': %s",
                host,
                port,
                cmd.strip(),
                err,
            )
            raise HomeAssistantError(
                f"Error sending command '{cmd.strip()}' to eBUSd: {err}"
            ) from err
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

        await self._async_fetch_ebusd_tcp_info()
        return resp

    # -------------------------------------------------------------------------
    # Real-Time Thermodynamic Calculations (Section 6.2)
    # -------------------------------------------------------------------------

    def _set_calculated(self, key: str, value: Any) -> None:
        """Store a calculated metric and notify its entity listeners if changed."""
        state_key = (CALC_CIRCUIT, key)
        prev = self._state.get(state_key, {}).get("value")
        self._canonical_names[(CALC_CIRCUIT, key.lower())] = key
        self._state[state_key] = {"value": value}
        if prev != value:
            self._async_notify_message_listeners(CALC_CIRCUIT, key)

    @callback
    def _async_recalculate_thermodynamics(self) -> None:
        """Recalculate Delta T, Thermal Power, Live COP, Mode Totals (Wh), and Historical COP/EER."""
        # 1. Primary Flow and Return Temperatures -> Delta T (K)
        flow_temp = self.get_float(CIRCUIT_HMUX0, "RunDataFlowTemp", "value")
        if flow_temp is None:
            flow_temp = self.get_float(CIRCUIT_HMUX0, "Status01", "temp1")

        return_temp = self.get_float(CIRCUIT_HMUX0, "RunDataReturnTemp", "value")
        if return_temp is None:
            return_temp = self.get_float(CIRCUIT_HMUX0, "Status01", "return_temp")

        delta_t = calculate_delta_t(flow_temp, return_temp)
        if delta_t is not None:
            self._set_calculated(CALC_DELTA_T, delta_t)

        # 2. Instantaneous Thermal Power (W)
        hmu_status = self.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status") or ""
        flow_rate = self.get_float(CIRCUIT_HMUX0, "RunDataFlowRate", "flow_rate")
        thermal_power = calculate_thermal_power(flow_rate, delta_t, hmu_status)
        if thermal_power is not None:
            self._set_calculated(CALC_THERMAL_POWER, thermal_power)

        # 3. Live Instantaneous COP / EER
        elec_power = self.get_instantaneous_electric_power()
        live_cop, is_active = calculate_live_cop(
            thermal_power, elec_power, hmu_status, frozenset(ACTIVE_COMPRESSOR_STATUSES)
        )
        if live_cop is not None:
            if is_active:
                self.last_active_cop = live_cop
            self._set_calculated(CALC_LIVE_COP, live_cop)

        # 4 & 5. Per-Mode & Combined System Cumulative Electrical Energy (Wh) & Efficiency (COP / EER)
        is_split_hmu = self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00)
        vwzio_elec_hc = self.get_float(CIRCUIT_VWZIO, "PrEnergyElectricHc", "energy")
        vwzio_elec_hwc = self.get_float(CIRCUIT_VWZIO, "PrEnergyElectricHwc", "energy")
        vwzio_therm_hc = self.get_float(CIRCUIT_VWZIO, "PrEnergyThermalHc", "energy")
        vwzio_therm_hwc = self.get_float(CIRCUIT_VWZIO, "PrEnergyThermalHwc", "energy")

        if is_split_hmu:
            # HMU / HMU00 (HW5103): 76.vwzio only meters indoor standby/immersion heater,
            # while outdoor compressor metering lives in 08.hmu (b51a, kWh) and 15.* (b524, kWh).
            pr_sum_hc_kwh = self.get_float(CIRCUIT_BASS3, "PrEnergySumHc", "value")
            if pr_sum_hc_kwh is not None:
                self._set_calculated(
                    CALC_HEATING_TOTAL_ENERGY, round(pr_sum_hc_kwh * 1000.0, 1)
                )

            pr_sum_hwc_kwh = self.get_float(CIRCUIT_BASS3, "PrEnergySumHwc", "value")
            if pr_sum_hwc_kwh is not None:
                self._set_calculated(
                    CALC_DHW_TOTAL_ENERGY, round(pr_sum_hwc_kwh * 1000.0, 1)
                )

            total_usage_kwh = self.get_float(CIRCUIT_HMU, "TotalEnergyUsage", "value")
            if (
                total_usage_kwh is not None
                and vwzio_elec_hc is not None
                and vwzio_elec_hwc is not None
            ):
                self._set_calculated(
                    CALC_SYSTEM_TOTAL_ENERGY,
                    round(total_usage_kwh * 1000.0 + vwzio_elec_hc + vwzio_elec_hwc, 1),
                )

            yield_hc_kwh = self.get_float(CIRCUIT_HMU, "YieldHc", "value")
            yield_hwc_kwh = self.get_float(CIRCUIT_HMU, "YieldHwc", "value")
            yield_cool_kwh = self.get_float(CIRCUIT_HMU, "YieldCooling", "value")
            hmu_cop_hc = self.get_float(CIRCUIT_HMU, "CopHc", "value")
            hmu_cop_hwc = self.get_float(CIRCUIT_HMU, "CopHwc", "value")
            hmu_cop_cool = self.get_float(CIRCUIT_HMU, "CopCooling", "value")

            hc_cop: float | None = None
            if hmu_cop_hc is not None and hmu_cop_hc > 0:
                hc_cop = round(hmu_cop_hc, 2)
            elif yield_hc_kwh is not None and pr_sum_hc_kwh is not None:
                hc_cop = calculate_period_cop(
                    (yield_hc_kwh + pr_sum_hc_kwh) * 1000.0,
                    pr_sum_hc_kwh * 1000.0,
                    min_elec_energy=MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH,
                )
            if hc_cop is not None:
                self._set_calculated(CALC_HC_COP, hc_cop)

            hwc_cop: float | None = None
            if hmu_cop_hwc is not None and hmu_cop_hwc > 0:
                hwc_cop = round(hmu_cop_hwc, 2)
            elif yield_hwc_kwh is not None and pr_sum_hwc_kwh is not None:
                hwc_cop = calculate_period_cop(
                    (yield_hwc_kwh + pr_sum_hwc_kwh) * 1000.0,
                    pr_sum_hwc_kwh * 1000.0,
                    min_elec_energy=MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH,
                )
            if hwc_cop is not None:
                self._set_calculated(CALC_HWC_COP, hwc_cop)

            cool_eer: float | None = None
            if hmu_cop_cool is not None and hmu_cop_cool > 0:
                cool_eer = round(hmu_cop_cool, 2)
            elif yield_cool_kwh is not None and yield_cool_kwh == 0.0:
                cool_eer = 0.0
            if cool_eer is not None:
                self._set_calculated(CALC_COOL_EER, cool_eer)

            if (
                yield_hc_kwh is not None
                and yield_hwc_kwh is not None
                and yield_cool_kwh is not None
                and total_usage_kwh is not None
            ):
                outdoor_therm_wh = (
                    yield_hc_kwh + yield_hwc_kwh + yield_cool_kwh + total_usage_kwh
                ) * 1000.0
                global_efficiency = calculate_combined_efficiency(
                    (outdoor_therm_wh, vwzio_therm_hc, vwzio_therm_hwc),
                    (total_usage_kwh * 1000.0, vwzio_elec_hc, vwzio_elec_hwc),
                )
                if global_efficiency is not None:
                    self._set_calculated(CALC_GLOBAL_EFFICIENCY, global_efficiency)
        else:
            # HMUX0 (HW0402): High-resolution b516 Wh EEPROM counters on 08.hmux0 + 76.vwzio
            hmux0_elec_hc = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyElectricHc", "energy"
            )
            hmux0_elec_hwc = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyElectricHwc", "energy"
            )
            hmux0_elec_cool = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyElectricCool", "energy"
            )

            heating_total_wh = calculate_combined_mode_energy(
                hmux0_elec_hc, vwzio_elec_hc
            )
            if heating_total_wh is not None:
                self._set_calculated(CALC_HEATING_TOTAL_ENERGY, heating_total_wh)

            dhw_total_wh = calculate_combined_mode_energy(
                hmux0_elec_hwc, vwzio_elec_hwc
            )
            if dhw_total_wh is not None:
                self._set_calculated(CALC_DHW_TOTAL_ENERGY, dhw_total_wh)

            system_total_wh = calculate_system_total_energy(
                heating_total_wh, dhw_total_wh, hmux0_elec_cool
            )
            if system_total_wh is not None:
                self._set_calculated(CALC_SYSTEM_TOTAL_ENERGY, system_total_wh)

            hmux0_therm_hc = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyThermalHc", "energy"
            )
            hmux0_therm_hwc = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyThermalHwc", "energy"
            )
            hmux0_therm_cool = self.get_float(
                CIRCUIT_HMUX0, "PrEnergyThermalCool", "energy"
            )

            hc_cop = calculate_combined_efficiency(
                (hmux0_therm_hc, vwzio_therm_hc),
                (hmux0_elec_hc, vwzio_elec_hc),
            )
            if hc_cop is not None:
                self._set_calculated(CALC_HC_COP, hc_cop)

            hwc_cop = calculate_combined_efficiency(
                (hmux0_therm_hwc, vwzio_therm_hwc),
                (hmux0_elec_hwc, vwzio_elec_hwc),
            )
            if hwc_cop is not None:
                self._set_calculated(CALC_HWC_COP, hwc_cop)

            cool_eer = calculate_period_cop(
                hmux0_therm_cool,
                hmux0_elec_cool,
                min_elec_energy=MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH,
            )
            if cool_eer is not None:
                self._set_calculated(CALC_COOL_EER, cool_eer)

            global_efficiency = calculate_combined_efficiency(
                (
                    hmux0_therm_hc,
                    vwzio_therm_hc,
                    hmux0_therm_hwc,
                    vwzio_therm_hwc,
                    hmux0_therm_cool,
                ),
                (
                    hmux0_elec_hc,
                    vwzio_elec_hc,
                    hmux0_elec_hwc,
                    vwzio_elec_hwc,
                    hmux0_elec_cool,
                ),
            )
            if global_efficiency is not None:
                self._set_calculated(CALC_GLOBAL_EFFICIENCY, global_efficiency)

    # -------------------------------------------------------------------------
    # Smart Forced DHW Boost Manager (Section 7.2)
    # -------------------------------------------------------------------------

    async def async_trigger_dhw_boost(
        self, override_boost_temp: float | None = None
    ) -> None:
        """Activate DHW One-Time Boost (HwcSFMode=load), dynamically overcoming hysteresis."""
        storage_temp = self.get_float(CIRCUIT_BASS3, "HwcStorageTemp", "value")
        target_temp = self.get_float(CIRCUIT_BASS3, "HwcTempDesired", "value") or 50.0
        hyst = (
            self.get_float(
                CIRCUIT_BASS3, "CylinderChargeHyst", "value", DEFAULT_CYLINDER_HYST
            )
            or DEFAULT_CYLINDER_HYST
        )

        needs_hyst_bypass = (
            self.force_dhw_boost
            and storage_temp is not None
            and storage_temp > (target_temp - hyst)
        )
        needs_override_elevation = (
            override_boost_temp is not None and override_boost_temp > target_temp
        )

        if needs_hyst_bypass or needs_override_elevation:
            # Save original target temperature only if not already in a forced boost cycle
            if not self._dhw_boost_active or self._saved_dhw_target_temp is None:
                self._saved_dhw_target_temp = target_temp

            # Dynamic temporary setpoint: T_storage + Hysteresis + 1.5 °C (or explicit service override if higher)
            dynamic_temp = (
                storage_temp + hyst + DHW_BOOST_HYST_MARGIN
                if storage_temp is not None
                else target_temp + hyst + DHW_BOOST_HYST_MARGIN
            )
            desired_boost = (
                max(override_boost_temp, dynamic_temp)
                if override_boost_temp is not None
                else dynamic_temp
            )
            raw_temp = min(68.0, desired_boost)
            temp_setpoint = round(raw_temp * 2.0) / 2.0  # Round to 0.5 °C step

            _LOGGER.info(
                "Smart Forced DHW Boost: storage=%s°C, original_target=%.1f°C, hyst=%.1fK. "
                "Temporarily elevating HwcTempDesired to %.1f°C before sending HwcSFMode=load",
                f"{storage_temp:.1f}" if storage_temp is not None else "unknown",
                self._saved_dhw_target_temp,
                hyst,
                temp_setpoint,
            )

            self._dhw_boost_active = True
            self._dhw_boost_goal_temp = (
                override_boost_temp
                if override_boost_temp is not None
                else self._saved_dhw_target_temp
            )
            self._dhw_boost_started_at = time.monotonic()
            self._dhw_boost_seen_load = False

            # Schedule 60-minute safety restoration timer
            if self._dhw_boost_timeout_unsub is not None:
                self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = async_call_later(
                self.hass,
                DHW_BOOST_MAX_TIMEOUT_SECONDS,
                self._async_on_dhw_boost_timeout,
            )

            await self.async_write_parameter(
                CIRCUIT_BASS3, "HwcTempDesired", temp_setpoint
            )
            # Physical eBUS pacing: 1.0s delay allows the controller to accept the new setpoint
            # before sending the one-time load trigger command over the 2400-baud bus.
            await asyncio.sleep(1.0)
            await self.async_write_parameter(CIRCUIT_BASS3, "HwcSFMode", "load")
        else:
            _LOGGER.info(
                "Standard DHW Boost: sending HwcSFMode=load directly (storage=%s, target=%.1f°C)",
                storage_temp,
                target_temp,
            )
            await self.async_write_parameter(CIRCUIT_BASS3, "HwcSFMode", "load")

    def cancel_dhw_boost_tracking(self, new_target: float | None = None) -> None:
        """Cancel or update boost tracking if user manually adjusts temperature."""
        if self._dhw_boost_active:
            if new_target is not None:
                self._saved_dhw_target_temp = new_target
                self._dhw_boost_goal_temp = new_target
            else:
                self._dhw_boost_active = False
                self._saved_dhw_target_temp = None
                self._dhw_boost_goal_temp = None

    async def async_cancel_dhw_boost(self) -> None:
        """Cancel DHW One-Time Boost (HwcSFMode=auto) and restore original setpoint if elevated."""
        await self.async_write_parameter(CIRCUIT_BASS3, "HwcSFMode", "auto")
        if self._dhw_boost_active and self._saved_dhw_target_temp is not None:
            await self._async_restore_dhw_target_temp("user cancelled boost")

    @callback
    def _async_on_dhw_boost_timeout(self, _now: datetime) -> None:
        """Handle 60-minute safety timeout for forced DHW boost."""
        self._dhw_boost_timeout_unsub = None
        if self._dhw_boost_active and self._saved_dhw_target_temp is not None:
            self.hass.async_create_task(
                self._async_restore_dhw_target_temp("60-minute safety timeout")
            )

    @callback
    def _async_check_dhw_boost_restoration(self) -> None:
        """Check whether the forced DHW boost has completed and original setpoint should be restored."""
        if not self._dhw_boost_active or self._saved_dhw_target_temp is None:
            return

        sf_mode = (self.get_str(CIRCUIT_BASS3, "HwcSFMode", "value") or "").lower()
        hwc_status = (self.get_str(CIRCUIT_BASS3, "HwcStatus", "value") or "").lower()
        storage_temp = self.get_float(CIRCUIT_BASS3, "HwcStorageTemp", "value")

        if sf_mode == "load" or hwc_status == "load":
            self._dhw_boost_seen_load = True

        elapsed = time.monotonic() - self._dhw_boost_started_at

        # Condition 1: HwcSFMode returned to "auto" (after either seeing "load" or 15s grace period)
        if sf_mode == "auto" and (self._dhw_boost_seen_load or elapsed > 15.0):
            self.hass.async_create_task(
                self._async_restore_dhw_target_temp("HwcSFMode returned to auto")
            )
            return

        # Condition 2: Storage temperature exceeded goal target + 1.0 °C
        goal_temp = (
            self._dhw_boost_goal_temp
            if self._dhw_boost_goal_temp is not None
            else self._saved_dhw_target_temp
        )
        if (
            storage_temp is not None
            and storage_temp >= (goal_temp + 1.0)
            and elapsed > 10.0
        ):
            self.hass.async_create_task(
                self._async_restore_dhw_target_temp(
                    f"HwcStorageTemp ({storage_temp:.1f}°C) reached target ({goal_temp:.1f}°C) + 1.0°C"
                )
            )

    async def _async_restore_dhw_target_temp(self, reason: str) -> None:
        """Restore HwcTempDesired to its pre-boost setpoint and clear boost state."""
        saved_temp = self._saved_dhw_target_temp
        self._dhw_boost_active = False
        self._saved_dhw_target_temp = None
        self._dhw_boost_goal_temp = None
        self._dhw_boost_seen_load = False

        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None

        if saved_temp is not None:
            _LOGGER.info(
                "Restoring HwcTempDesired to original setpoint %.1f°C (%s)",
                saved_temp,
                reason,
            )
            await self.async_write_parameter(
                CIRCUIT_BASS3, "HwcTempDesired", saved_temp
            )

    async def async_activate_holiday_mode(
        self,
        temp: float = DEFAULT_HOLIDAY_TEMP,
        start_date: str | None = None,
        start_time: str | None = None,
        end_date: str | None = None,
        end_time: str | None = None,
    ) -> None:
        """Activate Holiday / Away Mode with specified setback temperature and time window."""
        now = datetime.now()
        cur_date_str = f"{now.day:02d};{now.month:02d};{now.year % 100:02d}"
        cur_time_str = f"{now.hour:02d};{now.minute:02d};{now.second:02d}"

        # If explicit arguments not supplied, check preselected datetime buffers
        if start_date is None and self._preselected_holiday_start_datetime is not None:
            s_dt = self._preselected_holiday_start_datetime
            start_date = f"{s_dt.day:02d};{s_dt.month:02d};{s_dt.year % 100:02d}"
            if start_time is None:
                start_time = f"{s_dt.hour:02d};{s_dt.minute:02d};{s_dt.second:02d}"

        if end_date is None and self._preselected_holiday_end_datetime is not None:
            e_dt = self._preselected_holiday_end_datetime
            end_date = f"{e_dt.day:02d};{e_dt.month:02d};{e_dt.year % 100:02d}"
            if end_time is None:
                end_time = f"{e_dt.hour:02d};{e_dt.minute:02d};{e_dt.second:02d}"

        target_start_date = _normalize_date_param(start_date, cur_date_str)
        target_start_time = _normalize_time_param(start_time, cur_time_str)
        target_end_date = _normalize_date_param(end_date, HOLIDAY_INDEFINITE_END_DATE)
        target_end_time = _normalize_time_param(end_time, HOLIDAY_DEFAULT_END_TIME)

        _LOGGER.info(
            "Activating Holiday / Away Mode: temp=%.1f°C, window=[%s %s to %s %s]",
            temp,
            target_start_date,
            target_start_time,
            target_end_date,
            target_end_time,
        )

        # Ensure any active synthetic cooling quick veto is restored and cancelled cleanly before Holiday takes over
        if getattr(self, "cooling_quick_veto_active", False):
            await self.async_cancel_cooling_quick_veto(restore=True)
            await asyncio.sleep(0.4)

        # Step 1: Set setback temperature (EXP float)
        await self.async_write_parameter(CIRCUIT_BASS3, "HolidayTemp", temp)
        await asyncio.sleep(0.4)

        # Step 2: Set start date
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartDate", target_start_date
        )
        await asyncio.sleep(0.4)

        # Step 3: Set start time
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartTime", target_start_time
        )
        await asyncio.sleep(0.4)

        # Step 4: Set end date
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndDate", target_end_date
        )
        await asyncio.sleep(0.4)

        # Step 5: Set end time
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndTime", target_end_time
        )

    def get_holiday_remaining_days(self) -> int | str:
        """Calculate remaining days of holiday mode.

        Returns:
            - STATE_INACTIVE ('Inactive'): when holiday mode is off (Z1Status != 'holidayaway' or reset sentinel 2015).
            - STATE_OPEN_ENDED ('Open-ended'): when holiday mode is active with indefinite / open-ended end date (year == 99).
            - int: number of days remaining (>= 0) when holiday mode is active with a defined calendar window.
        """
        z1_status = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        start_msg = self.get_message(CIRCUIT_BASS3, "HolidayStartDate")
        end_msg = self.get_message(CIRCUIT_BASS3, "HolidayEndDate")

        if not end_msg:
            return STATE_INACTIVE

        day = end_msg.get("day")
        month = end_msg.get("month")
        year = end_msg.get("year")
        if day is None or month is None or year is None or year == 15:
            return STATE_INACTIVE

        start_year = start_msg.get("year") if start_msg else None
        if start_year == 15:
            return STATE_INACTIVE

        if z1_status and z1_status != "holidayaway" and start_year is None:
            return STATE_INACTIVE

        if year == 99:
            return STATE_OPEN_ENDED

        try:
            target_date = datetime(2000 + int(year), int(month), int(day)).date()
            diff = (target_date - datetime.now().date()).days
            if diff < 0:
                return STATE_INACTIVE
            return diff
        except (ValueError, TypeError, OverflowError):
            return STATE_INACTIVE

    def _format_bass3_date(
        self, circuit: str, message: str, sentinel_year: int
    ) -> str | None:
        """Format a bass3 date field as DD/MM/20YY, or None if sentinel."""
        msg = self.get_message(circuit, message)
        if not msg:
            return None
        day = msg.get("day")
        month = msg.get("month")
        year = msg.get("year")
        if (
            not isinstance(day, int)
            or not isinstance(month, int)
            or not isinstance(year, int)
        ):
            return None
        if year == sentinel_year:
            return None
        return f"{day:02d}/{month:02d}/20{year:02d}"

    def get_holiday_remaining_attributes(self) -> dict[str, Any]:
        """Return structured extra attributes for holiday duration remaining."""
        val = self.get_holiday_remaining_days()
        is_active = val != STATE_INACTIVE
        is_open_ended = val == STATE_OPEN_ENDED
        return {
            "days_remaining": val
            if isinstance(val, int)
            else (0 if val == STATE_INACTIVE else None),
            "is_active": is_active,
            "is_open_ended": is_open_ended,
            "start_date": self._format_bass3_date(
                CIRCUIT_BASS3, "HolidayStartDate", 15
            ),
            "end_date": self._format_bass3_date(CIRCUIT_BASS3, "HolidayEndDate", 15),
        }

    def get_cooling_remaining_days(self) -> int | str:
        """Calculate remaining days of cooling period.

        Returns:
            - STATE_INACTIVE ('Inactive'): when cooling is off (release status 'off', year == 19 epoch, or expired).
            - STATE_OPEN_ENDED ('Open-ended'): when cooling is active with indefinite / open-ended end date (year == 99).
            - int: number of days remaining (>= 0) when cooling is active within a defined window.
        """
        release_status = self.get_str(CIRCUIT_BASS3, "CoolingReleaseStatus", "value")
        z1_op_mode_cooling = (
            self.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or ""
        ).lower()
        end_msg = self.get_message(CIRCUIT_BASS3, "CoolingEndDate")

        if not end_msg:
            return STATE_INACTIVE

        day = end_msg.get("day")
        month = end_msg.get("month")
        year = end_msg.get("year")
        if day is None or month is None or year is None or year == 19:
            return STATE_INACTIVE

        # Explicitly off in status and not year 99
        if (
            release_status is not None
            and release_status.lower() == "off"
            and year != 99
        ):
            return STATE_INACTIVE
        if z1_op_mode_cooling == "off" and year != 99:
            return STATE_INACTIVE

        if year == 99:
            return STATE_OPEN_ENDED

        try:
            target_date = datetime(2000 + int(year), int(month), int(day)).date()
            diff = (target_date - datetime.now().date()).days
            if diff < 0:
                return STATE_INACTIVE
            return diff
        except (ValueError, TypeError, OverflowError):
            return STATE_INACTIVE

    def get_cooling_remaining_attributes(self) -> dict[str, Any]:
        """Return structured extra attributes for cooling duration remaining."""
        val = self.get_cooling_remaining_days()
        is_active = val != STATE_INACTIVE
        is_open_ended = val == STATE_OPEN_ENDED
        return {
            "days_remaining": val
            if isinstance(val, int)
            else (0 if val == STATE_INACTIVE else None),
            "is_active": is_active,
            "is_open_ended": is_open_ended,
            "start_date": self._format_bass3_date(
                CIRCUIT_BASS3, "CoolingStartDate", 19
            ),
            "end_date": self._format_bass3_date(CIRCUIT_BASS3, "CoolingEndDate", 19),
        }

    async def async_cancel_holiday_mode(self) -> None:
        """Cancel Holiday / Away Mode and restore central controller to automatic operation."""
        _LOGGER.info("Cancelling Holiday / Away Mode and restoring auto operation")
        self._preselected_holiday_start_datetime = None
        self._preselected_holiday_end_datetime = None
        # Step 1: Reset start date to sentinel 2015
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartDate", HOLIDAY_RESET_DATE
        )
        await asyncio.sleep(0.4)

        # Step 2: Reset start time to 00:00:00
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartTime", HOLIDAY_RESET_TIME
        )
        await asyncio.sleep(0.4)

        # Step 3: Reset end date to sentinel 2015
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndDate", HOLIDAY_RESET_DATE
        )
        await asyncio.sleep(0.4)

        # Step 4: Reset end time to 00:00:00
        await self.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndTime", HOLIDAY_RESET_TIME
        )
        await asyncio.sleep(0.4)

        # Step 5: Fire cancel execution trigger flag (UCH 01)
        await self.async_write_parameter(CIRCUIT_BASS3, "HolidayCancel", 1)

    @callback
    def _async_check_quick_veto_restoration(self) -> None:
        """Check whether hardware countdown timer ended quick veto and restore prior state."""
        if self._pre_veto_opmode != "off":
            return
        sf_mode = (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").lower()
        if sf_mode != "veto":
            self._pre_veto_opmode = None
            self.hass.async_create_task(
                self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
            )

    async def async_set_quick_veto(
        self,
        temperature: float | None = None,
        duration: float | None = None,
    ) -> None:
        """Activate Quick Veto on Zone 1 with target temperature and duration."""
        if not self.is_ebus_operational:
            raise HomeAssistantError(
                "Cannot execute quick veto: eBUS communication is not operational."
            )

        z1_status = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        if z1_status == "holidayaway":
            raise HomeAssistantError(
                "Cannot activate quick veto while Holiday / Away mode is active."
            )

        current_opmode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "auto"
        ).lower()
        if current_opmode == "off":
            self._pre_veto_opmode = "off"
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "auto")
            await asyncio.sleep(0.3)
        elif self._pre_veto_opmode is None:
            self._pre_veto_opmode = current_opmode

        # Determine target temperature
        if temperature is not None:
            target_temp = round(float(temperature), 1)
        else:
            # Fallback logic: if heating was off, use Z1ManualTemp;
            # if running, use current target + 3.0 °C
            current_target = self.get_float(
                CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
            )
            manual_temp = self.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "value")
            if (
                current_target is not None
                and current_target > 5.5
                and self._pre_veto_opmode != "off"
            ):
                target_temp = round(current_target + self.quick_veto_boost_delta, 1)
            elif manual_temp is not None and manual_temp > 5.0:
                target_temp = round(manual_temp, 1)
            else:
                target_temp = DEFAULT_COMFORT_TEMP

        target_temp = max(10.0, min(30.0, target_temp))

        # Determine duration
        if duration is not None:
            dur_val = round(float(duration), 1)
        else:
            configured_dur = self.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoDuration", "value"
            )
            dur_val = (
                configured_dur
                if configured_dur and configured_dur > 0
                else DEFAULT_QUICK_VETO_DURATION
            )

        dur_val = max(0.5, min(12.0, dur_val))

        _LOGGER.info(
            "Activating Quick Veto: target_temp=%.1f°C, duration=%.1fh",
            target_temp,
            dur_val,
        )
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoTemp", target_temp)
        await asyncio.sleep(0.3)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", dur_val)
        await asyncio.sleep(0.3)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "veto")

    async def async_cancel_quick_veto(self) -> None:
        """Cancel Quick Veto and restore prior operating mode."""
        if not self.is_ebus_operational:
            raise HomeAssistantError(
                "Cannot cancel quick veto: eBUS communication is not operational."
            )

        _LOGGER.info("Cancelling Quick Veto and restoring auto operation")
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "auto")
        await asyncio.sleep(0.3)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0)

        if self._pre_veto_opmode == "off":
            await asyncio.sleep(0.3)
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
        self._pre_veto_opmode = None

    def is_cooling_active(self) -> bool:
        """Return True if Zone 1 cooling mode is currently physically/logically active."""
        cool_mode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or ""
        ).lower()
        heat_mode = (self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "").lower()
        if cool_mode not in ("auto", "day", "night"):
            return False
        if cool_mode == "day":
            return True
        cooling_release = (
            self.get_str(CIRCUIT_BASS3, "CoolingReleaseStatus", "value") or ""
        ).lower()
        if cooling_release == "on":
            return True
        if cooling_release == "off":
            return False
        return heat_mode not in ("auto", "day", "night")

    async def async_set_cooling_quick_veto(
        self,
        temperature: float | None = None,
        duration: float | None = None,
    ) -> None:
        """Activate Cooling Quick Veto on Zone 1 with target temperature and duration."""
        if not self.is_ebus_operational:
            raise HomeAssistantError(
                "Cannot execute cooling quick veto: eBUS communication is not operational."
            )

        z1_status = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        if z1_status == "holidayaway":
            raise HomeAssistantError(
                "Cannot activate cooling quick veto while Holiday / Away mode is active."
            )

        # Cancel any running timers without resetting pre-veto memory
        if self._cooling_veto_unsub is not None:
            self._cooling_veto_unsub()
            self._cooling_veto_unsub = None

        if self._cooling_veto_get_unsub is not None:
            self._cooling_veto_get_unsub()
            self._cooling_veto_get_unsub = None

        if self._cooling_veto_restore_unsub is not None:
            self._cooling_veto_restore_unsub()
            self._cooling_veto_restore_unsub = None

        self._pending_cooling_veto_restore = False

        current_opmode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or "auto"
        ).lower()

        # Capture pre-veto operating mode if starting fresh
        if self._pre_cooling_veto_opmode is None:
            self._pre_cooling_veto_opmode = current_opmode

        manual_temp = self.get_float(CIRCUIT_BASS3, "Z1CoolingManualTemp", "value")
        desired_temp = self.get_float(CIRCUIT_BASS3, "Z1CoolingTempDesired", "value")

        # Determine current baseline target (only for computing default boost drop)
        if desired_temp is not None and desired_temp < SENTINEL_COOLING_THRESHOLD:
            current_target = desired_temp
        elif manual_temp is not None and 10.0 <= manual_temp <= 30.0:
            current_target = manual_temp
        else:
            current_target = DEFAULT_COOLING_TEMP

        # Preserve original Z1CoolingManualTemp separately so active schedule slots
        # never overwrite the user's configured manual cooling setpoint on restore.
        if self._pre_cooling_veto_temp is None:
            if manual_temp is not None and 10.0 <= manual_temp <= 30.0:
                self._pre_cooling_veto_temp = manual_temp
            elif (
                current_opmode == "day"
                and desired_temp is not None
                and 10.0 <= desired_temp <= 30.0
            ):
                self._pre_cooling_veto_temp = desired_temp

        # Determine target temperature
        if temperature is not None:
            target_temp = round(float(temperature), 1)
        else:
            if current_opmode == "auto" and (
                desired_temp is None or desired_temp >= SENTINEL_COOLING_THRESHOLD
            ):
                # Outside scheduled cooling slot: take manual setpoint
                target_temp = (
                    manual_temp
                    if (manual_temp is not None and 10.0 <= manual_temp <= 30.0)
                    else DEFAULT_COOLING_TEMP
                )
            else:
                # In manual or actively cooling in slot: apply cooling boost delta (lower temp)
                target_temp = round(
                    current_target - self.cooling_quick_veto_boost_delta, 1
                )

        target_temp = max(15.0, min(30.0, target_temp))

        # Determine duration
        if duration is not None:
            dur_val = round(float(duration), 1)
        else:
            configured_dur = self.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoDuration", "value"
            )
            dur_val = (
                configured_dur
                if configured_dur and configured_dur > 0
                else DEFAULT_QUICK_VETO_DURATION
            )

        dur_val = max(0.5, min(12.0, dur_val))

        _LOGGER.info(
            "Activating Cooling Quick Veto: target_temp=%.1f°C, duration=%.1fh (pre_opmode=%s, pre_temp=%s)",
            target_temp,
            dur_val,
            self._pre_cooling_veto_opmode,
            self._pre_cooling_veto_temp,
        )

        # If from auto (or not day), switch Z1OpModeCooling to "day" so heat pump produces cooling continuously
        if current_opmode != "day":
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpModeCooling", "day")
            await asyncio.sleep(0.3)

        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingManualTemp", target_temp
        )
        await asyncio.sleep(0.3)
        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingTempDesired", target_temp
        )

        self._cooling_veto_active_temp = target_temp
        self._cooling_veto_end_time = datetime.now() + timedelta(hours=dur_val)

        seconds = dur_val * 3600.0

        @callback
        def _async_on_cooling_veto_timeout(_now: datetime) -> None:
            self._cooling_veto_unsub = None
            self.hass.async_create_task(
                self.async_cancel_cooling_quick_veto(restore=True)
            )

        self._cooling_veto_unsub = async_call_later(
            self.hass, seconds, _async_on_cooling_veto_timeout
        )
        await self._async_save_cooling_veto_state()
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1OpModeCooling")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingManualTemp")

    async def async_update_cooling_quick_veto_temperature(
        self, temperature: float
    ) -> None:
        """Update target temperature of active cooling quick veto without altering remaining duration."""
        if not self.cooling_quick_veto_active:
            await self.async_set_cooling_quick_veto(temperature=temperature)
            return

        target_temp = max(15.0, min(30.0, round(float(temperature), 1)))
        self._cooling_veto_active_temp = target_temp

        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingManualTemp", target_temp
        )
        await asyncio.sleep(0.3)
        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingTempDesired", target_temp
        )
        await self._async_save_cooling_veto_state()
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1OpModeCooling")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingManualTemp")

    async def async_cancel_cooling_quick_veto(
        self, restore: bool = True, restore_temp: bool | None = None
    ) -> None:
        """Cancel Cooling Quick Veto and optionally restore prior operating mode and setpoint."""
        if self._cooling_veto_unsub is not None:
            self._cooling_veto_unsub()
            self._cooling_veto_unsub = None

        if self._cooling_veto_get_unsub is not None:
            self._cooling_veto_get_unsub()
            self._cooling_veto_get_unsub = None

        if self._cooling_veto_restore_unsub is not None:
            self._cooling_veto_restore_unsub()
            self._cooling_veto_restore_unsub = None

        self._pending_cooling_veto_restore = False
        self._cooling_veto_end_time = None
        self._cooling_veto_active_temp = None

        pre_opmode = self._pre_cooling_veto_opmode
        pre_temp = self._pre_cooling_veto_temp
        self._pre_cooling_veto_opmode = None
        self._pre_cooling_veto_temp = None

        await self._async_clear_cooling_veto_store()

        should_restore_temp = restore if restore_temp is None else restore_temp

        if (restore or should_restore_temp) and self.is_ebus_operational:
            _LOGGER.info(
                "Cancelling Cooling Quick Veto: restore=%s, restore_temp=%s (pre_opmode=%s, pre_temp=%s)",
                restore,
                should_restore_temp,
                pre_opmode,
                pre_temp,
            )
            if restore and pre_opmode is not None and pre_opmode != "day":
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpModeCooling", pre_opmode
                )
                await asyncio.sleep(0.3)

            if (
                should_restore_temp
                and pre_temp is not None
                and pre_temp < SENTINEL_COOLING_THRESHOLD
            ):
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", pre_temp
                )
                if restore and pre_opmode == "day":
                    await asyncio.sleep(0.3)
                    await self.async_write_parameter(
                        CIRCUIT_BASS3, "Z1CoolingTempDesired", pre_temp
                    )

            # Returning to auto/night: schedule a confirmation read of Z1CoolingTempDesired
            # so HA picks up the controller's real schedule/setback setpoint (or 99 °C sentinel).
            if restore and pre_opmode != "day":

                @callback
                def _async_refresh_cooling_desired(_now: datetime) -> None:
                    self._cooling_veto_get_unsub = None
                    self.hass.async_create_task(
                        self.async_request_get(CIRCUIT_BASS3, "Z1CoolingTempDesired")
                    )

                self._cooling_veto_get_unsub = async_call_later(
                    self.hass,
                    SET_CONFIRMATION_DELAY_SECONDS,
                    _async_refresh_cooling_desired,
                )

        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1OpModeCooling")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingManualTemp")

    async def _async_save_cooling_veto_state(self) -> None:
        """Persist active cooling quick veto state across Home Assistant restarts."""
        if self._cooling_veto_end_time is None:
            await self._async_clear_cooling_veto_store()
            return
        data = {
            "end_timestamp": self._cooling_veto_end_time.timestamp(),
            "end_time": self._cooling_veto_end_time.isoformat(),
            "active_temp": self._cooling_veto_active_temp,
            "pre_opmode": self._pre_cooling_veto_opmode,
            "pre_temp": self._pre_cooling_veto_temp,
        }
        try:
            await self._cooling_veto_store.async_save(data)
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning("Failed to persist cooling quick veto state: %s", err)

    async def _async_clear_cooling_veto_store(self) -> None:
        """Remove persisted cooling quick veto state from Home Assistant storage."""
        try:
            await self._cooling_veto_store.async_remove()
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning(
                "Failed to remove persisted cooling quick veto state: %s", err
            )

    async def _async_restore_persisted_cooling_veto(self) -> None:
        """Restore or finalize a persisted cooling quick veto after Home Assistant restart."""
        try:
            data = await self._cooling_veto_store.async_load()
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning(
                "Failed to load persisted cooling quick veto state: %s", err
            )
            return

        if not data or not isinstance(data, dict):
            return

        end_ts_raw = data.get("end_timestamp")
        end_iso = data.get("end_time")
        end_ts: float | None = None
        if isinstance(end_ts_raw, (int, float)):
            end_ts = float(end_ts_raw)
        elif isinstance(end_iso, str):
            with contextlib.suppress(ValueError):
                end_ts = datetime.fromisoformat(end_iso).timestamp()

        if end_ts is None:
            await self._async_clear_cooling_veto_store()
            return

        pre_opmode = data.get("pre_opmode")
        pre_temp_raw = data.get("pre_temp")
        active_temp_raw = data.get("active_temp")

        self._pre_cooling_veto_opmode = (
            str(pre_opmode).lower() if isinstance(pre_opmode, str) else None
        )
        self._pre_cooling_veto_temp = (
            float(pre_temp_raw) if isinstance(pre_temp_raw, (int, float)) else None
        )
        self._cooling_veto_active_temp = (
            float(active_temp_raw)
            if isinstance(active_temp_raw, (int, float))
            else None
        )

        remaining = end_ts - datetime.now().timestamp()
        if remaining > 0:
            self._cooling_veto_end_time = datetime.fromtimestamp(end_ts)
            if self._cooling_veto_unsub is not None:
                self._cooling_veto_unsub()

            @callback
            def _async_on_cooling_veto_timeout(_now: datetime) -> None:
                self._cooling_veto_unsub = None
                self.hass.async_create_task(
                    self.async_cancel_cooling_quick_veto(restore=True)
                )

            self._cooling_veto_unsub = async_call_later(
                self.hass, remaining, _async_on_cooling_veto_timeout
            )
            _LOGGER.info(
                "Restored active cooling quick veto after restart (%.0fs remaining, active_temp=%s, pre_opmode=%s, pre_temp=%s)",
                remaining,
                self._cooling_veto_active_temp,
                self._pre_cooling_veto_opmode,
                self._pre_cooling_veto_temp,
            )
        else:
            self._cooling_veto_end_time = None
            self._cooling_veto_active_temp = None
            if self.is_ebus_operational:
                await self.async_cancel_cooling_quick_veto(restore=True)
            else:
                self._pending_cooling_veto_restore = True
                _LOGGER.info(
                    "Persisted cooling quick veto expired while offline; deferring bus restoration until eBUS is operational (pre_opmode=%s, pre_temp=%s)",
                    self._pre_cooling_veto_opmode,
                    self._pre_cooling_veto_temp,
                )

    async def _async_execute_pending_cooling_veto_restore(self) -> None:
        """Execute deferred restoration for a persisted cooling veto that expired offline."""
        if not self._pending_cooling_veto_restore:
            return
        if not self.is_ebus_operational:
            return
        _LOGGER.info(
            "Executing deferred restoration of expired cooling quick veto (pre_opmode=%s, pre_temp=%s)",
            self._pre_cooling_veto_opmode,
            self._pre_cooling_veto_temp,
        )
        await self.async_cancel_cooling_quick_veto(restore=True)

    # -------------------------------------------------------------------------
    # Passive Scan & Hardware/Software Version Detection
    # -------------------------------------------------------------------------

    def get_device_sw_version(self, device_key: str) -> str | None:
        """Return detected or default software version for device."""
        return self._device_versions.get(device_key, {}).get("sw")

    def get_device_hw_version(self, device_key: str) -> str | None:
        """Return detected or default hardware version for device."""
        return self._device_versions.get(device_key, {}).get("hw")

    def get_device_serial_number(self, device_key: str) -> str | None:
        """Return detected serial number for device if available."""
        return self._device_versions.get(device_key, {}).get("serial_number")

    @callback
    def _async_handle_scan_message(self, parts: list[str], raw_payload: Any) -> None:
        """Passively extract SW, HW, and serial numbers from ebusd scan.* MQTT messages."""
        circuit_name = parts[0]
        addr = circuit_name.lower().replace("scan.", "").strip()
        device_key = SCAN_ADDRESS_TO_DEVICE_KEY.get(addr)
        if not device_key:
            return

        payload_str = (
            raw_payload.decode("utf-8", errors="replace")
            if isinstance(raw_payload, (bytes, bytearray))
            else str(raw_payload)
        ).strip()
        if not payload_str:
            return

        parsed = parse_ebusd_payload(payload_str)
        val_str = str(parsed.get("value", "") or payload_str).strip()

        # Passive detection of active controller circuit from address 15 scan
        if addr == "15":
            payload_upper = (
                f"{val_str} {parsed.get('id', '')} {parsed.get('ID', '')}"
            ).upper()
            if (
                "CTLV3" in payload_upper
                and self._active_controller_circuit != CIRCUIT_CTLV3
            ):
                _LOGGER.info(
                    "Detected Vaillant sensoCOMFORT (CTLV3) on eBUS address 15; setting controller circuit to %s",
                    CIRCUIT_CTLV3,
                )
                self._active_controller_circuit = CIRCUIT_CTLV3
            elif (
                "CTLV2" in payload_upper
                and self._active_controller_circuit != CIRCUIT_CTLV2
            ):
                _LOGGER.info(
                    "Detected Vaillant sensoCOMFORT (CTLV2) on eBUS address 15; setting controller circuit to %s",
                    CIRCUIT_CTLV2,
                )
                self._active_controller_circuit = CIRCUIT_CTLV2
            elif (
                "BASV" in payload_upper
                and self._active_controller_circuit != CIRCUIT_BASV3
            ):
                _LOGGER.info(
                    "Detected Vaillant sensoCOMFORT (BASV3) on eBUS address 15; setting controller circuit to %s",
                    CIRCUIT_BASV3,
                )
                self._active_controller_circuit = CIRCUIT_BASV3
            elif (
                "BASS" in payload_upper
                and self._active_controller_circuit != CIRCUIT_BASS3
            ):
                _LOGGER.info(
                    "Detected Saunier Duval MiPro Sense (BASS3) on eBUS address 15; setting controller circuit to %s",
                    CIRCUIT_BASS3,
                )
                self._active_controller_circuit = CIRCUIT_BASS3

        # Passive detection of active outdoor unit circuit from address 08 scan
        if addr == "08":
            payload_upper = (
                f"{val_str} {parsed.get('id', '')} {parsed.get('ID', '')}"
            ).upper()
            if (
                ("HMU00" in payload_upper or "HMU" in payload_upper)
                and "HMUX" not in payload_upper
                and self._active_outdoor_circuit != CIRCUIT_HMU
            ):
                _LOGGER.info(
                    "Detected Vaillant aroTHERM HMU00 on eBUS address 08; setting outdoor circuit to %s",
                    CIRCUIT_HMU,
                )
                self._active_outdoor_circuit = CIRCUIT_HMU
                self._async_on_outdoor_circuit_changed(CIRCUIT_HMU)
            elif (
                "HMUX" in payload_upper
                and self._active_outdoor_circuit != CIRCUIT_HMUX0
            ):
                _LOGGER.info(
                    "Detected Saunier Duval / Vaillant HMUX0 on eBUS address 08; setting outdoor circuit to %s",
                    CIRCUIT_HMUX0,
                )
                self._active_outdoor_circuit = CIRCUIT_HMUX0
                self._async_on_outdoor_circuit_changed(CIRCUIT_HMUX0)

        detected_sw: str | None = None
        detected_hw: str | None = None
        detected_serial: str | None = None

        # 1. Check dictionary keys (from ebusd --mqttjson or parsed dict)
        for k, v in parsed.items():
            k_lower = k.lower()
            if k_lower == "sw" and v is not None:
                detected_sw = str(v).strip()
            elif k_lower == "hw" and v is not None:
                detected_hw = str(v).strip()

        # 2. Check semicolon-delimited string format (e.g. "Vaillant;HMUX0;0407;0504")
        if ";" in val_str:
            tokens = [t.strip() for t in val_str.split(";")]
            clean = [t for t in tokens if t]
            # Standard scan string: MF;ID;SW;HW
            if len(clean) >= 4 and clean[0].lower() in (
                "vaillant",
                "saunier duval",
                "saunierduval",
                "sd",
            ):
                detected_sw = clean[2]
                detected_hw = clean[3]
            elif len(clean) == 3 and not any(len(t) > 6 for t in clean):
                detected_sw = clean[1]
                detected_hw = clean[2]

        # 3. Check for serial number:
        # a) 7-part semicolon token string (e.g. "21;24;10;0020123456;1234;567890;N1")
        if ";" in val_str:
            id_tokens = [t.strip() for t in val_str.split(";") if t.strip()]
            if len(id_tokens) == 7:
                joined = "".join(id_tokens)
                if len(joined) == 28:
                    detected_serial = joined

        # b) JSON fields from Scan.<zz>/Id
        if not detected_serial:
            p_product = str(parsed.get("product") or "").strip()
            p_counter = str(parsed.get("counter") or "").strip()
            if p_product and p_counter:
                p_prefix = str(parsed.get("prefix") or "").strip()
                p_year = str(parsed.get("year") or "").strip()
                p_week = str(parsed.get("week") or "").strip()
                p_supplier = str(parsed.get("supplier") or "").strip()
                p_suffix = str(parsed.get("suffix") or "").strip()
                candidate = f"{p_prefix}{p_year}{p_week}{p_product}{p_supplier}{p_counter}{p_suffix}"
                if len(candidate) == 28:
                    detected_serial = candidate

        # c) Explicit serial / id fields
        if not detected_serial:
            for field in ("serial", "serial_number", "serialnumber"):
                if field in parsed:
                    candidate = str(parsed[field]).strip()
                    if len(candidate) >= 20:
                        detected_serial = candidate
                        break
            if not detected_serial and "id" in parsed:
                candidate = str(parsed["id"]).strip()
                if len(candidate) == 28:
                    detected_serial = candidate

        # d) Raw 28-char string under an Id topic (e.g. Scan.08/Id)
        if (
            not detected_serial
            and len(parts) >= 2
            and parts[1].lower() in ("id", "identification")
        ):
            clean_val = val_str.replace(";", "").replace(" ", "").strip()
            if len(clean_val) == 28:
                detected_serial = clean_val

        # Update cache and notify Device Registry if any property changed
        target_dict = self._device_versions.setdefault(device_key, {})
        updated = False
        if detected_sw and target_dict.get("sw") != detected_sw:
            target_dict["sw"] = detected_sw
            updated = True
        if detected_hw and target_dict.get("hw") != detected_hw:
            target_dict["hw"] = detected_hw
            updated = True
        if detected_serial and target_dict.get("serial_number") != detected_serial:
            target_dict["serial_number"] = detected_serial
            updated = True

        if updated:
            _LOGGER.info(
                "Passively detected hardware info for %s (%s): SW=%s, HW=%s, Serial=%s",
                device_key,
                addr,
                target_dict.get("sw"),
                target_dict.get("hw"),
                target_dict.get("serial_number"),
            )
            self._async_update_device_registry(device_key)

    @callback
    def _async_update_device_registry(self, device_key: str) -> None:
        """Update Home Assistant Device Registry with detected hardware/software versions and serial."""
        if not self.hass:
            return

        try:
            from homeassistant.helpers import device_registry as dr

            dev_reg = dr.async_get(self.hass)
            entry_id = self.entry.entry_id
            device_id_key = f"{entry_id}_{device_key}"
            if hasattr(dev_reg, "async_get_device_by_identifier"):
                device = dev_reg.async_get_device_by_identifier((DOMAIN, device_id_key))
            else:
                device = dev_reg.async_get_device(identifiers={(DOMAIN, device_id_key)})
            if not device:
                return

            ver_info = self._device_versions.get(device_key, {})
            kwargs: dict[str, Any] = {}
            if ver_info.get("sw"):
                kwargs["sw_version"] = ver_info["sw"]
            if ver_info.get("hw"):
                kwargs["hw_version"] = ver_info["hw"]
            if ver_info.get("serial_number"):
                kwargs["serial_number"] = ver_info["serial_number"]

            if kwargs:
                dev_reg.async_update_device(device.id, **kwargs)
                _LOGGER.debug(
                    "Updated Device Registry for %s with %s", device_id_key, kwargs
                )
        except Exception:
            _LOGGER.exception("Failed to update Device Registry for %s", device_key)


def _normalize_date_param(val: str | None, default: str) -> str:
    """Normalize input date to DD;MM;YY (2-digit year) for ebusd BASS3."""
    if not val:
        return default
    s = val.strip().replace("-", "/").replace(";", "/")
    parts = s.split("/")
    if len(parts) == 3:
        try:
            if len(parts[0]) == 4:  # YYYY/MM/DD
                year, month, day = int(parts[0]) % 100, int(parts[1]), int(parts[2])
            else:  # DD/MM/YYYY or DD/MM/YY
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2]) % 100
            return f"{day:02d};{month:02d};{year:02d}"
        except (ValueError, TypeError):
            pass
    return default


def _normalize_time_param(val: str | None, default: str) -> str:
    """Normalize input time to HH;MM;SS for ebusd BASS3."""
    if not val:
        return default
    s = val.strip().replace(":", ";")
    parts = s.split(";")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            sec = int(parts[2]) if len(parts) >= 3 else 0
            return f"{h:02d};{m:02d};{sec:02d}"
        except (ValueError, TypeError):
            pass
    return default
