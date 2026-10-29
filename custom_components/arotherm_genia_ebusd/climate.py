"""Climate platform for Saunier Duval MiPro Sense Zone 1 (Double-Lock + Anti-Sentinel)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_COOLING_TEMP,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
    SENTINEL_COOLING_THRESHOLD,
    SENTINEL_HEATING_THRESHOLD,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity

PRESET_COMFORT = "comfort"
PRESET_MANUAL = "manual"
PRESET_ECO = "eco"
PRESET_BOOST = "boost"

SEASON_HEATING = "heating"
SEASON_COOLING = "cooling"

# Z1OpModeCooling / Z1OpMode values that mean the season circuit is enabled
COOLING_ACTIVE_MODES: frozenset[str] = frozenset({"auto", "day"})
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

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
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
            HVACMode.AUTO,
        ]
        self._attr_preset_modes = [
            PRESET_COMFORT,
            PRESET_MANUAL,
            PRESET_ECO,
            PRESET_BOOST,
        ]
        subscriptions = [
            (CIRCUIT_BASS3, "Z1RoomTemp"),
            (CIRCUIT_BASS3, "Z1ActualRoomTempDesired"),
            (CIRCUIT_BASS3, "Z1DayTemp"),
            (CIRCUIT_BASS3, "Z1NightTemp"),
            (CIRCUIT_BASS3, "Z1ManualTemp"),
            (CIRCUIT_BASS3, "Z1QuickVetoTemp"),
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
            (CIRCUIT_BASS3, "CoolingTimer_Monday"),
            (CIRCUIT_BASS3, "SystemOperatingState"),
            (CIRCUIT_BASS3, "DisplayedOutsideTemp"),
            (CIRCUIT_HMUX0, "HMUStatusCode"),
            (CIRCUIT_NETX3, "RoomTempDial"),
            (CIRCUIT_NETX3_ALT, "RoomTempDial"),
            (CIRCUIT_BROADCAST, "Outsidetemp"),
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
        # True while a multi-step write sequence (mode/setpoint/preset) is in progress:
        # seasonal setpoint learning is paused so that intermediate optimistic states
        # (e.g. Z1DayTemp still holding the previous season value) are never memorized.
        self._transition_in_progress: bool = False

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

    def _is_cooling_context(self) -> bool:
        """Return True if Zone 1 is in cooling (COOL, or AUTO with cooling season)."""
        cool_mode, _ = self._read_modes()
        return cool_mode in COOLING_ACTIVE_MODES

    @callback
    def _async_refresh_derived_state(self) -> None:
        """Update active season and seasonal setpoint memory from the latest bus data.

        - Season: cooling if Z1OpModeCooling is auto/day, heating if Z1OpMode is
          auto/day/night; if both are off, the last known season is kept (needed to
          restore the right setpoint when switching back on).
        - Setpoint memory: learns the cooling target from Z1CoolingTempDesired (ignoring
          the 99.0 °C sentinel) and the heating target from Z1DayTemp (ignoring the
          5.0 °C sentinel), so changes made from MiGo Link or MiPro Sense are kept.
        """
        cool_mode, heat_mode = self._read_modes()
        if cool_mode in COOLING_ACTIVE_MODES:
            self._active_season = SEASON_COOLING
        elif heat_mode in HEATING_ACTIVE_MODES:
            self._active_season = SEASON_HEATING

        if self._transition_in_progress:
            return

        if cool_mode in COOLING_ACTIVE_MODES:
            val = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", "value"
            )
            if val is not None and val < SENTINEL_COOLING_THRESHOLD:
                self._saved_cooling_target = val
        elif self._active_season == SEASON_HEATING:
            day_temp = self.coordinator.get_float(CIRCUIT_BASS3, "Z1DayTemp", "value")
            if day_temp is not None and day_temp > SENTINEL_HEATING_THRESHOLD:
                self._saved_heating_target = day_temp

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh derived season/setpoint memory, then write the new HA state."""
        self._async_refresh_derived_state()
        super()._handle_coordinator_update()

    async def _async_run_transition(self, sequence: Awaitable[None]) -> None:
        """Run a multi-step eBUS write sequence with setpoint learning paused."""
        self._transition_in_progress = True
        try:
            await sequence
        finally:
            self._transition_in_progress = False
            self._async_refresh_derived_state()
            self.async_write_ha_state()

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature allowed (15.0 °C in cooling as supported by MiGo Link, 5.0 °C in heating)."""
        if self._is_cooling_context():
            return 15.0
        return 5.0

    # -------------------------------------------------------------------------
    # A) Current Room Temperature
    # -------------------------------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
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

    # -------------------------------------------------------------------------
    # C) HVAC Mode State Machine
    # -------------------------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode combining Z1OpMode and Z1OpModeCooling."""
        cool_mode, heat_mode = self._read_modes()

        if cool_mode in COOLING_ACTIVE_MODES:
            return HVACMode.AUTO if cool_mode == "auto" else HVACMode.COOL

        if heat_mode in HEATING_ACTIVE_MODES:
            return HVACMode.AUTO if heat_mode == "auto" else HVACMode.HEAT

        return HVACMode.OFF

    # -------------------------------------------------------------------------
    # Preset Modes
    # -------------------------------------------------------------------------

    @property
    def preset_mode(self) -> str:
        """Return the current preset mode."""
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
        ).lower()
        z1_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1Status", "value") or ""
        ).lower()
        if sf_mode == "veto" or z1_status == "veto":
            return PRESET_BOOST

        cool_mode, heat_mode = self._read_modes()
        if heat_mode == "night":
            return PRESET_ECO
        if heat_mode == "day" or cool_mode == "day":
            return PRESET_MANUAL
        return PRESET_COMFORT

    # -------------------------------------------------------------------------
    # B) Anti-Sentinel Target Temperature Filter
    # -------------------------------------------------------------------------

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature while filtering out 99.0 °C (cooling off) and 5.0 °C (heating off) sentinels."""
        if self._is_cooling_context():
            val = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", "value"
            )
            if val is not None and val < SENTINEL_COOLING_THRESHOLD:
                return val
            return self._saved_cooling_target

        # Heating / Auto (heating) / Off context
        current_preset = self.preset_mode
        day_temp = (
            self.coordinator.get_float(CIRCUIT_BASS3, "Z1DayTemp", "value")
            or self._saved_heating_target
        )

        if current_preset == PRESET_BOOST:
            veto_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoTemp", "value"
            )
            if veto_temp is not None and veto_temp > 5.0:
                return veto_temp
            return day_temp

        if current_preset == PRESET_MANUAL:
            manual_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1ManualTemp", "value"
            )
            if manual_temp is not None and manual_temp > 5.0:
                return manual_temp
            return day_temp

        if current_preset == PRESET_ECO:
            night_temp = self.coordinator.get_float(
                CIRCUIT_BASS3, "Z1NightTemp", "value"
            )
            if night_temp is not None and night_temp > 5.0:
                return night_temp
            return day_temp

        # PRESET_COMFORT (Scheduled) or fallback: return heating target
        return (
            day_temp
            if day_temp > SENTINEL_HEATING_THRESHOLD
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
        raw_heating_desired = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
        )

        return {
            "active_season": self._active_season,
            "saved_heating_target": self._saved_heating_target,
            "saved_cooling_target": self._saved_cooling_target,
            "defrost_active": hmu_status in ("deicing", "deicing_active"),
            "cooling_lock_released": cooling_release == "on",
            "z1_heating_demand": z1_demand == "on",
            "raw_z1_actual_room_temp_desired": raw_heating_desired,
            "raw_z1_cooling_temp_desired": raw_cooling_desired,
        }

    # -------------------------------------------------------------------------
    # Commands: Set HVAC Mode, Temperature, Preset
    # -------------------------------------------------------------------------

    async def _async_ensure_cooling_lock_open(self) -> None:
        """Open Lock 1 (CoolingStartDate=01;01;26, CoolingEndDate=01;01;99: indefinite) if auto bypass enabled."""
        if not self.coordinator.auto_cooling_lock_bypass:
            return

        # Avoid redundant writes if already open
        start_year = self.coordinator.get_int(CIRCUIT_BASS3, "CoolingStartDate", "year")
        end_year = self.coordinator.get_int(CIRCUIT_BASS3, "CoolingEndDate", "year")
        if start_year == 26 and end_year == 99:
            return

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", "01;01;26"
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", "01;01;99"
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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target HVAC mode with transparent Double-Lock and seasonal setpoint memory."""
        await self._async_run_transition(self._async_apply_hvac_mode(hvac_mode))

    async def _async_apply_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Write the eBUS sequence for a new HVAC mode (runs with learning paused).

        Note: Multi-step write sequences use 0.3s-0.5s pacing to allow the 2400-baud physical eBUS
        sufficient time to arbitrate collisions and let the MiPro Sense controller process state transitions.
        """
        current_day_temp = self.coordinator.get_float(
            CIRCUIT_BASS3, "Z1DayTemp", "value"
        )
        previous_season = self._active_season
        day_temp_valid = (
            current_day_temp is not None and 10.0 <= current_day_temp <= 30.0
        )

        if hvac_mode == HVACMode.OFF:
            # Save active season target before shutting down
            if previous_season == SEASON_COOLING and day_temp_valid:
                self._saved_cooling_target = current_day_temp
            elif previous_season == SEASON_HEATING and day_temp_valid:
                self._saved_heating_target = current_day_temp

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

            # If switching off from cooling, restore heating setpoint to baseline Z1DayTemp
            if previous_season == SEASON_COOLING:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1DayTemp", self._saved_heating_target
                )
            return

        if hvac_mode == HVACMode.HEAT:
            # If transitioning from cooling, remember cooling setpoint
            if previous_season == SEASON_COOLING and day_temp_valid:
                self._saved_cooling_target = current_day_temp
            heating_target = self._saved_heating_target

            self._active_season = SEASON_HEATING
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling", "off"
            )
            await asyncio.sleep(0.5)
            # Ensure cooling calendar is locked out during heating season
            await self._async_ensure_cooling_lock_closed()
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", "day"
            )

            # Auto-restore saved heating setpoint to Z1DayTemp
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1DayTemp", heating_target
            )
            if self.preset_mode == PRESET_MANUAL:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1ManualTemp", heating_target
                )
            return

        if hvac_mode == HVACMode.COOL:
            # If transitioning from heating, remember heating setpoint
            if previous_season == SEASON_HEATING and day_temp_valid:
                self._saved_heating_target = current_day_temp
            cooling_target = self._saved_cooling_target

            self._active_season = SEASON_COOLING
            # 1. Turn off heating
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", "off"
            )
            await asyncio.sleep(0.5)
            # 2. Open Lock 1 automatically (01;01;26 to 01;01;99)
            await self._async_ensure_cooling_lock_open()
            # 3. Open Lock 2 (manual cooling day mode)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling", "day"
            )

            # 4. Auto-restore saved cooling setpoint to Z1DayTemp and Z1CoolingTempDesired
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1DayTemp", cooling_target
            )
            if self.preset_mode == PRESET_MANUAL:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1ManualTemp", cooling_target
                )
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1CoolingTempDesired", cooling_target
            )
            return

        if hvac_mode == HVACMode.AUTO:
            outside_temp = self.coordinator.get_float(
                CIRCUIT_BROADCAST, "Outsidetemp", "temp"
            )
            if outside_temp is None:
                outside_temp = self.coordinator.get_float(
                    CIRCUIT_BASS3, "DisplayedOutsideTemp", "value"
                )

            use_heating = (
                outside_temp is None
                or outside_temp < 20.0
                or previous_season != SEASON_COOLING
            )
            if use_heating:
                if previous_season == SEASON_COOLING and day_temp_valid:
                    self._saved_cooling_target = current_day_temp
                heating_target = self._saved_heating_target

                self._active_season = SEASON_HEATING
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpModeCooling", "off"
                )
                await asyncio.sleep(0.5)
                await self._async_ensure_cooling_lock_closed()
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpMode", "auto"
                )
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1DayTemp", heating_target
                )
            else:
                if previous_season == SEASON_HEATING and day_temp_valid:
                    self._saved_heating_target = current_day_temp
                cooling_target = self._saved_cooling_target

                self._active_season = SEASON_COOLING
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpMode", "off"
                )
                await asyncio.sleep(0.5)
                await self._async_ensure_cooling_lock_open()
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpModeCooling", "auto"
                )
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1DayTemp", cooling_target
                )
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingTempDesired", cooling_target
                )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature according to active mode and preset, updating seasonal memory."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temp_val = round(float(temperature) * 2.0) / 2.0
        await self._async_run_transition(self._async_apply_temperature(temp_val))

    async def _async_apply_temperature(self, temp_val: float) -> None:
        """Write the eBUS sequence for a new target temperature (runs with learning paused)."""
        cool_mode, heat_mode = self._read_modes()
        if self.hvac_mode == HVACMode.COOL or (cool_mode or "off") != "off":
            self._saved_cooling_target = temp_val
            # In cooling, MiGo Link writes Z1DayTemp as the active comfort setpoint.
            # Writing Z1DayTemp (and Z1ManualTemp if manual) ensures BASS3 recalculates
            # Z1CoolingTempDesired without bouncing, leaving Z1CoolingTemp intact at 30°C.
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1DayTemp", temp_val
            )
            if self.preset_mode == PRESET_MANUAL:
                await asyncio.sleep(0.3)
                await self.coordinator.async_write_parameter(
                    CIRCUIT_BASS3, "Z1ManualTemp", temp_val
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
            return

        if self.preset_mode == PRESET_ECO:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1NightTemp", temp_val
            )
            return

        # Heating comfort / manual: update saved heating target
        self._saved_heating_target = temp_val
        if (heat_mode or "off") == "day" or self.preset_mode == PRESET_MANUAL:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1ManualTemp", temp_val
            )
            await asyncio.sleep(0.3)

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "Z1DayTemp", temp_val
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode (comfort, manual, eco, boost)."""
        await self._async_run_transition(self._async_apply_preset_mode(preset_mode))

    async def _async_apply_preset_mode(self, preset_mode: str) -> None:
        """Write the eBUS sequence for a new preset (runs with learning paused)."""
        if preset_mode == PRESET_BOOST:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1SFMode", "veto"
            )
            return

        # Clear quick veto if active
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "Z1SFMode", "value") or ""
        ).lower()
        if sf_mode == "veto":
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1SFMode", "auto"
            )
            await asyncio.sleep(0.5)

        in_cooling = (
            self.hvac_mode == HVACMode.COOL or self._active_season == SEASON_COOLING
        )

        if preset_mode == PRESET_ECO:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpMode", "night"
            )
        elif preset_mode == PRESET_MANUAL:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling" if in_cooling else "Z1OpMode", "day"
            )
        elif preset_mode == PRESET_COMFORT:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1OpModeCooling" if in_cooling else "Z1OpMode", "auto"
            )

    async def async_turn_on(self) -> None:
        """Turn the climate entity on (restores AUTO mode)."""
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        """Turn the climate entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
