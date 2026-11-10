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
from homeassistant.components.climate import HVACMode

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
    MESSAGE_ALIASES,
    OUTDOOR_CIRCUITS,
    PRESET_COMFORT,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator
from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
    SENSOR_DESCRIPTIONS,
)
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
                        alias = MESSAGE_ALIASES.get(msg_name.lower())
                        for circ in target_circuits:
                            coord._canonical_names[(circ, msg_name.lower())] = msg_name
                            coord._state[(circ, msg_name)] = payload
                            if alias and alias != msg_name:
                                coord._canonical_names[(circ, alias.lower())] = alias
                                coord._state[(circ, alias)] = payload

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
                        self.assertIsInstance(delta_t, float)
                        thermal_power = coord.get_float(
                            CALC_CIRCUIT, CALC_THERMAL_POWER
                        )
                        self.assertIsNotNone(thermal_power)

                    # 8. Instantiate Climate and Water Heater entities and verify properties
                    climate = SaunierGeniaZone1Climate(coord)
                    self.assertTrue(climate.available)
                    if climate.target_temperature is not None:
                        self.assertIsInstance(climate.target_temperature, float)
                    self.assertIsNotNone(climate.hvac_mode)
                    if fixture_name == "saunier_geniaair_max_heating.json":
                        self.assertEqual(climate.current_humidity, 67)
                    elif fixture_name == "saunier_geniaair_max_acs.json":
                        self.assertEqual(climate.current_humidity, 64)
                    elif fixture_name == "saunier_geniaair_max_standby.json":
                        self.assertEqual(climate.current_humidity, 66)
                    elif fixture_name == "vaillant_arotherm_plus_basv3.json":
                        self.assertEqual(climate.current_humidity, 63)
                    elif fixture_name == "vaillant_arotherm_plus_ctlv3_lassal.json":
                        self.assertEqual(coord.active_controller_circuit, "ctlv3")
                        self.assertEqual(coord.active_outdoor_circuit, "hmux0")

                    water_heater = SaunierGeniaWaterHeater(coord)
                    self.assertTrue(water_heater.available)
                    if water_heater.target_temperature is not None:
                        self.assertIsInstance(water_heater.target_temperature, float)
                    self.assertIsNotNone(water_heater.current_operation)

    def test_lassal_ctlv3_hmux0_fixture_telemetry(self) -> None:
        """Verify specialized sensors, dual-fan telemetry and COP from Dominique (Lassal) dump."""
        fixture_path = os.path.join(
            self.fixtures_dir, "vaillant_arotherm_plus_ctlv3_lassal.json"
        )
        self.assertTrue(os.path.isfile(fixture_path))
        with open(fixture_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        entry = MagicMock()
        entry.entry_id = data["entry_id"]
        entry.data = {
            CONF_MQTT_PREFIX: data.get("mqtt_prefix", "ebusd"),
            CONF_MANUFACTURER: "Vaillant",
            CONF_OUTDOOR_MODEL: data.get("outdoor_model"),
            CONF_INDOOR_MODEL: data.get("indoor_model"),
        }
        entry.options = {}

        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = data["active_outdoor_circuit"]
        coord._active_controller_circuit = data["active_controller_circuit"]

        for circuit, messages in data["values"].items():
            c_key = circuit.lower()
            for msg_name, payload in messages.items():
                coord._canonical_names[(c_key, msg_name.lower())] = msg_name
                coord._state[(c_key, msg_name)] = payload

        coord._last_telemetry_time = 1000000000.0

        # Assert hardware identification
        self.assertEqual(coord.active_controller_circuit, "ctlv3")
        self.assertEqual(coord.active_outdoor_circuit, "hmux0")
        self.assertEqual(coord.outdoor_model, "aroTHERM plus VWL 105/8.1 A 400V")
        self.assertEqual(coord.indoor_model, "VWZ MEH 97/7")

        # Verify dual fan metrics in hmux0
        fan1_hours = coord.get_float("hmux0", "RunStatsFan1Hours")
        fan2_hours = coord.get_float("hmux0", "RunStatsFan2Hours")
        self.assertEqual(fan1_hours, 1342.0)
        self.assertEqual(fan2_hours, 1342.0)

        # Verify dual fan start counts and defrost starts via sensor entities
        fan1_starts_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "stats_fan1_starts"
        )
        fan2_starts_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "stats_fan2_starts"
        )
        deice_starts_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "stats_deice_starts"
        )

        s_fan1_starts = SaunierGeniaSensor(coord, fan1_starts_desc)
        s_fan2_starts = SaunierGeniaSensor(coord, fan2_starts_desc)
        s_deice_starts = SaunierGeniaSensor(coord, deice_starts_desc)

        self.assertEqual(s_fan1_starts.native_value, 1092)
        self.assertEqual(s_fan2_starts.native_value, 1092)
        self.assertEqual(s_deice_starts.native_value, 29)

        # Verify energy registers and heating seasonal COP
        elec_hc = coord.get_float("hmux0", "PrEnergyElectricHc")
        thermal_hc = coord.get_float("hmux0", "PrEnergyThermalHc")
        self.assertEqual(elec_hc, 1539400.0)
        self.assertEqual(thermal_hc, 5447760.0)
        self.assertGreater(thermal_hc / elec_hc, 3.5)

        # Verify weekly timer slots exist in CTLV3
        z1_slots = coord.get_message("ctlv3", "Z1Timer_Slots")
        self.assertIsNotNone(z1_slots)
        hwc_slots = coord.get_message("ctlv3", "HwcTimer_Slots")
        self.assertIsNotNone(hwc_slots)

        # Verify climate entity properties on Lassal's controller (Issue #7)
        climate = SaunierGeniaZone1Climate(coord)
        self.assertEqual(climate.hvac_mode, HVACMode.HEAT)
        self.assertEqual(climate.preset_mode, PRESET_COMFORT)
        self.assertIsNone(
            climate.target_temperature
        )  # Idle at night (0 °C reported by eBUS)

        # When active daytime slot is simulated (e.g. 21.0 °C), target_temperature reports 21.0
        coord._state[("ctlv3", "Z1ActualRoomTempDesired")] = {"value": 21.0}
        self.assertEqual(climate.target_temperature, 21.0)


if __name__ == "__main__":
    unittest.main()
