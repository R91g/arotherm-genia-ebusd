"""Unit tests for sensor registry, entity descriptions, and unique ID integrity."""

import json
import os
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
)
from custom_components.arotherm_genia_ebusd.const import (
    CALC_CIRCUIT,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    CIRCUIT_VWZIO,
    DEPRECATED_UNIQUE_ID_SUFFIXES,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES,
)
from custom_components.arotherm_genia_ebusd.number import NUMBER_DESCRIPTIONS
from custom_components.arotherm_genia_ebusd.select import SELECT_DESCRIPTIONS
from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
    SENSOR_DESCRIPTIONS,
    WEEKLY_SCHEDULE_SENSORS,
    _get_electric_power,
    _get_z1_room_humidity,
)
from custom_components.arotherm_genia_ebusd.switch import STANDARD_SWITCH_DESCRIPTIONS


class TestSensorRegistry(unittest.TestCase):
    """Test entity description catalog, circuits, and unique ID generation."""

    def setUp(self) -> None:
        """Set up valid circuits and devices sets."""
        self.valid_circuits = {
            CIRCUIT_HMUX0,
            CIRCUIT_BASS3,
            CIRCUIT_VWZIO,
            CIRCUIT_NETX3,
            CIRCUIT_NETX3_ALT,
            CIRCUIT_BROADCAST,
            CIRCUIT_GLOBAL,
            CALC_CIRCUIT,
        }
        self.valid_devices = {
            DEVICE_OUTDOOR_UNIT,
            DEVICE_CLIMATE_CONTROLLER,
            DEVICE_HYDRAULIC_INTERFACE,
            DEVICE_WIRELESS_THERMOSTAT,
        }

    def test_sensors_validity(self) -> None:
        """Verify all telemetry sensors have valid circuits, messages, and fields."""
        self.assertGreater(len(SENSOR_DESCRIPTIONS), 80)
        uids = []
        for desc in SENSOR_DESCRIPTIONS:
            self.assertIn(desc.circuit, self.valid_circuits)
            self.assertIn(desc.device_key, self.valid_devices)
            self.assertTrue(bool(desc.message), f"Empty message in {desc.key}")
            self.assertTrue(bool(desc.field), f"Empty field in {desc.key}")

            # Check unique_id suffix
            c = desc.circuit.lower()
            m = desc.message.lower()
            f = desc.field.lower()
            uid = desc.unique_id_suffix or f"{c}_{m}_{f}"
            uids.append(uid)

        # Check for duplicate unique_id suffixes among standard sensors
        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(
            duplicates, {}, f"Duplicate sensor unique_ids found: {duplicates}"
        )

    def test_wireless_room_target_is_stable_mirror_of_z1daytemp(self) -> None:
        """The thermostat target sensor mirrors Z1DayTemp and keeps its legacy unique_id."""
        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "wireless_room_target_temp"
        )
        self.assertEqual(desc.message, "Z1DayTemp")
        self.assertIsNone(desc.fallback_message)
        self.assertEqual(desc.unique_id_suffix, "04_roomtargettemp_temp")

    def test_primary_flow_rate_field_alignment_and_unique_id(self) -> None:
        """Primary flow rate aligns with modern 08.hmux0.csv while preserving legacy unique_id."""
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "primary_flow_rate")
        self.assertEqual(desc.message, "RunDataFlowRate")
        self.assertEqual(desc.field, "flow_rate")
        self.assertEqual(desc.fallback_field, "value")
        self.assertEqual(desc.unique_id_suffix, "hmux0_rundataflowrate_value")

    def test_electric_power_consumption_alignment_and_unique_id(self) -> None:
        """Electric power consumption prioritizes PowerStatus while preserving legacy unique_id."""
        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "electric_power_consumption"
        )
        self.assertEqual(desc.message, "PowerStatus")
        self.assertEqual(desc.field, "power")
        self.assertEqual(desc.fallback_message, "RunDataElectricPowerConsumption")
        self.assertEqual(desc.fallback_field, "power")
        self.assertEqual(
            desc.unique_id_suffix, "hmux0_rundataelectricpowerconsumption_power"
        )
        self.assertIsNotNone(desc.value_fn)

        from unittest.mock import MagicMock

        coord = MagicMock()
        coord.active_outdoor_circuit = CIRCUIT_HMUX0

        # Case 1: Neither exists -> returns None
        coord.get_float.return_value = None
        self.assertIsNone(_get_electric_power(coord))

        # Case 2: Only RunDataElectricPowerConsumption exists -> returns fallback
        def mock_get_float_fallback(circuit, message, field):
            if message == "RunDataElectricPowerConsumption" and field == "power":
                return 123.4
            return None

        coord.get_float.side_effect = mock_get_float_fallback
        self.assertEqual(_get_electric_power(coord), 123.4)

        # Case 3: Both exist -> PowerStatus MUST take precedence
        def mock_get_float_both(circuit, message, field):
            if message == "PowerStatus" and field == "power":
                return 456.7
            if message == "RunDataElectricPowerConsumption" and field == "power":
                return 123.4
            return None

        coord.get_float.side_effect = mock_get_float_both
        self.assertEqual(_get_electric_power(coord), 456.7)

    def test_binary_sensors_validity(self) -> None:
        """Verify binary sensors have valid circuits and unique ID suffixes."""
        self.assertGreaterEqual(len(BINARY_SENSOR_DESCRIPTIONS), 8)
        uids = []
        for desc in BINARY_SENSOR_DESCRIPTIONS:
            self.assertIn(desc.circuit, self.valid_circuits)
            self.assertIn(desc.device_key, self.valid_devices)
            self.assertIsNotNone(desc.is_on_fn)
            uid = f"binary_{desc.circuit.lower()}_{desc.message.lower()}_{desc.field.lower()}"
            uids.append(uid)

        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(
            duplicates, {}, f"Duplicate binary_sensor unique_ids: {duplicates}"
        )

    def test_numbers_validity(self) -> None:
        """Verify number entities have valid min/max/step values and unique IDs."""
        self.assertGreaterEqual(len(NUMBER_DESCRIPTIONS), 10)
        uids = []
        for desc in NUMBER_DESCRIPTIONS:
            self.assertIn(desc.circuit, self.valid_circuits)
            self.assertIsNotNone(desc.native_min_value)
            self.assertIsNotNone(desc.native_max_value)
            self.assertGreater(desc.native_max_value, desc.native_min_value)
            self.assertIsNotNone(desc.native_step)
            uid = f"number_{desc.circuit.lower()}_{desc.message.lower()}_{desc.field.lower()}"
            uids.append(uid)

        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(duplicates, {}, f"Duplicate number unique_ids: {duplicates}")

    def test_selects_validity(self) -> None:
        """Verify select entities have non-empty option lists."""
        self.assertGreaterEqual(len(SELECT_DESCRIPTIONS), 4)
        uids = []
        for desc in SELECT_DESCRIPTIONS:
            self.assertIn(desc.circuit, self.valid_circuits)
            self.assertTrue(bool(desc.options))
            uid = f"select_{desc.circuit.lower()}_{desc.message.lower()}_{desc.field.lower()}"
            uids.append(uid)

        # Ensure z1_op_mode_cooling includes 'night' for ECO preset alignment
        z1_cooling = next(
            d for d in SELECT_DESCRIPTIONS if d.key == "z1_op_mode_cooling"
        )
        self.assertEqual(
            z1_cooling.options,
            ["off", "auto", "day", "night"],
            "z1_op_mode_cooling must include 'night' option",
        )

        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(duplicates, {}, f"Duplicate select unique_ids: {duplicates}")

    def test_switches_validity(self) -> None:
        """Verify standard switches have payloads and unique IDs."""
        self.assertGreaterEqual(len(STANDARD_SWITCH_DESCRIPTIONS), 3)
        uids = []
        for desc in STANDARD_SWITCH_DESCRIPTIONS:
            self.assertIn(desc.circuit, self.valid_circuits)
            self.assertTrue(bool(desc.payload_on))
            self.assertTrue(bool(desc.payload_off))
            uid = f"switch_{desc.circuit.lower()}_{desc.message.lower()}_{desc.field.lower()}"
            uids.append(uid)

        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(duplicates, {}, f"Duplicate switch unique_ids: {duplicates}")

    def test_brand_neutrality_in_all_entity_keys(self) -> None:
        """Verify zero brand names ('saunier', 'vaillant') exist in any key or translation_key."""
        all_descriptions = [
            *SENSOR_DESCRIPTIONS,
            *BINARY_SENSOR_DESCRIPTIONS,
            *NUMBER_DESCRIPTIONS,
            *SELECT_DESCRIPTIONS,
            *STANDARD_SWITCH_DESCRIPTIONS,
        ]

        forbidden = ["saunier", "vaillant"]
        for desc in all_descriptions:
            key_lower = desc.key.lower()
            tkey_lower = (desc.translation_key or "").lower()
            for brand in forbidden:
                self.assertNotIn(
                    brand,
                    key_lower,
                    f"Forbidden brand '{brand}' found in entity key '{desc.key}'",
                )
                self.assertNotIn(
                    brand,
                    tkey_lower,
                    f"Forbidden brand '{brand}' found in translation_key '{desc.translation_key}'",
                )

    def test_sensor_translations_and_deprecated_non_overlap(self) -> None:
        """Verify every sensor translation_key exists in strings/en/es and deprecated IDs do not collide."""
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        comp_dir = os.path.join(root_dir, "custom_components", "arotherm_genia_ebusd")
        with open(os.path.join(comp_dir, "strings.json"), encoding="utf-8") as fp:
            strings = json.load(fp)
        with open(
            os.path.join(comp_dir, "translations", "en.json"), encoding="utf-8"
        ) as fp:
            en = json.load(fp)
        with open(
            os.path.join(comp_dir, "translations", "es.json"), encoding="utf-8"
        ) as fp:
            es = json.load(fp)

        self.assertEqual(strings, en, "strings.json and translations/en.json diverged")

        sensor_keys_strings = set(strings["entity"]["sensor"].keys())
        sensor_keys_es = set(es["entity"]["sensor"].keys())
        self.assertEqual(sensor_keys_strings, sensor_keys_es)

        expected_sensor_tkeys = {
            desc.translation_key or desc.key for desc in SENSOR_DESCRIPTIONS
        } | {tkey for tkey, _ in WEEKLY_SCHEDULE_SENSORS}
        self.assertEqual(expected_sensor_tkeys, sensor_keys_strings)

        active_uids = {
            d.unique_id_suffix
            or f"{d.circuit.lower()}_{d.message.lower()}_{d.field.lower()}"
            for d in SENSOR_DESCRIPTIONS
        } | {
            f"binary_{d.circuit.lower()}_{d.message.lower()}_{d.field.lower()}"
            for d in BINARY_SENSOR_DESCRIPTIONS
        }
        overlap = active_uids & set(DEPRECATED_UNIQUE_ID_SUFFIXES)
        self.assertEqual(
            overlap, set(), f"Active unique_id overlaps deprecated list: {overlap}"
        )

    def test_hmux0_only_sensor_unique_id_suffixes_match_descriptions(self) -> None:
        """Verify HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES matches exactly the 3 hmux0_only descriptions."""
        hmux0_only_descs = [d for d in SENSOR_DESCRIPTIONS if d.hmux0_only]
        self.assertEqual(
            {d.key for d in hmux0_only_descs},
            {
                "energy_electric_cool",
                "energy_electric_hc_outdoor",
                "energy_electric_hwc_outdoor",
            },
        )
        computed_suffixes = {
            d.unique_id_suffix
            or f"{d.circuit.lower()}_{d.message.lower()}_{d.field.lower()}"
            for d in hmux0_only_descs
        }
        self.assertEqual(computed_suffixes, set(HMUX0_ONLY_SENSOR_UNIQUE_ID_SUFFIXES))

    def test_z1_room_humidity_sensor_and_bounds(self) -> None:
        """Verify z1_room_humidity sensor description and physical bounds filter."""
        from unittest.mock import MagicMock

        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "z1_room_humidity")
        self.assertEqual(desc.device_key, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(desc.circuit, CIRCUIT_BASS3)
        self.assertEqual(desc.message, "Z1RoomHumidity")
        self.assertEqual(desc.field, "value")

        coord = MagicMock()
        coord.get_float.return_value = 66.24
        self.assertEqual(_get_z1_room_humidity(coord), 66.2)

        for invalid in (None, 0.0, -1.0, 100.5, 255.0):
            coord.get_float.return_value = invalid
            self.assertIsNone(_get_z1_room_humidity(coord))


if __name__ == "__main__":
    unittest.main()
