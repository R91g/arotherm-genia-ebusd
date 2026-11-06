"""Unit tests verifying community-contributed installation dump fixtures.

Validates that real-world eBUS telemetry snapshots from diverse heat pump families
(Saunier Duval GeniaAir Max, Vaillant aroTHERM plus, aroTHERM Split, CTLV2, CTLV3)
can rehydrate the coordinator, compute thermodynamics, and drive all entities without errors.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

# Add tests directory to sys.path if running as standalone module
TESTS_DIR = os.path.dirname(__file__)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.climate import SaunierGeniaZone1Climate
from custom_components.arotherm_genia_ebusd.const import (
    CALC_CIRCUIT,
    CALC_DELTA_T,
    CALC_THERMAL_POWER,
    CONF_INDOOR_MODEL,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    CONF_OUTDOOR_MODEL,
    CONTROLLER_CIRCUITS,
    DOMAIN,
    OUTDOOR_CIRCUITS,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator
from custom_components.arotherm_genia_ebusd.water_heater import SaunierGeniaWaterHeater


class TestCommunityFixtures(unittest.TestCase):
    """Test suite validating community fixtures across diverse hardware setups."""

    def setUp(self) -> None:
        """Set up test environment and find community fixtures."""
        self.hass = MagicMock()
        self.fixtures_dir = os.path.join(
            os.path.dirname(__file__), "fixtures", "community"
        )
        self.fixture_files = sorted(
            glob.glob(os.path.join(self.fixtures_dir, "*.json"))
        )

    def test_fixtures_directory_contains_data(self) -> None:
        """Verify at least one community fixture exists in tests/fixtures/community/."""
        self.assertTrue(
            os.path.isdir(self.fixtures_dir), "Community fixtures directory missing."
        )
        self.assertGreater(
            len(self.fixture_files),
            0,
            "No community fixtures found in tests/fixtures/community/.",
        )

    def test_all_community_fixtures_rehydrate_and_drive_entities(self) -> None:
        """Rehydrate coordinator from each community fixture and verify entity stability."""
        for fixture_path in self.fixture_files:
            fixture_name = os.path.basename(fixture_path)
            with self.subTest(fixture=fixture_name):
                with open(fixture_path, "r", encoding="utf-8") as fp:
                    data: dict[str, Any] = json.load(fp)

                # 1. Verify schema of fixture
                self.assertEqual(data.get("domain"), DOMAIN)
                self.assertIn("entry_id", data)
                self.assertIn("active_outdoor_circuit", data)
                self.assertIn("active_controller_circuit", data)
                self.assertIn("values", data)
                self.assertIsInstance(data["values"], dict)

                # 2. Build mock ConfigEntry
                entry = MagicMock()
                entry.entry_id = data["entry_id"]
                entry.data = {
                    CONF_MQTT_PREFIX: data.get("mqtt_prefix", "ebusd"),
                    CONF_MANUFACTURER: data.get("manufacturer", "Saunier Duval"),
                    CONF_OUTDOOR_MODEL: data.get("outdoor_model", "GeniaAir Max 15"),
                    CONF_INDOOR_MODEL: data.get("indoor_model", "MiPro Sense"),
                }
                entry.options = {}

                # 3. Create coordinator and hydrate _state
                coord = SaunierGeniaCoordinator(self.hass, entry)
                coord._active_outdoor_circuit = data["active_outdoor_circuit"]
                coord._active_controller_circuit = data["active_controller_circuit"]

                for circuit, messages in data["values"].items():
                    c_key = circuit.lower()
                    target_circuits = [c_key]
                    if c_key in CONTROLLER_CIRCUITS:
                        target_circuits = list(CONTROLLER_CIRCUITS)
                    elif c_key in OUTDOOR_CIRCUITS:
                        target_circuits = list(OUTDOOR_CIRCUITS)

                    for msg_name, payload in messages.items():
                        for circ in target_circuits:
                            coord._canonical_names[(circ, msg_name.lower())] = msg_name
                            coord._state[(circ, msg_name)] = payload

                coord._last_telemetry_time = 1000000000.0

                with patch("time.monotonic", return_value=1000000000.0):
                    # 4. Trigger thermodynamic recalculation
                    coord._async_recalculate_thermodynamics()

                    # 5. Assert eBUS operational status
                    self.assertTrue(
                        coord.is_ebus_operational,
                        f"Fixture '{fixture_name}' failed is_ebus_operational check.",
                    )

                    # 6. Verify circuit resolution matches or normalizes correctly
                    self.assertEqual(
                        coord.resolve_circuit(data["active_outdoor_circuit"]),
                        data["active_outdoor_circuit"],
                    )
                    self.assertEqual(
                        coord.resolve_circuit(data["active_controller_circuit"]),
                        data["active_controller_circuit"],
                    )

                    # 7. Check thermodynamic calculations if primary temps exist
                    delta_t = coord.get_float(CALC_CIRCUIT, CALC_DELTA_T)
                    if delta_t is not None:
                        self.assertGreater(delta_t, 0.0)
                        thermal_power = coord.get_float(
                            CALC_CIRCUIT, CALC_THERMAL_POWER
                        )
                        self.assertIsNotNone(thermal_power)

                    # 8. Instantiate Climate and Water Heater entities and verify properties
                    climate = SaunierGeniaZone1Climate(coord)
                    self.assertTrue(climate.available)
                    self.assertIsNotNone(climate.target_temperature)
                    self.assertIsNotNone(climate.hvac_mode)

                    water_heater = SaunierGeniaWaterHeater(coord)
                    self.assertTrue(water_heater.available)
                    self.assertIsNotNone(water_heater.target_temperature)
                    self.assertIsNotNone(water_heater.current_operation)


if __name__ == "__main__":
    unittest.main()
