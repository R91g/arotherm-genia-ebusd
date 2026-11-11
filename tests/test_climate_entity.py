"""Unit tests for climate entity season handling and preset modes."""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.components.climate import HVACMode

from custom_components.arotherm_genia_ebusd.climate import (
    COOLING_ACTIVE_MODES,
    HEATING_ACTIVE_MODES,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_MANUAL,
    SEASON_COOLING,
    SEASON_HEATING,
    SaunierGeniaZone1Climate,
)
from custom_components.arotherm_genia_ebusd.const import (
    CIRCUIT_BASS3,
)


class MockCoordinatorForClimate:
    """Mock coordinator for Climate entity tests."""

    def __init__(self) -> None:
        self.entry = MagicMock(entry_id="test_entry_id", options={})
        self._state: dict[tuple[str, str], dict[str, Any]] = {}
        self.writes: list[tuple[str, str, Any]] = []
        self.manufacturer = "Saunier Duval"
        self.outdoor_model = "GeniaAir Max ES 15"
        self.indoor_model = "HPIM 7 230V"
        self.has_wireless_room_unit = True
        self.auto_cooling_lock_bypass = True
        self.custom_cooling_start_date: str | None = None
        self.custom_cooling_end_date: str | None = None
        self.cooling_quick_veto_boost_delta = 2.0
        self.cooling_quick_veto_active = False
        self.cooling_quick_veto_target_temp: float | None = None
        self.cooling_quick_veto_remaining_minutes: int | None = None
        self._cooling_veto_end_time: datetime | None = None
        self._pre_cooling_veto_opmode: str | None = None
        self._pre_cooling_veto_temp: float | None = None

    @property
    def is_ebus_operational(self) -> bool:
        if not self._state:
            return False
        for circuit_msg in ("signal", "running"):
            val = self.get_str("global", circuit_msg)
            if val is not None and val.lower() in ("false", "0", "no", "off"):
                return False
        return True

    def get_message(self, circuit: str, message: str) -> dict[str, Any] | None:
        return self._state.get((circuit.lower(), message.lower()))

    def get_str(self, circuit: str, message: str, field: str = "value") -> str | None:
        msg = self.get_message(circuit, message)
        return str(msg.get(field)) if msg and field in msg else None

    def get_float(
        self, circuit: str, message: str, field: str = "value"
    ) -> float | None:
        msg = self.get_message(circuit, message)
        if msg and field in msg:
            try:
                return float(msg[field])
            except (ValueError, TypeError):
                return None
        return None

    def get_int(self, circuit: str, message: str, field: str = "value") -> int | None:
        msg = self.get_message(circuit, message)
        if msg and field in msg:
            try:
                return int(msg[field])
            except (ValueError, TypeError):
                return None
        return None

    async def async_write_parameter(
        self, circuit: str, message: str, value: Any
    ) -> None:
        self.writes.append((circuit, message, value))
        self._state[(circuit.lower(), message.lower())] = {"value": value}

    async def async_set_quick_veto(
        self,
        temperature: float | None = None,
        duration: float | None = None,
    ) -> None:
        current_opmode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "auto"
        ).lower()
        if current_opmode == "off":
            self._pre_veto_opmode = "off"
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "auto")
        elif getattr(self, "_pre_veto_opmode", None) is None:
            self._pre_veto_opmode = current_opmode

        if temperature is not None:
            target_temp = round(float(temperature), 1)
        else:
            current_target = self.get_float(
                CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value"
            )
            manual_temp = self.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "value")
            if (
                current_target is not None
                and current_target > 5.5
                and getattr(self, "_pre_veto_opmode", None) != "off"
            ):
                target_temp = round(current_target + 3.0, 1)
            elif manual_temp is not None and manual_temp > 5.0:
                target_temp = round(manual_temp, 1)
            else:
                target_temp = 22.0

        target_temp = max(10.0, min(30.0, target_temp))

        if duration is not None:
            dur_val = round(float(duration), 1)
        else:
            configured_dur = self.get_float(
                CIRCUIT_BASS3, "Z1QuickVetoDuration", "value"
            )
            dur_val = configured_dur if configured_dur and configured_dur > 0 else 3.0

        dur_val = max(0.5, min(12.0, dur_val))

        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoTemp", target_temp)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", dur_val)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "veto")

    async def async_cancel_quick_veto(self) -> None:
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "auto")
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0)
        if getattr(self, "_pre_veto_opmode", None) == "off":
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
        self._pre_veto_opmode = None

    def is_cooling_active(self) -> bool:
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
        current_opmode = (
            self.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value") or "auto"
        ).lower()
        if self._pre_cooling_veto_opmode is None:
            self._pre_cooling_veto_opmode = current_opmode

        manual_temp = self.get_float(CIRCUIT_BASS3, "Z1CoolingManualTemp", "value")
        desired_temp = self.get_float(CIRCUIT_BASS3, "Z1CoolingTempDesired", "value")

        if desired_temp is not None and desired_temp < 40.0:
            current_target = desired_temp
        elif manual_temp is not None and 10.0 <= manual_temp <= 30.0:
            current_target = manual_temp
        else:
            current_target = 23.0

        if self._pre_cooling_veto_temp is None:
            self._pre_cooling_veto_temp = current_target

        if temperature is not None:
            target_temp = round(float(temperature), 1)
        else:
            if current_opmode == "auto" and (
                desired_temp is None or desired_temp >= 40.0
            ):
                target_temp = (
                    manual_temp
                    if (manual_temp is not None and 10.0 <= manual_temp <= 30.0)
                    else 23.0
                )
            else:
                target_temp = round(
                    current_target - self.cooling_quick_veto_boost_delta, 1
                )

        target_temp = max(15.0, min(30.0, target_temp))

        if current_opmode != "day":
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpModeCooling", "day")

        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingManualTemp", target_temp
        )
        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingTempDesired", target_temp
        )

        self.cooling_quick_veto_active = True
        self.cooling_quick_veto_target_temp = target_temp
        self.cooling_quick_veto_remaining_minutes = int((duration or 3.0) * 60)

    async def async_update_cooling_quick_veto_temperature(
        self, temperature: float
    ) -> None:
        target_temp = max(15.0, min(30.0, round(float(temperature), 1)))
        self.cooling_quick_veto_target_temp = target_temp
        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingManualTemp", target_temp
        )
        await self.async_write_parameter(
            CIRCUIT_BASS3, "Z1CoolingTempDesired", target_temp
        )

    async def async_cancel_cooling_quick_veto(self, restore: bool = True) -> None:
        self.cooling_quick_veto_active = False
        self.cooling_quick_veto_target_temp = None
        self.cooling_quick_veto_remaining_minutes = None
        pre_opmode = self._pre_cooling_veto_opmode
        pre_temp = self._pre_cooling_veto_temp
        self._pre_cooling_veto_opmode = None
        self._pre_cooling_veto_temp = None

        if restore:
            if pre_opmode is not None and pre_opmode != "day":
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpModeCooling", pre_opmode
                )
            if pre_temp is not None and pre_temp < 40.0:
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", pre_temp
                )
                await self.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingTempDesired", pre_temp
                )


