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
    CIRCUIT_HMU,
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
    _get_vwzio_secondary_hwc_status,
    _get_z1_actual_desired_filtered,
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

    def test_wireless_room_target_is_stable_mirror_of_z1manualtemp(self) -> None:
        """The thermostat target sensor mirrors Z1ManualTemp and keeps its legacy unique_id."""
        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "wireless_room_target_temp"
        )
        self.assertEqual(desc.message, "Z1ManualTemp")
        self.assertIsNone(desc.fallback_message)
        self.assertEqual(desc.unique_id_suffix, "04_roomtargettemp_temp")

    def test_primary_flow_rate_field_alignment_and_unique_id(self) -> None:
        """Primary flow rate aligns with upstream 08.hmux0.csv ('value') while preserving legacy fallback and unique_id."""
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "primary_flow_rate")
        self.assertEqual(desc.message, "RunDataFlowRate")
        self.assertEqual(desc.field, "value")
        self.assertEqual(desc.fallback_field, "flow_rate")
        self.assertEqual(desc.unique_id_suffix, "hmux0_rundataflowrate_value")

    def test_aux_heater_switches_alignment_and_unique_id(self) -> None:
        """Auxiliary heater switches aligns with upstream RunStatsAuxHeaterSwitches while preserving legacy unique_id."""
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "stats_hc_starts")
        self.assertEqual(desc.message, "RunStatsAuxHeaterSwitches")
        self.assertEqual(desc.fallback_message, "RunStatsAuxHeaterSwitches")
        self.assertEqual(desc.unique_id_suffix, "hmux0_runstatshcstarts_value")

    def test_electric_power_consumption_alignment_and_unique_id(self) -> None:
        """Electric power consumption prioritizes RunDataElectricPowerConsumption while preserving legacy unique_id."""
        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "electric_power_consumption"
        )
        self.assertEqual(desc.message, "RunDataElectricPowerConsumption")
        self.assertEqual(desc.field, "power")
        self.assertEqual(desc.fallback_message, "PowerStatus")
        self.assertEqual(desc.fallback_field, "power")
        self.assertEqual(
            desc.unique_id_suffix, "hmux0_rundataelectricpowerconsumption_power"
        )
        self.assertIsNotNone(desc.value_fn)

        from unittest.mock import MagicMock

        coord = MagicMock()
        coord.active_outdoor_circuit = CIRCUIT_HMUX0

        # Case 1: Neither exists -> returns None
        coord.get_instantaneous_electric_power.return_value = None
        self.assertIsNone(_get_electric_power(coord))

        # Case 2: Only PowerStatus exists -> returns fallback
        coord.get_instantaneous_electric_power.return_value = 456.7
        self.assertEqual(_get_electric_power(coord), 456.7)

        # Case 3: Both exist -> RunDataElectricPowerConsumption (active high-frequency r1) MUST take precedence
        coord.get_instantaneous_electric_power.return_value = 123.4
        self.assertEqual(_get_electric_power(coord), 123.4)

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

    def test_quick_veto_remaining_time_sensor_description(self) -> None:
        """Verify unified quick_veto_remaining_time sensor definition and subscriptions."""
        from unittest.mock import MagicMock

        from homeassistant.components.sensor import (
            SensorDeviceClass,
            SensorStateClass,
        )
        from homeassistant.const import UnitOfTime

        from custom_components.arotherm_genia_ebusd.const import (
            CALC_CIRCUIT,
            CIRCUIT_BASS3,
            DEVICE_CLIMATE_CONTROLLER,
        )
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor

        descs = [d for d in SENSOR_DESCRIPTIONS if d.key == "quick_veto_remaining_time"]
        self.assertEqual(len(descs), 1)
        desc = descs[0]
        self.assertEqual(desc.device_key, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(desc.circuit, CALC_CIRCUIT)
        self.assertEqual(desc.device_class, SensorDeviceClass.DURATION)
        self.assertEqual(desc.state_class, SensorStateClass.MEASUREMENT)
        self.assertEqual(desc.native_unit_of_measurement, UnitOfTime.MINUTES)

        mock_coord = MagicMock()
        mock_coord.entry_id = "test_entry"
        mock_coord.get_quick_veto_remaining_minutes.return_value = 45
        mock_coord.get_quick_veto_remaining_attributes.return_value = {
            "is_active": True,
            "veto_type": "cooling",
            "end_time": "2026-11-15T20:00:00",
            "target_temperature": 19.0,
            "remaining_minutes": 45,
        }
        sensor_ent = SaunierGeniaSensor(mock_coord, desc)
        self.assertEqual(sensor_ent.native_value, 45)
        self.assertEqual(sensor_ent.native_unit_of_measurement, UnitOfTime.MINUTES)
        self.assertEqual(
            sensor_ent.extra_state_attributes,
            {
                "is_active": True,
                "veto_type": "cooling",
                "end_time": "2026-11-15T20:00:00",
                "target_temperature": 19.0,
                "remaining_minutes": 45,
            },
        )
        self.assertIn((CALC_CIRCUIT, "QuickVetoRemaining"), sensor_ent._subscriptions)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode"), sensor_ent._subscriptions)
        self.assertIn((CIRCUIT_BASS3, "Z1OpModeCooling"), sensor_ent._subscriptions)

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

    def test_subcooling_sensor_subscriptions_and_value(self) -> None:
        """Verify subcooling sensor subscribes to condensation and condensate temperatures."""
        from unittest.mock import MagicMock

        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor

        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "subcooling")
        mock_coord = MagicMock()
        mock_coord.entry.entry_id = "test_entry"
        mock_coord.get_float.side_effect = lambda c, m, _f: {
            (CIRCUIT_HMUX0, "RunDataCondensationTemp"): 42.5,
            (CIRCUIT_HMUX0, "RunDataCondensateTemp"): 37.2,
        }.get((c, m))

        sensor_ent = SaunierGeniaSensor(mock_coord, desc)
        for expected_sub in (
            (CIRCUIT_HMUX0, "RunDataCondensationTemp"),
            (CIRCUIT_HMUX0, "RunDataCondensateTemp"),
            (CIRCUIT_HMU, "RunDataCondensationTemp"),
            (CIRCUIT_HMU, "RunDataCondensateTemp"),
        ):
            self.assertIn(expected_sub, sensor_ent._subscriptions)
        self.assertEqual(sensor_ent.native_value, 5.3)

    def test_vwzio_secondary_hwc_and_z1_desired_sentinel_filters(self) -> None:
        """Verify vwzio_secondary_circuit_hwc subscriptions/parsing and Z1 5°C sentinel filtering."""
        from unittest.mock import MagicMock

        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor

        hwc_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "vwzio_secondary_circuit_hwc"
        )
        mock_coord = MagicMock()
        mock_coord.entry.entry_id = "test_entry"
        hwc_ent = SaunierGeniaSensor(mock_coord, hwc_desc)
        self.assertIn((CIRCUIT_VWZIO, "Status01"), hwc_ent._subscriptions)

        mock_coord.get_str.side_effect = lambda _c, m, _f: {
            "Status01": None,
            "SecondaryCircuitStatusHwc": "00 00",
        }.get(m)
        self.assertEqual(_get_vwzio_secondary_hwc_status(mock_coord), "standby")

        mock_coord.get_str.side_effect = lambda _c, m, _f: {
            "Status01": None,
            "SecondaryCircuitStatusHwc": "standby",
        }.get(m)
        self.assertEqual(_get_vwzio_secondary_hwc_status(mock_coord), "standby")

        mock_coord.get_str.side_effect = lambda _c, m, _f: {
            "Status01": None,
            "SecondaryCircuitStatusHwc": "ERR: element not found",
        }.get(m)
        self.assertIsNone(_get_vwzio_secondary_hwc_status(mock_coord))

        mock_coord.get_str.side_effect = lambda _c, m, _f: {
            "Status01": None,
            "SecondaryCircuitStatusHwc": "20 00",
        }.get(m)
        self.assertEqual(_get_vwzio_secondary_hwc_status(mock_coord), "dhw")

        # Z1ActualRoomTempDesired sentinel checks
        coord_z1 = MagicMock()
        coord_z1.get_float.side_effect = lambda _c, m, _f: (
            5.0 if m == "Z1ActualRoomTempDesired" else 21.5
        )
        coord_z1.get_str.return_value = "auto"
        self.assertIsNone(_get_z1_actual_desired_filtered(coord_z1))

        coord_z1.get_str.return_value = "day"
        self.assertEqual(_get_z1_actual_desired_filtered(coord_z1), 5.0)

        coord_z1.get_str.return_value = "off"
        self.assertIsNone(_get_z1_actual_desired_filtered(coord_z1))

    def test_vwzio_secondary_status_unhydrated_and_subscriptions(self) -> None:
        """vwzio_secondary_circuit_status returns None when unhydrated and subscribes Hc1PumpStatus."""
        from unittest.mock import MagicMock

        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            _get_vwzio_secondary_status,
        )

        coord = MagicMock()
        coord.entry.entry_id = "test_entry"
        coord.get_str.return_value = None
        coord.get_int.return_value = None
        self.assertIsNone(_get_vwzio_secondary_status(coord))
        self.assertIsNone(_get_vwzio_secondary_hwc_status(coord))

        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "vwzio_secondary_circuit_status"
        )
        ent = SaunierGeniaSensor(coord, desc)
        self.assertIn((CIRCUIT_BASS3, "Hc1PumpStatus"), ent._subscriptions)
        self.assertIn((CIRCUIT_BASS3, "CoolingReleaseStatus"), ent._subscriptions)

    def test_stats_hwc_starts_has_vwzio_fallback(self) -> None:
        """stats_hwc_starts falls back to 76.vwzio RunStatsHwcStarts when hmux0 has no value."""
        from unittest.mock import MagicMock

        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor

        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "stats_hwc_starts")
        self.assertEqual(desc.fallback_circuit, CIRCUIT_VWZIO)
        self.assertEqual(desc.fallback_message, "RunStatsHwcStarts")
        self.assertEqual(desc.fallback_field, "value")

        mock_coord = MagicMock()
        mock_coord.entry.entry_id = "test_entry"
        mock_coord.get_int.side_effect = lambda c, m, _f: (
            42 if (c == CIRCUIT_VWZIO and m == "RunStatsHwcStarts") else None
        )
        sensor_ent = SaunierGeniaSensor(mock_coord, desc)
        self.assertIn((CIRCUIT_VWZIO, "RunStatsHwcStarts"), sensor_ent._subscriptions)
        self.assertEqual(sensor_ent.native_value, 42)

    def test_stats_sensors_are_diagnostic_and_hc1_pump_is_primary(self) -> None:
        """Verify all stats_* counters use EntityCategory.DIAGNOSTIC while hc1_pump_status stays primary."""
        from homeassistant.const import EntityCategory

        stats_descs = [d for d in SENSOR_DESCRIPTIONS if d.key.startswith("stats_")]
        self.assertEqual(len(stats_descs), 29)
        for desc in stats_descs:
            self.assertEqual(
                desc.entity_category,
                EntityCategory.DIAGNOSTIC,
                f"Expected {desc.key} to have EntityCategory.DIAGNOSTIC",
            )

        hc1_pump = next(d for d in SENSOR_DESCRIPTIONS if d.key == "hc1_pump_status")
        self.assertIsNone(hc1_pump.entity_category)

    def test_delta_sensors_use_celsius_and_temperature_delta(self) -> None:
        """Verify temperature-delta sensors use UnitOfTemperature.CELSIUS instead of legacy K."""
        from homeassistant.components.sensor import SensorDeviceClass
        from homeassistant.const import UnitOfTemperature

        expected_delta_keys = {"calculated_delta_t", "superheat", "subcooling"}
        expected_dc = getattr(SensorDeviceClass, "TEMPERATURE_DELTA", None)
        found = set()
        for desc in SENSOR_DESCRIPTIONS:
            self.assertNotEqual(
                desc.native_unit_of_measurement,
                "K",
                f"Unexpected legacy Kelvin unit on {desc.key}",
            )
            if desc.key in expected_delta_keys:
                found.add(desc.key)
                self.assertEqual(
                    desc.native_unit_of_measurement, UnitOfTemperature.CELSIUS
                )
                self.assertEqual(desc.device_class, expected_dc)
        self.assertEqual(found, expected_delta_keys)

    def test_dew_point_and_additional_csv_entities_registered(self) -> None:
        """Verify newly added documented CSV sensors, binary sensors, numbers, and switches."""
        from custom_components.arotherm_genia_ebusd.const import (
            ESSENTIAL_HYDRATION_MESSAGES,
            HMUX0_EXCLUSIVE_MESSAGES,
        )

        sensor_keys = {d.key for d in SENSOR_DESCRIPTIONS}
        self.assertTrue(
            {
                "energy_env_yield_cool",
                "hc1_circuit_type",
                "hc1_heat_curve_adaptation",
                "hc1_mixer_movement",
                "multi_relay_setting",
            }.issubset(sensor_keys)
        )
        self.assertIn("PrEnergyEnvYieldCool", HMUX0_EXCLUSIVE_MESSAGES)

        binary_keys = {d.key for d in BINARY_SENSOR_DESCRIPTIONS}
        self.assertTrue({"maintenance_due", "app_session_status"}.issubset(binary_keys))

        number_keys = {d.key for d in NUMBER_DESCRIPTIONS}
        self.assertTrue(
            {
                "dew_point_offset",
                "cooling_outside_temp_threshold",
                "offset_outside_temp",
                "continuous_heating_threshold",
                "frost_override_time",
            }.issubset(number_keys)
        )

        switch_keys = {d.key for d in STANDARD_SWITCH_DESCRIPTIONS}
        self.assertIn("dew_point_monitoring", switch_keys)

        hydrated_msgs = {m for _c, m in ESSENTIAL_HYDRATION_MESSAGES}
        self.assertTrue(
            {
                "DewPointMonitoring",
                "DewPointOffset",
                "Hc1CoolingEnabled",
                "Hc1DewPointOffset",
                "Z1TimeSlotActive",
                "Z1CoolingTimeSlotActive",
                "Z1QuickVetoEndTime",
                "Z1QuickVetoEndDate",
                "CoolingOutsideTempThreshold",
                "OffsetOutsideTemp",
                "ContinuosHeating",
                "FrostOverRideTime",
                "MultiRelaySetting",
                "MaintenanceDue",
                "Hc1CircuitType",
                "Hc1MixerMovement",
                "Hc1HeatCurveAdaption",
                "AppSessionStatus",
                "PrEnergyEnvYieldCool",
            }.issubset(hydrated_msgs)
        )

    def test_venting_pumpstate_subcooling_and_bass3_entities(self) -> None:
        """Verify venting pumpstate mapping, direct SubcoolingTemp priority, and new BASS3 entities."""
        from datetime import datetime, timedelta
        from unittest.mock import MagicMock

        from homeassistant.util import dt as dt_util

        from custom_components.arotherm_genia_ebusd.const import (
            VWZIO_SECONDARY_STATUS_OPTIONS,
        )
        from custom_components.arotherm_genia_ebusd.coordinator import (
            SaunierGeniaCoordinator,
        )
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            _get_subcooling,
            _get_vwzio_secondary_status,
        )

        # 1. pumpstate 8 / venting mapped in both secondary status helpers and options
        self.assertIn("venting", VWZIO_SECONDARY_STATUS_OPTIONS)
        mock_coord = MagicMock()
        mock_coord.get_str.side_effect = lambda _c, m, _f: (
            "venting" if m == "Status01" else None
        )
        self.assertEqual(_get_vwzio_secondary_status(mock_coord), "venting")
        self.assertEqual(_get_vwzio_secondary_hwc_status(mock_coord), "standby")

        mock_coord.get_str.side_effect = lambda _c, m, _f: (
            "8" if m == "Status01" else None
        )
        self.assertEqual(_get_vwzio_secondary_status(mock_coord), "venting")
        self.assertEqual(_get_vwzio_secondary_hwc_status(mock_coord), "standby")

        # 2. Subcooling prefers direct D.375 SubcoolingTemp when present
        sub_coord = MagicMock()
        sub_coord.entry.entry_id = "test_entry"
        sub_coord.get_float.side_effect = lambda c, m, _f: {
            (CIRCUIT_HMUX0, "SubcoolingTemp"): 6.25,
            (CIRCUIT_HMUX0, "RunDataCondensationTemp"): 42.5,
            (CIRCUIT_HMUX0, "RunDataCondensateTemp"): 37.2,
        }.get((c, m))
        self.assertEqual(_get_subcooling(sub_coord), 6.25)

        sub_desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "subcooling")
        sub_ent = SaunierGeniaSensor(sub_coord, sub_desc)
        self.assertIn((CIRCUIT_HMUX0, "SubcoolingTemp"), sub_ent._subscriptions)
        self.assertIn((CIRCUIT_HMU, "SubcoolingTemp"), sub_ent._subscriptions)

        # 3. New BASS3 binary sensors, switch, and number registered
        binary_by_key = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}
        self.assertIn("z1_time_slot_active", binary_by_key)
        self.assertIn("z1_cooling_time_slot_active", binary_by_key)
        self.assertFalse(
            binary_by_key["z1_cooling_time_slot_active"].entity_registry_enabled_default
        )

        slot_coord = MagicMock()
        slot_coord.get_str.return_value = "yes"
        self.assertTrue(binary_by_key["z1_time_slot_active"].is_on_fn(slot_coord))
        slot_coord.get_str.return_value = "no"
        self.assertFalse(
            binary_by_key["z1_cooling_time_slot_active"].is_on_fn(slot_coord)
        )

        switch_keys = {d.key for d in STANDARD_SWITCH_DESCRIPTIONS}
        self.assertIn("hc1_cooling_enabled", switch_keys)
        number_keys = {d.key for d in NUMBER_DESCRIPTIONS}
        self.assertIn("hc1_dew_point_offset", number_keys)

        # 4. Hardware Z1QuickVetoEndDate + Z1QuickVetoEndTime parsed when veto active
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_veto_hw"
        entry.data = {}
        coord = SaunierGeniaCoordinator(hass, entry)
        future_dt = datetime.now(tz=dt_util.get_default_time_zone()) + timedelta(
            minutes=45
        )
        coord._state[(CIRCUIT_BASS3, "Z1SFMode")] = {"value": "veto"}
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoTemp")] = {"value": 23.0}
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoEndDate")] = {
            "value": future_dt.strftime("%d.%m.%Y")
        }
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoEndTime")] = {
            "value": future_dt.strftime("%H:%M:%S")
        }
        rem = coord.get_quick_veto_remaining_minutes()
        attrs = coord.get_quick_veto_remaining_attributes()
        self.assertIsNotNone(rem)
        assert rem is not None
        self.assertGreaterEqual(rem, 44)
        self.assertLessEqual(rem, 46)
        self.assertTrue(attrs["is_active"])
        self.assertIsNotNone(attrs["end_time"])

        # Placeholder date (year 2019, observed on BASS3 when idle) is ignored cleanly
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoEndDate")] = {"value": "01.01.2019"}
        self.assertIsNone(coord.get_quick_veto_remaining_minutes())

        # 5. Unified active_fault binary sensor aggregates Currenterror across boards
        from custom_components.arotherm_genia_ebusd.binary_sensor import (
            SaunierGeniaBinarySensor,
        )

        fault_desc = binary_by_key["active_fault"]
        fault_ent = SaunierGeniaBinarySensor(coord, fault_desc)
        self.assertIn((CIRCUIT_HMUX0, "Currenterror"), fault_ent._subscriptions)
        self.assertIn((CIRCUIT_BASS3, "Currenterror"), fault_ent._subscriptions)
        self.assertIn((CIRCUIT_VWZIO, "Currenterror"), fault_ent._subscriptions)
        self.assertIsNone(fault_ent.is_on)

        coord._state[(CIRCUIT_HMUX0, "Currenterror")] = {"error": "-"}
        coord._state[(CIRCUIT_BASS3, "Currenterror")] = {"error": "0"}
        coord._state[(CIRCUIT_VWZIO, "Currenterror")] = {"error": "-"}
        self.assertFalse(fault_ent.is_on)
        self.assertEqual(
            fault_ent.extra_state_attributes,
            {
                "outdoor_unit": "OK",
                "climate_controller": "OK",
                "hydraulic_interface": "OK",
            },
        )

        coord._state[(CIRCUIT_HMUX0, "Currenterror")] = {"error": "733"}
        self.assertTrue(fault_ent.is_on)
        self.assertEqual(
            fault_ent.extra_state_attributes,
            {
                "outdoor_unit": "733",
                "climate_controller": "OK",
                "hydraulic_interface": "OK",
            },
        )

    def test_system_health_alert_and_hmu_fault_status_codes(self) -> None:
        """Verify active_fault HMUStatusCode fault detection and aggregated system_health_alert."""
        from unittest.mock import MagicMock

        from custom_components.arotherm_genia_ebusd.binary_sensor import (
            SaunierGeniaBinarySensor,
        )
        from custom_components.arotherm_genia_ebusd.const import (
            CIRCUIT_GLOBAL,
            CIRCUIT_HMU,
            HMU_FAULT_STATUS_CODES,
            HMU_STATUS_CODES,
        )
        from custom_components.arotherm_genia_ebusd.coordinator import (
            SaunierGeniaCoordinator,
        )

        # Every fault status code must be a valid member of HMU_STATUS_CODES
        self.assertTrue(HMU_FAULT_STATUS_CODES.issubset(set(HMU_STATUS_CODES)))

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_health_alert"
        entry.data = {}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)

        binary_by_key = {d.key: d for d in BINARY_SENSOR_DESCRIPTIONS}
        fault_ent = SaunierGeniaBinarySensor(coord, binary_by_key["active_fault"])
        health_ent = SaunierGeniaBinarySensor(
            coord, binary_by_key["system_health_alert"]
        )

        # Subscriptions cover Currenterror, HMUStatusCode, WaterPressure/FlowPressure, and eBUS status
        self.assertIn((CIRCUIT_HMUX0, "HMUStatusCode"), fault_ent._subscriptions)
        for required_sub in (
            (CIRCUIT_HMUX0, "Currenterror"),
            (CIRCUIT_HMUX0, "HMUStatusCode"),
            (CIRCUIT_HMU, "FlowPressure"),
            (CIRCUIT_BASS3, "Currenterror"),
            (CIRCUIT_BASS3, "WaterPressure"),
            (CIRCUIT_VWZIO, "Currenterror"),
            (CIRCUIT_GLOBAL, "running"),
            (CIRCUIT_GLOBAL, "signal"),
        ):
            self.assertIn(required_sub, health_ent._subscriptions)

        # Unhydrated state returns None (no false startup alert)
        self.assertIsNone(fault_ent.is_on)
        self.assertIsNone(health_ent.is_on)

        # Healthy state
        coord._state[(CIRCUIT_GLOBAL, "running")] = {"value": "true"}
        coord._state[(CIRCUIT_GLOBAL, "signal")] = {"value": "true"}
        coord._state[(CIRCUIT_HMUX0, "Currenterror")] = {"error": "-"}
        coord._state[(CIRCUIT_BASS3, "Currenterror")] = {"error": "0"}
        coord._state[(CIRCUIT_VWZIO, "Currenterror")] = {"error": "-"}
        coord._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {"status": "standby"}
        coord._state[(CIRCUIT_BASS3, "WaterPressure")] = {"press": 1.5}
        self.assertFalse(fault_ent.is_on)
        self.assertFalse(health_ent.is_on)
        attrs = health_ent.extra_state_attributes
        self.assertIsNotNone(attrs)
        assert attrs is not None
        self.assertEqual(attrs["alerts"], [])
        self.assertEqual(attrs["alert_count"], 0)
        self.assertTrue(attrs["ebus_operational"])
        self.assertEqual(attrs["water_pressure_bar"], 1.5)

        # Transient ambient statuses (wind / current limit) do NOT trigger faults
        for non_fault in ("fan1_wind", "fan2_wind", "current_limt_active"):
            coord._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {"status": non_fault}
            self.assertFalse(fault_ent.is_on)
            self.assertFalse(health_ent.is_on)

        # Genuine HMUStatusCode fault triggers BOTH active_fault and system_health_alert
        coord._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {
            "status": "building_circuit_flow_too_low"
        }
        self.assertTrue(fault_ent.is_on)
        self.assertEqual(
            (fault_ent.extra_state_attributes or {}).get("hmu_fault_status"),
            "building_circuit_flow_too_low",
        )
        self.assertTrue(health_ent.is_on)
        self.assertIn(
            "hmu_status_fault", (health_ent.extra_state_attributes or {})["alerts"]
        )

        # Restore HMU status; test low & high water pressure (including FlowPressure fallback)
        coord._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {"status": "standby"}
        coord._state[(CIRCUIT_BASS3, "WaterPressure")] = {"press": 0.7}
        self.assertFalse(fault_ent.is_on)
        self.assertTrue(health_ent.is_on)
        self.assertEqual(
            (health_ent.extra_state_attributes or {})["alerts"],
            ["low_water_pressure"],
        )

        coord._state.pop((CIRCUIT_BASS3, "WaterPressure"))
        coord._state[(CIRCUIT_HMUX0, "FlowPressure")] = {"value": 2.9}
        self.assertTrue(health_ent.is_on)
        self.assertEqual(
            (health_ent.extra_state_attributes or {})["alerts"],
            ["high_water_pressure"],
        )

        # Restore pressure; test eBUS offline detection
        coord._state[(CIRCUIT_HMUX0, "FlowPressure")] = {"value": 1.6}
        coord._state[(CIRCUIT_GLOBAL, "signal")] = {"value": "false"}
        self.assertTrue(health_ent.is_on)
        self.assertEqual(
            (health_ent.extra_state_attributes or {})["alerts"],
            ["ebus_offline"],
        )
        self.assertFalse((health_ent.extra_state_attributes or {})["ebus_operational"])

    def test_official_automation_blueprints_integrity(self) -> None:
        """Verify official Home Assistant blueprints declare valid metadata and matching !input refs."""
        import re
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        bp_dir = repo_root / "blueprints" / "automation"
        expected_files = {
            "system_health_alerts.yaml",
            "pv_surplus_dhw_boost.yaml",
        }
        actual_files = {p.name for p in bp_dir.glob("*.yaml")}
        self.assertEqual(actual_files, expected_files)

        for filename in sorted(expected_files):
            path = bp_dir / filename
            raw = path.read_bytes()
            self.assertNotIn(
                b"\r\n", raw, f"Blueprint {filename} must use Unix LF line endings"
            )
            text = raw.decode("utf-8")
            self.assertIn("domain: automation", text)
            self.assertIn(
                f"source_url: https://github.com/R91g/arotherm-genia-ebusd/blob/main/blueprints/automation/{filename}",
                text,
            )

            # Extract declared inputs under blueprint -> input: (4-space indented keys)
            input_block = re.search(
                r"^  input:\n((?:    .*\n|\n)+?)(?=^\S)", text, re.MULTILINE
            )
            self.assertIsNotNone(input_block, f"Missing input block in {filename}")
            assert input_block is not None
            declared_inputs = set(
                re.findall(
                    r"^    ([a-zA-Z0-9_]+):$", input_block.group(1), re.MULTILINE
                )
            )
            referenced_inputs = set(re.findall(r"!input\s+([a-zA-Z0-9_]+)", text))
            self.assertTrue(
                referenced_inputs.issubset(declared_inputs),
                f"{filename} references undeclared !input(s): {referenced_inputs - declared_inputs}",
            )


if __name__ == "__main__":
    unittest.main()
