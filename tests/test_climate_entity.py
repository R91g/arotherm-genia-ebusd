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
    PRESET_ECO,
    SEASON_COOLING,
    SEASON_HEATING,
    SaunierGeniaZone1Climate,
)
from custom_components.arotherm_genia_ebusd.const import CIRCUIT_BASS3


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

    async def async_write_parameter(
        self, circuit: str, message: str, value: Any
    ) -> None:
        self.writes.append((circuit, message, value))
        self._state[(circuit.lower(), message.lower())] = {"value": value}


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


if __name__ == "__main__":
    unittest.main()