class TestClimateEntity(unittest.TestCase):
    """Test SaunierGeniaZone1Climate preset modes and cooling state handling."""

    def setUp(self) -> None:
        self.coordinator = MockCoordinatorForClimate()
        self.climate = SaunierGeniaZone1Climate(self.coordinator)

    def test_cooling_active_modes_includes_night(self) -> None:
        """Verify COOLING_ACTIVE_MODES includes 'night' for symmetrical operation."""
        self.assertIn("night", COOLING_ACTIVE_MODES)
        self.assertIn("auto", COOLING_ACTIVE_MODES)
        self.assertIn("day", COOLING_ACTIVE_MODES)
        self.assertEqual(COOLING_ACTIVE_MODES, HEATING_ACTIVE_MODES)

    def test_cooling_night_mode_reports_cool_hvac_and_eco_preset(self) -> None:
        """Verify Z1OpModeCooling=night reports HVACMode.COOL and PRESET_ECO."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "night"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}

        self.assertEqual(self.climate.hvac_mode, HVACMode.COOL)
        self.assertEqual(self.climate.preset_mode, PRESET_ECO)

    def test_apply_preset_eco_in_cooling_writes_z1opmodecooling(self) -> None:
        """Verify applying PRESET_ECO while in cooling season writes Z1OpModeCooling=night."""
        self.climate._active_season = SEASON_COOLING
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "day"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}

        asyncio.run(self.climate.async_set_preset_mode(PRESET_ECO))

        # Must write Z1OpModeCooling="night", NOT Z1OpMode="night"
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "night"), self.coordinator.writes
        )
        self.assertNotIn((CIRCUIT_BASS3, "Z1OpMode", "night"), self.coordinator.writes)

    def test_apply_preset_eco_in_heating_writes_z1opmode(self) -> None:
        """Verify applying PRESET_ECO while in heating season writes Z1OpMode=night."""
        self.climate._active_season = SEASON_HEATING
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}

        asyncio.run(self.climate.async_set_preset_mode(PRESET_ECO))

        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "night"), self.coordinator.writes)
        self.assertNotIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "night"), self.coordinator.writes
        )

    def test_hvac_modes_contains_only_off_heat_cool(self) -> None:
        """Verify HVACMode.AUTO is removed and only OFF, HEAT, COOL are exposed."""
        self.assertEqual(
            self.climate.hvac_modes,
            [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL],
        )
        self.assertNotIn(HVACMode.AUTO, self.climate.hvac_modes)

    def test_apply_hvac_mode_heat_sets_heating_and_preserves_schedule(self) -> None:
        """Verify setting HVACMode.HEAT turns off cooling and writes Z1OpMode=auto by default."""
        self.climate._active_season = SEASON_COOLING
        asyncio.run(self.climate.async_set_hvac_mode(HVACMode.HEAT))

        self.assertEqual(self.climate._active_season, SEASON_HEATING)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "off"), self.coordinator.writes
        )
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "auto"), self.coordinator.writes)

    def test_apply_hvac_mode_cool_sets_cooling_and_opens_calendar(self) -> None:
        """Verify setting HVACMode.COOL turns off heating, opens calendar lock, and writes Z1OpModeCooling=auto."""
        self.climate._active_season = SEASON_HEATING
        asyncio.run(self.climate.async_set_hvac_mode(HVACMode.COOL))

        self.assertEqual(self.climate._active_season, SEASON_COOLING)
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "off"), self.coordinator.writes)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "auto"), self.coordinator.writes
        )

    def test_hvac_mode_stays_heat_across_presets(self) -> None:
        """Verify hvac_mode remains HVACMode.HEAT across comfort (auto), manual (day), and eco (night) presets."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }

        # Preset comfort (Z1OpMode = "auto")
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.assertEqual(self.climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(self.climate.preset_mode, PRESET_COMFORT)

        # Preset manual (Z1OpMode = "day")
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "day"}
        self.assertEqual(self.climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(self.climate.preset_mode, PRESET_MANUAL)

        # Preset eco (Z1OpMode = "night")
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {
            "value": "night"
        }
        self.assertEqual(self.climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(self.climate.preset_mode, PRESET_ECO)

    def test_target_temperature_prioritizes_actual_desired_and_none_when_idle(
        self,
    ) -> None:
        """Verify target_temperature returns Z1ActualRoomTempDesired when active and None when idle outside schedule."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1manualtemp")] = {
            "value": 24.0
        }

        # During active schedule slot (e.g. 21.0 °C desired)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 21.0
        }
        self.assertEqual(self.climate.target_temperature, 21.0)
        self.assertEqual(self.climate.native_target_temperature, 21.0)

        # Room temperature telemetry
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1roomtemp")] = {"value": 20.5}
        self.assertEqual(self.climate.current_temperature, 20.5)
        self.assertEqual(self.climate.native_current_temperature, 20.5)

        # Outside schedule slot at night (0.0 °C reported, idle)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 0.0
        }
        self.assertIsNone(self.climate.target_temperature)
        self.assertIsNone(self.climate.native_target_temperature)

    def test_cooling_release_off_with_both_auto_defaults_to_heat(self) -> None:
        """Verify that when both modes are auto but CoolingReleaseStatus=off, heating is active (Issue #7)."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "auto"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "coolingreleasestatus")] = {
            "value": "off"
        }

        self.assertEqual(self.climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(self.climate.preset_mode, PRESET_COMFORT)

    def test_cooling_release_off_with_both_auto_set_temperature_writes_heating(
        self,
    ) -> None:
        """Verify adjusting temperature when cooling is blocked routes to heating (F1 fix)."""
        import asyncio

        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "auto"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "coolingreleasestatus")] = {
            "value": "off"
        }
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_temperature(temperature=21.5))

        cooling_regs = {"Z1CoolingManualTemp", "Z1CoolingTempDesired", "Z1CoolingTemp"}
        heating_regs = {"Z1ManualTemp", "Z1QuickVetoTemp", "Z1NightTemp"}

        touched_cooling = [w for w in self.coordinator.writes if w[1] in cooling_regs]
        touched_heating = [w for w in self.coordinator.writes if w[1] in heating_regs]

        self.assertEqual(touched_cooling, [])
        self.assertTrue(len(touched_heating) > 0)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 21.5), self.coordinator.writes)

    def test_climate_and_water_heater_availability(self) -> None:
        """Verify climate and DHW entities availability gates on is_ebus_operational."""
        from custom_components.arotherm_genia_ebusd.water_heater import (
            SaunierGeniaWaterHeater,
        )

        water_heater = SaunierGeniaWaterHeater(self.coordinator)

        # 1. Unhydrated -> both unavailable
        self.coordinator._state = {}
        self.assertFalse(self.climate.available)
        self.assertFalse(water_heater.available)

        # 2. Hydrated normal -> both available
        self.coordinator._state[("bass3", "z1opmode")] = {"value": "auto"}
        self.assertTrue(self.climate.available)
        self.assertTrue(water_heater.available)

        # 3. ebusd global/signal is false -> both unavailable
        self.coordinator._state[("global", "signal")] = {"value": "false"}
        self.assertFalse(self.climate.available)
        self.assertFalse(water_heater.available)

        # 4. signal recovers -> both available
        self.coordinator._state[("global", "signal")] = {"value": "true"}
        self.assertTrue(self.climate.available)
        self.assertTrue(water_heater.available)

        # 5. ebusd global/running is off -> both unavailable
        self.coordinator._state[("global", "running")] = {"value": "off"}
        self.assertFalse(self.climate.available)
        self.assertFalse(water_heater.available)

    def test_current_humidity_valid_and_out_of_bounds(self) -> None:
        """Verify Zone 1 climate entity exposes Z1RoomHumidity and filters invalid values."""
        self.assertIsNone(self.climate.current_humidity)

        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1roomhumidity")] = {
            "value": 63.4
        }
        self.assertEqual(self.climate.current_humidity, 63)

        # Out-of-bounds or sentinel readings (<= 0 or > 100) must return None
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1roomhumidity")] = {
            "value": 0.0
        }
        self.assertIsNone(self.climate.current_humidity)

        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1roomhumidity")] = {
            "value": 105.0
        }
        self.assertIsNone(self.climate.current_humidity)

    def test_quick_veto_activation_from_off_restores_off(self) -> None:
        """Verify selecting Boost while OFF activates heating, then restores OFF when cancelled."""
        import asyncio

        # Initial state: Climate OFF, manual temp 21.5
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1manualtemp")] = {
            "value": 21.5
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1quickvetoduration")] = {
            "value": 0.0
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1sfmode")] = {"value": "auto"}

        written: list[tuple[str, str, Any]] = []

        async def mock_write(circuit: str, param: str, val: Any) -> bool:
            written.append((circuit, param, val))
            self.coordinator._state[(circuit.lower(), param.lower())] = {"value": val}
            return True

        self.coordinator.async_write_parameter = mock_write

        # 1. Activate Boost
        asyncio.run(self.climate.async_set_preset_mode(PRESET_BOOST))

        # Must have written Z1OpMode auto, Z1QuickVetoTemp 21.5, Z1QuickVetoDuration 3.0, Z1SFMode veto
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "auto"), written)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 21.5), written)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0), written)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), written)

        # 2. Cancel Boost by selecting Comfort
        written.clear()
        asyncio.run(self.climate.async_set_preset_mode(PRESET_COMFORT))

        # Must clear veto, duration to 0, and restore Z1OpMode to off
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "auto"), written)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0), written)
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "off"), written)

    def test_adjust_temperature_in_comfort_triggers_quick_veto(self) -> None:
        """Verify adjusting target temperature while in scheduled mode triggers Quick Veto."""
        import asyncio

        # State: In heating scheduled mode
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1sfmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1manualtemp")] = {
            "value": 20.0
        }

        written: list[tuple[str, str, Any]] = []

        async def mock_write(circuit: str, param: str, val: Any) -> bool:
            written.append((circuit, param, val))
            self.coordinator._state[(circuit.lower(), param.lower())] = {"value": val}
            return True

        self.coordinator.async_write_parameter = mock_write

        # Set temperature to 23.5 on climate dial
        asyncio.run(self.climate.async_set_temperature(temperature=23.5))

        # Must write Z1QuickVetoTemp 23.5, Z1QuickVetoDuration 3.0, Z1SFMode veto
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 23.5), written)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0), written)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), written)
        # Must NOT have written Z1DayTemp or Z1CoolingManualTemp
        unwanted_writes = [
            w for w in written if w[1] in ("Z1DayTemp", "Z1CoolingManualTemp")
        ]
        self.assertEqual(len(unwanted_writes), 0)

    def test_boost_preset_while_heating_runs_boosts_3_degrees(self) -> None:
        """Verify entering Boost while heating is active adds +3.0 °C to active target temperature."""
        import asyncio

        # State: Active slot at 20.0 °C
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 20.0
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1sfmode")] = {"value": "auto"}

        written: list[tuple[str, str, Any]] = []

        async def mock_write(circuit: str, param: str, val: Any) -> bool:
            written.append((circuit, param, val))
            self.coordinator._state[(circuit.lower(), param.lower())] = {"value": val}
            return True

        self.coordinator.async_write_parameter = mock_write

        asyncio.run(self.climate.async_set_preset_mode(PRESET_BOOST))

        # 20.0 + 3.0 = 23.0 °C
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 23.0), written)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0), written)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), written)

    def test_water_heater_native_temperatures(self) -> None:
        """Verify water heater exposes native_current_temperature and native_target_temperature."""
        from custom_components.arotherm_genia_ebusd.water_heater import (
            SaunierGeniaWaterHeater,
        )

        water_heater = SaunierGeniaWaterHeater(self.coordinator)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "hwcstoragetemp")] = {
            "value": 52.3
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "hwctempdesired")] = {
            "value": 55.0
        }

        self.assertEqual(water_heater.native_current_temperature, 52.3)
        self.assertEqual(water_heater.current_temperature, 52.3)
        self.assertEqual(water_heater.native_target_temperature, 55.0)
        self.assertEqual(water_heater.target_temperature, 55.0)

    def test_set_temperature_in_cooling_writes_cooling_setpoints_only(self) -> None:
        """Verify setting temperature in cooling writes Z1CoolingManualTemp and Z1CoolingTempDesired only."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "day"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_temperature(temperature=23.5))

        # Must write Z1CoolingManualTemp and Z1CoolingTempDesired
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.5), self.coordinator.writes
        )
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingTempDesired", 23.5), self.coordinator.writes
        )

        # Must NOT write heating setpoint Z1ManualTemp or legacy Z1DayTemp
        for _, param, _ in self.coordinator.writes:
            self.assertNotIn(param, ("Z1ManualTemp", "Z1DayTemp"))

    def test_set_temperature_in_heating_manual_writes_heating_setpoint_only(
        self,
    ) -> None:
        """Verify setting temperature in heating manual writes Z1ManualTemp only."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "day"}
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_temperature(temperature=21.5))

        # Must write Z1ManualTemp
        self.assertIn((CIRCUIT_BASS3, "Z1ManualTemp", 21.5), self.coordinator.writes)

        # Must NOT write cooling setpoints or legacy Z1DayTemp
        for _, param, _ in self.coordinator.writes:
            self.assertNotIn(
                param, ("Z1CoolingManualTemp", "Z1CoolingTempDesired", "Z1DayTemp")
            )

    def test_cooling_target_temperature_resolution(self) -> None:
        """Verify cooling target temperature anti-sentinel resolution and fallbacks."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "day"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}

        # 1. Active cooling running (< 40.0) -> returns active setpoint
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {
            "value": 22.0
        }
        self.assertEqual(self.climate.native_target_temperature, 22.0)

        # 2. Cooling idle / off sentinel (99.0) in PRESET_MANUAL -> returns Z1CoolingManualTemp
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {
            "value": 99.0
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingmanualtemp")] = {
            "value": 24.0
        }
        self.assertEqual(self.climate.native_target_temperature, 24.0)

        # 3. Cooling idle / off sentinel (99.0) in PRESET_COMFORT -> returns None (idle outside slot)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "auto"
        }
        self.assertEqual(self.climate.preset_mode, PRESET_COMFORT)
        self.assertIsNone(self.climate.native_target_temperature)

        # 4. Cooling idle / off sentinel (99.0) in PRESET_ECO -> returns Z1CoolingTemp
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "night"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtemp")] = {
            "value": 28.0
        }
        self.assertEqual(self.climate.preset_mode, PRESET_ECO)
        self.assertEqual(self.climate.native_target_temperature, 28.0)

    def test_set_temperature_in_cooling_eco_writes_z1coolingtemp(self) -> None:
        """Verify setting temperature in cooling PRESET_ECO writes Z1CoolingTemp and Z1CoolingTempDesired."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "night"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_temperature(temperature=26.0))

        # Must write Z1CoolingTemp and Z1CoolingTempDesired
        self.assertIn((CIRCUIT_BASS3, "Z1CoolingTemp", 26.0), self.coordinator.writes)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingTempDesired", 26.0), self.coordinator.writes
        )
        self.assertNotIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 26.0), self.coordinator.writes
        )

    def test_hvac_mode_switch_cooling_heating_decoupled(self) -> None:
        """Verify switching between COOL and HEAT never contaminates opposite setpoints."""
        # 1. Start in HEAT, saved cooling target is 23.0
        self.climate._saved_cooling_target = 23.0
        self.climate._saved_heating_target = 21.0
        self.coordinator.writes.clear()

        # Switch to COOL
        asyncio.run(self.climate.async_set_hvac_mode(HVACMode.COOL))
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.0), self.coordinator.writes
        )
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingTempDesired", 23.0), self.coordinator.writes
        )
        self.assertNotIn((CIRCUIT_BASS3, "Z1ManualTemp", 23.0), self.coordinator.writes)

        # 2. Switch back to HEAT (preset manual)
        self.coordinator.writes.clear()
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "day"}
        asyncio.run(self.climate.async_set_hvac_mode(HVACMode.HEAT))
        self.assertIn((CIRCUIT_BASS3, "Z1ManualTemp", 21.0), self.coordinator.writes)
        self.assertNotIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 21.0), self.coordinator.writes
        )

    def test_boost_preset_from_off_triggers_heating_veto(self) -> None:
        """Verify selecting Boost while OFF activates heating quick veto (never cooling)."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "off"
        }
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_preset_mode(PRESET_BOOST))

        written = self.coordinator.writes
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "auto"), written)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), written)
        # Cooling must never be touched
        for circuit, param, _ in written:
            self.assertNotIn("cooling", param.lower())

    def test_cooling_quick_veto_in_manual_cooling(self) -> None:
        """Verify activating Boost in manual cooling lowers temperature and restores on cancel."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "day"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingmanualtemp")] = {
            "value": 24.0
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {
            "value": 24.0
        }
        self.coordinator.cooling_quick_veto_boost_delta = 2.0
        self.coordinator.writes.clear()

        # 1. Activate Boost: 24.0 - 2.0 = 22.0 °C
        asyncio.run(self.climate.async_set_preset_mode(PRESET_BOOST))
        self.assertTrue(self.coordinator.cooling_quick_veto_active)
        self.assertEqual(self.climate.preset_mode, PRESET_BOOST)
        self.assertEqual(self.climate.native_target_temperature, 22.0)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 22.0), self.coordinator.writes
        )
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingTempDesired", 22.0), self.coordinator.writes
        )

        # 2. Adjust temperature during active veto to 21.5 °C
        self.coordinator.writes.clear()
        asyncio.run(self.climate.async_set_temperature(temperature=21.5))
        self.assertEqual(self.climate.native_target_temperature, 21.5)
        self.assertEqual(self.coordinator.cooling_quick_veto_target_temp, 21.5)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 21.5), self.coordinator.writes
        )

        # 3. Cancel / switch away: restores manual setpoint
        self.coordinator.writes.clear()
        asyncio.run(self.coordinator.async_cancel_cooling_quick_veto(restore=True))
        self.assertFalse(self.coordinator.cooling_quick_veto_active)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 24.0), self.coordinator.writes
        )

    def test_cooling_quick_veto_in_scheduled_cooling_outside_slot(self) -> None:
        """Verify activating Boost outside scheduled cooling slot uses manual setpoint and temporarily sets day mode."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "auto"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "coolingreleasestatus")] = {
            "value": "on"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingmanualtemp")] = {
            "value": 23.0
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {
            "value": 99.0
        }  # outside slot sentinel
        self.coordinator.writes.clear()

        # Activate Boost
        asyncio.run(self.climate.async_set_preset_mode(PRESET_BOOST))
        self.assertTrue(self.coordinator.cooling_quick_veto_active)
        self.assertEqual(self.climate.preset_mode, PRESET_BOOST)
        self.assertEqual(self.climate.native_target_temperature, 23.0)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "day"), self.coordinator.writes
        )
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.0), self.coordinator.writes
        )

        # On cancellation / timeout, restores auto
        self.coordinator.writes.clear()
        asyncio.run(self.coordinator.async_cancel_cooling_quick_veto(restore=True))
        self.assertFalse(self.coordinator.cooling_quick_veto_active)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "auto"), self.coordinator.writes
        )

    def test_cooling_scheduled_set_temperature_triggers_cooling_veto(self) -> None:
        """Verify setting temperature in scheduled cooling triggers a cooling quick veto."""
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {
            "value": "auto"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "coolingreleasestatus")] = {
            "value": "on"
        }
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {
            "value": 24.0
        }
        self.coordinator.writes.clear()

        asyncio.run(self.climate.async_set_temperature(temperature=22.5))

        self.assertTrue(self.coordinator.cooling_quick_veto_active)
        self.assertEqual(self.climate.preset_mode, PRESET_BOOST)
        self.assertEqual(self.climate.native_target_temperature, 22.5)
        self.assertIn(
            (CIRCUIT_BASS3, "Z1OpModeCooling", "day"), self.coordinator.writes
        )
        self.assertIn(
            (CIRCUIT_BASS3, "Z1CoolingManualTemp", 22.5), self.coordinator.writes
        )


if __name__ == "__main__":
    unittest.main()
