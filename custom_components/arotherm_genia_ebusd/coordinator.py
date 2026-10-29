"""MQTT Coordinator, Hydration Queue, DHW Boost Manager, and Thermodynamic Calculator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import json
import logging
import time
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    CALC_CIRCUIT,
    CALC_DAILY_COP,
    CALC_DELTA_T,
    CALC_LIVE_COP,
    CALC_MONTHLY_COP,
    CALC_THERMAL_POWER,
    CALC_TOTAL_COP,
    CALC_TOTAL_ENERGY,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    CIRCUIT_VWZIO,
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
    DEFAULT_CYLINDER_HYST,
    DEFAULT_FALLBACK_POLL_INTERVAL,
    DEFAULT_FORCE_DHW_BOOST,
    DEFAULT_HAS_MIGO_LINK,
    DEFAULT_HAS_WIRELESS_ROOM_UNIT,
    DEFAULT_INDOOR_MODEL,
    DEFAULT_MANUFACTURER,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_OUTDOOR_MODEL,
    DHW_BOOST_HYST_MARGIN,
    DHW_BOOST_MAX_TIMEOUT_SECONDS,
    ESSENTIAL_HYDRATION_MESSAGES,
    HYDRATION_STEP_DELAY_SECONDS,
    INITIAL_HYDRATION_WAIT_SECONDS,
    SET_CONFIRMATION_DELAY_SECONDS,
)
from .thermodynamics import (
    MIN_DAILY_ELECTRICAL_ENERGY_WH,
    calculate_delta_t,
    calculate_live_cop,
    calculate_period_cop,
    calculate_thermal_power,
    calculate_total_energy,
)

_LOGGER = logging.getLogger(__name__)

# Inputs in hmux0 that trigger recalculation of thermodynamic sensors
THERMO_TRIGGER_MESSAGES: set[str] = {
    "RunDataFlowTemp",
    "RunDataReturnTemp",
    "Status01",
    "RunDataFlowRate",
    "RunDataElectricPowerConsumption",
    "HMUStatusCode",
    "PrEnergyElectricToday",
    "PrEnergyThermalToday",
    "PrEnergyElectricMonth",
    "PrEnergyThermalMonth",
    "PrEnergyElectricTotal",
    "PrEnergyThermalTotal",
    "PrEnergyCoolingElectricTotal",
    "PrEnergySumHc",
    "PrEnergySumHwc",
}

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
TIMER_WRITE_FIELDS: tuple[str, ...] = ("from_hour", "from_min", "to_hour", "to_min")


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
    if message in ("CoolingStartDate", "CoolingEndDate"):
        return DATE_WRITE_FIELDS
    if "Timer_" in message and not message.endswith("_Slots"):
        return TIMER_WRITE_FIELDS
    # Generic fallback: reuse the field order already published by ebusd
    data_keys = tuple(k for k in current if k != "value")
    return data_keys or None


# Whitelist of writable parameters that have active read priority (r / r9) on eBUS.
# ONLY these parameters query physical bus hardware on confirmation /get.
# For all other writable parameters (passive 'u'), confirmation /get is NEVER sent,
# preventing eBUSd from echoing stale RAM cache over user input.
ACTIVE_READ_CONFIRMATION_MESSAGES: frozenset[tuple[str, str]] = frozenset({
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
    (CIRCUIT_BASS3.lower(), "Z1HolidayTemp"),
    (CIRCUIT_BASS3.lower(), "Z1ValveStatus"),
})


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
        # Case-insensitive index mapping (circuit_lower, message_lower) -> canonical message_name
        self._canonical_names: dict[tuple[str, str], str] = {}

        # Listeners indexed by (circuit_lower, message_lower)
        self._listeners: dict[tuple[str, str], list[ Callable[[], None] ]] = {}
        self._global_listeners: list[Callable[[], None]] = []

        # Subscriptions and background tasks cleanup callbacks
        self._mqtt_unsubs: list[CALLBACK_TYPE] = []
        self._hydration_timer_unsub: CALLBACK_TYPE | None = None
        self._fallback_poll_unsub: CALLBACK_TYPE | None = None
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
    def fallback_poll_interval(self) -> int:
        """Return fallback poll interval in seconds when has_migo_link is False."""
        return int(
            self.entry.options.get(
                CONF_FALLBACK_POLL_INTERVAL, DEFAULT_FALLBACK_POLL_INTERVAL
            )
        )

    @property
    def saved_dhw_target_temp(self) -> float | None:
        """Return original DHW target temperature saved before a forced boost."""
        return self._saved_dhw_target_temp

    @property
    def dhw_boost_forced_active(self) -> bool:
        """Return True if a forced DHW boost setpoint elevation is currently active."""
        return self._dhw_boost_active

    # -------------------------------------------------------------------------
    # Lifecycle Setup & Unload
    # -------------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to ebusd MQTT topics and schedule initial hydration."""
        prefix = self.mqtt_prefix
        circuits_to_subscribe = [
            CIRCUIT_BASS3,
            CIRCUIT_HMUX0,
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

        if self._dhw_boost_timeout_unsub is not None:
            self._dhw_boost_timeout_unsub()
            self._dhw_boost_timeout_unsub = None

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
        if topic.endswith("/get") or topic.endswith("/set"):
            return

        prefix_with_slash = f"{self.mqtt_prefix}/"
        if not topic.startswith(prefix_with_slash):
            return

        rel_topic = topic[len(prefix_with_slash) :]
        parts = rel_topic.split("/")
        if len(parts) < 2:
            return

        circuit_raw = parts[0]
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

        self._canonical_names[(circuit_key, msg_lower)] = message_name
        self._state[(circuit_key, message_name)] = parsed

        # Notify subscribers for this (circuit, message)
        self._async_notify_message_listeners(circuit_key, message_name)

        # Trigger thermodynamic calculations if relevant outdoor unit telemetry changed
        if circuit_key == CIRCUIT_HMUX0 and message_name in THERMO_TRIGGER_MESSAGES:
            self._async_recalculate_thermodynamics()

        # Check DHW boost restoration conditions when bass3 HwcSFMode or HwcStorageTemp updates
        if circuit_key == CIRCUIT_BASS3 and message_name in (
            "HwcSFMode",
            "HwcStorageTemp",
            "HwcStatus",
        ):
            self._async_check_dhw_boost_restoration()

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
        return (c_key, canonical) in self._state

    def get_message(self, circuit: str, message: str) -> dict[str, Any] | None:
        """Return the full normalized dict for (circuit, message), or None."""
        c_key = circuit.lower()
        m_lower = message.lower()
        canonical = self._canonical_names.get((c_key, m_lower), message)
        return self._state.get((c_key, canonical))

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

        # 2. Fallback to 'value' (standard single-field name in 15.bass3.csv & 08.hmux0.csv)
        if "value" in msg_data and msg_data["value"] is not None:
            return msg_data["value"]

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

    # -------------------------------------------------------------------------
    # MQTT Publishing (/set and /get) & Hydration Queue
    # -------------------------------------------------------------------------

    async def async_request_get(self, circuit: str, message: str) -> None:
        """Publish an empty payload to <mqtt_prefix>/<circuit>/<message>/get."""
        topic = f"{self.mqtt_prefix}/{circuit}/{message}/get"
        await mqtt.async_publish(self.hass, topic, "", qos=0, retain=False)

    async def async_write_parameter(
        self,
        circuit: str,
        message: str,
        value: Any,
    ) -> None:
        """Publish a write command to <mqtt_prefix>/<circuit>/<message>/set and schedule confirmation /get."""
        topic = f"{self.mqtt_prefix}/{circuit}/{message}/set"
        payload = str(value)
        _LOGGER.debug("Publishing eBUSd write: %s -> '%s'", topic, payload)

        # Optimistic local update so Home Assistant UI reflects the user's action immediately.
        # For passive 'u' messages this is the ONLY state refresh until MiGo Link (f1) or the
        # controller (10) polls the register again, so it must update the real field names.
        self._apply_optimistic_update(circuit, message, value)
        self._async_notify_message_listeners(circuit, message)

        await mqtt.async_publish(self.hass, topic, payload, qos=0, retain=False)

        # Schedule confirmation /get ONLY for active read commands (r / r9 whitelist).
        # For all passive 'u' commands (setpoints, modes, timers, dates), NEVER send /get,
        # perfectly preserving the optimistic UI update without stale cache rebounds.
        key = (circuit.lower(), message)
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

    def _apply_optimistic_update(
        self, circuit: str, message: str, value: Any
    ) -> None:
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
                current.update(zip(layout, parts))
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
    def _async_start_initial_hydration(self, _now: datetime) -> None:
        """Start background task to hydrate missing messages after retained wait."""
        self._hydration_timer_unsub = None
        missing: list[tuple[str, str]] = [
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

    async def _async_run_hydration_queue(
        self, messages: list[tuple[str, str]]
    ) -> None:
        """Publish /get sequentially with 0.8s spacing to avoid eBUS collisions."""
        try:
            for circuit, message in messages:
                if self.has_message(circuit, message):
                    continue
                await self.async_request_get(circuit, message)
                await asyncio.sleep(HYDRATION_STEP_DELAY_SECONDS)
        except asyncio.CancelledError:
            _LOGGER.debug("Initial eBUSd hydration task cancelled")
            raise
        _LOGGER.info("Completed initial staggered eBUSd hydration queue")

    async def _async_run_fallback_poll(self, _now: datetime) -> None:
        """Periodic fallback poll executed only when has_migo_link is False."""
        if self.has_migo_link:
            return
        if self._hydration_task is not None and not self._hydration_task.done():
            return
        # Poll core operational messages with gentle spacing
        core_messages = ESSENTIAL_HYDRATION_MESSAGES[:40]
        self._hydration_task = self.hass.async_create_background_task(
            self._async_force_poll_queue(core_messages),
            name=f"{self.entry.domain}_fallback_poll",
        )

    async def _async_force_poll_queue(
        self, messages: list[tuple[str, str]]
    ) -> None:
        """Sequentially request /get on messages with 0.8s spacing."""
        try:
            for circuit, message in messages:
                await self.async_request_get(circuit, message)
                await asyncio.sleep(HYDRATION_STEP_DELAY_SECONDS)
        except asyncio.CancelledError:
            raise

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
        """Recalculate Delta T, Thermal Power, Live COP, Daily COP, Monthly COP, and Total SCOP."""
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
        hmu_status = (
            self.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status") or ""
        )
        flow_rate = self.get_float(CIRCUIT_HMUX0, "RunDataFlowRate", "value")
        thermal_power = calculate_thermal_power(flow_rate, delta_t, hmu_status)
        if thermal_power is not None:
            self._set_calculated(CALC_THERMAL_POWER, thermal_power)

        # 3. Live Instantaneous COP / EER
        elec_power = self.get_float(
            CIRCUIT_HMUX0, "RunDataElectricPowerConsumption", "power"
        )
        live_cop, is_active = calculate_live_cop(
            thermal_power, elec_power, hmu_status, frozenset(ACTIVE_COMPRESSOR_STATUSES)
        )
        if live_cop is not None:
            if is_active:
                self.last_active_cop = live_cop
            self._set_calculated(CALC_LIVE_COP, live_cop)

        # 4. Daily Real COP
        elec_today = self.get_float(CIRCUIT_HMUX0, "PrEnergyElectricToday", "energy")
        therm_today = self.get_float(CIRCUIT_HMUX0, "PrEnergyThermalToday", "energy")
        daily_cop = calculate_period_cop(
            therm_today, elec_today, min_elec_energy=MIN_DAILY_ELECTRICAL_ENERGY_WH
        )
        if daily_cop is not None:
            self._set_calculated(CALC_DAILY_COP, daily_cop)

        # 5. Monthly Real COP & Total Historical SCOP
        elec_month = self.get_float(CIRCUIT_HMUX0, "PrEnergyElectricMonth", "energy")
        therm_month = self.get_float(CIRCUIT_HMUX0, "PrEnergyThermalMonth", "energy")
        monthly_cop = calculate_period_cop(
            therm_month, elec_month, min_elec_energy=0.0
        )
        if monthly_cop is not None:
            self._set_calculated(CALC_MONTHLY_COP, monthly_cop)

        elec_total = self.get_float(CIRCUIT_HMUX0, "PrEnergyElectricTotal", "energy")
        therm_total = self.get_float(CIRCUIT_HMUX0, "PrEnergyThermalTotal", "energy")
        total_cop = calculate_period_cop(
            therm_total, elec_total, min_elec_energy=0.0
        )
        if total_cop is not None:
            self._set_calculated(CALC_TOTAL_COP, total_cop)

        # Combined Total Electrical Energy Consumed (Heating + DHW + Cooling)
        hc_total = self.get_float(CIRCUIT_BASS3, "PrEnergySumHc", "value")
        hwc_total = self.get_float(CIRCUIT_BASS3, "PrEnergySumHwc", "value")
        cool_total = self.get_float(
            CIRCUIT_HMUX0, "PrEnergyCoolingElectricTotal", "energy"
        )
        total_energy = calculate_total_energy(hc_total, hwc_total, cool_total)
        if total_energy is not None:
            self._set_calculated(CALC_TOTAL_ENERGY, total_energy)

    # -------------------------------------------------------------------------
    # Smart Forced DHW Boost Manager (Section 7.2)
    # -------------------------------------------------------------------------

    async def async_trigger_dhw_boost(
        self, override_boost_temp: float | None = None
    ) -> None:
        """Activate DHW One-Time Boost (HwcSFMode=load), dynamically overcoming hysteresis."""
        storage_temp = self.get_float(CIRCUIT_BASS3, "HwcStorageTemp", "value")
        target_temp = (
            self.get_float(CIRCUIT_BASS3, "HwcTempDesired", "value") or 50.0
        )
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

        sf_mode = (
            self.get_str(CIRCUIT_BASS3, "HwcSFMode", "value") or ""
        ).lower()
        hwc_status = (
            self.get_str(CIRCUIT_BASS3, "HwcStatus", "value") or ""
        ).lower()
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
