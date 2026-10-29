"""Unit tests for sensor registry, entity descriptions, and unique ID integrity."""

from collections import Counter
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.binary_sensor import BINARY_SENSOR_DESCRIPTIONS
from custom_components.arotherm_genia_ebusd.const import (
    CALC_CIRCUIT,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    CIRCUIT_VWZIO,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
)
from custom_components.arotherm_genia_ebusd.number import NUMBER_DESCRIPTIONS
from custom_components.arotherm_genia_ebusd.select import SELECT_DESCRIPTIONS
from custom_components.arotherm_genia_ebusd.sensor_descriptions import SENSOR_DESCRIPTIONS
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
            uid = f"{c}_{m}_{f}"
            uids.append(uid)

        # Check for duplicate unique_id suffixes among standard sensors
        counter = Counter(uids)
        duplicates = {k: v for k, v in counter.items() if v > 1}
        self.assertEqual(duplicates, {}, f"Duplicate sensor unique_ids found: {duplicates}")

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
        self.assertEqual(duplicates, {}, f"Duplicate binary_sensor unique_ids: {duplicates}")

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


if __name__ == "__main__":
    unittest.main()

