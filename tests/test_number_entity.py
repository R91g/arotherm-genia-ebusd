"""Unit tests for the Number platform and CompressorSilentOperationLevel slider."""

import os
import sys
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.components.number import NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory

from custom_components.arotherm_genia_ebusd.const import (
    CIRCUIT_BASS3,
    CIRCUIT_HMUX0,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
    MANUFACTURER_VAILLANT,
    SENTINEL_COOLING_THRESHOLD,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator
from custom_components.arotherm_genia_ebusd.number import (
    NUMBER_DESCRIPTIONS,
    SaunierGeniaNumber,
    SaunierGeniaQuickVetoBoostDeltaNumber,
    async_setup_entry,
)


class TestNumberPlatform(unittest.IsolatedAsyncioTestCase):
    """Test suite for Number platform entities."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.hass = MagicMock()
        self.hass.data = {}
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry_number"
        self.entry.data = {
            CONF_MQTT_PREFIX: "ebusd",
            CONF_MANUFACTURER: MANUFACTURER_VAILLANT,
        }
        self.entry.options = {}
        self.coordinator = SaunierGeniaCoordinator(self.hass, self.entry)
        self.hass.data[DOMAIN] = {self.entry.entry_id: self.coordinator}

    def test_number_descriptions_structure(self) -> None:
        """Verify that NUMBER_DESCRIPTIONS contains valid and expected definitions."""
        self.assertEqual(len(NUMBER_DESCRIPTIONS), 27)

        keys = [d.key for d in NUMBER_DESCRIPTIONS]
        self.assertEqual(
            len(keys), len(set(keys)), "Duplicate keys in NUMBER_DESCRIPTIONS"
        )
        self.assertIn("z1_quick_veto_duration", keys)

        # Verify compressor_silent_operation_level specifics
        silent_desc = next(
            (
                d
                for d in NUMBER_DESCRIPTIONS
                if d.key == "compressor_silent_operation_level"
            ),
            None,
        )
        self.assertIsNotNone(silent_desc)
        assert silent_desc is not None
        self.assertEqual(
            silent_desc.translation_key, "compressor_silent_operation_level"
        )
        self.assertEqual(silent_desc.device_key, DEVICE_OUTDOOR_UNIT)
        self.assertEqual(silent_desc.circuit, CIRCUIT_HMUX0)
        self.assertEqual(silent_desc.message, "CompressorSilentOperationLevel")
        self.assertEqual(silent_desc.field, "value")
        self.assertEqual(silent_desc.native_min_value, 30.0)
        self.assertEqual(silent_desc.native_max_value, 60.0)
        self.assertEqual(silent_desc.native_step, 1.0)
        self.assertEqual(silent_desc.native_unit_of_measurement, PERCENTAGE)
        self.assertEqual(silent_desc.mode, NumberMode.BOX)
        self.assertEqual(silent_desc.entity_category, EntityCategory.CONFIG)
        self.assertTrue(silent_desc.is_integer)

        # Verify max_cylinder_charge_time supports 0 (Off) and 15 min (observed on VRC 720 BASV3)
        charge_desc = next(
            (d for d in NUMBER_DESCRIPTIONS if d.key == "max_cylinder_charge_time"),
            None,
        )
        self.assertIsNotNone(charge_desc)
        assert charge_desc is not None
        self.assertEqual(charge_desc.native_min_value, 0)
        self.assertEqual(charge_desc.native_max_value, 180)
        self.assertEqual(charge_desc.native_step, 5)

        # Verify all entities stay strictly in NumberMode.BOX
        for d in NUMBER_DESCRIPTIONS:
            self.assertEqual(
                d.mode,
                NumberMode.BOX,
                f"Entity {d.key} must strictly use NumberMode.BOX",
            )
            if d.key != "compressor_silent_operation_level":
                self.assertEqual(
                    d.device_key,
                    DEVICE_CLIMATE_CONTROLLER,
                    f"Entity {d.key} must be attached to climate controller",
                )

    async def test_async_setup_entry(self) -> None:
        """Verify that async_setup_entry registers all number entities correctly."""
        added_entities: list[SaunierGeniaNumber] = []

        def mock_add_entities(entities: Any) -> None:
            added_entities.extend(entities)

        await async_setup_entry(self.hass, self.entry, mock_add_entities)
        self.assertEqual(len(added_entities), 28)

        # Check boost delta entity setup
        boost_delta_entity = next(
            (
                e
                for e in added_entities
                if isinstance(e, SaunierGeniaQuickVetoBoostDeltaNumber)
            ),
            None,
        )
        self.assertIsNotNone(boost_delta_entity)
        assert boost_delta_entity is not None
        self.assertEqual(boost_delta_entity.native_value, 3.0)

        # Check veto duration entity setup
        veto_dur_entity = next(
            (
                e
                for e in added_entities
                if e.entity_description.key == "z1_quick_veto_duration"
            ),
            None,
        )
        self.assertIsNotNone(veto_dur_entity)
        self.assertEqual(
            veto_dur_entity.entity_description.message, "Z1QuickVetoDuration"
        )

        # Check silent level entity setup
        silent_entity = next(
            (
                e
                for e in added_entities
                if e.entity_description.key == "compressor_silent_operation_level"
            ),
            None,
        )
        self.assertIsNotNone(silent_entity)
        assert silent_entity is not None
        self.assertEqual(silent_entity.mode, NumberMode.BOX)
        self.assertTrue(
            silent_entity.unique_id.endswith(
                "number_hmux0_compressorsilentoperationlevel_value"
            )
        )
        self.assertEqual(
            silent_entity.device_info["identifiers"],
            {(DOMAIN, f"{self.entry.entry_id}_{DEVICE_OUTDOOR_UNIT}")},
        )

    async def test_compressor_silent_operation_level_read_and_write_split_hmu(
        self,
    ) -> None:
        """Verify live reading and writing on Split HMU systems (aliased from HMUX0)."""
        silent_desc = next(
            d
            for d in NUMBER_DESCRIPTIONS
            if d.key == "compressor_silent_operation_level"
        )
        entity = SaunierGeniaNumber(self.coordinator, silent_desc)

        # Initial state is None before telemetry arrives
        self.assertIsNone(entity.native_value)

        # Telemetry arrives on ebusd/hmu/CompressorSilentOperationLevel (Split unit, e.g. 33% on VWL 55/6 A)
        msg = MagicMock()
        msg.topic = "ebusd/hmu/CompressorSilentOperationLevel"
        msg.payload = '{"value": {"value": 33}}'
        self.coordinator._async_on_mqtt_message(msg)

        # Native value must reflect 33.0% and lie cleanly within [native_min_value, native_max_value]
        self.assertEqual(entity.native_value, 33.0)
        self.assertGreaterEqual(entity.native_value, entity.native_min_value)
        self.assertLessEqual(entity.native_value, entity.native_max_value)

        # Setting value to 50 via async_set_native_value on HMU Split
        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as mock_pub:
            await entity.async_set_native_value(50.0)

            # Target circuit must resolve to active outdoor circuit 'hmu'
            mock_pub.assert_called_once_with(
                self.hass,
                "ebusd/hmu/CompressorSilentOperationLevel/set",
                "50",
                qos=0,
                retain=False,
            )

            # Optimistic state update immediately reflects 50.0%
            self.assertEqual(entity.native_value, 50.0)

    async def test_compressor_silent_operation_level_read_and_write_monobloc_hmux0(
        self,
    ) -> None:
        """Verify live reading and writing on Monobloc HMUX0 systems."""
        # Ensure active outdoor circuit is HMUX0
        self.coordinator._active_outdoor_circuit = CIRCUIT_HMUX0

        silent_desc = next(
            d
            for d in NUMBER_DESCRIPTIONS
            if d.key == "compressor_silent_operation_level"
        )
        entity = SaunierGeniaNumber(self.coordinator, silent_desc)

        # Telemetry arrives on ebusd/hmux0/CompressorSilentOperationLevel (Monobloc unit)
        msg = MagicMock()
        msg.topic = "ebusd/hmux0/CompressorSilentOperationLevel"
        msg.payload = '{"value": {"value": 40}}'
        self.coordinator._async_on_mqtt_message(msg)

        # Native value must reflect 40.0%
        self.assertEqual(entity.native_value, 40.0)

        # Setting value to 55 via async_set_native_value on HMUX0 Monobloc
        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as mock_pub:
            await entity.async_set_native_value(55.0)

            # Target circuit must resolve to 'hmux0'
            mock_pub.assert_called_once_with(
                self.hass,
                "ebusd/hmux0/CompressorSilentOperationLevel/set",
                "55",
                qos=0,
                retain=False,
            )

            # Optimistic update immediately reflects 55.0%
            self.assertEqual(entity.native_value, 55.0)

    def test_number_availability_gates_on_ebus_operational(self) -> None:
        """Verify that number entities become unavailable when eBUS communication is down."""
        silent_desc = next(
            d
            for d in NUMBER_DESCRIPTIONS
            if d.key == "compressor_silent_operation_level"
        )
        entity = SaunierGeniaNumber(self.coordinator, silent_desc)

        # By default coordinator is not operational until telemetry arrives
        self.assertFalse(entity.available)

        # Telemetry arrives, marks eBUS operational
        msg = MagicMock()
        msg.topic = "ebusd/hmu/CompressorSilentOperationLevel"
        msg.payload = '{"value": {"value": 50}}'
        self.coordinator._async_on_mqtt_message(msg)

        self.assertTrue(self.coordinator.is_ebus_operational)
        self.assertTrue(entity.available)

    async def test_controller_number_box_mode_and_anti_sentinel(self) -> None:
        """Verify standard climate controller setpoints behavior and anti-sentinel filtering."""
        # 1. Heating curve (float setpoint)
        hc_desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == "hc1_heat_curve")
        hc_entity = SaunierGeniaNumber(self.coordinator, hc_desc)
        self.assertEqual(hc_entity.mode, NumberMode.BOX)

        msg = MagicMock()
        msg.topic = "ebusd/bass3/Hc1HeatCurve"
        msg.payload = '{"value": {"value": 1.25}}'
        self.coordinator._async_on_mqtt_message(msg)
        self.assertEqual(hc_entity.native_value, 1.25)

        # 2. Cooling manual temp anti-sentinel
        cooling_desc = next(
            d for d in NUMBER_DESCRIPTIONS if d.key == "z1_cooling_temp_manual"
        )
        cooling_entity = SaunierGeniaNumber(self.coordinator, cooling_desc)

        # Valid temperature
        msg = MagicMock()
        msg.topic = "ebusd/bass3/Z1CoolingTempDesired"
        msg.payload = '{"value": {"value": 24.5}}'
        self.coordinator._async_on_mqtt_message(msg)
        self.assertEqual(cooling_entity.native_value, 24.5)

        # Sentinel value (>= SENTINEL_COOLING_THRESHOLD, e.g. 99.0)
        msg.payload = f'{{"value": {{"value": {SENTINEL_COOLING_THRESHOLD}}}}}'
        self.coordinator._async_on_mqtt_message(msg)
        # Must retain last valid cooling value
        self.assertEqual(cooling_entity.native_value, 24.5)

    async def test_quick_veto_duration_in_veto_mode_rearms_veto(self) -> None:
        """Verify that changing quick veto duration while in veto re-arms veto mode."""
        dur_desc = next(
            d for d in NUMBER_DESCRIPTIONS if d.key == "z1_quick_veto_duration"
        )
        dur_entity = SaunierGeniaNumber(self.coordinator, dur_desc)

        written: list[tuple[str, str, Any]] = []

        async def mock_write(circuit: str, param: str, val: Any) -> bool:
            written.append((circuit, param, val))
            self.coordinator._state[(circuit.lower(), param.lower())] = {"value": val}
            return True

        self.coordinator.async_write_parameter = mock_write

        # 1. When NOT in veto: simply writes duration parameter
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
        await dur_entity.async_set_native_value(2.0)
        self.assertEqual(written, [(CIRCUIT_BASS3, "Z1QuickVetoDuration", 2.0)])

        # 2. When in veto: writes duration AND re-affirms Z1SFMode = veto
        written.clear()
        self.coordinator._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "veto"}
        await dur_entity.async_set_native_value(4.5)
        self.assertEqual(
            written,
            [
                (CIRCUIT_BASS3, "Z1QuickVetoDuration", 4.5),
                (CIRCUIT_BASS3, "Z1SFMode", "veto"),
            ],
        )

    async def test_quick_veto_boost_delta_entity(self) -> None:
        """Verify SaunierGeniaQuickVetoBoostDeltaNumber functionality and state restoration."""
        delta_entity = SaunierGeniaQuickVetoBoostDeltaNumber(self.coordinator)
        self.assertEqual(delta_entity.native_value, 3.0)
        self.assertEqual(delta_entity.native_min_value, 0.5)
        self.assertEqual(delta_entity.native_max_value, 10.0)
        self.assertEqual(delta_entity.native_step, 0.5)

        # Set new value
        await delta_entity.async_set_native_value(5.0)
        self.assertEqual(delta_entity.native_value, 5.0)
        self.assertEqual(self.coordinator.quick_veto_boost_delta, 5.0)

        # State restoration
        mock_state = MagicMock()
        mock_state.state = "4.5"
        delta_entity._mock_last_state = mock_state
        await delta_entity.async_added_to_hass()
        self.assertEqual(delta_entity.native_value, 4.5)
        self.assertEqual(self.coordinator.quick_veto_boost_delta, 4.5)


if __name__ == "__main__":
    unittest.main()
