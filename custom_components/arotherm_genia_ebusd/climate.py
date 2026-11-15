"""Climate platform for Saunier Duval MiPro Sense Zone 1 (Double-Lock + Anti-Sentinel)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CALC_CIRCUIT,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_COOLING_TEMP,
    DEFAULT_HOLIDAY_TEMP,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_MANUAL,
    PRESET_VENTILATION,
    SENTINEL_COOLING_THRESHOLD,
    SENTINEL_HEATING_THRESHOLD,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity

SEASON_HEATING = "heating"
SEASON_COOLING = "cooling"

# Z1OpModeCooling / Z1OpMode values that mean the season circuit is enabled
COOLING_ACTIVE_MODES: frozenset[str] = frozenset({"auto", "day", "night"})
HEATING_ACTIVE_MODES: frozenset[str] = frozenset({"auto", "day", "night"})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the MiPro Sense Zone 1 Climate entity."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory: Instantiate the unified Zone 1 Climate thermostat entity.
    # Implements the bi-directional state machine combining heating and cooling circuits,
    # automatic cooling calendar lock bypass (Lock 1 & 2), and sentinel setpoint filtering.
    async_add_entities([SaunierGeniaZone1Climate(coordinator)])


class SaunierGeniaZone1Climate(SaunierGeniaEntity, ClimateEntity, RestoreEntity):
    """Representation of MiPro Sense Climate Zone 1 with Double-Lock and Sentinel Filtering."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_max_temp = 30.0

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Zone 1 climate entity."""
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
        ]
        self._attr_preset_modes = [
            PRESET_COMFORT,
            PRESET_MANUAL,
            PRESET_ECO,
            PRESET_BOOST,
            PRESET_AWAY,
            PRESET_VENTILATION,
        ]
        subscriptions = [
            (CIRCUIT_BASS3, "Z1RoomTemp"),
            (CIRCUIT_BASS3, "Z1RoomHumidity"),
            (CIRCUIT_BASS3, "Z1ActualRoomTempDesired"),
            (CIRCUIT_BASS3, "Z1CoolingManualTemp"),
            (CIRCUIT_BASS3, "Z1NightTemp"),
            (CIRCUIT_BASS3, "Z1ManualTemp"),
            (CIRCUIT_BASS3, "Z1QuickVetoTemp"),
            (CIRCUIT_BASS3, "Z1QuickVetoDuration"),
            (CIRCUIT_BASS3, "Z1OpMode"),
            (CIRCUIT_BASS3, "Z1OpModeCooling"),
            (CIRCUIT_BASS3, "Z1SFMode"),
            (CIRCUIT_BASS3, "Z1Status"),
            (CIRCUIT_BASS3, "Z1HeatingState"),
            (CIRCUIT_BASS3, "Z1CoolingTemp"),
            (CIRCUIT_BASS3, "Z1CoolingTempDesired"),
            (CIRCUIT_BASS3, "CoolingReleaseStatus"),
            (CIRCUIT_BASS3, "CoolingStartDate"),
            (CIRCUIT_BASS3, "CoolingEndDate"),
            (CIRCUIT_BASS3, "HolidayTemp"),
            (CIRCUIT_BASS3, "HolidayStartDate"),
            (CIRCUIT_BASS3, "HolidayStartTime"),
            (CIRCUIT_BASS3, "HolidayEndDate"),
            (CIRCUIT_BASS3, "HolidayEndTime"),
            (CIRCUIT_BASS3, "CoolingTimer_Monday"),
            (CIRCUIT_BASS3, "SystemOperatingState"),
            (CIRCUIT_BASS3, "DisplayedOutsideTemp"),
            (CIRCUIT_HMUX0, "HMUStatusCode"),
            (CIRCUIT_NETX3, "RoomTempDial"),
            (CIRCUIT_NETX3_ALT, "RoomTempDial"),
            (CIRCUIT_BROADCAST, "Outsidetemp"),
            (CIRCUIT_GLOBAL, "signal"),
            (CIRCUIT_GLOBAL, "running"),
            (CALC_CIRCUIT, "QuickVetoRemaining"),
            (CALC_CIRCUIT, "VentilationBoostRemaining"),
            (CALC_CIRCUIT, "HolidayRemaining"),
        ]

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="zone_1_climate",
            subscriptions=subscriptions,
            unique_id_suffix="climate_zone_1",
        )

        self._saved_heating_target: float = DEFAULT_COMFORT_TEMP
        self._saved_cooling_target: float = DEFAULT_COOLING_TEMP
        self._active_season: str = SEASON_HEATING
        self._pre_boost_hvac_mode: HVACMode | None = None
        self._pre_boost_preset_mode: str | None = None
        # True while a multi-step write sequence (mode/setpoint/preset) is in progress:
        # seasonal setpoint learning is paused so that intermediate optimistic states
        # are never erroneously memorized.
        self._transition_in_progress: bool = False
        self._transition_lock: asyncio.Lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Restore previous season targets across Home Assistant restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes:
            saved_heat = last_state.attributes.get("saved_heating_target")
            if saved_heat is not None:
                try:
                    self._saved_heating_target = float(saved_heat)
                except (ValueError, TypeError):
                    pass
            saved_cool = last_state.attributes.get("saved_cooling_target")
            if saved_cool is not None:
                try:
                    self._saved_cooling_target = float(saved_cool)
                except (ValueError, TypeError):
                    pass
            saved_season = last_state.attributes.get("active_season")
            if saved_season in (SEASON_HEATING, SEASON_COOLING):
                self._active_season = saved_season

        # Retained MQTT payloads may already be in the coordinator: derive state now
        self._async_refresh_derived_state()

    # -------------------------------------------------------------------------
    # Derived State (updated only on coordinator data changes, never in getters)
    # -------------------------------------------------------------------------

    def _read_modes(self) -> tuple[str, str]:
        """Return (Z1OpModeCooling, Z1OpMode) normalized to lowercase."""
        cool_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or ""
        ).lower()
        heat_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or ""
        ).lower()
        return cool_mode, heat_mode

    def _is_cooling_active(self) -> bool:
        """Return True if cooling mode is currently active."""
        return self.coordinator.is_cooling_active()

    def _is_heating_active(self) -> bool:
        """Return True if heating mode is currently active."""
        if self._is_cooling_active():
            return False
        _, heat_mode = self._read_modes()
        return heat_mode in HEATING_ACTIVE_MODES

    def _is_cooling_context(self) -> bool:
        """Return True if Zone 1 is in active cooling."""
        return self._is_cooling_active()

    @callback
    def _async_refresh_derived_state(self) -> None:
        """Update active season and seasonal setpoint memory from the latest bus data.

        - Season: cooling if cooling is active, heating if heating is active; if both
          are off, the last known season is kept (needed to restore the right setpoint
          when switching back on).
        - Setpoint memory: learns the cooling target from Z1CoolingManualTemp or Z1CoolingTempDesired
          (ignoring the 99.0 °C sentinel) and the heating target from Z1ActualRoomTempDesired or
          Z1ManualTemp (ignoring the 5.0 °C sentinel), so changes made from MiGo Link or
          MiPro Sense are kept cleanly decoupled.
        """
        if self._is_cooling_active():
            self._active_season = SEASON_COOLING
        elif self._is_heating_active():
            self._active_season = SEASON_HEATING

        if self._transition_in_progress or self.coordinator.cooling_quick_veto_active:
            return

        if self._is_cooling_active():
            manual_c = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1CoolingManualTemp", "value"
            )
            if manual_c is not None and 10.0 <= manual_c <= 30.0:
                self._saved_cooling_target = manual_c
            else:
                val = self.coordinator.get_float(
                    CIRCUIT_BASS3, "Z1CoolingTempDesired", "value"
                )
                if val is not None and val < SENTINEL_COOLING_THRESHOLD:
                    self._saved_cooling_target = val
        elif self._active_season == SEASON_HEATING:
            actual_desired = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
            )
            if (
                actual_desired is not None
                and actual_desired > SENTINEL_HEATING_THRESHOLD
            ):
                self._saved_heating_target = actual_desired
            else:
                manual_temp = self.coordinator.get_float(
                    CIRCUIT_BASS3, "Z1ManualTemp", "value"
                )
                if manual_temp is not None and manual_temp > SENTINEL_HEATING_THRESHOLD:
                    self._saved_heating_target = manual_temp

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh derived season/setpoint memory, then write the new HA state."""
        self._async_refresh_derived_state()
        if (
            not self._transition_in_progress
            and self._pre_boost_hvac_mode == HVACMode.OFF
        ):
            sf_mode = (
                self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
            ).lower()
            if sf_mode and sf_mode != "veto":
                self._pre_boost_hvac_mode = None
                self._pre_boost_preset_mode = None
                # Coordinator owns authoritative pre-veto 'off' restore & Store cleanup;
                # only fall back here when pre_veto_opmode is not already tracked there.
                if getattr(self.coordinator, "pre_veto_opmode", None) != "off":
                    self.hass.async_create_task(
                        self.coordinator.async_write_parameter(
                            CIRCUIT_BASS3, "Z1OpMode", "off"
                        )
                    )
        super()._handle_coordinator_update()

    async def _async_run_transition(
        self, sequence_factory: Callable[[], Awaitable[None]]
    ) -> None:
        """Run a multi-step eBUS write sequence serialized with setpoint learning paused."""
        async with self._transition_lock:
            self._transition_in_progress = True
            try:
                await sequence_factory()
            finally:
                self._transition_in_progress = False
                self._async_refresh_derived_state()
                self.async_write_ha_state()

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes."""
        return self._attr_hvac_modes

    @property
    def available(self) -> bool:
        """Return True if climate entity is operational on eBUS."""
        return self.coordinator.is_ebus_operational

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature allowed (15.0 °C in cooling, 5.0 °C in heating or away mode)."""
        if self.preset_mode == PRESET_AWAY:
            return 5.0
        if self._is_cooling_context():
            return 15.0
        return 5.0

    # -------------------------------------------------------------------------
    # A) Current Room Temperature
    # -------------------------------------------------------------------------

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current room temperature (Priority 1: Z1RoomTemp, Priority 2: RoomTempDial)."""
        temp = self.coordinator.get_float(CIRCUIT_BASS3, "Z1RoomTemp", "value")
        if temp is not None:
            return round(temp, 2)

        temp_dial = self.coordinator.get_float(CIRCUIT_NETX3, "RoomTempDial", "temp")
        if temp_dial is None:
            temp_dial = self.coordinator.get_float(
                CIRCUIT_NETX3_ALT, "RoomTempDial", "temp"
            )
        return round(temp_dial, 2) if temp_dial is not None else None

    @property
    def current_humidity(self) -> int | None:
        """Return the current relative room humidity (%) in Zone 1."""
        humidity = self.coordinator.get_float(CIRCUIT_BASS3, "Z1RoomHumidity", "value")
        if humidity is None or humidity <= 0.0 or humidity > 100.0:
            return None
        return round(humidity)

    # -------------------------------------------------------------------------
    # C) HVAC Mode State Machine
    # -------------------------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode combining Z1OpMode and Z1OpModeCooling."""
        if self._is_cooling_active():
            return HVACMode.COOL
        if self._is_heating_active():
            return HVACMode.HEAT
        return HVACMode.OFF

    # -------------------------------------------------------------------------
    # Preset Modes
    # -------------------------------------------------------------------------

    @property
    def preset_mode(self) -> str:
        """Return the current preset mode."""
        z1_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower()
        if z1_status == "holidayaway":
            return PRESET_AWAY

        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
        ).lower()
        if z1_status == "ventilation" or sf_mode == "ventilation":
            return PRESET_VENTILATION

        if self.coordinator.cooling_quick_veto_active:
            return PRESET_BOOST

        if sf_mode == "veto" or z1_status == "veto":
            return PRESET_BOOST

        cool_mode, heat_mode = self._read_modes()
        active_op_mode = cool_mode if self._is_cooling_active() else heat_mode
        if active_op_mode == "night":
            return PRESET_ECO
        if active_op_mode == "day":
            return PRESET_MANUAL
        return PRESET_COMFORT

    # -------------------------------------------------------------------------
    # B) Anti-Sentinel Target Temperature Filter
    # -------------------------------------------------------------------------

    @property
    def native_target_temperature(self) -> float | None:
        """Return target temperature while filtering out 99.0 °C (cooling off) and 5.0 °C (heating off) sentinels."""
        if self.hvac_mode == HVACMode.OFF:
            return None

        current_preset = self.preset_mode
        if current_preset == PRESET_AWAY:
            holiday_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "HolidayTemp", "value"
            )
            if holiday_temp is not None and holiday_temp >= 5.0:
                return round(holiday_temp, 1)
            return DEFAULT_HOLIDAY_TEMP

        if current_preset == PRESET_VENTILATION:
            return None

        if (
            self.coordinator.cooling_quick_veto_active
            and self.coordinator.cooling_quick_veto_target_temp is not None
        ):
            return self.coordinator.cooling_quick_veto_target_temp

        if self._is_cooling_active():
            val = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", "value"
            )
            if val is not None and val < SENTINEL_COOLING_THRESHOLD:
                return round(val, 1)
            if current_preset == PRESET_MANUAL:
                manual_c = self.coordinator.get_float(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", "value"
                )
                if manual_c is not None and 10.0 <= manual_c <= 30.0:
                    return round(manual_c, 1)
            if current_preset == PRESET_ECO:
                eco_c = self.coordinator.get_float(
                    CIRCUIT_BASS3, "Z1CoolingTemp", "value"
                )
                if eco_c is not None and 10.0 <= eco_c <= 30.0:
                    return round(eco_c, 1)
            if current_preset == PRESET_COMFORT:
                # Outside cooling schedule slot: idle
                return None
            return self._saved_cooling_target

        # Heating context
        if current_preset == PRESET_BOOST:
            veto_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoTemp", "value"
            )
            if veto_temp is not None and veto_temp >= 5.0:
                return round(veto_temp, 1)
            return self._saved_heating_target

        if current_preset == PRESET_MANUAL:
            manual_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1ManualTemp", "value"
            )
            if manual_temp is not None and manual_temp >= 5.0:
                return round(manual_temp, 1)
            return self._saved_heating_target

        if current_preset == PRESET_ECO:
            night_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1NightTemp", "value"
            )
            if night_temp is not None and night_temp >= 5.0:
                return round(night_temp, 1)
            return self._saved_heating_target

        # PRESET_COMFORT (Scheduled): prioritize real-time desired room temperature
        actual_desired = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
        )
        if actual_desired is not None:
            if actual_desired > SENTINEL_HEATING_THRESHOLD:
                return round(actual_desired, 1)
            # Outside scheduled slot or setback off: return None so HA displays no target during night/idle
            return None

        # Fallback if Z1ActualRoomTempDesired not available on eBUS
        manual_temp = self.coordinator.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "value")
        return (
            round(manual_temp, 1)
            if manual_temp is not None and manual_temp > SENTINEL_HEATING_THRESHOLD
            else self._saved_heating_target
        )

    # -------------------------------------------------------------------------
    # E) Real-Time HVAC Action
    # -------------------------------------------------------------------------

    @property
    def hvac_action(self) -> HVACAction:
        """Return current real-time HVAC operational action."""
        hmu_status = (
            self.coordinator.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status") or ""
        ).lower()
        sys_state = (
            self.coordinator.get_str(CIRCUIT_BASS3, "SystemOperatingState", "value")
            or ""
        ).lower()

        if hmu_status in ("deicing", "deicing_active"):
            return HVACAction.PREHEATING

        if sys_state == "heating" or hmu_status in (
            "heat_compressor_active",
            "heat_immersion_active",
            "heat_immersion_heater_active",
        ):
            return HVACAction.HEATING

        if sys_state == "cooling" or hmu_status == "cool_compressor_active":
            return HVACAction.COOLING

        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extended diagnostic attributes for Zone 1 climate."""
        hmu_status = (
            self.coordinator.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status") or ""
        ).lower()
        cooling_release = self.coordinator.get_str(
            CIRCUIT_BASS3, "CoolingReleaseStatus", "value"
        )
        z1_demand = self.coordinator.get_str(CIRCUIT_BASS3, "Z1HeatingState", "value")
        raw_cooling_desired = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1CoolingTempDesired", "value"
        )
        raw_cooling_manual = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1CoolingManualTemp", "value"
        )
        raw_heating_desired = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
        )
        raw_heating_manual = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1ManualTemp", "value"
        )

        cooling_veto_end = (
            self.coordinator._cooling_veto_end_time.isoformat()
            if self.coordinator._cooling_veto_end_time is not None
            else None
        )
        veto_attrs = self.coordinator.get_quick_veto_remaining_attributes()
        vent_attrs = self.coordinator.get_ventilation_remaining_attributes()
        holiday_attrs = self.coordinator.get_holiday_remaining_attributes()
        veto_rem_min = (
            veto_attrs.get("remaining_minutes") if veto_attrs.get("is_active") else None
        )
        vent_rem_min = (
            vent_attrs.get("remaining_minutes") if vent_attrs.get("is_active") else None
        )
        holiday_rem_days = (
            holiday_attrs.get("days_remaining")
            if holiday_attrs.get("is_active")
            else None
        )

        active_preset = self.preset_mode
        active_preset_remaining: str | None = None
        if active_preset == PRESET_BOOST:
            active_preset_remaining = veto_attrs.get("remaining_formatted")
        elif active_preset == PRESET_VENTILATION:
            active_preset_remaining = vent_attrs.get("remaining_formatted")
        elif active_preset == PRESET_AWAY and holiday_attrs.get("is_active"):
            active_preset_remaining = holiday_attrs.get("remaining_formatted")

        return {
            "active_season": self._active_season,
            "active_preset_remaining": active_preset_remaining,
            "saved_heating_target": self._saved_heating_target,
            "saved_cooling_target": self._saved_cooling_target,
            "defrost_active": hmu_status in ("deicing", "deicing_active"),
            "cooling_lock_released": cooling_release == "on",
            "z1_heating_demand": z1_demand == "on",
            "cooling_quick_veto_active": self.coordinator.cooling_quick_veto_active,
            "cooling_quick_veto_remaining_minutes": self.coordinator.cooling_quick_veto_remaining_minutes,
            "cooling_quick_veto_end_time": cooling_veto_end,
            "quick_veto_remaining_minutes": veto_rem_min,
            "quick_veto_remaining_formatted": veto_attrs.get("remaining_formatted"),
            "quick_veto_end_time": veto_attrs.get("end_time"),
            "ventilation_remaining_minutes": vent_rem_min,
            "ventilation_remaining_formatted": vent_attrs.get("remaining_formatted"),
            "ventilation_end_time": vent_attrs.get("end_time"),
            "holiday_remaining_days": holiday_rem_days,
            "holiday_remaining_hours": holiday_attrs.get("remaining_hours"),
            "holiday_remaining_minutes": holiday_attrs.get("remaining_minutes"),
            "holiday_remaining_formatted": holiday_attrs.get("remaining_formatted"),
            "holiday_start_date": holiday_attrs.get("start_date"),
            "holiday_start_time": holiday_attrs.get("start_time"),
            "holiday_end_date": holiday_attrs.get("end_date"),
            "holiday_end_time": holiday_attrs.get("end_time"),
            "raw_z1_actual_room_temp_desired": raw_heating_desired,
            "raw_z1_cooling_temp_desired": raw_cooling_desired,
            "raw_z1_cooling_manual_temp": raw_cooling_manual,
            "raw_z1_manual_temp": raw_heating_manual,
        }

    # -------------------------------------------------------------------------
    # Commands: Set HVAC Mode, Temperature, Preset
    # -------------------------------------------------------------------------

    def _is_cooling_lock_currently_open(self) -> bool:
        """Return True if Cooling Lock 1 holds an active window covering today (or open-ended 99)."""
        end_msg = self.coordinator.get_message(CIRCUIT_BASS3, "CoolingEndDate")
        if not isinstance(end_msg, dict):
            return False
        end_year = end_msg.get("year")
        if not isinstance(end_year, int) or end_year == 19:
            return False
        if end_year == 99:
            return True
        end_month = end_msg.get("month")
        end_day = end_msg.get("day")
        if not isinstance(end_month, int) or not isinstance(end_day, int):
            return False
        try:
            end_dt = date(2000 + end_year, end_month, end_day)
        except ValueError:
            return False

        today = date.today()
        if end_dt < today:
            return False

        start_msg = self.coordinator.get_message(CIRCUIT_BASS3, "CoolingStartDate")
        if isinstance(start_msg, dict):
            sy = start_msg.get("year")
            sm = start_msg.get("month")
            sd = start_msg.get("day")
            if isinstance(sy, int) and isinstance(sm, int) and isinstance(sd, int):
                try:
                    if date(2000 + sy, sm, sd) > today:
                        return False
                except ValueError:
                    return False
        return True

    async def _async_ensure_cooling_lock_open(self) -> None:
        """Open Lock 1 (custom period if pre-set or 01;01;26 to 01;01;99: indefinite) if auto bypass enabled."""
        if not self.coordinator.auto_cooling_lock_bypass:
            return

        # If already open with active custom dates or open-ended 99, do not overwrite!
        if self._is_cooling_lock_currently_open():
            return

        start_date = self.coordinator.custom_cooling_start_date or "01;01;26"
        end_date = self.coordinator.custom_cooling_end_date or "01;01;99"

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", start_date
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", end_date
        )
        await asyncio.sleep(0.5)

    async def _async_ensure_cooling_lock_closed(self) -> None:
        """Close Lock 1 (CoolingStartDate=01;01;19, CoolingEndDate=01;01;19) to lock cooling out during winter/off."""
        if not self.coordinator.auto_cooling_lock_bypass:
            return

        # Avoid redundant writes if already closed
        start_year = self.coordinator.get_int(CIRCUIT_BASS3, "CoolingStartDate", "year")
        end_year = self.coordinator.get_int(CIRCUIT_BASS3, "CoolingEndDate", "year")
        if start_year == 19 and end_year == 19:
            return

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", "01;01;19"
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", "01;01;19"
        )
        await asyncio.sleep(0.5)

    def _is_ventilation_active(self) -> bool:
        """Return True if intensive ventilation boost is currently active."""
        z1_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower()
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
        ).lower()
        return z1_status == "ventilation" or sf_mode == "ventilation"

    async def _async_clear_ventilation_if_active(self) -> None:
        """Cancel active intensive ventilation boost before changing mode or preset."""
        if self._is_ventilation_active():
            await self.coordinator.async_cancel_ventilation_boost()
            await asyncio.sleep(0.5)

    def _is_heating_veto_active(self) -> bool:
        """Return True if a heating quick veto is active on bus state or coordinator."""
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
        ).lower()
        z1_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower()
        return (
            sf_mode == "veto"
            or z1_status == "veto"
            or getattr(self.coordinator, "_heating_veto_end_time", None) is not None
        )

    async def _async_clear_active_vetos(
        self,
        *,
        restore_heating_opmode: bool,
        restore_cooling_opmode: bool,
        restore_cooling_temp: bool,
    ) -> bool:
        """Cancel any active cooling or heating quick veto and reset boost memory."""
        was_cooling_veto = self.coordinator.cooling_quick_veto_active
        if was_cooling_veto:
            await self.coordinator.async_cancel_cooling_quick_veto(
                restore=restore_cooling_opmode,
                restore_temp=restore_cooling_temp,
            )

        if self._is_heating_veto_active():
            await self.coordinator.async_cancel_quick_veto(
                restore_opmode=restore_heating_opmode
            )
            await asyncio.sleep(0.3)

        self._pre_boost_hvac_mode = None
        self._pre_boost_preset_mode = None
        return was_cooling_veto

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target HVAC mode with transparent Double-Lock and seasonal setpoint memory."""
        await self._async_run_transition(lambda: self._async_apply_hvac_mode(hvac_mode))

    async def _async_apply_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Write the eBUS sequence for a new HVAC mode (runs with learning paused).

        Note: Multi-step write sequences use 0.3s-0.5s pacing to allow the 2400-baud physical eBUS
        sufficient time to arbitrate collisions and let the MiPro Sense controller process state transitions.
        """
        if hvac_mode == HVACMode.OFF:
            await self._async_clear_ventilation_if_active()
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", "off"
            )
            await asyncio.sleep(0.5)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling", "off"
            )
            await asyncio.sleep(0.5)
            # Automatic Lock 1 closure when turning off
            await self._async_ensure_cooling_lock_closed()

            # Clear any active quick veto (Z1OpMode is already forced to 'off')
            await self._async_clear_active_vetos(
                restore_heating_opmode=False,
                restore_cooling_opmode=False,
                restore_cooling_temp=False,
            )
            return

        if hvac_mode == HVACMode.HEAT:
            # Never carry active/stale vetos, ventilation, or holidayaway accidentally into HEAT
            await self._async_clear_ventilation_if_active()
            await self._async_clear_active_vetos(
                restore_heating_opmode=False,
                restore_cooling_opmode=False,
                restore_cooling_temp=True,
            )
            z1_status = (
                self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
            ).lower()
            if z1_status == "holidayaway":
                await self.coordinator.async_cancel_holiday_mode()
                await asyncio.sleep(0.5)

            # Capture preset before turning off cooling so MANUAL/ECO survives COOL -> HEAT
            desired_preset = self.preset_mode

            self._active_season = SEASON_HEATING
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling", "off"
            )
            await asyncio.sleep(0.5)
            # Ensure cooling calendar is locked out during heating season
            await self._async_ensure_cooling_lock_closed()

            target_opmode = (
                "day"
                if desired_preset == PRESET_MANUAL
                else ("night" if desired_preset == PRESET_ECO else "auto")
            )
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", target_opmode
            )

            if desired_preset == PRESET_MANUAL:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1ManualTemp", self._saved_heating_target
                )
            return

        if hvac_mode == HVACMode.COOL:
            z1_status = (
                self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
            ).lower()
            if z1_status == "holidayaway":
                raise HomeAssistantError(
                    "Cannot activate cooling while Holiday / Away mode is active."
                )

            # Clear any active ventilation or quick veto before switching into COOL
            await self._async_clear_ventilation_if_active()
            await self._async_clear_active_vetos(
                restore_heating_opmode=False,
                restore_cooling_opmode=False,
                restore_cooling_temp=True,
            )

            # Capture preset before turning off heating so MANUAL/ECO survives HEAT -> COOL
            desired_preset = self.preset_mode

            self._active_season = SEASON_COOLING
            # 1. Turn off heating
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", "off"
            )
            await asyncio.sleep(0.5)
            # 2. Open Lock 1 automatically (01;01;26 to 01;01;99)
            await self._async_ensure_cooling_lock_open()
            # 3. Set cooling mode (preserving preset or default to auto)
            target_opmode = (
                "day"
                if desired_preset == PRESET_MANUAL
                else ("night" if desired_preset == PRESET_ECO else "auto")
            )
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling", target_opmode
            )

            # 4. Auto-restore saved cooling setpoint to Z1CoolingManualTemp and Z1CoolingTempDesired
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1CoolingManualTemp", self._saved_cooling_target
            )
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", self._saved_cooling_target
            )
            return

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature according to active mode and preset, updating seasonal memory."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temp_val = round(float(temperature) * 2.0) / 2.0
        await self._async_run_transition(
            lambda: self._async_apply_temperature(temp_val)
        )

    async def _async_apply_temperature(self, temp_val: float) -> None:
        """Write the eBUS sequence for a new target temperature (runs with learning paused)."""
        if self.preset_mode == PRESET_VENTILATION:
            raise HomeAssistantError(
                "Cannot change target temperature while intensive ventilation boost is active."
            )

        if self.preset_mode == PRESET_AWAY:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "HolidayTemp", temp_val
            )
            return

        if self._is_cooling_active():
            if self.coordinator.cooling_quick_veto_active:
                await self.coordinator.async_update_cooling_quick_veto_temperature(
                    temp_val
                )
                return

            cool_mode, _ = self._read_modes()
            if cool_mode == "auto":
                if self._pre_boost_hvac_mode is None:
                    self._pre_boost_hvac_mode = self.hvac_mode
                    self._pre_boost_preset_mode = PRESET_COMFORT
                await self.coordinator.async_set_cooling_quick_veto(
                    temperature=temp_val
                )
                return

            self._saved_cooling_target = temp_val
            target_cooling_msg = (
                "Z1CoolingTemp"
                if self.preset_mode == PRESET_ECO
                else "Z1CoolingManualTemp"
            )
            # In cooling, write to target cooling register and Z1CoolingTempDesired cleanly decoupled from heating
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, target_cooling_msg, temp_val
            )
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", temp_val
            )
            return

        if self.preset_mode == PRESET_BOOST:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1QuickVetoTemp", temp_val
            )
            duration = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoDuration", "value"
            )
            if not duration or duration <= 0:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0
                )
            return

        if self.preset_mode == PRESET_COMFORT and not self._is_cooling_active():
            # In scheduled heating, adjusting target temperature triggers Quick Veto
            # for that exact target temperature (just like the physical thermostat and official app).
            if self._pre_boost_hvac_mode is None:
                self._pre_boost_hvac_mode = self.hvac_mode
                self._pre_boost_preset_mode = PRESET_COMFORT

            await self.coordinator.async_set_quick_veto(temperature=temp_val)
            return

        if self.preset_mode == PRESET_ECO:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1NightTemp", temp_val
            )
            return

        # Heating manual / comfort: update saved heating target and write to Z1ManualTemp
        self._saved_heating_target = temp_val
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "Z1ManualTemp", temp_val
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode (comfort, manual, eco, boost, away, ventilation)."""
        await self._async_run_transition(
            lambda: self._async_apply_preset_mode(preset_mode)
        )

    async def _async_apply_preset_mode(self, preset_mode: str) -> None:
        """Write the eBUS sequence for a new preset (runs with learning paused)."""
        current_z1_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower()

        # If currently in holiday mode and switching to another preset, cancel holiday mode
        if current_z1_status == "holidayaway" and preset_mode != PRESET_AWAY:
            await self.coordinator.async_cancel_holiday_mode()
            await asyncio.sleep(0.5)

        if preset_mode == PRESET_VENTILATION:
            await self._async_clear_active_vetos(
                restore_heating_opmode=True,
                restore_cooling_opmode=False,
                restore_cooling_temp=True,
            )
            await self.coordinator.async_activate_ventilation_boost()
            return

        # Cancel active intensive ventilation before applying any other preset
        await self._async_clear_ventilation_if_active()

        if preset_mode == PRESET_AWAY:
            await self._async_clear_active_vetos(
                restore_heating_opmode=True,
                restore_cooling_opmode=False,
                restore_cooling_temp=True,
            )
            await self.coordinator.async_activate_holiday_mode()
            return

        if preset_mode == PRESET_BOOST:
            current_preset = self.preset_mode
            if current_preset == PRESET_BOOST:
                return
            self._pre_boost_hvac_mode = self.hvac_mode
            self._pre_boost_preset_mode = current_preset

            if self.hvac_mode == HVACMode.OFF:
                await self.coordinator.async_set_quick_veto()
            elif self._is_cooling_active():
                await self.coordinator.async_set_cooling_quick_veto()
            else:
                await self.coordinator.async_set_quick_veto()
            return

        # Clear any active quick veto before applying the new preset
        # (never bounce Z1OpMode through 'off' since the target opmode is written below)
        pre_cool_temp = getattr(self.coordinator, "pre_cooling_veto_temp", None)
        was_cooling_veto = await self._async_clear_active_vetos(
            restore_heating_opmode=False,
            restore_cooling_opmode=False,
            restore_cooling_temp=True,
        )

        in_cooling = self._is_cooling_active()

        if preset_mode == PRESET_ECO:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling" if in_cooling else "Z1OpMode", "night"
            )
        elif preset_mode == PRESET_MANUAL:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling" if in_cooling else "Z1OpMode", "day"
            )
            if in_cooling and was_cooling_veto:
                restore_desired = (
                    pre_cool_temp
                    if pre_cool_temp is not None
                    else self._saved_cooling_target
                )
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingTempDesired", restore_desired
                )
        elif preset_mode == PRESET_COMFORT:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling" if in_cooling else "Z1OpMode", "auto"
            )

    async def async_turn_on(self) -> None:
        """Turn the climate entity on (restores previous active season, defaulting to HEAT)."""
        target_mode = (
            HVACMode.COOL if self._active_season == SEASON_COOLING else HVACMode.HEAT
        )
        await self.async_set_hvac_mode(target_mode)

    async def async_turn_off(self) -> None:
        """Turn the climate entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)


# Backward compatibility for HA versions older than 2026.11
if not hasattr(ClimateEntity, "native_current_temperature"):
    SaunierGeniaZone1Climate.current_temperature = property(  # type: ignore[attr-defined]
        lambda self: self.native_current_temperature
    )
    SaunierGeniaZone1Climate.target_temperature = property(  # type: ignore[attr-defined]
        lambda self: self.native_target_temperature
    )
    SaunierGeniaZone1Climate._attr_temperature_unit = UnitOfTemperature.CELSIUS  # type: ignore[attr-defined]
