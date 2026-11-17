"""MQTT Coordinator, Hydration Queue, DHW Boost Manager, and Thermodynamic Calculator."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    ELECTRIC_POWER_UNAVAILABLE_TIMEOUT_SECONDS,
    ESSENTIAL_HYDRATION_MESSAGES,
    EXTERNAL_SWEEP_CANARY_MESSAGES,
    EXTERNAL_SWEEP_CANARY_THRESHOLD,
    EXTERNAL_SWEEP_CLEAR_SECONDS,
    EXTERNAL_SWEEP_MIN_REPEAT_INTERVAL_SECONDS,
    EXTERNAL_SWEEP_MIN_REPEATS_PER_CANARY,
    EXTERNAL_SWEEP_SELF_GET_GRACE_SECONDS,
    FALLBACK_FAST_BASS3_MESSAGES,
    FALLBACK_SLOW_BASS3_MESSAGES,
    FALLBACK_SLOW_OUTDOOR_COMMON_MESSAGES,
    FALLBACK_SLOW_POLL_INTERVAL_SECONDS,
    FALLBACK_SLOW_VWZIO_MESSAGES,
    HEATING_VETO_SFMODE_FRESHNESS_SECONDS,
    HMU_FLOW_PRESSURE_MIN_SW,
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
    ISSUE_EBUSD_EXTERNAL_SWEEP,
    ISSUE_EBUSD_SLOW_POLLING_SEED,
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
    SLOW_POLLING_WARNING_THRESHOLD_SECONDS,
    TIMER_CIRCUIT_PREFIXES,
    UPSTREAM_DEFAULT_CSV_MESSAGES,
    VENTILATION_BOOST_DURATION_MINUTES,
    WEEKDAYS_LIST,
)
from .ebusd_tcp import (
    LOOPBACK_HOSTS,
    async_check_hassio_seed_mqtt_cfg,
    async_open_ebusd_tcp_connection,
    async_probe_ebusd_tcp,
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
_DEFERRED_RESTORE_END_ISO = datetime.fromtimestamp(0.0, tz=UTC).isoformat()

_HMU_SW902_MESSAGES: frozenset[str] = frozenset(
    {"FlowPressure", "CompressorHc", "CompressorHwc", "CompressorCool"}
)

_OUTDOOR_THERMO_TRIGGER_NAMES: tuple[str, ...] = (
    "rundataflowtemp",
    "rundatareturntemp",
    "status01",
    "rundataflowrate",
    "rundataelectricpowerconsumption",
    "powerstatus",
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
        self._fallback_slow_poll_unsub: CALLBACK_TYPE | None = None
        self._ebusd_tcp_poll_unsub: CALLBACK_TYPE | None = None
        self._tcp_autodiscover_task: asyncio.Task[None] | None = None
        self._seed_check_task: asyncio.Task[None] | None = None
        self._resolved_tcp_host: str | None = None
        self._resolved_tcp_port: int | None = None
        self._tcp_autodiscover_attempted: bool = False
        self._external_sweep_canaries: dict[tuple[str, str], list[float]] = {}
        self._self_requested_canaries: dict[tuple[str, str], float] = {}
        self._hassio_seed_mqtt_enabled: bool | None = None
        self._last_seed_check_mono: float = 0.0
        self._unloaded: bool = False
        self._hydration_task: asyncio.Task[None] | None = None
        self._pending_get_unsubs: dict[tuple[str, str], CALLBACK_TYPE] = {}

        # Thermodynamic calculation state
        self.last_active_cop: float | None = None

        # Smart Forced DHW Boost state
        self._saved_dhw_target_temp: float | None = None
        self._dhw_boost_goal_temp: float | None = None
        self._dhw_boost_active: bool = False
        self._dhw_boost_started_at: float = 0.0
        self._dhw_boost_started_ts: float | None = None
        self._dhw_boost_end_time: datetime | None = None
        self._dhw_boost_seen_load: bool = False
        self._dhw_boost_timeout_unsub: CALLBACK_TYPE | None = None
        self._dhw_boost_restore_unsub: CALLBACK_TYPE | None = None
        self._pending_dhw_boost_restore: bool = False
        self._dhw_boost_lock: asyncio.Lock = asyncio.Lock()
        self._dhw_boost_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_dhw_boost"
        )

        # Custom cooling season window state
        self._custom_cooling_start_date: str | None = None
        self._custom_cooling_end_date: str | None = None

        # Preselected / pending holiday mode parameters
        self._preselected_holiday_start_datetime: datetime | None = None
        self._preselected_holiday_end_datetime: datetime | None = None

        # Pre-veto operating mode memory (to restore 'off' when heating veto ends)
        self._pre_veto_opmode: str | None = None
        self._heating_veto_end_time: datetime | None = None
        self._heating_veto_unsub: CALLBACK_TYPE | None = None
        self._heating_veto_restore_unsub: CALLBACK_TYPE | None = None
        self._pending_heating_veto_restore: bool = False
        self._heating_veto_activating: bool = False
        self._heating_veto_started_mono: float = 0.0
        self._last_heating_veto_duration: float | None = None
        self._last_z1_sfmode_sync_time: float = -30.0
        self._heating_veto_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_heating_veto"
        )

        # Intensive ventilation boost countdown state (30-minute fixed timer)
        self._ventilation_end_time: datetime | None = None
        self._ventilation_ha_activated_mono: float = 0.0
        self._ventilation_store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_ventilation"
        )

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
        # Confirmed outdoor unit SW version from scan.08 or TCP info (excludes default placeholder)
        self._detected_outdoor_sw: str | None = None

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
        self._cleared_repair_issues: set[str] = set()
        self._missing_controller_registers: set[str] = set()
        self._missing_outdoor_silent_circuits: set[str] = set()
        self._last_err_responses: dict[
            tuple[str, str], tuple[float, dict[str, Any]]
        ] = {}

        # Silence watchdog and last telemetry timestamp
        self._last_telemetry_time: float | None = None
        self._last_ebus_operational: bool = False
        self._watchdog_unsub: CALLBACK_TYPE | None = None
        self._last_watchdog_elec_power: float | None = None
        self._last_watchdog_date: date = dt_util.now().date()
        self._last_power_consumption_receive_time: float | None = None

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
        if self._resolved_tcp_host is not None and not self._is_tcp_option_configured():
            return True
        return bool(
            self.entry.options.get(CONF_ENABLE_EBUSD_TCP, DEFAULT_ENABLE_EBUSD_TCP)
        )

    @property
    def ebusd_tcp_host(self) -> str:
        """Return configured or auto-discovered eBUSd TCP host."""
        configured = str(
            self.entry.options.get(CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST)
        ).strip()
        if self._resolved_tcp_host and configured in ("", *LOOPBACK_HOSTS):
            return self._resolved_tcp_host
        return configured

    @property
    def ebusd_tcp_port(self) -> int:
        """Return configured or auto-discovered eBUSd TCP port."""
        configured = int(
            self.entry.options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT)
        )
        if (
            self._resolved_tcp_port is not None
            and self._resolved_tcp_host is not None
            and str(
                self.entry.options.get(CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST)
            ).strip()
            in ("", *LOOPBACK_HOSTS)
        ):
            return self._resolved_tcp_port
        return configured

    def _is_tcp_option_configured(self) -> bool:
        """Return True if CONF_ENABLE_EBUSD_TCP was explicitly saved in entry options."""
        return CONF_ENABLE_EBUSD_TCP in self.entry.options

    def _get_device_registry_entry(self, dev_reg: Any, device_key: str) -> Any:
        """Look up a DeviceEntry for device_key scoped to this config entry."""
        entry_id = self.entry.entry_id
        identifier = (DOMAIN, f"{entry_id}_{device_key}")
        if hasattr(dev_reg, "async_get_device_by_identifier"):
            return dev_reg.async_get_device_by_identifier(identifier, entry_id)
        return dev_reg.async_get_device(identifiers={identifier})

    @property
    def outdoor_device_id(self) -> str | None:
        """Return the internal Home Assistant Device Registry ID for the outdoor unit."""
        if self._outdoor_device_id:
            return self._outdoor_device_id
        if not self.hass:
            return None
        from homeassistant.helpers import device_registry as dr

        dev_reg = dr.async_get(self.hass)
        device = self._get_device_registry_entry(dev_reg, DEVICE_OUTDOOR_UNIT)
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
    def pending_dhw_boost_restore(self) -> bool:
        """Return True if an expired forced DHW boost is awaiting bus restoration."""
        return self._pending_dhw_boost_restore

    @property
    def pending_heating_veto_restore(self) -> bool:
        """Return True if an expired heating quick veto from 'off' is awaiting restoration."""
        return self._pending_heating_veto_restore

    @property
    def pending_cooling_veto_restore(self) -> bool:
        """Return True if an expired cooling quick veto is awaiting bus restoration."""
        return self._pending_cooling_veto_restore

    async def async_discard_pending_heating_restore(self) -> None:
        """Cancel any deferred heating quick veto 'off' restore without writing Z1OpMode."""
        if self._heating_veto_restore_unsub is not None:
            self._heating_veto_restore_unsub()
            self._heating_veto_restore_unsub = None
        if not self._pending_heating_veto_restore:
            return
        self._pending_heating_veto_restore = False
        self._pre_veto_opmode = None
        self._last_heating_veto_duration = None
        self._heating_veto_started_mono = 0.0
        await self._async_clear_store(self._heating_veto_store, "heating quick veto")
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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

    @staticmethod
    def _utc_deadline(delta: timedelta) -> datetime:
        """Return a local timezone-aware deadline offset from UTC now by delta."""
        return dt_util.as_local(dt_util.utcnow() + delta)

    @staticmethod
    def _seconds_until(target_dt: datetime) -> float:
        """Return seconds remaining until target_dt using unambiguous UTC timestamps."""
        return target_dt.timestamp() - dt_util.utcnow().timestamp()

    @property
    def cooling_quick_veto_active(self) -> bool:
        """Return True if cooling quick veto is currently active."""
        if self._cooling_veto_end_time is None:
            return False
        return self._seconds_until(self._cooling_veto_end_time) > 0

    @property
    def cooling_quick_veto_remaining_minutes(self) -> int | None:
        """Return remaining minutes of active cooling quick veto."""
        if not self.cooling_quick_veto_active or self._cooling_veto_end_time is None:
            return None
        diff = self._seconds_until(self._cooling_veto_end_time)
        if diff <= 0:
            return None
        return max(1, math.ceil(diff / 60.0))

    @property
    def cooling_quick_veto_target_temp(self) -> float | None:
        """Return active target temperature of cooling quick veto."""
        return self._cooling_veto_active_temp

    @staticmethod
    def _format_remaining_duration(total_minutes: int) -> str:
        """Format remaining minutes with days, hours, and minutes (e.g. '2d 4h 15min', '2h 30min', '45 min')."""
        if total_minutes <= 0:
            return "0 min"
        days, rem = divmod(total_minutes, 1440)
        hours, mins = divmod(rem, 60)
        if days == 0 and hours == 0:
            return f"{mins} min"
        parts: list[str] = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if mins > 0:
            parts.append(f"{mins}min")
        return " ".join(parts)

    def _get_quick_veto_status(
        self,
    ) -> tuple[int | None, dict[str, Any]]:
        """Compute unified quick veto remaining minutes and attributes."""
        if self.cooling_quick_veto_active and self._cooling_veto_end_time is not None:
            diff = self._seconds_until(self._cooling_veto_end_time)
            rem = max(1, math.ceil(diff / 60.0)) if diff > 0 else 0
            return rem, {
                "is_active": True,
                "veto_type": "cooling",
                "end_time": self._cooling_veto_end_time.isoformat(),
                "target_temperature": self._cooling_veto_active_temp,
                "remaining_minutes": rem,
                "remaining_formatted": (
                    self._format_remaining_duration(rem) if rem > 0 else "0 min"
                ),
            }

        sf_mode = (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").lower()
        target_temp = self.get_float(CIRCUIT_BASS3, "Z1QuickVetoTemp", "value")

        if self._heating_veto_end_time is not None:
            diff = self._seconds_until(self._heating_veto_end_time)
            if diff > 0:
                rem = max(1, math.ceil(diff / 60.0))
                return rem, {
                    "is_active": True,
                    "veto_type": "heating",
                    "end_time": self._heating_veto_end_time.isoformat(),
                    "target_temperature": target_temp,
                    "remaining_minutes": rem,
                    "remaining_formatted": self._format_remaining_duration(rem),
                }

        if sf_mode == "veto":
            if self._heating_veto_end_time is not None:
                return 0, {
                    "is_active": True,
                    "veto_type": "heating",
                    "end_time": self._heating_veto_end_time.isoformat(),
                    "target_temperature": target_temp,
                    "remaining_minutes": 0,
                    "remaining_formatted": "0 min",
                }
            return None, {
                "is_active": True,
                "veto_type": "heating",
                "end_time": None,
                "target_temperature": target_temp,
                "remaining_minutes": None,
                "remaining_formatted": None,
            }

        return 0, {
            "is_active": False,
            "veto_type": None,
            "end_time": None,
            "target_temperature": None,
            "remaining_minutes": 0,
            "remaining_formatted": None,
        }

    def get_quick_veto_remaining_minutes(self) -> int | None:
        """Return remaining minutes for active heating or cooling quick veto, 0 if inactive, or None if unknown."""
        remaining, _ = self._get_quick_veto_status()
        return remaining

    def get_quick_veto_remaining_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes for the unified quick veto countdown sensor."""
        _, attrs = self._get_quick_veto_status()
        return attrs

    def _get_ventilation_status(self) -> tuple[int | None, dict[str, Any]]:
        """Compute intensive ventilation boost remaining minutes and attributes."""
        z1_status = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        sf_mode = (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").lower()
        is_active = z1_status == "ventilation" or sf_mode == "ventilation"
        if not is_active:
            return 0, {
                "is_active": False,
                "duration_minutes": VENTILATION_BOOST_DURATION_MINUTES,
                "end_time": None,
                "remaining_minutes": 0,
                "remaining_formatted": None,
            }

        if self._ventilation_end_time is None:
            return None, {
                "is_active": True,
                "duration_minutes": VENTILATION_BOOST_DURATION_MINUTES,
                "end_time": None,
                "remaining_minutes": None,
                "remaining_formatted": None,
            }

        diff = self._seconds_until(self._ventilation_end_time)
        rem = max(1, math.ceil(diff / 60.0)) if diff > 0 else 0
        return rem, {
            "is_active": True,
            "duration_minutes": VENTILATION_BOOST_DURATION_MINUTES,
            "end_time": self._ventilation_end_time.isoformat(),
            "remaining_minutes": rem,
            "remaining_formatted": (
                self._format_remaining_duration(rem) if rem > 0 else "0 min"
            ),
        }

    def get_ventilation_remaining_minutes(self) -> int | None:
        """Return remaining minutes for active ventilation boost, 0 if inactive, or None if unknown."""
        remaining, _ = self._get_ventilation_status()
        return remaining

    def get_ventilation_remaining_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes for the intensive ventilation countdown sensor."""
        _, attrs = self._get_ventilation_status()
        return attrs

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
        """Subscribe to ebusd MQTT topics, load persisted state, and schedule initial hydration."""
        await self._async_restore_persisted_cooling_veto()
        await self._async_restore_persisted_heating_veto()
        await self._async_restore_persisted_ventilation()
        await self._async_restore_persisted_dhw_boost()

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

        # Optional Supervisor check for seed_mqtt_cfg: true on HA OS / Supervised
        self._seed_check_task = self._schedule_background_task(
            self._async_check_seed_mqtt_cfg(),
            name=f"{DOMAIN}_seed_check_{self.entry.entry_id}",
        )

    @callback
    def _async_sync_ebus_operational_listeners(self) -> None:
        """Notify availability-gated entities whenever is_ebus_operational transitions."""
        curr_op = self.is_ebus_operational
        if curr_op != self._last_ebus_operational:
            self._last_ebus_operational = curr_op
            self._async_notify_message_listeners(CIRCUIT_GLOBAL, "running")
            self._async_notify_message_listeners(CIRCUIT_GLOBAL, "signal")

    @callback
    def _async_check_watchdog(self, _now: datetime) -> None:
        """Periodic watchdog checking for communication silence and stale electric power."""
        if self._last_telemetry_time is not None:
            elapsed = time.monotonic() - self._last_telemetry_time
            if elapsed > EBUSD_TRAFFIC_TIMEOUT_SECONDS:
                self._last_ebus_operational = False
                self._async_notify_message_listeners(CIRCUIT_GLOBAL, "running")
                self._async_notify_message_listeners(CIRCUIT_GLOBAL, "signal")
        self._async_sync_ebus_operational_listeners()

        # Re-evaluate stale electric power / Live COP every 60s so expired power metrics update cleanly
        curr_elec = self.get_instantaneous_electric_power()
        if curr_elec != self._last_watchdog_elec_power:
            self._last_watchdog_elec_power = curr_elec
            for circuit in dict.fromkeys(
                (self._active_outdoor_circuit, CIRCUIT_HMUX0, CIRCUIT_HMU)
            ):
                self._async_notify_message_listeners(
                    circuit, "RunDataElectricPowerConsumption"
                )
                self._async_notify_message_listeners(circuit, "PowerStatus")
            self._async_recalculate_thermodynamics()

        # Refresh unified Quick Veto and Ventilation countdown sensors every 60s while active
        if (
            self._heating_veto_end_time is not None
            or self._cooling_veto_end_time is not None
        ):
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

        if self._ventilation_end_time is not None:
            self._async_notify_message_listeners(
                CALC_CIRCUIT, "VentilationBoostRemaining"
            )
            if (
                self._seconds_until(self._ventilation_end_time) <= 0
                and self.is_ebus_operational
                and (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
                == "ventilation"
            ):
                self.hass.async_create_task(
                    self.async_request_get(CIRCUIT_BASS3, "Z1Status")
                )

        if (
            self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower() == "holidayaway":
            self._async_notify_message_listeners(CALC_CIRCUIT, "HolidayRemaining")

        today_date = dt_util.now().date()
        if today_date != self._last_watchdog_date:
            self._last_watchdog_date = today_date
            self._async_notify_message_listeners(CIRCUIT_BASS3, "CoolingEndDate")
            self._async_notify_message_listeners(CIRCUIT_BASS3, "HolidayEndDate")
            self._async_notify_message_listeners(CALC_CIRCUIT, "HolidayRemaining")
            for prefix in (
                "Z1Timer",
                "HwcTimer",
                "CoolingTimer",
                "CirculationTimer",
                "SilentTimer",
            ):
                self._async_notify_message_listeners(CIRCUIT_BASS3, f"{prefix}_Slots")

        # Check for slow power telemetry / seed_mqtt_cfg issue:
        # If RunDataElectricPowerConsumption has been seen at least once, but its age exceeds threshold
        # while general bus traffic is actively arriving (telemetry within last 60s and operational bus)
        if (
            self._last_power_consumption_receive_time is not None
            and self.is_ebus_operational
        ):
            power_age = time.monotonic() - self._last_power_consumption_receive_time
            slow_thresh = (
                SLOW_POLLING_WARNING_THRESHOLD_SECONDS
                if self.has_migo_link
                else max(
                    SLOW_POLLING_WARNING_THRESHOLD_SECONDS,
                    float(self.fallback_poll_interval) * 1.5,
                )
            )
            if power_age >= slow_thresh:
                bus_active = (
                    self._last_telemetry_time is not None
                    and (time.monotonic() - self._last_telemetry_time) <= 60.0
                )
                if bus_active:
                    minutes_str = f"{round(power_age / 60.0, 1)}"
                    self._async_set_repair_issue(
                        ISSUE_EBUSD_SLOW_POLLING_SEED,
                        active=True,
                        placeholders={"interval": minutes_str},
                    )

        # Prune aged external-sweep canary observations and auto-clear if sweeps stopped
        if (
            ISSUE_EBUSD_EXTERNAL_SWEEP in self._active_repair_issues
            or self._external_sweep_canaries
        ):
            now_mono = time.monotonic()
            if (
                self._hassio_seed_mqtt_enabled is True
                and (now_mono - self._last_seed_check_mono) >= 300.0
                and self.hass
                and not self._unloaded
                and (self._seed_check_task is None or self._seed_check_task.done())
            ):
                self._seed_check_task = self._schedule_background_task(
                    self._async_check_seed_mqtt_cfg(),
                    name=f"{DOMAIN}_seed_recheck_{self.entry.entry_id}",
                )
            self._async_evaluate_external_sweep_issue(now_mono)

    @callback
    def async_update_options(self) -> None:
        """Reconfigure runtime timers when OptionsFlow is updated."""
        if self._fallback_poll_unsub is not None:
            self._fallback_poll_unsub()
            self._fallback_poll_unsub = None

        if self._fallback_slow_poll_unsub is not None:
            self._fallback_slow_poll_unsub()
            self._fallback_slow_poll_unsub = None

        if not self.has_migo_link:
            interval = max(60, self.fallback_poll_interval)
            _LOGGER.info(
                "MiGo Link (f1) disabled; enabling fast fallback MQTT /get polling every %ds and hourly slow sync (%ds)",
                interval,
                FALLBACK_SLOW_POLL_INTERVAL_SECONDS,
            )
            self._fallback_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_run_fallback_poll,
                timedelta(seconds=interval),
            )
            self._fallback_slow_poll_unsub = async_track_time_interval(
                self.hass,
                self._async_run_fallback_slow_poll,
                timedelta(seconds=FALLBACK_SLOW_POLL_INTERVAL_SECONDS),
            )

        self._resolved_tcp_host_reset_if_overridden()
        self._async_setup_ebusd_tcp_polling()

    def _resolved_tcp_host_reset_if_overridden(self) -> None:
        """Clear runtime resolved host cache if user saved an explicit host or disabled TCP."""
        configured = str(
            self.entry.options.get(CONF_EBUSD_TCP_HOST, DEFAULT_EBUSD_TCP_HOST)
        ).strip()
        if (
            self._is_tcp_option_configured()
            and not bool(self.entry.options.get(CONF_ENABLE_EBUSD_TCP))
        ) or (
            configured not in ("", *LOOPBACK_HOSTS)
            and configured != self._resolved_tcp_host
        ):
            self._resolved_tcp_host = None
            self._resolved_tcp_port = None

    async def async_unload(self) -> None:
        """Unsubscribe from MQTT and cancel all background tasks and timers."""
        self._unloaded = True
        for unsub in self._mqtt_unsubs:
            unsub()
        self._mqtt_unsubs.clear()

        if self._hydration_timer_unsub is not None:
            self._hydration_timer_unsub()
            self._hydration_timer_unsub = None

        if self._fallback_poll_unsub is not None:
            self._fallback_poll_unsub()
            self._fallback_poll_unsub = None

        if self._fallback_slow_poll_unsub is not None:
            self._fallback_slow_poll_unsub()
            self._fallback_slow_poll_unsub = None

        if self._ebusd_tcp_poll_unsub is not None:
            self._ebusd_tcp_poll_unsub()
            self._ebusd_tcp_poll_unsub = None

        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None

        if self._dhw_boost_restore_unsub is not None:
            self._dhw_boost_restore_unsub()
            self._dhw_boost_restore_unsub = None

        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
            self._heating_veto_unsub = None

        if self._heating_veto_restore_unsub is not None:
            self._heating_veto_restore_unsub()
            self._heating_veto_restore_unsub = None

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

        if (
            self._tcp_autodiscover_task is not None
            and not self._tcp_autodiscover_task.done()
        ):
            self._tcp_autodiscover_task.cancel()
            self._tcp_autodiscover_task = None

        if self._seed_check_task is not None and not self._seed_check_task.done():
            self._seed_check_task.cancel()
            self._seed_check_task = None

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
            self._async_sync_ebus_operational_listeners()
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

        is_err_payload = raw_payload.strip().startswith(
            "ERR:"
        ) or self._is_ebusd_err_msg(parsed)
        if is_err_payload:
            # Record transient error for explicit read_parameter diagnostics and run CSV
            # Repair checks, but NEVER poison coordinator._state, timestamps, hydration,
            # or active overrides (e.g. ventilation countdown / quick veto tracking).
            now_mono = time.monotonic()
            self._last_err_responses[(circuit_key, msg_lower)] = (now_mono, parsed)
            canonical_alias = MESSAGE_ALIASES.get(msg_lower)
            if canonical_alias and canonical_alias != message_name:
                self._last_err_responses[(circuit_key, canonical_alias.lower())] = (
                    now_mono,
                    parsed,
                )
            self._async_check_csv_compatibility_on_message(
                circuit_key, msg_lower, parsed, raw_payload
            )
            for listener_msg in dict.fromkeys(
                [msg_lower] + ([canonical_alias.lower()] if canonical_alias else [])
            ):
                for cb in list(self._listeners.get((circuit_key, listener_msg), [])):
                    cb()
            return

        self._last_err_responses.pop((circuit_key, msg_lower), None)

        # If ebusd published a subfield topic <prefix>/<circuit>/<message>/<field>
        if len(parts) == 3:
            subfield = parts[2]
            sub_val = parsed.get("value", next(iter(parsed.values())))
            existing = dict(self._state.get((circuit_key, message_name), {}))
            existing[subfield] = sub_val
            parsed = existing

        prev_z1_sf_mode: str | None = None
        prev_z1_status: str | None = None
        prev_veto_dur: float | None = None
        if circuit_key in CONTROLLER_CIRCUITS:
            if msg_lower == "z1sfmode":
                prev_z1_sf_mode = self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value")
            elif msg_lower == "z1status":
                prev_z1_status = self.get_str(CIRCUIT_BASS3, "Z1Status", "value")
            elif msg_lower == "z1quickvetoduration":
                prev_veto_dur = self.get_float(
                    CIRCUIT_BASS3, "Z1QuickVetoDuration", "value"
                )

        now = time.time()
        self._canonical_names[(circuit_key, msg_lower)] = message_name
        self._state[(circuit_key, message_name)] = parsed
        self._message_timestamps[(circuit_key, msg_lower)] = now

        # Notify subscribers for this (circuit, message)
        self._async_notify_message_listeners(circuit_key, message_name)

        # Track non-retained external sweep canary messages (never emitted passively or by us)
        if getattr(msg, "retain", False) is not True:
            self._async_record_external_sweep_canary(circuit_key, msg_lower)

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

        # Monitor high-priority electrical power update interval to detect slow polling / seed_mqtt_cfg
        if (
            circuit_key in OUTDOOR_CIRCUITS
            and msg_lower == "rundataelectricpowerconsumption"
        ):
            now_mono = time.monotonic()
            if self._last_power_consumption_receive_time is not None:
                interval = now_mono - self._last_power_consumption_receive_time
                slow_thresh = (
                    SLOW_POLLING_WARNING_THRESHOLD_SECONDS
                    if self.has_migo_link
                    else max(
                        SLOW_POLLING_WARNING_THRESHOLD_SECONDS,
                        float(self.fallback_poll_interval) * 1.5,
                    )
                )
                clear_thresh = (
                    60.0
                    if self.has_migo_link
                    else max(60.0, float(self.fallback_poll_interval) * 1.1)
                )
                if interval <= clear_thresh:
                    self._async_set_repair_issue(
                        ISSUE_EBUSD_SLOW_POLLING_SEED, active=False
                    )
                elif interval >= slow_thresh and self.is_ebus_operational:
                    minutes_str = f"{round(interval / 60.0, 1)}"
                    self._async_set_repair_issue(
                        ISSUE_EBUSD_SLOW_POLLING_SEED,
                        active=True,
                        placeholders={"interval": minutes_str},
                    )
            self._last_power_consumption_receive_time = now_mono

        # Check DHW boost restoration conditions when bass3/basv3 HwcSFMode, HwcStorageTemp, or HwcStatus updates
        if circuit_key in CONTROLLER_CIRCUITS and msg_lower in (
            "hwcsfmode",
            "hwcstoragetemp",
            "hwcstatus",
        ):
            self._async_check_dhw_boost_restoration()

        # Check Quick Veto restoration conditions when controller Z1SFMode, Z1Status, or Z1QuickVetoDuration updates
        if circuit_key in CONTROLLER_CIRCUITS and msg_lower in (
            "z1sfmode",
            "z1status",
            "z1quickvetoduration",
        ):
            self._async_check_quick_veto_restoration(trigger_msg=msg_lower)
            if (
                msg_lower == "z1sfmode"
                and not self._heating_veto_activating
                and prev_z1_sf_mode is not None
                and prev_z1_sf_mode.lower() != "veto"
                and self._heating_veto_end_time is None
            ):
                new_sf_mode = (
                    self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
                ).lower()
                if new_sf_mode == "veto":
                    self._async_start_external_heating_veto_tracking()
            if msg_lower == "z1quickvetoduration":
                new_dur = self.get_float(CIRCUIT_BASS3, "Z1QuickVetoDuration", "value")
                sf_mode_now = (
                    self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
                ).lower()
                z1_status_now = (
                    self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
                ).lower()
                baseline_dur = (
                    prev_veto_dur
                    if prev_veto_dur is not None
                    else self._last_heating_veto_duration
                )
                if (
                    sf_mode_now == "veto"
                    and z1_status_now in ("", "veto")
                    and self._heating_veto_end_time is not None
                    and self._seconds_until(self._heating_veto_end_time) > 0
                    and new_dur is not None
                    and new_dur >= 0.5
                    # Controller r9 polls read back the static 3.0h default even during an
                    # app-adjusted veto (e.g. 0.5h), so never let a passive 3.0h readback
                    # clobber a different active duration.
                    and abs(new_dur - DEFAULT_QUICK_VETO_DURATION) >= 0.05
                    and baseline_dur is not None
                    and abs(new_dur - baseline_dur) >= 0.05
                    and (
                        self._last_heating_veto_duration is None
                        or abs(new_dur - self._last_heating_veto_duration) >= 0.05
                    )
                ):
                    self.hass.async_create_task(
                        self.async_refresh_heating_veto_duration(new_dur)
                    )
            if msg_lower == "z1status":
                prev_status_low = (prev_z1_status or "").lower()
                z1_status_val = (
                    self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
                ).lower()
                ha_just_activated_vent = (
                    self._ventilation_ha_activated_mono > 0.0
                    and (time.monotonic() - self._ventilation_ha_activated_mono) < 15.0
                )
                if z1_status_val == "ventilation":
                    self._ventilation_ha_activated_mono = 0.0
                    if self._ventilation_end_time is None:
                        self._start_ventilation_countdown()
                    if (
                        prev_status_low
                        and prev_status_low != "ventilation"
                        and self.is_ebus_operational
                    ):
                        self._schedule_confirmation_get(
                            CIRCUIT_BASS3,
                            "Z1ActualRoomTempDesired",
                            key_circuit=CIRCUIT_BASS3.lower(),
                        )
                elif self._ventilation_end_time is not None or (
                    prev_status_low == "ventilation"
                ):
                    if (
                        ha_just_activated_vent
                        and self._ventilation_end_time is not None
                    ):
                        for ctrl_circuit in CONTROLLER_CIRCUITS:
                            self._apply_optimistic_update(
                                ctrl_circuit, "Z1Status", "ventilation"
                            )
                            self._async_notify_message_listeners(
                                ctrl_circuit, "Z1Status"
                            )
                        if self.is_ebus_operational:
                            self._schedule_confirmation_get(
                                CIRCUIT_BASS3,
                                "Z1Status",
                                key_circuit=CIRCUIT_BASS3.lower(),
                            )
                    else:
                        self._clear_ventilation_countdown()
                        if (
                            prev_status_low == "ventilation"
                            and self.is_ebus_operational
                        ):
                            self._schedule_confirmation_get(
                                CIRCUIT_BASS3,
                                "Z1ActualRoomTempDesired",
                                key_circuit=CIRCUIT_BASS3.lower(),
                            )
                if z1_status_val == "holidayaway" and self.cooling_quick_veto_active:

                    async def _cancel_cooling_veto_task() -> None:
                        try:
                            await self.async_cancel_cooling_quick_veto(restore=True)
                        except HomeAssistantError as err:
                            _LOGGER.debug(
                                "Holiday away cooling veto cancel failed: %s", err
                            )

                    self.hass.async_create_task(_cancel_cooling_veto_task())
                sf_mode_now = (
                    self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
                ).lower()
                now_mono = time.monotonic()
                if (
                    sf_mode_now == "veto"
                    and z1_status_val not in ("", "veto")
                    and self.is_ebus_operational
                ):
                    prev_status_low = (prev_z1_status or "").lower()
                    just_activated = (
                        self._heating_veto_started_mono > 0.0
                        and (now_mono - self._heating_veto_started_mono) < 30.0
                    )
                    if prev_status_low == "veto" or (
                        not just_activated
                        and (now_mono - self._last_z1_sfmode_sync_time) >= 30.0
                    ):
                        self._last_z1_sfmode_sync_time = now_mono
                        self.hass.async_create_task(
                            self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
                        )
                elif (
                    z1_status_val == "veto"
                    and sf_mode_now != "veto"
                    and self.is_ebus_operational
                    and (now_mono - self._last_z1_sfmode_sync_time) >= 30.0
                ):
                    self._last_z1_sfmode_sync_time = now_mono
                    self.hass.async_create_task(
                        self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
                    )

        # If any persisted transient override expired while HA/eBUS was offline, restore once operational
        if self.is_ebus_operational and (
            circuit_key in CONTROLLER_CIRCUITS or circuit_key in OUTDOOR_CIRCUITS
        ):
            self._async_schedule_pending_restores()

        # Verify eBUSd CSV compatibility and manage Home Assistant Repair issues
        self._async_check_csv_compatibility_on_message(
            circuit_key, msg_lower, parsed, raw_payload
        )

        # Wake up availability-gated entities (e.g. subscriptions=[]) on offline -> online transitions
        if circuit_key == CIRCUIT_GLOBAL and msg_lower in ("running", "signal"):
            self._last_ebus_operational = self.is_ebus_operational
        else:
            self._async_sync_ebus_operational_listeners()

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
            self._cleared_repair_issues.discard(issue_id)
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
                learn_more_url="https://github.com/R91g/arotherm-genia-ebusd/blob/main/docs/installation.md#2-deploy-the-ebusd-csv-configuration",
            )
        else:
            if (
                issue_id in self._active_repair_issues
                or issue_id not in self._cleared_repair_issues
            ):
                self._active_repair_issues.discard(issue_id)
                self._cleared_repair_issues.add(issue_id)
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _schedule_background_task(
        self, coro: Coroutine[Any, Any, None], name: str
    ) -> asyncio.Task[None] | None:
        """Schedule a background task on hass and close unused coroutines in offline mocks."""
        if not self.hass or self._unloaded:
            coro.close()
            return None
        task = self.hass.async_create_background_task(coro, name=name)
        if isinstance(task, asyncio.Task):
            return task
        coro.close()
        return None

    async def _async_check_seed_mqtt_cfg(self) -> None:
        """Optionally check Supervisor add-on options for seed_mqtt_cfg: true."""
        if self._unloaded:
            return
        self._last_seed_check_mono = time.monotonic()
        self._hassio_seed_mqtt_enabled = await async_check_hassio_seed_mqtt_cfg(
            self.hass
        )
        if not self._unloaded:
            self._async_evaluate_external_sweep_issue(time.monotonic())

    @callback
    def _async_record_external_sweep_canary(
        self, circuit_key: str, msg_lower: str
    ) -> None:
        """Record an incoming non-retained canary message if not requested by us."""
        if msg_lower not in EXTERNAL_SWEEP_CANARY_MESSAGES:
            return

        now_mono = time.monotonic()
        self_get_ts = self._self_requested_canaries.get((circuit_key, msg_lower))
        if (
            self_get_ts is not None
            and (now_mono - self_get_ts) <= EXTERNAL_SWEEP_SELF_GET_GRACE_SECONDS
        ):
            return

        key = (circuit_key, msg_lower)
        timestamps = self._external_sweep_canaries.setdefault(key, [])
        if (
            not timestamps
            or (now_mono - timestamps[-1]) >= EXTERNAL_SWEEP_MIN_REPEAT_INTERVAL_SECONDS
        ):
            timestamps.append(now_mono)
        self._async_evaluate_external_sweep_issue(now_mono)

    @callback
    def _async_evaluate_external_sweep_issue(self, now_mono: float) -> None:
        """Activate or clear the external sweep repair based on seed_mqtt_cfg and repeated canaries."""
        for key in list(self._external_sweep_canaries):
            fresh = [
                ts
                for ts in self._external_sweep_canaries[key]
                if (now_mono - ts) <= EXTERNAL_SWEEP_CLEAR_SECONDS
            ]
            if fresh:
                self._external_sweep_canaries[key] = fresh
            else:
                self._external_sweep_canaries.pop(key, None)

        repeated_canaries = sorted(
            key
            for key, timestamps in self._external_sweep_canaries.items()
            if len(timestamps) >= EXTERNAL_SWEEP_MIN_REPEATS_PER_CANARY
        )
        has_canary_sweep = len(repeated_canaries) >= EXTERNAL_SWEEP_CANARY_THRESHOLD
        if self._hassio_seed_mqtt_enabled is True:
            canary_list = ", ".join(
                f"{circ}/{msg}" for circ, msg in sorted(self._external_sweep_canaries)
            )
            registers_desc = canary_list if canary_list else "seed_mqtt_cfg: true"
            self._async_set_repair_issue(
                ISSUE_EBUSD_EXTERNAL_SWEEP,
                active=True,
                placeholders={
                    "source": "seed_mqtt_cfg (Home Assistant eBUSd Add-on)",
                    "registers": registers_desc,
                },
            )
            return

        if has_canary_sweep:
            sample = [f"{circ}/{msg}" for circ, msg in repeated_canaries[:5]]
            suffix = (
                f" (+{len(repeated_canaries) - 5})"
                if len(repeated_canaries) > 5
                else ""
            )
            self._async_set_repair_issue(
                ISSUE_EBUSD_EXTERNAL_SWEEP,
                active=True,
                placeholders={
                    "source": "MQTT /get / filter-seen sweep",
                    "registers": ", ".join(sample) + suffix,
                },
            )
            return

        if (
            ISSUE_EBUSD_EXTERNAL_SWEEP in self._active_repair_issues
            and self._hassio_seed_mqtt_enabled is not True
        ):
            self._async_set_repair_issue(ISSUE_EBUSD_EXTERNAL_SWEEP, active=False)

    @staticmethod
    def _is_ebusd_err_msg(msg: dict[str, Any] | str | None) -> bool:
        """Return True if a cached eBUSd message represents an ERR: failure."""
        if isinstance(msg, str):
            return msg.strip().startswith("ERR:")
        if isinstance(msg, dict):
            return any(
                isinstance(val, str) and val.strip().startswith("ERR:")
                for val in msg.values()
            )
        return False

    def _has_hmux0_csv_incompatibility(self) -> bool:
        """Return True if any cached 08.hmux0 register indicates an outdated CSV."""
        sc_msg = self.get_message(CIRCUIT_HMUX0, "StateCompressor") or {}
        has_legacy_sc = (
            isinstance(sc_msg, dict)
            and "comp_speed" in sc_msg
            and "flow_temp" not in sc_msg
        )
        flow_msg = self.get_message(CIRCUIT_HMUX0, "RunDataFlowRate") or {}
        has_legacy_flow = (
            isinstance(flow_msg, dict)
            and "value" in flow_msg
            and "flow_rate" not in flow_msg
        )
        is_silent_err = (
            CIRCUIT_HMUX0 in self._missing_outdoor_silent_circuits
            or self._is_ebusd_err_msg(
                self.get_message(CIRCUIT_HMUX0, "CompressorSilentOperationLevel")
            )
        )
        return has_legacy_sc or has_legacy_flow or is_silent_err

    def _has_hmu_csv_incompatibility(self, circuit_key: str) -> bool:
        """Return True if any cached 08.hmu/hmu00 register indicates an outdated CSV."""
        status_msg = self.get_message(circuit_key, "Status01") or {}
        has_legacy_status = (
            isinstance(status_msg, dict)
            and "temp_1" in status_msg
            and "flow_temp" not in status_msg
        )
        is_silent_err = (
            circuit_key in self._missing_outdoor_silent_circuits
            or self._is_ebusd_err_msg(
                self.get_message(circuit_key, "CompressorSilentOperationLevel")
            )
        )
        return has_legacy_status or is_silent_err

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
        if circuit_key == CIRCUIT_HMUX0:
            if msg_lower == "statecompressor":
                if (
                    isinstance(parsed, dict)
                    and "comp_speed" in parsed
                    and "flow_temp" not in parsed
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)
                elif (
                    isinstance(parsed, dict)
                    and "flow_temp" in parsed
                    and not self._has_hmux0_csv_incompatibility()
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)

            elif msg_lower == "rundataflowrate":
                if (
                    isinstance(parsed, dict)
                    and "flow_rate" in parsed
                    and not self._has_hmux0_csv_incompatibility()
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)
                elif (
                    isinstance(parsed, dict)
                    and "value" in parsed
                    and "flow_rate" not in parsed
                    and raw_payload.strip().startswith("{")
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)

            elif msg_lower == "rundatanominalflowrate":
                if not self._has_hmux0_csv_incompatibility():
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=False)

            elif msg_lower == "compressorsilentoperationlevel":
                if raw_payload.strip().startswith("ERR:"):
                    self._missing_outdoor_silent_circuits.add(circuit_key)
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMUX0_CSV, active=True)
                else:
                    self._missing_outdoor_silent_circuits.discard(circuit_key)
                    if not self._has_hmux0_csv_incompatibility():
                        self._async_set_repair_issue(
                            ISSUE_OUTDATED_HMUX0_CSV, active=False
                        )

        # 2a. Detect legacy/upstream vs custom 08.hmu.csv / 08.hmu.HW5103.csv
        if circuit_key in (CIRCUIT_HMU, CIRCUIT_HMU00):
            if msg_lower == "status01":
                if (
                    isinstance(parsed, dict)
                    and "temp_1" in parsed
                    and "flow_temp" not in parsed
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)
                elif (
                    isinstance(parsed, dict)
                    and "flow_temp" in parsed
                    and not self._has_hmu_csv_incompatibility(circuit_key)
                ):
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=False)

            elif msg_lower in UPSTREAM_DEFAULT_CSV_MESSAGES:
                self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)

            elif msg_lower == "compressorsilentoperationlevel":
                if raw_payload.strip().startswith("ERR:"):
                    self._missing_outdoor_silent_circuits.add(circuit_key)
                    self._async_set_repair_issue(ISSUE_OUTDATED_HMU_CSV, active=True)
                else:
                    self._missing_outdoor_silent_circuits.discard(circuit_key)
                    if not self._has_hmu_csv_incompatibility(circuit_key):
                        self._async_set_repair_issue(
                            ISSUE_OUTDATED_HMU_CSV, active=False
                        )

        # 2b. Detect legacy vs modern controller CSVs (Z1HolidayTemp/Z1DayTemp vs HolidayTemp/Z1CoolingManualTemp/SilentTimer/VentilationBoost)
        if circuit_key in CONTROLLER_CIRCUITS:
            is_err = raw_payload.strip().startswith("ERR:")
            probe_registers = (
                "hwclegionelladay",
                "silenttimer_slots",
                "z1coolingmanualtemp",
                "ventilationboost",
            )
            if not is_err and msg_lower in ("z1holidaytemp", "z1daytemp"):
                self._async_set_repair_issue(ISSUE_OUTDATED_CONTROLLER_CSV, active=True)
            elif is_err and msg_lower in probe_registers:
                self._missing_controller_registers.add(msg_lower)
                self._async_set_repair_issue(ISSUE_OUTDATED_CONTROLLER_CSV, active=True)
            elif not is_err:
                if msg_lower in probe_registers:
                    self._missing_controller_registers.discard(msg_lower)
                if msg_lower in (
                    "holidaytemp",
                    "hwclegionelladay",
                    "z1coolingmanualtemp",
                    "silenttimer_slots",
                    "ventilationboost",
                ) or (
                    msg_lower == "holidaystartdate"
                    and isinstance(parsed, dict)
                    and "year" in parsed
                ):
                    for c in CONTROLLER_CIRCUITS:
                        self._state.pop((c, "Z1HolidayTemp"), None)
                        self._state.pop((c, "z1holidaytemp"), None)
                        self._state.pop((c, "Z1DayTemp"), None)
                        self._state.pop((c, "z1daytemp"), None)
                        self._canonical_names.pop((c, "z1holidaytemp"), None)
                        self._canonical_names.pop((c, "z1daytemp"), None)
                    if not self._missing_controller_registers:
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
        has_controller = any(
            c in CONTROLLER_CIRCUITS and not self._is_ebusd_err_msg(v)
            for (c, _), v in self._state.items()
        )
        has_vwzio = any(
            c == CIRCUIT_VWZIO and not self._is_ebusd_err_msg(v)
            for (c, _), v in self._state.items()
        )
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
            (c in OUTDOOR_CIRCUITS or c in CONTROLLER_CIRCUITS or c == CIRCUIT_VWZIO)
            and not self._is_ebusd_err_msg(v)
            for (c, _), v in self._state.items()
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
        """Return True if we have received valid non-error data for (circuit, message)."""
        c_key = circuit.lower()
        m_lower = message.lower()
        canonical = self._canonical_names.get((c_key, m_lower), message)
        for key in ((c_key, canonical), (c_key, m_lower)):
            if key in self._state and not self._is_ebusd_err_msg(self._state[key]):
                return True
        return False

    def get_recent_error(
        self, circuit: str, message: str, *, since_mono: float = 0.0
    ) -> dict[str, Any] | None:
        """Return recent ERR: payload recorded for (circuit, message) since since_mono."""
        c_key = circuit.lower()
        m_lower = message.lower()
        entry = self._last_err_responses.get((c_key, m_lower))
        if entry is None:
            resolved = self.resolve_circuit(circuit).lower()
            if resolved != c_key:
                entry = self._last_err_responses.get((resolved, m_lower))
        if entry is not None and entry[0] >= since_mono:
            return entry[1]
        return None

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

    @staticmethod
    def _sanitize_field_value(val: Any, default: Any) -> Any:
        """Never propagate raw eBUSd 'ERR: ...' strings to callers."""
        if isinstance(val, str) and val.strip().startswith("ERR:"):
            return default
        return val

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
            return self._sanitize_field_value(msg_data[field], default)

        # 2. Fallback to 'value' or 'flow_rate' (standard single-field names in 15.bass3.csv & 08.hmux0.csv)
        for single_alias in ("value", "flow_rate"):
            if single_alias in msg_data and msg_data[single_alias] is not None:
                return self._sanitize_field_value(msg_data[single_alias], default)

        # 3. Specific multi-field alias mappings between specification and CSVs
        if field in ("temp1", "flow_temp", "temp"):
            for alias in ("temp", "flow_temp", "temp1"):
                if alias in msg_data and msg_data[alias] is not None:
                    return self._sanitize_field_value(msg_data[alias], default)
        elif field in ("return_temp", "temp_1"):
            for alias in ("temp_1", "return_temp"):
                if alias in msg_data and msg_data[alias] is not None:
                    return self._sanitize_field_value(msg_data[alias], default)
        elif field in ("cooling_temp", "temp") and "cooling_temp" in msg_data:
            return self._sanitize_field_value(msg_data["cooling_temp"], default)
        elif field in ("pumpstate", "status"):
            for alias in ("pumpstate", "status", "value"):
                if alias in msg_data and msg_data[alias] is not None:
                    return self._sanitize_field_value(msg_data[alias], default)

        # 4. If the message has only 1 field in the JSON dict, return its value
        if len(msg_data) == 1:
            only_val = next(iter(msg_data.values()))
            if only_val is not None:
                return self._sanitize_field_value(only_val, default)

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
        If RunDataElectricPowerConsumption is stale (> 180s) and PowerStatus is fresher,
        dynamically falls back to PowerStatus. If all available sources exceed 600s (or 2x fallback
        poll interval) without updates, returns None so power and Live COP show unavailable.
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

        unavailable_timeout = ELECTRIC_POWER_UNAVAILABLE_TIMEOUT_SECONDS
        if not self.has_migo_link:
            unavailable_timeout = max(
                unavailable_timeout, float(self.fallback_poll_interval) * 2.0
            )

        if run_val is None and ps_val is None:
            return None

        if run_val is None:
            if ps_age is not None and ps_age > unavailable_timeout:
                return None
            return ps_val

        if ps_val is None:
            if run_age is not None and run_age > unavailable_timeout:
                return None
            return run_val

        # Both are present: check staleness
        is_run_stale = (
            run_age is not None and run_age > ELECTRIC_POWER_STALE_TIMEOUT_SECONDS
        )
        if not is_run_stale:
            return run_val

        # RunData is stale (> 180s). Prefer PowerStatus if fresher; invalidate if all stale > unavailable_timeout.
        ps_is_newer = (ps_ts is not None and run_ts is not None and ps_ts > run_ts) or (
            ps_age is not None and ps_age <= ELECTRIC_POWER_STALE_TIMEOUT_SECONDS
        )
        candidate_val = ps_val if ps_is_newer else run_val
        candidate_age = ps_age if ps_is_newer else run_age
        if candidate_age is not None and candidate_age > unavailable_timeout:
            return None
        return candidate_val

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
        msg_lower = message.lower()
        if msg_lower in EXTERNAL_SWEEP_CANARY_MESSAGES:
            now_mono = time.monotonic()
            self._self_requested_canaries[(circuit.lower(), msg_lower)] = now_mono
            self._self_requested_canaries[(target_circuit.lower(), msg_lower)] = (
                now_mono
            )
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

        await mqtt.async_publish(self.hass, topic, payload, qos=0, retain=False)

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

        # Schedule confirmation /get ONLY for active read commands (r / r9 whitelist).
        # For all passive 'u' commands (setpoints, modes, timers, dates), NEVER send /get,
        # perfectly preserving the optimistic UI update without stale cache rebounds.
        check_circuit = CIRCUIT_BASS3.lower() if is_controller else circuit.lower()
        key = (check_circuit, message)
        if key in ACTIVE_READ_CONFIRMATION_MESSAGES:
            self._schedule_confirmation_get(circuit, message, key_circuit=check_circuit)

    @callback
    def _schedule_confirmation_get(
        self, circuit: str, message: str, *, key_circuit: str | None = None
    ) -> None:
        """Schedule a delayed /get confirmation read for a register."""
        key = ((key_circuit or circuit).lower(), message)
        if key in self._pending_get_unsubs:
            self._pending_get_unsubs.pop(key)()

        @callback
        def _confirm_get(_now: datetime) -> None:
            self._pending_get_unsubs.pop(key, None)
            self.hass.async_create_task(self.async_request_get(circuit, message))

        self._pending_get_unsubs[key] = async_call_later(
            self.hass, SET_CONFIRMATION_DELAY_SECONDS, _confirm_get
        )

    @callback
    def _optimistically_clear_z1_status(
        self, expected_status: str, *, force_off: bool = False
    ) -> None:
        """Clear stale Z1Status ('veto'/'holidayaway') optimistically and schedule /get."""
        z1_status_now = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        if z1_status_now != expected_status.lower():
            return
        op_now = (self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "").lower()
        optimistic_status = "off" if (force_off or op_now == "off") else "auto"
        for ctrl_circuit in CONTROLLER_CIRCUITS:
            self._apply_optimistic_update(ctrl_circuit, "Z1Status", optimistic_status)
            self._async_notify_message_listeners(ctrl_circuit, "Z1Status")
        self._schedule_confirmation_get(
            CIRCUIT_BASS3, "Z1Status", key_circuit=CIRCUIT_BASS3.lower()
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

    def _is_hmu_flow_pressure_supported(self) -> bool:
        """Return True unless outdoor SW is confirmed below 0902 ([id_sw>=902])."""
        if self._detected_outdoor_sw is None:
            return True
        sw_str = self._detected_outdoor_sw.strip()
        if not sw_str.isdigit():
            return True
        return int(sw_str) >= HMU_FLOW_PRESSURE_MIN_SW

    def _record_detected_outdoor_sw(self, sw_ver: str | None) -> None:
        """Record confirmed outdoor SW version and drop SW>=902 registers if SW < 902."""
        if not sw_ver or not sw_ver.strip():
            return
        self._detected_outdoor_sw = sw_ver.strip()
        if not self._is_hmu_flow_pressure_supported():
            self._pending_hydration = [
                (c, m)
                for (c, m) in self._pending_hydration
                if not (c in OUTDOOR_CIRCUITS and m in _HMU_SW902_MESSAGES)
            ]

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
                and not (
                    c in OUTDOOR_CIRCUITS
                    and m in _HMU_SW902_MESSAGES
                    and not self._is_hmu_flow_pressure_supported()
                )
            ]
            # 2. Find missing HMU specific messages
            missing_hmu = [
                (c, m)
                for (c, m) in HMU_HW5103_HYDRATION_MESSAGES
                if not self.has_message(c, m)
                and (c, m) not in self._pending_hydration
                and (
                    m not in _HMU_SW902_MESSAGES
                    or self._is_hmu_flow_pressure_supported()
                )
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
                if (
                    message in _HMU_SW902_MESSAGES
                    and not self._is_hmu_flow_pressure_supported()
                ):
                    continue
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

        for item in self._collect_active_timer_slot_messages(only_if_missing=True):
            if item not in missing:
                missing.append(item)

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

    def _collect_active_timer_slot_messages(
        self, *, only_if_missing: bool
    ) -> list[tuple[str, str]]:
        """Build daily weekly-timer slot /get targets from known <prefix>_Slots counts."""
        slot_targets: list[tuple[str, str]] = []
        for prefix in TIMER_CIRCUIT_PREFIXES.values():
            slots_data = self.get_message(CIRCUIT_BASS3, f"{prefix}_Slots")
            if not isinstance(slots_data, dict):
                continue
            for day in WEEKDAYS_LIST:
                short_key = DAY_SHORT_KEYS[day]
                raw_count = slots_data.get(short_key)
                if raw_count is None:
                    continue
                try:
                    slot_count = int(float(raw_count))
                except (TypeError, ValueError):
                    continue
                for slot_idx, suffix in ((1, ""), (2, "_Slot2"), (3, "_Slot3")):
                    if slot_count < slot_idx:
                        continue
                    msg_name = f"{prefix}_{day}{suffix}"
                    if not only_if_missing or not self.has_message(
                        CIRCUIT_BASS3, msg_name
                    ):
                        slot_targets.append((CIRCUIT_BASS3, msg_name))
        return slot_targets

    async def _async_run_hydration_queue(self, messages: list[tuple[str, str]]) -> None:
        """Publish /get sequentially with 0.8s spacing to avoid eBUS collisions."""
        self._pending_hydration = list(messages)
        timer_slots_expanded = False
        try:
            while self._pending_hydration or not timer_slots_expanded:
                if not self._pending_hydration:
                    timer_slots_expanded = True
                    extra_timers = self._collect_active_timer_slot_messages(
                        only_if_missing=True
                    )
                    if extra_timers:
                        self._pending_hydration.extend(extra_timers)
                    continue
                circuit, message = self._pending_hydration.pop(0)
                if self.has_message(circuit, message):
                    continue
                if (
                    self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00)
                    and circuit in OUTDOOR_CIRCUITS
                    and message in HMUX0_EXCLUSIVE_MESSAGES
                ):
                    continue
                if (
                    circuit in OUTDOOR_CIRCUITS
                    and message in _HMU_SW902_MESSAGES
                    and not self._is_hmu_flow_pressure_supported()
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
        """Periodic fast fallback poll for dynamic telemetry when has_migo_link is False."""
        if self.has_migo_link:
            return
        if self._hydration_task is not None and not self._hydration_task.done():
            return
        # Poll dynamic operational states, live thermodynamics & energy counters with gentle spacing
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
                (CIRCUIT_HMU, "RunDataFlowTempDesired"),
                (CIRCUIT_HMU, "RunDataHeatOutput"),
                (CIRCUIT_HMU, "RunDataCondensationTemp"),
                (CIRCUIT_HMU, "RunDataCondensateTemp"),
                (CIRCUIT_HMU, "RunDataEvaporationTemp"),
                (CIRCUIT_HMU, "RunDataSuperheat"),
                (CIRCUIT_HMU, "YieldHc"),
                (CIRCUIT_HMU, "YieldHwc"),
                (CIRCUIT_HMU, "YieldCooling"),
                (CIRCUIT_HMU, "CopHc"),
                (CIRCUIT_HMU, "CopHwc"),
                (CIRCUIT_HMU, "CopCooling"),
                (CIRCUIT_HMU, "TotalEnergyUsage"),
                (CIRCUIT_HMU, "FlowPressure"),
                (CIRCUIT_HMU, "EnergyIntegral"),
                (CIRCUIT_VWZIO, "PowerStatus"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
            ]
            if not self._is_hmu_flow_pressure_supported():
                fallback_energy_messages = [
                    item
                    for item in fallback_energy_messages
                    if item[1] != "FlowPressure"
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
                (CIRCUIT_HMUX0, "RunDataFlowTempDesired"),
                (CIRCUIT_HMUX0, "RunDataHeatOutput"),
                (CIRCUIT_HMUX0, "RunDataEnergyIntegral"),
                (CIRCUIT_HMUX0, "RunDataCondensationTemp"),
                (CIRCUIT_HMUX0, "RunDataCondensateTemp"),
                (CIRCUIT_HMUX0, "RunDataEvaporationTemp"),
                (CIRCUIT_HMUX0, "RunDataSuperheat"),
                (CIRCUIT_HMUX0, "PrEnergyElectricHc"),
                (CIRCUIT_HMUX0, "PrEnergyElectricHwc"),
                (CIRCUIT_HMUX0, "PrEnergyElectricCool"),
                (CIRCUIT_HMUX0, "PrEnergyThermalHc"),
                (CIRCUIT_HMUX0, "PrEnergyThermalHwc"),
                (CIRCUIT_HMUX0, "PrEnergyThermalCool"),
                (CIRCUIT_HMUX0, "PrEnergyEnvYieldHc"),
                (CIRCUIT_HMUX0, "PrEnergyEnvYieldHwc"),
                (CIRCUIT_HMUX0, "PrEnergyEnvYieldCool"),
                (CIRCUIT_VWZIO, "PowerStatus"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
                (CIRCUIT_VWZIO, "PrEnergyElectricHwc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHc"),
                (CIRCUIT_VWZIO, "PrEnergyThermalHwc"),
            ]
        core_messages = list(
            dict.fromkeys([*FALLBACK_FAST_BASS3_MESSAGES, *fallback_energy_messages])
        )
        self._hydration_task = self.hass.async_create_background_task(
            self._async_force_poll_queue(core_messages),
            name=f"{self.entry.domain}_fallback_poll",
        )

    async def _async_run_fallback_slow_poll(self, _now: datetime) -> None:
        """Hourly MiGo-style fallback poll for config, stats, and weekly timers when has_migo_link is False."""
        if self.has_migo_link:
            return
        if self._hydration_task is not None and not self._hydration_task.done():
            return
        outdoor_circuit = (
            CIRCUIT_HMU
            if self._active_outdoor_circuit in (CIRCUIT_HMU, CIRCUIT_HMU00)
            else CIRCUIT_HMUX0
        )
        slow_outdoor: list[tuple[str, str]] = [
            (outdoor_circuit, msg)
            for msg in FALLBACK_SLOW_OUTDOOR_COMMON_MESSAGES
            if not (outdoor_circuit == CIRCUIT_HMU and msg in HMUX0_EXCLUSIVE_MESSAGES)
        ]
        if outdoor_circuit == CIRCUIT_HMU:
            slow_outdoor.extend(
                [
                    (CIRCUIT_HMU, "CompressorHours"),
                    (CIRCUIT_HMU, "CompressorStarts"),
                ]
            )
            if self._is_hmu_flow_pressure_supported():
                slow_outdoor.extend(
                    [
                        (CIRCUIT_HMU, "CompressorHc"),
                        (CIRCUIT_HMU, "CompressorHwc"),
                        (CIRCUIT_HMU, "CompressorCool"),
                    ]
                )
        slow_messages = list(
            dict.fromkeys(
                [
                    *FALLBACK_SLOW_BASS3_MESSAGES,
                    *slow_outdoor,
                    *FALLBACK_SLOW_VWZIO_MESSAGES,
                    *self._collect_active_timer_slot_messages(only_if_missing=False),
                ]
            )
        )
        self._hydration_task = self.hass.async_create_background_task(
            self._async_force_poll_queue(slow_messages, expand_timer_slots=True),
            name=f"{self.entry.domain}_fallback_slow_poll",
        )

    async def _async_force_poll_queue(
        self,
        messages: list[tuple[str, str]],
        *,
        expand_timer_slots: bool = False,
    ) -> None:
        """Sequentially request /get on messages with gentle spacing."""
        queue = list(messages)
        step_delay = (
            HYDRATION_STEP_DELAY_SECONDS * 1.25
            if HYDRATION_STEP_DELAY_SECONDS > 0
            else 0.0
        )
        seen = set(queue)
        slots_checked = False
        while queue or (expand_timer_slots and not slots_checked):
            if not queue:
                slots_checked = True
                for item in self._collect_active_timer_slot_messages(
                    only_if_missing=False
                ):
                    if item not in seen:
                        seen.add(item)
                        queue.append(item)
                continue
            circuit, message = queue.pop(0)
            await self.async_request_get(circuit, message)
            await asyncio.sleep(step_delay)

    # -------------------------------------------------------------------------
    # Advanced eBUSd TCP Daemon Polling (Diagnostics & Info)
    # -------------------------------------------------------------------------

    @callback
    def _persist_discovered_tcp_options(
        self, host: str, port: int, *, enable_tcp: bool = False
    ) -> None:
        """Persist auto-discovered eBUSd TCP host/port into ConfigEntry options."""
        if self._unloaded or not self.hass or not self.entry:
            return
        options = dict(self.entry.options)
        changed = False
        if enable_tcp and not options.get(CONF_ENABLE_EBUSD_TCP):
            options[CONF_ENABLE_EBUSD_TCP] = True
            changed = True
        if str(options.get(CONF_EBUSD_TCP_HOST, "")).strip() != host:
            options[CONF_EBUSD_TCP_HOST] = host
            changed = True
        if int(options.get(CONF_EBUSD_TCP_PORT, DEFAULT_EBUSD_TCP_PORT)) != int(port):
            options[CONF_EBUSD_TCP_PORT] = int(port)
            changed = True
        if not changed:
            return

        cfg_entries = getattr(self.hass, "config_entries", None)
        update_entry = getattr(cfg_entries, "async_update_entry", None)
        if not callable(update_entry):
            return
        try:
            res = update_entry(self.entry, options=options)
            if asyncio.iscoroutine(res):
                res.close()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed persisting auto-discovered TCP options: %s", err)

    async def _async_autodiscover_ebusd_tcp(self) -> None:
        """Probe once at startup to auto-enable and autocomplete eBUSd TCP options."""
        if self._unloaded or self._is_tcp_option_configured():
            return

        detected = await async_probe_ebusd_tcp(
            self.hass,
            configured_host=self.ebusd_tcp_host,
            port=self.ebusd_tcp_port,
        )
        if detected is None or self._unloaded:
            return

        host, port = detected
        self._resolved_tcp_host = host
        self._resolved_tcp_port = port
        self._persist_discovered_tcp_options(host, port, enable_tcp=True)
        if self._ebusd_tcp_poll_unsub is None:
            self._async_setup_ebusd_tcp_polling()

    def _async_setup_ebusd_tcp_polling(self) -> None:
        """Set up or cancel periodic eBUSd TCP info polling based on options."""
        if self._ebusd_tcp_poll_unsub is not None:
            self._ebusd_tcp_poll_unsub()
            self._ebusd_tcp_poll_unsub = None

        if not self.is_ebusd_tcp_enabled:
            if (
                not self._is_tcp_option_configured()
                and not self._tcp_autodiscover_attempted
                and self.hass
                and not self._unloaded
            ):
                self._tcp_autodiscover_attempted = True
                self._tcp_autodiscover_task = self._schedule_background_task(
                    self._async_autodiscover_ebusd_tcp(),
                    name=f"{DOMAIN}_tcp_autodiscover_{self.entry.entry_id}",
                )
            return

        _LOGGER.info(
            "Advanced eBUSd TCP connection enabled; polling info from %s:%s every 60s",
            self.ebusd_tcp_host,
            self.ebusd_tcp_port,
        )

        if self.hass:
            self._schedule_background_task(
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
        """Open TCP connection to eBUSd socket, prioritizing HA add-on over loopback."""
        (
            reader,
            writer,
            resolved_host,
            resolved_port,
        ) = await async_open_ebusd_tcp_connection(
            self.hass, host, port, timeout=timeout
        )
        if (resolved_host != host or resolved_port != port) and host in (
            "",
            *LOOPBACK_HOSTS,
        ):
            self._resolved_tcp_host = resolved_host
            self._resolved_tcp_port = resolved_port
            self._persist_discovered_tcp_options(resolved_host, resolved_port)
        return reader, writer

    async def _async_read_tcp_block(
        self, reader: asyncio.StreamReader, timeout: float = 3.0
    ) -> list[str]:
        """Read lines from an eBUSd TCP command until terminating blank line or EOF."""
        lines: list[str] = []
        while True:
            try:
                line_bytes = await asyncio.wait_for(reader.readline(), timeout=timeout)
            except (TimeoutError, StopAsyncIteration, OSError):
                break
            if not line_bytes:
                break
            line = line_bytes.decode("ascii", errors="replace").strip()
            if not line:
                if lines:
                    break
                continue
            lines.append(line)
        return lines

    async def _async_verify_csvs_via_tcp(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        loaded_csv_devices: list[dict[str, str]],
    ) -> None:
        """Verify loaded CSV definitions using eBUSd TCP `find` (zero bus traffic)."""
        has_ctrl_csv = any("15." in d["csv"] for d in loaded_csv_devices)
        has_outdoor_csv = any("08." in d["csv"] for d in loaded_csv_devices)
        if not has_ctrl_csv and not has_outdoor_csv:
            return

        async def _tcp_find(msg_name: str) -> str | None:
            writer.write(f"find {msg_name}\n".encode("ascii"))
            await writer.drain()
            resp = await self._async_read_tcp_block(reader, timeout=2.0)
            if not resp:
                return None
            return resp[0]

        if has_ctrl_csv:
            ctrl_probe_names = (
                ("HwcLegionellaDay", "hwclegionelladay"),
                ("SilentTimer_Slots", "silenttimer_slots"),
                ("VentilationBoost", "ventilationboost"),
            )
            ctrl_results = [
                (key, await _tcp_find(name)) for name, key in ctrl_probe_names
            ]
            has_ctrl_err = False
            for key, resp in ctrl_results:
                if resp is not None and resp.startswith("ERR:"):
                    self._missing_controller_registers.add(key)
                    has_ctrl_err = True
                elif resp is not None:
                    self._missing_controller_registers.discard(key)
            if has_ctrl_err:
                self._async_set_repair_issue(ISSUE_OUTDATED_CONTROLLER_CSV, active=True)
            elif all(resp is not None for _key, resp in ctrl_results):
                for c in CONTROLLER_CIRCUITS:
                    self._state.pop((c, "Z1HolidayTemp"), None)
                    self._state.pop((c, "z1holidaytemp"), None)
                    self._state.pop((c, "Z1DayTemp"), None)
                    self._state.pop((c, "z1daytemp"), None)
                    self._canonical_names.pop((c, "z1holidaytemp"), None)
                    self._canonical_names.pop((c, "z1daytemp"), None)
                if not self._missing_controller_registers:
                    self._async_set_repair_issue(
                        ISSUE_OUTDATED_CONTROLLER_CSV, active=False
                    )

        if has_outdoor_csv:
            is_hmux0_csv = any(
                "hmux0" in d["csv"].lower() or d["id"].lower() == "hmux0"
                for d in loaded_csv_devices
            )
            outdoor_issue = (
                ISSUE_OUTDATED_HMUX0_CSV if is_hmux0_csv else ISSUE_OUTDATED_HMU_CSV
            )
            out_probes = [
                await _tcp_find("CompressorSilentOperationLevel"),
                await _tcp_find("RunDataElectricPowerConsumption"),
            ]
            silent_resp = out_probes[0]
            active_out_circuits = (
                (CIRCUIT_HMUX0,) if is_hmux0_csv else (CIRCUIT_HMU, CIRCUIT_HMU00)
            )
            if silent_resp is not None and silent_resp.startswith("ERR:"):
                self._missing_outdoor_silent_circuits.update(active_out_circuits)
            elif silent_resp is not None:
                for c_out in active_out_circuits:
                    self._missing_outdoor_silent_circuits.discard(c_out)
            if any(r is not None and r.startswith("ERR:") for r in out_probes):
                self._async_set_repair_issue(outdoor_issue, active=True)
            elif all(r is not None and not r.startswith("ERR:") for r in out_probes):
                if is_hmux0_csv:
                    sc_msg = self.get_message(CIRCUIT_HMUX0, "StateCompressor") or {}
                    flow_msg = self.get_message(CIRCUIT_HMUX0, "RunDataFlowRate") or {}
                    has_legacy = (
                        isinstance(sc_msg, dict)
                        and "comp_speed" in sc_msg
                        and "flow_temp" not in sc_msg
                    ) or (
                        isinstance(flow_msg, dict)
                        and "value" in flow_msg
                        and "flow_rate" not in flow_msg
                    )
                else:
                    status_msg = (
                        self.get_message(CIRCUIT_HMU, "Status01")
                        or self.get_message(CIRCUIT_HMU00, "Status01")
                        or {}
                    )
                    has_legacy = (
                        isinstance(status_msg, dict)
                        and "temp_1" in status_msg
                        and "flow_temp" not in status_msg
                    )
                if not has_legacy:
                    self._async_set_repair_issue(outdoor_issue, active=False)

    async def _async_fetch_ebusd_tcp_info(self) -> None:
        """Fetch daemon health, metrics, and loaded CSV status directly from eBUSd TCP socket."""
        if not self.is_ebusd_tcp_enabled:
            return

        host = self.ebusd_tcp_host
        port = self.ebusd_tcp_port
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        lines: list[str] = []
        loaded_csv_devices: list[dict[str, str]] = []
        missing_csv_devices: list[dict[str, str]] = []
        total_scanned = 0

        try:
            reader, writer = await self._async_open_tcp_connection(
                host, port, timeout=3.0
            )
            writer.write(b"info\n")
            await writer.drain()
            lines = await self._async_read_tcp_block(reader, timeout=3.0)

            if not lines:
                return

            for line in lines:
                if ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()

                if key == "version":
                    self._state[(CIRCUIT_GLOBAL, "version")] = {"value": val}
                    self._async_notify_message_listeners(CIRCUIT_GLOBAL, "version")
                elif key == "scan":
                    self._state[(CIRCUIT_GLOBAL, "scan")] = {"value": val}
                    self._async_notify_message_listeners(CIRCUIT_GLOBAL, "scan")
                elif key == "symbol rate":
                    with contextlib.suppress(ValueError):
                        self._state[(CIRCUIT_GLOBAL, "symbol_rate")] = {
                            "value": int(val)
                        }
                        self._async_notify_message_listeners(
                            CIRCUIT_GLOBAL, "symbol_rate"
                        )
                elif key == "reconnects":
                    with contextlib.suppress(ValueError):
                        self._state[(CIRCUIT_GLOBAL, "reconnects")] = {
                            "value": int(val)
                        }
                        self._async_notify_message_listeners(
                            CIRCUIT_GLOBAL, "reconnects"
                        )
                elif key == "masters":
                    with contextlib.suppress(ValueError):
                        self._state[(CIRCUIT_GLOBAL, "masters")] = {"value": int(val)}
                        self._async_notify_message_listeners(CIRCUIT_GLOBAL, "masters")
                elif key in ("max arbitration micros", "arbitration micros"):
                    with contextlib.suppress(ValueError):
                        micros = int(val)
                        ms = round(micros / 1000.0)
                        self._state[(CIRCUIT_GLOBAL, "arbitration_latency")] = {
                            "value": ms
                        }
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
                    if addr.lower() == "08" and sw_ver:
                        self._record_detected_outdoor_sw(sw_ver)
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

            await self._async_verify_csvs_via_tcp(reader, writer, loaded_csv_devices)

            with contextlib.suppress(TimeoutError, OSError):
                writer.write(b"quit\n")
                await writer.drain()
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

    def _clear_calculated(self, key: str) -> None:
        """Remove a calculated metric from state and notify listeners if it existed."""
        state_key = (CALC_CIRCUIT, key)
        if state_key in self._state:
            self._state.pop(state_key, None)
            self._async_notify_message_listeners(CALC_CIRCUIT, key)

    @callback
    def _async_recalculate_thermodynamics(self) -> None:
        """Recalculate Delta T, Thermal Power, Live COP, Mode Totals (Wh), and Historical COP/EER."""
        # 1. Primary Flow and Return Temperatures -> Delta T (K)
        flow_temp = self.get_float(CIRCUIT_HMUX0, "RunDataFlowTemp", "value")
        if flow_temp is None:
            flow_temp = self.get_float(CIRCUIT_HMUX0, "Status01", "flow_temp")

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
        self._last_watchdog_elec_power = elec_power
        live_cop, is_active = calculate_live_cop(
            thermal_power, elec_power, hmu_status, frozenset(ACTIVE_COMPRESSOR_STATUSES)
        )
        if live_cop is not None:
            if is_active:
                self.last_active_cop = live_cop
            self._set_calculated(CALC_LIVE_COP, live_cop)
        else:
            self._clear_calculated(CALC_LIVE_COP)

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
        async with self._dhw_boost_lock:
            await self._async_trigger_dhw_boost_locked(override_boost_temp)

    async def _async_trigger_dhw_boost_locked(
        self, override_boost_temp: float | None = None
    ) -> None:
        """Execute DHW boost activation while holding self._dhw_boost_lock."""
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
            # or awaiting a deferred setpoint restore so re-triggering preserves the baseline.
            if (
                not self._dhw_boost_active and not self._pending_dhw_boost_restore
            ) or self._saved_dhw_target_temp is None:
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

            if self._dhw_boost_restore_unsub is not None:
                self._dhw_boost_restore_unsub()
                self._dhw_boost_restore_unsub = None
            self._pending_dhw_boost_restore = False

            now_utc = dt_util.utcnow()
            self._dhw_boost_active = True
            self._dhw_boost_goal_temp = (
                override_boost_temp
                if override_boost_temp is not None
                else self._saved_dhw_target_temp
            )
            self._dhw_boost_started_at = time.monotonic()
            self._dhw_boost_started_ts = now_utc.timestamp()
            self._dhw_boost_end_time = dt_util.as_local(
                now_utc + timedelta(seconds=DHW_BOOST_MAX_TIMEOUT_SECONDS)
            )
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
            await self._async_save_dhw_boost_state()
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

    def _apply_dhw_boost_tracking_update(
        self, new_target: float | None = None
    ) -> tuple[bool, bool]:
        """Update or cancel in-memory DHW boost tracking; return (should_save, should_clear)."""
        if self._dhw_boost_active:
            if new_target is not None:
                self._saved_dhw_target_temp = new_target
                self._dhw_boost_goal_temp = new_target
                return True, False
            self._dhw_boost_active = False
            self._saved_dhw_target_temp = None
            self._dhw_boost_goal_temp = None
            self._dhw_boost_started_ts = None
            self._dhw_boost_end_time = None
            self._dhw_boost_seen_load = False
            if self._dhw_boost_timeout_unsub is not None:
                self._dhw_boost_timeout_unsub()
                self._dhw_boost_timeout_unsub = None
            return False, True
        if self._pending_dhw_boost_restore:
            self._pending_dhw_boost_restore = False
            self._saved_dhw_target_temp = None
            self._dhw_boost_goal_temp = None
            if self._dhw_boost_restore_unsub is not None:
                self._dhw_boost_restore_unsub()
                self._dhw_boost_restore_unsub = None
            return False, True
        return False, False

    def cancel_dhw_boost_tracking(self, new_target: float | None = None) -> None:
        """Cancel or update boost tracking if user manually adjusts temperature."""
        should_save, should_clear = self._apply_dhw_boost_tracking_update(new_target)
        if should_save:
            self.hass.async_create_task(self._async_save_dhw_boost_state())
        elif should_clear:
            self.hass.async_create_task(
                self._async_clear_store(self._dhw_boost_store, "DHW boost")
            )

    async def async_cancel_dhw_boost_tracking(
        self, new_target: float | None = None
    ) -> None:
        """Async variant to cancel or update boost tracking and persist store safely."""
        should_save, should_clear = self._apply_dhw_boost_tracking_update(new_target)
        if should_save:
            await self._async_save_dhw_boost_state()
        elif should_clear:
            await self._async_clear_store(self._dhw_boost_store, "DHW boost")

    async def async_cancel_dhw_boost(self) -> None:
        """Cancel DHW One-Time Boost (HwcSFMode=auto) and restore original setpoint if elevated."""
        async with self._dhw_boost_lock:
            await self.async_write_parameter(CIRCUIT_BASS3, "HwcSFMode", "auto")
            if (
                self._dhw_boost_active or self._pending_dhw_boost_restore
            ) and self._saved_dhw_target_temp is not None:
                await self._async_restore_dhw_target_temp_unlocked(
                    "user cancelled boost"
                )

    @callback
    def _defer_dhw_boost_restore_offline(self) -> None:
        """Mark DHW boost setpoint restoration as deferred offline and persist it."""
        self._dhw_boost_active = False
        self._dhw_boost_goal_temp = None
        self._dhw_boost_started_ts = None
        self._dhw_boost_end_time = None
        self._dhw_boost_seen_load = False
        self._pending_dhw_boost_restore = True
        if self._saved_dhw_target_temp is not None:
            saved_temp = self._saved_dhw_target_temp
            self.hass.async_create_task(
                self._async_save_store(
                    self._dhw_boost_store,
                    {
                        "saved_target_temp": saved_temp,
                        "end_timestamp": 0.0,
                        "end_time": _DEFERRED_RESTORE_END_ISO,
                    },
                    "DHW boost",
                )
            )

    @callback
    def _async_on_dhw_boost_timeout(self, _now: datetime) -> None:
        """Handle 60-minute safety timeout for forced DHW boost."""
        self._dhw_boost_timeout_unsub = None
        if self._dhw_boost_active and self._saved_dhw_target_temp is not None:
            if self.is_ebus_operational:
                self._dhw_boost_active = False

                async def _timeout_restore_task() -> None:
                    try:
                        await self._async_restore_dhw_target_temp(
                            "60-minute safety timeout"
                        )
                    except HomeAssistantError as err:
                        _LOGGER.debug(
                            "DHW boost safety timeout restore failed; will retry on next telemetry: %s",
                            err,
                        )

                self.hass.async_create_task(_timeout_restore_task())
            else:
                self._defer_dhw_boost_restore_offline()

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

        restore_reason: str | None = None
        # Condition 1: HwcSFMode returned to "auto" (after either seeing "load" or 15s grace period)
        if sf_mode == "auto" and (self._dhw_boost_seen_load or elapsed > 15.0):
            restore_reason = "HwcSFMode returned to auto"
        else:
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
                restore_reason = f"HwcStorageTemp ({storage_temp:.1f}°C) reached target ({goal_temp:.1f}°C) + 1.0°C"

        if restore_reason is None:
            return

        self._dhw_boost_active = False
        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None

        if self.is_ebus_operational:

            async def _tracking_restore_task() -> None:
                try:
                    await self._async_restore_dhw_target_temp(restore_reason)
                except HomeAssistantError as err:
                    _LOGGER.debug(
                        "DHW boost tracking restore failed; will retry on next telemetry: %s",
                        err,
                    )

            self.hass.async_create_task(_tracking_restore_task())
        else:
            self._defer_dhw_boost_restore_offline()

    async def _async_restore_dhw_target_temp(self, reason: str) -> None:
        """Acquire the DHW boost lock and restore HwcTempDesired."""
        async with self._dhw_boost_lock:
            await self._async_restore_dhw_target_temp_unlocked(reason)

    async def _async_restore_dhw_target_temp_unlocked(self, reason: str) -> None:
        """Restore HwcTempDesired to its pre-boost setpoint while holding self._dhw_boost_lock."""
        saved_temp = self._saved_dhw_target_temp
        self._dhw_boost_active = False
        self._dhw_boost_goal_temp = None
        self._dhw_boost_started_ts = None
        self._dhw_boost_end_time = None
        self._dhw_boost_seen_load = False

        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None
        if self._dhw_boost_restore_unsub is not None:
            self._dhw_boost_restore_unsub()
            self._dhw_boost_restore_unsub = None

        if saved_temp is not None:
            if not self.is_ebus_operational:
                self._saved_dhw_target_temp = saved_temp
                self._pending_dhw_boost_restore = True
                await self._async_save_store(
                    self._dhw_boost_store,
                    {
                        "saved_target_temp": saved_temp,
                        "end_timestamp": 0.0,
                        "end_time": _DEFERRED_RESTORE_END_ISO,
                    },
                    "DHW boost",
                )
                _LOGGER.info(
                    "DHW boost restore requested while eBUS offline; deferring restoration of HwcTempDesired=%.1f°C",
                    saved_temp,
                )
                return

            _LOGGER.info(
                "Restoring HwcTempDesired to original setpoint %.1f°C (%s)",
                saved_temp,
                reason,
            )
            try:
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "HwcTempDesired", saved_temp
                )
            except Exception as err:
                self._saved_dhw_target_temp = saved_temp
                self._pending_dhw_boost_restore = True
                await self._async_save_store(
                    self._dhw_boost_store,
                    {
                        "saved_target_temp": saved_temp,
                        "end_timestamp": 0.0,
                        "end_time": _DEFERRED_RESTORE_END_ISO,
                    },
                    "DHW boost",
                )
                _LOGGER.warning(
                    "Failed to write HwcTempDesired restoration to bus (%s); will retry on next telemetry: %s",
                    reason,
                    err,
                )
                raise

        self._saved_dhw_target_temp = None
        self._pending_dhw_boost_restore = False
        await self._async_clear_store(self._dhw_boost_store, "DHW boost")

    async def async_activate_holiday_mode(
        self,
        temp: float = DEFAULT_HOLIDAY_TEMP,
        start_date: str | None = None,
        start_time: str | None = None,
        end_date: str | None = None,
        end_time: str | None = None,
    ) -> None:
        """Activate Holiday / Away Mode with specified setback temperature and time window."""
        now = dt_util.now()
        cur_date_str = f"{now.day:02d};{now.month:02d};{now.year % 100:02d}"
        cur_time_str = f"{now.hour:02d};{now.minute:02d};{now.second:02d}"

        # If explicit arguments not supplied, check preselected datetime buffers
        if start_date is None and self._preselected_holiday_start_datetime is not None:
            raw_s_dt = self._preselected_holiday_start_datetime
            s_dt = (
                dt_util.as_local(raw_s_dt) if raw_s_dt.tzinfo is not None else raw_s_dt
            )
            start_date = f"{s_dt.day:02d};{s_dt.month:02d};{s_dt.year % 100:02d}"
            if start_time is None:
                start_time = f"{s_dt.hour:02d};{s_dt.minute:02d};{s_dt.second:02d}"

        if end_date is None and self._preselected_holiday_end_datetime is not None:
            raw_e_dt = self._preselected_holiday_end_datetime
            e_dt = (
                dt_util.as_local(raw_e_dt) if raw_e_dt.tzinfo is not None else raw_e_dt
            )
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

    def _compute_holiday_remaining(self) -> tuple[int | None, bool, bool]:
        """Compute holiday status and remaining calendar days.

        Returns:
            Tuple of `(days_remaining, is_active, is_open_ended)`:
            - Inactive: `(0, False, False)`
            - Open-ended (`year == 99`): `(None, True, True)`
            - Active timed window: `(days_diff >= 0, True, False)`
        """
        z1_status = (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").lower()
        start_msg = self.get_message(CIRCUIT_BASS3, "HolidayStartDate")
        end_msg = self.get_message(CIRCUIT_BASS3, "HolidayEndDate")

        if not end_msg:
            return (0, False, False)

        day = end_msg.get("day")
        month = end_msg.get("month")
        year = end_msg.get("year")
        if day is None or month is None or year is None or year == 15:
            return (0, False, False)

        start_year = start_msg.get("year") if start_msg else None
        if start_year == 15:
            return (0, False, False)

        if z1_status and z1_status != "holidayaway" and start_year is None:
            return (0, False, False)

        if year == 99:
            return (None, True, True)

        try:
            now = dt_util.now()
            target_date = datetime(2000 + int(year), int(month), int(day)).date()
            diff = (target_date - now.date()).days
            if diff < 0:
                return (0, False, False)
            end_dt = self._get_holiday_end_datetime()
            if end_dt is not None and end_dt <= now:
                return (0, False, False)
            return (diff, True, False)
        except (ValueError, TypeError, OverflowError):
            return (0, False, False)

    def get_holiday_remaining_days(self) -> int | None:
        """Return remaining days of holiday mode (`0` when inactive, `None` when open-ended)."""
        days, _is_active, _is_open_ended = self._compute_holiday_remaining()
        return days

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

    def _format_bass3_time(
        self,
        circuit: str,
        message: str,
        date_message: str | None = None,
        sentinel_year: int | None = None,
    ) -> str | None:
        """Format a bass3 time field as HH:MM:SS, or None when its paired date is at sentinel."""
        if date_message is not None and sentinel_year is not None:
            date_msg = self.get_message(circuit, date_message)
            if not date_msg or date_msg.get("year") == sentinel_year:
                return None
        msg = self.get_message(circuit, message)
        if not msg:
            return None
        hours = msg.get("hours")
        minutes = msg.get("minutes")
        seconds = msg.get("seconds", 0)
        if (
            not isinstance(hours, int)
            or not isinstance(minutes, int)
            or not isinstance(seconds, int)
        ):
            return None
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _get_holiday_end_datetime(self) -> datetime | None:
        """Build local end datetime from HolidayEndDate and HolidayEndTime (None if inactive/open-ended)."""
        end_msg = self.get_message(CIRCUIT_BASS3, "HolidayEndDate")
        if not end_msg:
            return None
        day = end_msg.get("day")
        month = end_msg.get("month")
        year = end_msg.get("year")
        if (
            not isinstance(day, int)
            or not isinstance(month, int)
            or not isinstance(year, int)
            or year in (15, 99)
        ):
            return None
        time_msg = self.get_message(CIRCUIT_BASS3, "HolidayEndTime") or {}
        h = time_msg.get("hours", 23)
        m = time_msg.get("minutes", 59)
        s = time_msg.get("seconds", 59)
        try:
            return datetime(
                2000 + year,
                month,
                day,
                int(h),
                int(m),
                int(s),
                tzinfo=dt_util.get_default_time_zone(),
            )
        except (ValueError, TypeError, OverflowError):
            return None

    def get_holiday_remaining_attributes(self) -> dict[str, Any]:
        """Return structured extra attributes for holiday duration remaining including hours."""
        days, is_active, is_open_ended = self._compute_holiday_remaining()

        rem_hours: int | None = None
        rem_mins: int | None = None
        rem_formatted: str | None = None
        end_dt = self._get_holiday_end_datetime()
        if is_active and not is_open_ended and end_dt is not None:
            diff_secs = (end_dt - dt_util.now()).total_seconds()
            total_mins = max(1, math.ceil(diff_secs / 60.0)) if diff_secs > 0 else 0
            _, rem_m_day = divmod(total_mins, 1440)
            rem_hours, rem_mins = divmod(rem_m_day, 60)
            rem_formatted = self._format_remaining_duration(total_mins)

        return {
            "days_remaining": days,
            "remaining_hours": rem_hours,
            "remaining_minutes": rem_mins,
            "remaining_formatted": rem_formatted,
            "is_active": is_active,
            "is_open_ended": is_open_ended,
            "start_date": self._format_bass3_date(
                CIRCUIT_BASS3, "HolidayStartDate", 15
            ),
            "start_time": self._format_bass3_time(
                CIRCUIT_BASS3, "HolidayStartTime", "HolidayStartDate", 15
            ),
            "end_date": self._format_bass3_date(CIRCUIT_BASS3, "HolidayEndDate", 15),
            "end_time": self._format_bass3_time(
                CIRCUIT_BASS3, "HolidayEndTime", "HolidayEndDate", 15
            ),
        }

    def _compute_cooling_remaining(self) -> tuple[int | None, bool, bool]:
        """Compute cooling window status and remaining calendar days.

        Returns:
            Tuple of `(days_remaining, is_active, is_open_ended)`:
            - Inactive: `(0, False, False)`
            - Open-ended (`year == 99`): `(None, True, True)`
            - Active timed window: `(days_diff >= 0, True, False)`
        """
        release_status = self.get_str(CIRCUIT_BASS3, "CoolingReleaseStatus", "value")
        z1_op_mode_cooling = (
            self.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or ""
        ).lower()
        end_msg = self.get_message(CIRCUIT_BASS3, "CoolingEndDate")

        if not end_msg:
            return (0, False, False)

        day = end_msg.get("day")
        month = end_msg.get("month")
        year = end_msg.get("year")
        if day is None or month is None or year is None or year == 19:
            return (0, False, False)

        # Explicitly off in status and not year 99
        if (
            release_status is not None
            and release_status.lower() == "off"
            and year != 99
        ):
            return (0, False, False)
        if z1_op_mode_cooling == "off" and year != 99:
            return (0, False, False)

        if year == 99:
            return (None, True, True)

        try:
            target_date = datetime(2000 + int(year), int(month), int(day)).date()
            diff = (target_date - dt_util.now().date()).days
            if diff < 0:
                return (0, False, False)
            return (diff, True, False)
        except (ValueError, TypeError, OverflowError):
            return (0, False, False)

    def get_cooling_remaining_days(self) -> int | None:
        """Return remaining days of cooling period (`0` when inactive, `None` when open-ended)."""
        days, _is_active, _is_open_ended = self._compute_cooling_remaining()
        return days

    def get_cooling_remaining_attributes(self) -> dict[str, Any]:
        """Return structured extra attributes for cooling duration remaining."""
        days, is_active, is_open_ended = self._compute_cooling_remaining()
        return {
            "days_remaining": days,
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
        self._optimistically_clear_z1_status("holidayaway")

    def _start_ventilation_countdown(self) -> None:
        """Start and persist the 30-minute ventilation countdown timer."""
        end_dt = self._utc_deadline(
            timedelta(minutes=VENTILATION_BOOST_DURATION_MINUTES)
        )
        self._ventilation_end_time = end_dt
        self.hass.async_create_task(
            self._async_save_store(
                self._ventilation_store,
                {
                    "end_timestamp": end_dt.timestamp(),
                    "end_time": end_dt.isoformat(),
                },
                "ventilation boost",
            )
        )
        self._async_notify_message_listeners(CALC_CIRCUIT, "VentilationBoostRemaining")

    def _clear_ventilation_countdown(self) -> None:
        """Clear ventilation countdown state and notify countdown listeners."""
        had_timer = self._ventilation_end_time is not None
        self._ventilation_end_time = None
        self._ventilation_ha_activated_mono = 0.0
        if had_timer:
            self.hass.async_create_task(
                self._async_clear_store(self._ventilation_store, "ventilation boost")
            )
        self._async_notify_message_listeners(CALC_CIRCUIT, "VentilationBoostRemaining")

    async def _async_restore_persisted_ventilation(self) -> None:
        """Restore active ventilation countdown across Home Assistant restarts."""
        data = await self._async_load_store(
            self._ventilation_store, "ventilation boost"
        )
        if data is None:
            return
        end_ts = self._parse_persisted_end_timestamp(data)
        if end_ts is None or end_ts <= dt_util.utcnow().timestamp():
            await self._async_clear_store(self._ventilation_store, "ventilation boost")
            return
        self._ventilation_end_time = dt_util.as_local(
            datetime.fromtimestamp(end_ts, tz=UTC)
        )
        self._async_notify_message_listeners(CALC_CIRCUIT, "VentilationBoostRemaining")

    async def async_activate_ventilation_boost(self) -> None:
        """Activate Intensive Ventilation Boost (30-minute heating pause)."""
        await self.async_write_parameter(CIRCUIT_BASS3, "VentilationBoost", "on")
        self._ventilation_ha_activated_mono = time.monotonic()
        self._start_ventilation_countdown()
        for ctrl_circuit in CONTROLLER_CIRCUITS:
            self._apply_optimistic_update(ctrl_circuit, "Z1Status", "ventilation")
            self._async_notify_message_listeners(ctrl_circuit, "Z1Status")
        self._schedule_confirmation_get(
            CIRCUIT_BASS3, "Z1Status", key_circuit=CIRCUIT_BASS3.lower()
        )
        self._schedule_confirmation_get(
            CIRCUIT_BASS3,
            "Z1ActualRoomTempDesired",
            key_circuit=CIRCUIT_BASS3.lower(),
        )

    async def async_cancel_ventilation_boost(self) -> None:
        """Cancel active Intensive Ventilation Boost."""
        await self.async_write_parameter(CIRCUIT_BASS3, "VentilationBoost", "off")
        self._clear_ventilation_countdown()
        self._optimistically_clear_z1_status("ventilation")
        self._schedule_confirmation_get(
            CIRCUIT_BASS3,
            "Z1ActualRoomTempDesired",
            key_circuit=CIRCUIT_BASS3.lower(),
        )

    @callback
    def _async_on_heating_veto_timeout(self, _now: datetime) -> None:
        """Handle backup timeout when a heating quick veto expires."""
        self._heating_veto_unsub = None
        if self._pre_veto_opmode != "off":
            if (
                self._heating_veto_end_time is not None
                or self._pre_veto_opmode is not None
            ):
                self._heating_veto_end_time = None
                self._pre_veto_opmode = None
                self._last_heating_veto_duration = None
                self._heating_veto_started_mono = 0.0
                self.hass.async_create_task(
                    self._async_clear_store(
                        self._heating_veto_store, "heating quick veto"
                    )
                )
                sf_mode = (
                    self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
                ).lower()
                if sf_mode == "veto" and self.is_ebus_operational:
                    self._last_z1_sfmode_sync_time = time.monotonic()
                    self.hass.async_create_task(
                        self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
                    )
                self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
            return
        if self.is_ebus_operational:

            async def _timeout_task() -> None:
                try:
                    before_status_ts = self.get_message_timestamp(
                        CIRCUIT_BASS3, "Z1Status"
                    )
                    before_sf_ts = self.get_message_timestamp(CIRCUIT_BASS3, "Z1SFMode")
                    await self.async_request_get(CIRCUIT_BASS3, "Z1Status")
                    await asyncio.sleep(0.3)
                    await self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
                    await asyncio.sleep(1.5)

                    if self._pre_veto_opmode != "off":
                        return

                    after_status_ts = self.get_message_timestamp(
                        CIRCUIT_BASS3, "Z1Status"
                    )
                    after_sf_ts = self.get_message_timestamp(CIRCUIT_BASS3, "Z1SFMode")
                    fresh_status = after_status_ts is not None and (
                        before_status_ts is None or after_status_ts > before_status_ts
                    )
                    fresh_sf = after_sf_ts is not None and (
                        before_sf_ts is None or after_sf_ts > before_sf_ts
                    )
                    z1_status_now = (
                        (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "")
                        .strip()
                        .lower()
                    )
                    sf_mode_now = (
                        (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "")
                        .strip()
                        .lower()
                    )

                    status_valid = (
                        fresh_status
                        and bool(z1_status_now)
                        and not z1_status_now.startswith("err:")
                    )
                    sf_valid = (
                        fresh_sf
                        and bool(sf_mode_now)
                        and not sf_mode_now.startswith("err:")
                    )
                    any_valid_veto = (status_valid and z1_status_now == "veto") or (
                        sf_valid and sf_mode_now == "veto"
                    )
                    any_valid_finished = (status_valid and z1_status_now != "veto") or (
                        sf_valid and sf_mode_now != "veto"
                    )
                    confirmed_active = any_valid_veto
                    confirmed_finished = any_valid_finished and not any_valid_veto
                    if confirmed_active or not confirmed_finished:
                        if self._heating_veto_started_mono <= 0.0:
                            self._heating_veto_started_mono = time.monotonic()
                        if (
                            time.monotonic() - self._heating_veto_started_mono
                        ) < 43200.0:
                            self._heating_veto_end_time = None
                            self._last_heating_veto_duration = None
                            now_dt = dt_util.now()
                            await self._async_save_store(
                                self._heating_veto_store,
                                {
                                    "pre_opmode": "off",
                                    "end_timestamp": now_dt.timestamp(),
                                    "end_time": now_dt.isoformat(),
                                },
                                "heating quick veto",
                            )
                            self._arm_heating_veto_timer(120.0)
                            self._async_notify_message_listeners(
                                CALC_CIRCUIT, "QuickVetoRemaining"
                            )
                            _LOGGER.info(
                                "Heating quick veto backup timer reached, %s; deferring Z1OpMode='off' restoration",
                                (
                                    "controller reports veto still active"
                                    if confirmed_active
                                    else "controller state not yet confirmed"
                                ),
                            )
                            return

                    await self._async_finish_heating_veto_off_restore(
                        "heating veto duration timeout"
                    )
                except HomeAssistantError as err:
                    _LOGGER.debug(
                        "Heating veto timeout restore failed; will retry on next telemetry: %s",
                        err,
                    )
                else:
                    sf_mode = (
                        self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
                    ).lower()
                    if sf_mode == "veto" and self.is_ebus_operational:
                        self._last_z1_sfmode_sync_time = time.monotonic()
                        await self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")

            self.hass.async_create_task(_timeout_task())
        else:
            self._heating_veto_end_time = None
            self._pending_heating_veto_restore = True
            self._last_heating_veto_duration = None
            self._heating_veto_started_mono = 0.0
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

    @callback
    def _async_check_quick_veto_restoration(
        self, *, trigger_msg: str | None = None
    ) -> None:
        """Check whether hardware countdown timer ended quick veto and restore prior state."""
        if self._heating_veto_activating:
            return
        if trigger_msg is not None and trigger_msg != "z1sfmode":
            return
        sf_mode = (
            (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").strip().lower()
        )
        if not sf_mode or sf_mode.startswith("err:") or sf_mode == "veto":
            return
        z1_status = (
            (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").strip().lower()
        )
        if trigger_msg is None and z1_status == "veto":
            return
        if self._pre_veto_opmode != "off":
            if (
                self._heating_veto_end_time is not None
                or self._pre_veto_opmode is not None
            ):
                if self._heating_veto_unsub is not None:
                    self._heating_veto_unsub()
                    self._heating_veto_unsub = None
                self._heating_veto_end_time = None
                self._pre_veto_opmode = None
                self._last_heating_veto_duration = None
                self._heating_veto_started_mono = 0.0
                self.hass.async_create_task(
                    self._async_clear_store(
                        self._heating_veto_store, "heating quick veto"
                    )
                )
                self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
            return
        if self._pending_heating_veto_restore:
            return
        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
            self._heating_veto_unsub = None
        if not self.is_ebus_operational:
            self._heating_veto_end_time = None
            self._pending_heating_veto_restore = True
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
            return
        self._pending_heating_veto_restore = True

        async def _sf_restore_task() -> None:
            try:
                await self._async_finish_heating_veto_off_restore(f"Z1SFMode={sf_mode}")
            except HomeAssistantError as err:
                _LOGGER.debug(
                    "Heating veto restore on Z1SFMode transition failed: %s", err
                )

        self.hass.async_create_task(_sf_restore_task())

    async def _async_finish_heating_veto_off_restore(self, reason: str) -> None:
        """Clear heating veto store and write Z1OpMode='off'."""
        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
            self._heating_veto_unsub = None
        if self._heating_veto_restore_unsub is not None:
            self._heating_veto_restore_unsub()
            self._heating_veto_restore_unsub = None
        self._heating_veto_end_time = None
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

        if not self.is_ebus_operational:
            self._pre_veto_opmode = "off"
            self._pending_heating_veto_restore = True
            await self._async_save_store(
                self._heating_veto_store,
                {
                    "pre_opmode": "off",
                    "end_timestamp": 0.0,
                    "end_time": _DEFERRED_RESTORE_END_ISO,
                },
                "heating quick veto",
            )
            _LOGGER.info(
                "Heating quick veto restore requested while eBUS offline; deferring Z1OpMode='off' restoration"
            )
            return

        _LOGGER.info(
            "Restoring Z1OpMode to 'off' after heating quick veto (%s)", reason
        )
        try:
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
        except Exception as err:
            self._pre_veto_opmode = "off"
            self._pending_heating_veto_restore = True
            await self._async_save_store(
                self._heating_veto_store,
                {
                    "pre_opmode": "off",
                    "end_timestamp": 0.0,
                    "end_time": _DEFERRED_RESTORE_END_ISO,
                },
                "heating quick veto",
            )
            _LOGGER.warning(
                "Failed to write Z1OpMode='off' restoration to bus (%s); will retry on next telemetry: %s",
                reason,
                err,
            )
            raise

        self._pending_heating_veto_restore = False
        self._pre_veto_opmode = None
        self._last_heating_veto_duration = None
        self._heating_veto_started_mono = 0.0
        await self._async_clear_store(self._heating_veto_store, "heating quick veto")
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

    def _arm_heating_veto_timer(self, delay_seconds: float) -> None:
        """Arm backup timer to handle heating quick veto expiration."""
        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
        self._heating_veto_unsub = async_call_later(
            self.hass,
            max(0.0, float(delay_seconds)),
            self._async_on_heating_veto_timeout,
        )

    @callback
    def _async_start_external_heating_veto_tracking(self) -> None:
        """Start software countdown when Z1SFMode externally transitions to 'veto'."""
        configured_dur = self.get_float(CIRCUIT_BASS3, "Z1QuickVetoDuration", "value")
        dur_val = (
            configured_dur
            if configured_dur and configured_dur > 0
            else DEFAULT_QUICK_VETO_DURATION
        )
        dur_val = max(0.5, min(12.0, round(float(dur_val), 1)))
        if self._pre_veto_opmode is None:
            current_opmode = (
                self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "auto"
            ).lower()
            self._pre_veto_opmode = (
                current_opmode if current_opmode != "off" else "auto"
            )
        self._heating_veto_end_time = self._utc_deadline(timedelta(hours=dur_val))
        self._heating_veto_started_mono = time.monotonic()
        self._last_heating_veto_duration = dur_val
        self._arm_heating_veto_timer(dur_val * 3600.0)
        self.hass.async_create_task(self._async_save_heating_veto_state())
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

    async def async_confirm_heating_veto_active(self) -> bool:
        """Return True only when heating Quick Veto is freshly confirmed on eBUS."""
        sf_mode = (
            (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").strip().lower()
        )
        if sf_mode != "veto":
            return False

        age = self.get_message_age(CIRCUIT_BASS3, "Z1SFMode")
        if age is not None and age <= HEATING_VETO_SFMODE_FRESHNESS_SECONDS:
            return True

        if not self.is_ebus_operational:
            return False

        before_ts = self.get_message_timestamp(CIRCUIT_BASS3, "Z1SFMode")
        try:
            await self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
        except HomeAssistantError:
            return False

        deadline = time.monotonic() + SET_CONFIRMATION_DELAY_SECONDS
        while True:
            after_ts = self.get_message_timestamp(CIRCUIT_BASS3, "Z1SFMode")
            if after_ts is not None and (before_ts is None or after_ts > before_ts):
                fresh_sf = (
                    (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "")
                    .strip()
                    .lower()
                )
                return fresh_sf == "veto"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.1, remaining))

    async def async_refresh_heating_veto_duration(self, duration: float) -> None:
        """Update persisted heating quick veto deadline when duration changes mid-veto."""
        sf_mode = (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").lower()
        if self._heating_veto_end_time is None and sf_mode != "veto":
            return
        if self._pre_veto_opmode is None:
            current_opmode = (
                self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "auto"
            ).lower()
            self._pre_veto_opmode = (
                current_opmode if current_opmode != "off" else "auto"
            )
        dur_val = max(0.5, min(12.0, round(float(duration), 1)))
        self._heating_veto_started_mono = time.monotonic()
        self._last_heating_veto_duration = dur_val
        self._heating_veto_end_time = self._utc_deadline(timedelta(hours=dur_val))
        self._arm_heating_veto_timer(dur_val * 3600.0)
        await self._async_save_heating_veto_state()
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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

        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
            self._heating_veto_unsub = None
        if self._heating_veto_restore_unsub is not None:
            self._heating_veto_restore_unsub()
            self._heating_veto_restore_unsub = None
        if self._pending_heating_veto_restore:
            self._pending_heating_veto_restore = False
            self._pre_veto_opmode = None

        current_opmode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "auto"
        ).lower()
        self._heating_veto_activating = True
        try:
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
            self._last_heating_veto_duration = dur_val
            await self.async_write_parameter(
                CIRCUIT_BASS3, "Z1QuickVetoTemp", target_temp
            )
            await asyncio.sleep(0.3)
            await self.async_write_parameter(
                CIRCUIT_BASS3, "Z1QuickVetoDuration", dur_val
            )
            await asyncio.sleep(0.3)
            self._heating_veto_started_mono = time.monotonic()
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "veto")

            self._heating_veto_end_time = self._utc_deadline(timedelta(hours=dur_val))
            self._arm_heating_veto_timer(dur_val * 3600.0)
            await self._async_save_heating_veto_state()
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
        finally:
            self._heating_veto_activating = False

    async def async_cancel_quick_veto(self, *, restore_opmode: bool = True) -> None:
        """Cancel Quick Veto and optionally restore prior 'off' operating mode."""
        if not self.is_ebus_operational:
            raise HomeAssistantError(
                "Cannot cancel quick veto: eBUS communication is not operational."
            )

        if self._heating_veto_unsub is not None:
            self._heating_veto_unsub()
            self._heating_veto_unsub = None
        if self._heating_veto_restore_unsub is not None:
            self._heating_veto_restore_unsub()
            self._heating_veto_restore_unsub = None

        was_pending_restore = self._pending_heating_veto_restore
        restored_off = (
            restore_opmode
            and not was_pending_restore
            and self._pre_veto_opmode == "off"
        )

        _LOGGER.info("Cancelling Quick Veto and restoring auto operation")
        try:
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "auto")
            await asyncio.sleep(0.3)
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0)
            if restored_off:
                await asyncio.sleep(0.3)
                await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
        except Exception:
            if self._heating_veto_end_time is not None:
                remaining = self._seconds_until(self._heating_veto_end_time)
                self._arm_heating_veto_timer(max(0.0, remaining))
            raise

        if was_pending_restore:
            self._pending_heating_veto_restore = False
        self._pre_veto_opmode = None
        self._heating_veto_end_time = None
        self._last_heating_veto_duration = None
        self._heating_veto_started_mono = 0.0

        self._optimistically_clear_z1_status("veto", force_off=restored_off)

        await self._async_clear_store(self._heating_veto_store, "heating quick veto")
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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

        if self._pending_cooling_veto_restore:
            self._pending_cooling_veto_restore = False
            self._pre_cooling_veto_opmode = None
            self._pre_cooling_veto_temp = None

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
        self._cooling_veto_end_time = self._utc_deadline(timedelta(hours=dur_val))

        seconds = dur_val * 3600.0
        self._arm_cooling_veto_timer(seconds)
        await self._async_save_cooling_veto_state()
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1OpModeCooling")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingManualTemp")
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

    def _arm_cooling_veto_timer(self, delay_seconds: float) -> None:
        """Arm backup timer to cancel cooling quick veto on expiration."""
        if self._cooling_veto_unsub is not None:
            self._cooling_veto_unsub()
            self._cooling_veto_unsub = None

        @callback
        def _async_on_cooling_veto_timeout(_now: datetime) -> None:
            self._cooling_veto_unsub = None

            async def _timeout_task() -> None:
                try:
                    await self.async_cancel_cooling_quick_veto(restore=True)
                except HomeAssistantError as err:
                    _LOGGER.debug(
                        "Cooling veto timeout restore will retry on next telemetry: %s",
                        err,
                    )

            self.hass.async_create_task(_timeout_task())

        self._cooling_veto_unsub = async_call_later(
            self.hass, max(0.0, float(delay_seconds)), _async_on_cooling_veto_timeout
        )

    async def async_refresh_cooling_veto_duration(self, duration: float) -> None:
        """Update cooling veto timer and persisted deadline without rewriting temperature."""
        if not self.cooling_quick_veto_active:
            return
        dur_val = max(0.5, min(12.0, round(float(duration), 1)))
        self._cooling_veto_end_time = self._utc_deadline(timedelta(hours=dur_val))
        self._arm_cooling_veto_timer(dur_val * 3600.0)
        await self._async_save_cooling_veto_state()
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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

        end_time = self._cooling_veto_end_time
        active_temp = self._cooling_veto_active_temp
        pre_opmode = self._pre_cooling_veto_opmode
        pre_temp = self._pre_cooling_veto_temp

        should_restore_temp = restore if restore_temp is None else restore_temp

        if restore or should_restore_temp:
            if not self.is_ebus_operational:
                if restore:
                    self._cooling_veto_end_time = None
                    self._cooling_veto_active_temp = None
                    self._pre_cooling_veto_opmode = pre_opmode
                    self._pre_cooling_veto_temp = pre_temp
                    self._pending_cooling_veto_restore = True
                    await self._async_save_store(
                        self._cooling_veto_store,
                        {
                            "end_timestamp": 0.0,
                            "end_time": _DEFERRED_RESTORE_END_ISO,
                            "pre_opmode": pre_opmode,
                            "pre_temp": pre_temp,
                        },
                        "cooling quick veto",
                    )
                    _LOGGER.info(
                        "Cooling quick veto cancelled while offline; deferring bus restoration until eBUS is operational"
                    )
                    self._async_notify_message_listeners(
                        CALC_CIRCUIT, "QuickVetoRemaining"
                    )
                    return

                # Preset change path (restore=False): preserve veto state in memory, re-arm timer with max(0.0, remaining), raise error
                self._cooling_veto_end_time = end_time
                self._cooling_veto_active_temp = active_temp
                self._pre_cooling_veto_opmode = pre_opmode
                self._pre_cooling_veto_temp = pre_temp
                if end_time is not None:
                    remaining = self._seconds_until(end_time)
                    self._arm_cooling_veto_timer(max(0.0, remaining))
                raise HomeAssistantError(
                    "Cannot cancel cooling quick veto: eBUS communication is not operational."
                )

            _LOGGER.info(
                "Cancelling Cooling Quick Veto: restore=%s, restore_temp=%s (pre_opmode=%s, pre_temp=%s)",
                restore,
                should_restore_temp,
                pre_opmode,
                pre_temp,
            )
            try:
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
            except Exception as err:
                if restore:
                    self._cooling_veto_end_time = None
                    self._cooling_veto_active_temp = None
                    self._pre_cooling_veto_opmode = pre_opmode
                    self._pre_cooling_veto_temp = pre_temp
                    self._pending_cooling_veto_restore = True
                    await self._async_save_store(
                        self._cooling_veto_store,
                        {
                            "end_timestamp": 0.0,
                            "end_time": _DEFERRED_RESTORE_END_ISO,
                            "pre_opmode": pre_opmode,
                            "pre_temp": pre_temp,
                        },
                        "cooling quick veto",
                    )
                    _LOGGER.warning(
                        "Failed to write cooling quick veto restoration to bus; will retry on next telemetry: %s",
                        err,
                    )
                    self._async_notify_message_listeners(
                        CALC_CIRCUIT, "QuickVetoRemaining"
                    )
                else:
                    self._cooling_veto_end_time = end_time
                    self._cooling_veto_active_temp = active_temp
                    self._pre_cooling_veto_opmode = pre_opmode
                    self._pre_cooling_veto_temp = pre_temp
                    if end_time is not None:
                        remaining = self._seconds_until(end_time)
                        self._arm_cooling_veto_timer(max(0.0, remaining))
                    _LOGGER.warning(
                        "Failed to restore cooling quick veto setpoint during cancellation: %s",
                        err,
                    )
                raise

            # Returning to auto/night: invalidate stale veto setpoint and schedule
            # confirmation read of Z1CoolingTempDesired so HA picks up the controller's
            # real schedule/setback setpoint (or 99 °C sentinel).
            if restore and pre_opmode != "day":
                self.schedule_cooling_desired_refresh(notify=False)

        self._cooling_veto_end_time = None
        self._cooling_veto_active_temp = None
        self._pending_cooling_veto_restore = False
        self._pre_cooling_veto_opmode = None
        self._pre_cooling_veto_temp = None
        await self._async_clear_cooling_veto_store()

        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1OpModeCooling")
        self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingManualTemp")
        self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

    def schedule_cooling_desired_refresh(
        self, *, invalidate_cached: bool = True, notify: bool = True
    ) -> None:
        """Invalidate cached boost Z1CoolingTempDesired and schedule a delayed /get read."""
        if invalidate_cached:
            for key in list(self._state):
                if (
                    key[0].lower() in CONTROLLER_CIRCUITS
                    and key[1].lower() == "z1coolingtempdesired"
                ):
                    self._state.pop(key, None)

        if self._cooling_veto_get_unsub is not None:
            self._cooling_veto_get_unsub()
            self._cooling_veto_get_unsub = None

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
        if notify:
            self._async_notify_message_listeners(CIRCUIT_BASS3, "Z1CoolingTempDesired")

    @staticmethod
    def _parse_persisted_end_timestamp(data: dict[str, Any]) -> float | None:
        """Extract Unix timestamp from persisted 'end_timestamp' or ISO 'end_time'."""
        end_ts_raw = data.get("end_timestamp")
        if isinstance(end_ts_raw, (int, float)):
            return float(end_ts_raw)
        end_iso = data.get("end_time")
        if isinstance(end_iso, str):
            with contextlib.suppress(ValueError):
                return datetime.fromisoformat(end_iso).timestamp()
        return None

    async def _async_save_store(
        self, store: Store[dict[str, Any]], data: dict[str, Any], label: str
    ) -> None:
        """Persist state dictionary to Home Assistant storage with warning on error."""
        try:
            await store.async_save(data)
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning("Failed to persist %s state: %s", label, err)

    async def _async_clear_store(
        self, store: Store[dict[str, Any]], label: str
    ) -> None:
        """Remove persisted state dictionary from Home Assistant storage."""
        try:
            await store.async_remove()
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning("Failed to remove persisted %s state: %s", label, err)

    async def _async_load_store(
        self, store: Store[dict[str, Any]], label: str
    ) -> dict[str, Any] | None:
        """Load persisted state dictionary from Home Assistant storage."""
        try:
            data = await store.async_load()
        except (OSError, ValueError, TypeError, HomeAssistantError) as err:
            _LOGGER.warning("Failed to load persisted %s state: %s", label, err)
            return None
        if not data or not isinstance(data, dict):
            return None
        return data

    @callback
    def _async_schedule_pending_restores(self) -> None:
        """Schedule deferred restores for overrides that expired while HA/eBUS was offline."""
        delay = (
            1.5
            if self._initial_hydration_started
            else INITIAL_HYDRATION_WAIT_SECONDS + 2.0
        )

        def _schedule_if_needed(
            pending: bool,
            unsub_attr: str,
            coro_factory: Callable[[], Coroutine[Any, Any, None]],
        ) -> None:
            if not pending or getattr(self, unsub_attr) is not None:
                return

            @callback
            def _on_delay(_now: datetime) -> None:
                setattr(self, unsub_attr, None)
                self.hass.async_create_task(coro_factory())

            setattr(
                self,
                unsub_attr,
                async_call_later(self.hass, delay, _on_delay),
            )

        _schedule_if_needed(
            self._pending_cooling_veto_restore,
            "_cooling_veto_restore_unsub",
            self._async_execute_pending_cooling_veto_restore,
        )
        _schedule_if_needed(
            self._pending_heating_veto_restore,
            "_heating_veto_restore_unsub",
            self._async_execute_pending_heating_veto_restore,
        )
        _schedule_if_needed(
            self._pending_dhw_boost_restore,
            "_dhw_boost_restore_unsub",
            self._async_execute_pending_dhw_boost_restore,
        )

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
        await self._async_save_store(
            self._cooling_veto_store, data, "cooling quick veto"
        )

    async def _async_clear_cooling_veto_store(self) -> None:
        """Remove persisted cooling quick veto state from Home Assistant storage."""
        await self._async_clear_store(self._cooling_veto_store, "cooling quick veto")

    async def _async_restore_persisted_cooling_veto(self) -> None:
        """Restore or finalize a persisted cooling quick veto after Home Assistant restart."""
        data = await self._async_load_store(
            self._cooling_veto_store, "cooling quick veto"
        )
        if data is None:
            return

        end_ts = self._parse_persisted_end_timestamp(data)
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

        remaining = end_ts - dt_util.utcnow().timestamp()
        if remaining > 0:
            self._cooling_veto_end_time = dt_util.as_local(
                datetime.fromtimestamp(end_ts, tz=UTC)
            )
            self._arm_cooling_veto_timer(remaining)
            _LOGGER.info(
                "Restored active cooling quick veto after restart (%.0fs remaining, active_temp=%s, pre_opmode=%s, pre_temp=%s)",
                remaining,
                self._cooling_veto_active_temp,
                self._pre_cooling_veto_opmode,
                self._pre_cooling_veto_temp,
            )
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
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
                self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")

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
        try:
            await self.async_cancel_cooling_quick_veto(restore=True)
        except HomeAssistantError as err:
            _LOGGER.debug(
                "Deferred cooling quick veto restore failed; will retry on next telemetry: %s",
                err,
            )

    async def _async_save_heating_veto_state(self) -> None:
        """Persist active heating quick veto across Home Assistant restarts."""
        if self._heating_veto_end_time is None:
            await self._async_clear_store(
                self._heating_veto_store, "heating quick veto"
            )
            return
        data = {
            "pre_opmode": self._pre_veto_opmode or "auto",
            "end_timestamp": self._heating_veto_end_time.timestamp(),
            "end_time": self._heating_veto_end_time.isoformat(),
        }
        await self._async_save_store(
            self._heating_veto_store, data, "heating quick veto"
        )

    async def _async_restore_persisted_heating_veto(self) -> None:
        """Restore or finalize a persisted heating quick veto after restart."""
        data = await self._async_load_store(
            self._heating_veto_store, "heating quick veto"
        )
        if data is None:
            return
        pre_opmode_raw = data.get("pre_opmode")
        if not isinstance(pre_opmode_raw, str) or not pre_opmode_raw:
            await self._async_clear_store(
                self._heating_veto_store, "heating quick veto"
            )
            return
        pre_opmode = pre_opmode_raw.lower()

        end_ts = self._parse_persisted_end_timestamp(data)
        if end_ts is None:
            await self._async_clear_store(
                self._heating_veto_store, "heating quick veto"
            )
            return

        self._pre_veto_opmode = pre_opmode
        remaining = end_ts - dt_util.utcnow().timestamp()
        if remaining > 0:
            self._heating_veto_end_time = dt_util.as_local(
                datetime.fromtimestamp(end_ts, tz=UTC)
            )
            self._arm_heating_veto_timer(remaining)
            _LOGGER.info(
                "Restored active heating quick veto from '%s' after restart (%.0fs remaining)",
                pre_opmode,
                remaining,
            )
            self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
        else:
            self._heating_veto_end_time = None
            if pre_opmode != "off":
                self._pre_veto_opmode = None
                await self._async_clear_store(
                    self._heating_veto_store, "heating quick veto"
                )
                self._async_notify_message_listeners(CALC_CIRCUIT, "QuickVetoRemaining")
                return
            sf_mode = (
                (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").strip().lower()
            )
            z1_status = (
                (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").strip().lower()
            )
            if sf_mode == "veto":
                return
            if (
                self.is_ebus_operational
                and sf_mode
                and not sf_mode.startswith("err:")
                and z1_status != "veto"
            ):
                await self._async_finish_heating_veto_off_restore(
                    "persisted veto expired during restart"
                )
            else:
                self._pending_heating_veto_restore = True
                _LOGGER.info(
                    "Persisted heating quick veto from 'off' expired; deferring bus restoration until eBUS is operational and controller state is confirmed"
                )

    async def _async_execute_pending_heating_veto_restore(self) -> None:
        """Execute deferred restoration for a persisted heating veto from 'off'."""
        if not self._pending_heating_veto_restore or not self.is_ebus_operational:
            return
        sf_mode = (
            (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "").strip().lower()
        )
        z1_status = (
            (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "").strip().lower()
        )
        if sf_mode == "veto":
            # Controller still actively running veto (e.g. extended on wall unit);
            # let Z1SFMode transition handle restoration instead of forcing 'off' early.
            self._pending_heating_veto_restore = False
            _LOGGER.info(
                "Deferred heating quick veto restore paused: controller reports Z1SFMode=veto still active"
            )
            return
        if not sf_mode or sf_mode.startswith("err:") or z1_status == "veto":
            now_mono = time.monotonic()
            if (now_mono - self._last_z1_sfmode_sync_time) >= 30.0:
                self._last_z1_sfmode_sync_time = now_mono
                try:
                    await self.async_request_get(CIRCUIT_BASS3, "Z1SFMode")
                except HomeAssistantError as err:
                    _LOGGER.debug(
                        "Failed to query Z1SFMode before deferred heating veto restore: %s",
                        err,
                    )
                    return
                if (
                    not self._pending_heating_veto_restore
                    or not self.is_ebus_operational
                ):
                    return
                sf_mode = (
                    (self.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or "")
                    .strip()
                    .lower()
                )
                z1_status = (
                    (self.get_str(CIRCUIT_BASS3, "Z1Status", "value") or "")
                    .strip()
                    .lower()
                )
                if sf_mode == "veto":
                    self._pending_heating_veto_restore = False
                    _LOGGER.info(
                        "Deferred heating quick veto restore paused: controller reports Z1SFMode=veto still active"
                    )
                    return
            if not sf_mode or sf_mode.startswith("err:") or z1_status == "veto":
                _LOGGER.debug(
                    "Deferred heating quick veto restore waiting for controller Z1SFMode confirmation"
                )
                return
        try:
            await self._async_finish_heating_veto_off_restore(
                "persisted heating quick veto expired while offline"
            )
        except HomeAssistantError as err:
            _LOGGER.debug(
                "Deferred heating quick veto restore failed; will retry on next telemetry: %s",
                err,
            )

    async def _async_save_dhw_boost_state(self) -> None:
        """Persist active forced DHW boost state across Home Assistant restarts."""
        if (
            not self._dhw_boost_active
            or self._dhw_boost_end_time is None
            or self._saved_dhw_target_temp is None
        ):
            await self._async_clear_store(self._dhw_boost_store, "DHW boost")
            return
        data = {
            "started_timestamp": self._dhw_boost_started_ts,
            "end_timestamp": self._dhw_boost_end_time.timestamp(),
            "end_time": self._dhw_boost_end_time.isoformat(),
            "saved_target_temp": self._saved_dhw_target_temp,
            "goal_temp": self._dhw_boost_goal_temp,
            "seen_load": self._dhw_boost_seen_load,
        }
        await self._async_save_store(self._dhw_boost_store, data, "DHW boost")

    async def _async_restore_persisted_dhw_boost(self) -> None:
        """Restore or finalize a persisted forced DHW boost after Home Assistant restart."""
        data = await self._async_load_store(self._dhw_boost_store, "DHW boost")
        if data is None:
            return

        saved_raw = data.get("saved_target_temp")
        end_ts = self._parse_persisted_end_timestamp(data)
        if not isinstance(saved_raw, (int, float)) or end_ts is None:
            await self._async_clear_store(self._dhw_boost_store, "DHW boost")
            return

        saved_temp = float(saved_raw)
        goal_raw = data.get("goal_temp")
        goal_temp = (
            float(goal_raw) if isinstance(goal_raw, (int, float)) else saved_temp
        )
        started_raw = data.get("started_timestamp")
        started_ts = (
            float(started_raw)
            if isinstance(started_raw, (int, float))
            else end_ts - DHW_BOOST_MAX_TIMEOUT_SECONDS
        )
        seen_load = bool(data.get("seen_load", False))

        now_ts = dt_util.utcnow().timestamp()
        remaining = end_ts - now_ts
        if remaining > 0:
            self._saved_dhw_target_temp = saved_temp
            self._dhw_boost_goal_temp = goal_temp
            self._dhw_boost_active = True
            self._dhw_boost_started_ts = started_ts
            self._dhw_boost_end_time = dt_util.as_local(
                datetime.fromtimestamp(end_ts, tz=UTC)
            )
            self._dhw_boost_seen_load = seen_load
            elapsed_since_start = max(0.0, now_ts - started_ts)
            self._dhw_boost_started_at = time.monotonic() - elapsed_since_start

            if self._dhw_boost_timeout_unsub is not None:
                self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = async_call_later(
                self.hass, remaining, self._async_on_dhw_boost_timeout
            )
            _LOGGER.info(
                "Restored active forced DHW boost after restart (%.0fs remaining, saved_target=%.1f°C, goal=%.1f°C)",
                remaining,
                saved_temp,
                goal_temp,
            )
        else:
            self._saved_dhw_target_temp = saved_temp
            self._dhw_boost_goal_temp = goal_temp
            self._dhw_boost_active = False
            self._dhw_boost_started_ts = None
            self._dhw_boost_end_time = None
            self._dhw_boost_seen_load = False
            if self.is_ebus_operational:
                await self._async_restore_dhw_target_temp(
                    "persisted 60-minute boost timeout expired during restart"
                )
            else:
                self._pending_dhw_boost_restore = True
                _LOGGER.info(
                    "Persisted forced DHW boost expired while offline; deferring restoration of HwcTempDesired=%.1f°C until eBUS is operational",
                    saved_temp,
                )

    async def _async_execute_pending_dhw_boost_restore(self) -> None:
        """Execute deferred restoration of pre-boost HwcTempDesired after restart/offline expiry."""
        async with self._dhw_boost_lock:
            if not self._pending_dhw_boost_restore or not self.is_ebus_operational:
                return
            try:
                await self._async_restore_dhw_target_temp_unlocked(
                    "deferred DHW boost setpoint restoration"
                )
            except HomeAssistantError as err:
                _LOGGER.debug(
                    "Deferred DHW boost restore failed; will retry on next telemetry: %s",
                    err,
                )

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

    @staticmethod
    def _is_valid_serial_candidate(
        candidate: str, *, min_len: int = 20, exact_len: int | None = None
    ) -> bool:
        """Return True if candidate looks like a valid serial string rather than an eBUSd error."""
        if not candidate or " " in candidate or candidate.upper().startswith("ERR:"):
            return False
        if exact_len is not None:
            return len(candidate) == exact_len
        return len(candidate) >= min_len

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
        if payload_str.upper().startswith("ERR:") or self._is_ebusd_err_msg(parsed):
            return
        val_str = str(parsed.get("value", "") or payload_str).strip()

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
                    if self._is_valid_serial_candidate(candidate, min_len=20):
                        detected_serial = candidate
                        break
            if not detected_serial and "id" in parsed:
                candidate = str(parsed["id"]).strip()
                if self._is_valid_serial_candidate(candidate, exact_len=28):
                    detected_serial = candidate

        # d) Raw 28-char string under an Id topic (e.g. Scan.08/Id)
        if (
            not detected_serial
            and len(parts) >= 2
            and parts[1].lower() in ("id", "identification")
            and not val_str.upper().startswith("ERR:")
        ):
            clean_val = val_str.replace(";", "").replace(" ", "").strip()
            if self._is_valid_serial_candidate(clean_val, exact_len=28):
                detected_serial = clean_val

        # Record outdoor SW before _async_on_outdoor_circuit_changed runs hydration logic
        if device_key == DEVICE_OUTDOOR_UNIT and detected_sw:
            self._record_detected_outdoor_sw(detected_sw)

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
            device = self._get_device_registry_entry(dev_reg, device_key)
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
                    "Updated Device Registry for %s_%s with %s",
                    self.entry.entry_id,
                    device_key,
                    kwargs,
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
