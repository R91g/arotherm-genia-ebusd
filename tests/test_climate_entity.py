"""Unit tests for climate entity season handling and preset modes."""

import asyncio
import os
import sys
import unittest
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

        dur_val = max(0.5, min(24.0, dur_val))

        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoTemp", target_temp)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", dur_val)
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "veto")

    async def async_cancel_quick_veto(self) -> None:
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1SFMode", "auto")
        await self.async_write_parameter(CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0)
        if getattr(self, "_pre_veto_opmode", None) == "off":
            await self.async_write_parameter(CIRCUIT_BASS3, "Z1OpMode", "off")
        self._pre_veto_opmode = None


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
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1daytemp")] = {"value": 24.0}

        # During active schedule slot (e.g. 21.0 °C desired)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 21.0
        }
        self.assertEqual(self.climate.target_temperature, 21.0)

        # Outside schedule slot at night (0.0 °C reported, idle)
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 0.0
        }
        self.assertIsNone(self.climate.target_temperature)

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
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "z1daytemp")] = {"value": 20.0}

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
        # Must NOT have written Z1DayTemp
        day_temp_writes = [w for w in written if w[1] == "Z1DayTemp"]
        self.assertEqual(len(day_temp_writes), 0)

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


if __name__ == "__main__":
    unittest.main()
