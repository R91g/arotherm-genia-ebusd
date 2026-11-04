"""Unit tests for coordinator payload parsing and optimistic update mapping."""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure tests/ directory is on path to load setup_mocks
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hacs"))
)

from custom_components.arotherm_genia_ebusd.__init__ import (
    _async_cleanup_deprecated_entities,
)
from custom_components.arotherm_genia_ebusd.binary_sensor import (
    _check_compressor_active,
    _check_energy_integration,
)
from custom_components.arotherm_genia_ebusd.const import (
    CALC_CIRCUIT,
    CALC_COOL_EER,
    CALC_DHW_TOTAL_ENERGY,
    CALC_GLOBAL_EFFICIENCY,
    CALC_HC_COP,
    CALC_HEATING_TOTAL_ENERGY,
    CALC_HWC_COP,
    CALC_LIVE_COP,
    CALC_SYSTEM_TOTAL_ENERGY,
    CIRCUIT_BASS3,
    CIRCUIT_BASV3,
    CIRCUIT_CTLV2,
    CIRCUIT_CTLV3,
    CIRCUIT_HMU,
    CIRCUIT_HMUX0,
    CONF_MANUFACTURER,
    CONTROLLER_CIRCUITS,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    DOMAIN,
    ISSUE_MISSING_CUSTOM_CSV,
    ISSUE_MQTTJSON_NOT_ENABLED,
    ISSUE_NO_EBUSD_MQTT_TRAFFIC,
    ISSUE_OUTDATED_CONTROLLER_CSV,
    ISSUE_OUTDATED_HMUX0_CSV,
    MANUFACTURER_SAUNIER_DUVAL,
    MANUFACTURER_VAILLANT,
)
from custom_components.arotherm_genia_ebusd.coordinator import (
    DATE_WRITE_FIELDS,
    TIME_WRITE_FIELDS,
    TIMER_WRITE_FIELDS,
    SaunierGeniaCoordinator,
    _coerce_scalar,
    _multi_field_layout,
    parse_ebusd_payload,
)
from custom_components.arotherm_genia_ebusd.entity import build_device_info
from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
    _get_compressor_modulation,
)


class TestCoordinatorLogic(unittest.TestCase):
    """Test coordinator MQTT payload parsing and optimistic field coercion."""

    def test_parse_ebusd_payload_json(self) -> None:
        """Test ebusd --mqttjson formatted payloads."""
        # Single field dict
        payload = '{"temp": {"value": 21.5}}'
        parsed = parse_ebusd_payload(payload)
        self.assertEqual(parsed, {"temp": 21.5})

        # Multi-field dict
        payload_multi = (
            '{"day": {"value": 15}, "month": {"value": 6}, "year": {"value": 24}}'
        )
        parsed_multi = parse_ebusd_payload(payload_multi)
        self.assertEqual(parsed_multi, {"day": 15, "month": 6, "year": 24})

    def test_parse_ebusd_payload_plain_text(self) -> None:
        """Test plain text fallback payloads."""
        self.assertEqual(parse_ebusd_payload("21.5"), {"value": 21.5})
        self.assertEqual(parse_ebusd_payload("auto"), {"value": "auto"})

    def test_coerce_scalar(self) -> None:
        """Test numeric and string coercion for optimistic updates."""
        self.assertEqual(_coerce_scalar("42"), 42)
        self.assertEqual(_coerce_scalar("-5"), -5)
        self.assertEqual(_coerce_scalar("21.5"), 21.5)
        self.assertEqual(_coerce_scalar("auto"), "auto")
        self.assertEqual(_coerce_scalar(21.5), 21.5)

    def test_multi_field_layout(self) -> None:
        """Test field layout resolution for dates and weekly schedules."""
        # Dates
        self.assertEqual(_multi_field_layout("CoolingStartDate", {}), DATE_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("CoolingEndDate", {}), DATE_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("HolidayStartDate", {}), DATE_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("HolidayEndDate", {}), DATE_WRITE_FIELDS)

        # Times
        self.assertEqual(_multi_field_layout("HolidayStartTime", {}), TIME_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("HolidayEndTime", {}), TIME_WRITE_FIELDS)

        # Timers
        self.assertEqual(_multi_field_layout("Z1Timer_Monday", {}), TIMER_WRITE_FIELDS)
        self.assertEqual(
            _multi_field_layout("HwcTimer_Sunday_Slot2", {}), TIMER_WRITE_FIELDS
        )
        self.assertEqual(
            _multi_field_layout("CoolingTimer_Friday_Slot3", {}), TIMER_WRITE_FIELDS
        )

        # Generic fallback using existing keys
        self.assertEqual(_multi_field_layout("CustomMsg", {"a": 1, "b": 2}), ("a", "b"))

        # Non-multi-field messages
        self.assertIsNone(_multi_field_layout("Z1DayTemp", {}))
        self.assertIsNone(_multi_field_layout("HwcTempDesired", {}))

    def test_apply_optimistic_update(self) -> None:
        """Test full coordinator optimistic state updates."""

        class MockCoordinator:
            def __init__(self) -> None:
                self._state: dict = {}
                self._canonical_names: dict = {}

            _apply_optimistic_update = SaunierGeniaCoordinator._apply_optimistic_update

        coord = MockCoordinator()

        # 1. Date with previous ebusd state
        coord._state[("bass3", "CoolingEndDate")] = {"day": 1, "month": 1, "year": 19}
        coord._apply_optimistic_update("bass3", "CoolingEndDate", "01;01;99")
        self.assertEqual(
            coord._state[("bass3", "CoolingEndDate")],
            {"day": 1, "month": 1, "year": 99},
        )

        # 2. Date without previous state
        coord._apply_optimistic_update("bass3", "CoolingStartDate", "15;06;24")
        self.assertEqual(
            coord._state[("bass3", "CoolingStartDate")],
            {"day": 15, "month": 6, "year": 24},
        )

        # 3. Weekly timer preserving read-only fields (e.g. cooling_temp)
        coord._state[("bass3", "Z1Timer_Monday")] = {
            "from_hour": 6,
            "from_min": 0,
            "to_hour": 22,
            "to_min": 0,
            "temp": 21.0,
        }
        coord._apply_optimistic_update("bass3", "Z1Timer_Monday", "08;30;20;15")
        self.assertEqual(
            coord._state[("bass3", "Z1Timer_Monday")],
            {"from_hour": 8, "from_min": 30, "to_hour": 20, "to_min": 15, "temp": 21.0},
        )

        # 4. Standard scalar (temperature)
        coord._apply_optimistic_update("bass3", "Z1DayTemp", 22.5)
        self.assertEqual(coord._state[("bass3", "Z1DayTemp")], {"value": 22.5})

        # 5. String enum mode
        coord._apply_optimistic_update("bass3", "HwcOpMode", "day")
        self.assertEqual(coord._state[("bass3", "HwcOpMode")], {"value": "day"})

    def test_dynamic_dhw_boost_formula(self) -> None:
        """Test Smart Forced DHW Boost dynamic T_storage + hyst + 1.5 °C calculation."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {"force_dhw_boost": True}
        hass = MagicMock()

        async def run_scenario(
            storage: float, target: float, hyst: float, override: float | None = None
        ) -> tuple[list[tuple], SaunierGeniaCoordinator]:
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._apply_optimistic_update("bass3", "HwcStorageTemp", storage)
            coord._apply_optimistic_update("bass3", "HwcTempDesired", target)
            coord._apply_optimistic_update("bass3", "CylinderChargeHyst", hyst)
            writes: list[tuple] = []

            async def fake_write(c: str, m: str, v: object) -> None:
                writes.append((c, m, v))

            coord.async_write_parameter = fake_write  # type: ignore[method-assign]
            with patch("asyncio.sleep", new=AsyncMock()):
                await coord.async_trigger_dhw_boost(override_boost_temp=override)
            return writes, coord

        # Case 1: Normal 50 °C target, tank at 47 °C, hyst 5.0 K -> 47 + 5 + 1.5 = 53.5 °C
        writes, coord = asyncio.run(run_scenario(47.0, 50.0, 5.0))
        self.assertEqual(
            writes,
            [("bass3", "HwcTempDesired", 53.5), ("bass3", "HwcSFMode", "load")],
        )
        self.assertEqual(coord.saved_dhw_target_temp, 50.0)

        # Case 2: User raised normal DHW to 55 °C, tank at 52 °C, hyst 5.0 K -> 52 + 5 + 1.5 = 58.5 °C
        writes, coord = asyncio.run(run_scenario(52.0, 55.0, 5.0))
        self.assertEqual(
            writes,
            [("bass3", "HwcTempDesired", 58.5), ("bass3", "HwcSFMode", "load")],
        )
        self.assertEqual(coord.saved_dhw_target_temp, 55.0)

        # Case 3: Lower 45 °C target, tank at 42 °C, hyst 5.0 K -> 42 + 5 + 1.5 = 48.5 °C (no needless 55 °C jump)
        writes, coord = asyncio.run(run_scenario(42.0, 45.0, 5.0))
        self.assertEqual(
            writes,
            [("bass3", "HwcTempDesired", 48.5), ("bass3", "HwcSFMode", "load")],
        )
        self.assertEqual(coord.saved_dhw_target_temp, 45.0)

        # Case 4: Explicit service override (e.g. 60.0 °C for solar PV surplus)
        writes, coord = asyncio.run(run_scenario(47.0, 50.0, 5.0, override=60.0))
        self.assertEqual(
            writes,
            [("bass3", "HwcTempDesired", 60.0), ("bass3", "HwcSFMode", "load")],
        )
        self.assertEqual(coord.saved_dhw_target_temp, 50.0)

    def test_holiday_mode_activation_and_cancellation(self) -> None:
        """Test Holiday Mode activation 5-step write and cancellation reset trigger."""
        writes: list[tuple[str, str, Any]] = []

        class MockCoordinator:
            def __init__(self) -> None:
                self._preselected_holiday_start_datetime = None
                self._preselected_holiday_end_datetime = None

            async def async_write_parameter(
                self, circuit: str, message: str, value: Any
            ) -> None:
                writes.append((circuit, message, value))

            async_activate_holiday_mode = (
                SaunierGeniaCoordinator.async_activate_holiday_mode
            )
            async_cancel_holiday_mode = (
                SaunierGeniaCoordinator.async_cancel_holiday_mode
            )

        coord = MockCoordinator()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # 1. Activation with explicit parameters
            writes.clear()
            asyncio.run(
                coord.async_activate_holiday_mode(
                    temp=14.0,
                    start_date="2026-11-01",
                    start_time="09:00",
                    end_date="2026-11-10",
                    end_time="18:30",
                )
            )
            self.assertEqual(
                writes,
                [
                    ("bass3", "HolidayTemp", 14.0),
                    ("bass3", "HolidayStartDate", "01;11;26"),
                    ("bass3", "HolidayStartTime", "09;00;00"),
                    ("bass3", "HolidayEndDate", "10;11;26"),
                    ("bass3", "HolidayEndTime", "18;30;00"),
                ],
            )

            # 2. Activation with defaults (indefinite mode at 15.0 °C)
            writes.clear()
            asyncio.run(coord.async_activate_holiday_mode())
            self.assertEqual(len(writes), 5)
            self.assertEqual(writes[0], ("bass3", "HolidayTemp", 15.0))
            self.assertEqual(writes[1][0:2], ("bass3", "HolidayStartDate"))
            self.assertEqual(writes[2][0:2], ("bass3", "HolidayStartTime"))
            self.assertEqual(writes[3], ("bass3", "HolidayEndDate", "01;01;99"))
            self.assertEqual(writes[4], ("bass3", "HolidayEndTime", "23;59;59"))

            # 3. Cancellation sequence (reset dates/times to 2015 sentinel + trigger flag 1)
            writes.clear()
            asyncio.run(coord.async_cancel_holiday_mode())
            self.assertEqual(
                writes,
                [
                    ("bass3", "HolidayStartDate", "01;01;15"),
                    ("bass3", "HolidayStartTime", "00;00;00"),
                    ("bass3", "HolidayEndDate", "01;01;15"),
                    ("bass3", "HolidayEndTime", "00;00;00"),
                    ("bass3", "HolidayCancel", 1),
                ],
            )

    def test_holiday_and_cooling_remaining_days_states(self) -> None:
        """Test remaining days calculations: Inactivo, Final abierto, and positive day counts."""
        coord = SaunierGeniaCoordinator(MagicMock(), MagicMock())
        c_bass3 = CIRCUIT_BASS3.lower()

        # 1. Holiday mode inactive: returns 'Inactivo'
        coord._state[(c_bass3, "Z1Status")] = {"value": "auto"}
        self.assertEqual(coord.get_holiday_remaining_days(), "Inactivo")
        attrs = coord.get_holiday_remaining_attributes()
        self.assertEqual(attrs["days_remaining"], 0)
        self.assertFalse(attrs["is_active"])
        self.assertFalse(attrs["is_open_ended"])

        # 2. Holiday mode active with open-ended date (year 99): returns 'Final abierto'
        coord._state[(c_bass3, "Z1Status")] = {"value": "holidayaway"}
        coord._state[(c_bass3, "HolidayStartDate")] = {
            "day": 30,
            "month": 10,
            "year": 26,
        }
        coord._state[(c_bass3, "HolidayEndDate")] = {"day": 1, "month": 1, "year": 99}
        self.assertEqual(coord.get_holiday_remaining_days(), "Final abierto")
        attrs = coord.get_holiday_remaining_attributes()
        self.assertIsNone(attrs["days_remaining"])
        self.assertTrue(attrs["is_active"])
        self.assertTrue(attrs["is_open_ended"])

        # 3. Holiday mode active with timed window (e.g. 5 days in future)
        future_date = datetime.now().date() + timedelta(days=5)
        coord._state[(c_bass3, "HolidayEndDate")] = {
            "day": future_date.day,
            "month": future_date.month,
            "year": future_date.year % 100,
        }
        self.assertEqual(coord.get_holiday_remaining_days(), 5)
        attrs = coord.get_holiday_remaining_attributes()
        self.assertEqual(attrs["days_remaining"], 5)
        self.assertTrue(attrs["is_active"])
        self.assertFalse(attrs["is_open_ended"])

        # 4. Cooling inactive (year 19 or release status off): returns 'Inactivo'
        coord._state[(c_bass3, "CoolingEndDate")] = {"day": 1, "month": 1, "year": 19}
        self.assertEqual(coord.get_cooling_remaining_days(), "Inactivo")
        c_attrs = coord.get_cooling_remaining_attributes()
        self.assertEqual(c_attrs["days_remaining"], 0)
        self.assertFalse(c_attrs["is_active"])
        self.assertFalse(c_attrs["is_open_ended"])

        # 5. Cooling active with open-ended date (year 99): returns 'Final abierto'
        coord._state[(c_bass3, "CoolingEndDate")] = {"day": 1, "month": 1, "year": 99}
        coord._state[(c_bass3, "CoolingReleaseStatus")] = {"value": "on"}
        coord._state[(c_bass3, "Z1OpModeCooling")] = {"value": "day"}
        self.assertEqual(coord.get_cooling_remaining_days(), "Final abierto")
        c_attrs = coord.get_cooling_remaining_attributes()
        self.assertIsNone(c_attrs["days_remaining"])
        self.assertTrue(c_attrs["is_active"])
        self.assertTrue(c_attrs["is_open_ended"])

        # 6. Cooling active with timed window: returns day count
        c_future = datetime.now().date() + timedelta(days=12)
        coord._state[(c_bass3, "CoolingEndDate")] = {
            "day": c_future.day,
            "month": c_future.month,
            "year": c_future.year % 100,
        }
        self.assertEqual(coord.get_cooling_remaining_days(), 12)
        c_attrs = coord.get_cooling_remaining_attributes()
        self.assertEqual(c_attrs["days_remaining"], 12)
        self.assertTrue(c_attrs["is_active"])
        self.assertFalse(c_attrs["is_open_ended"])

    def test_cross_circuit_b516_energy_and_efficiency_recalculation(self) -> None:
        """Test b5 16 cross-circuit (hmux0 + vwzio) triggers, partial-hydration guards, and PowerStatus."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Push only hmux0 b5 16 energy counters (vwzio not hydrated yet)
        push_mqtt("ebusd/hmux0/PrEnergyElectricHc", '{"energy": {"value": 19876.6}}')
        push_mqtt("ebusd/hmux0/PrEnergyElectricHwc", '{"energy": {"value": 69524.0}}')
        push_mqtt("ebusd/hmux0/PrEnergyElectricCool", '{"energy": {"value": 218460.1}}')
        push_mqtt("ebusd/hmux0/PrEnergyThermalHc", '{"energy": {"value": 46218.2}}')
        push_mqtt("ebusd/hmux0/PrEnergyThermalHwc", '{"energy": {"value": 246403.5}}')
        push_mqtt("ebusd/hmux0/PrEnergyThermalCool", '{"energy": {"value": 981270.4}}')

        # Cooling EER only needs hmux0, so it is already available (4.49)
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_COOL_EER), 4.49)
        # Combined hmux0 + vwzio totals & COPs must remain None until vwzio hydrates!
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HEATING_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_DHW_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_SYSTEM_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HC_COP))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HWC_COP))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_GLOBAL_EFFICIENCY))

        # 2. Now push vwzio b5 16 energy counters -> must trigger recalculation!
        push_mqtt("ebusd/vwzio/PrEnergyElectricHc", '{"energy": {"value": 8375.9}}')
        push_mqtt("ebusd/vwzio/PrEnergyElectricHwc", '{"energy": {"value": 0.0}}')
        push_mqtt("ebusd/vwzio/PrEnergyThermalHc", '{"energy": {"value": 0.0}}')
        push_mqtt("ebusd/vwzio/PrEnergyThermalHwc", '{"energy": {"value": 0.0}}')

        self.assertEqual(
            coord.get_float(CALC_CIRCUIT, CALC_HEATING_TOTAL_ENERGY), 28252.5
        )
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_DHW_TOTAL_ENERGY), 69524.0)
        self.assertEqual(
            coord.get_float(CALC_CIRCUIT, CALC_SYSTEM_TOTAL_ENERGY), 316236.6
        )
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_HC_COP), 1.64)
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_HWC_COP), 3.54)
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_GLOBAL_EFFICIENCY), 4.03)

        # 3. Verify PowerStatus triggers live COP fallback and cooling binary sensor
        push_mqtt("ebusd/hmux0/RunDataFlowTemp", '{"value": {"value": 12.0}}')
        push_mqtt("ebusd/hmux0/RunDataReturnTemp", '{"value": {"value": 16.0}}')
        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"value": {"value": 1000}}')
        push_mqtt(
            "ebusd/hmux0/HMUStatusCode",
            '{"status": {"value": "cool_compressor_active"}}',
        )
        push_mqtt(
            "ebusd/hmux0/PowerStatus",
            '{"status": {"value": "cooling"}, "power": {"value": 1000.0}}',
        )
        self.assertTrue(_check_energy_integration(coord))
        # Thermal power = 1000 * 4.0 * 1.163 = 4652.0 W; Live COP = 4652 / 1000 = 4.65
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 4.65)

        push_mqtt(
            "ebusd/hmux0/PowerStatus",
            '{"status": {"value": "standby"}, "power": {"value": 4.9}}',
        )
        self.assertFalse(_check_energy_integration(coord))

    def test_deprecated_entity_registry_cleanup(self) -> None:
        """Test automatic cleanup of obsolete b5 16 unique_ids on setup."""
        import sys

        er_mod = sys.modules["homeassistant.helpers.entity_registry"]
        ent_reg = MagicMock()
        er_mod.async_get.return_value = ent_reg

        old_entry = MagicMock()
        old_entry.entity_id = "sensor.old_electric_today"
        old_entry.unique_id = "entry123_hmux0_prenergyelectrictoday_energy"

        old_cop = MagicMock()
        old_cop.entity_id = "sensor.old_daily_cop"
        old_cop.unique_id = "entry123_calculated_calculated_daily_cop_value"

        old_rpm = MagicMock()
        old_rpm.entity_id = "sensor.old_comp_speed_rpm"
        old_rpm.unique_id = "entry123_hmux0_statecompressor_comp_speed"

        old_bin_comp = MagicMock()
        old_bin_comp.entity_id = "binary_sensor.old_comp_active"
        old_bin_comp.unique_id = "entry123_binary_hmux0_statecompressor_comp_speed"

        active_entry = MagicMock()
        active_entry.entity_id = "sensor.new_system_total"
        active_entry.unique_id = (
            "entry123_calculated_calculated_system_total_energy_value"
        )

        er_mod.async_entries_for_config_entry.return_value = [
            old_entry,
            old_cop,
            old_rpm,
            old_bin_comp,
            active_entry,
        ]

        cfg_entry = MagicMock()
        cfg_entry.entry_id = "entry123"
        _async_cleanup_deprecated_entities(MagicMock(), cfg_entry)

        ent_reg.async_remove.assert_any_call("sensor.old_electric_today")
        ent_reg.async_remove.assert_any_call("sensor.old_daily_cop")
        ent_reg.async_remove.assert_any_call("sensor.old_comp_speed_rpm")
        ent_reg.async_remove.assert_any_call("binary_sensor.old_comp_active")
        self.assertEqual(ent_reg.async_remove.call_count, 4)

    def test_compressor_active_ignores_comp_speed_and_uses_modulation_or_rps(
        self,
    ) -> None:
        """Test _check_compressor_active and _get_compressor_modulation decode state_bytes, HMUStatusCode, and rps."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 0. Unhydrated: returns None
        self.assertIsNone(_check_compressor_active(coord))
        self.assertIsNone(_get_compressor_modulation(coord))

        # 1. Idle state where StateCompressor.comp_speed is non-zero (603) and state_bytes is 00 00 00 00
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"comp_speed": {"value": 603}, "fan_speed": {"value": 15}, "modulation": {"value": 0}, "state_bytes": {"value": "00 00 00 00"}}',
        )
        self.assertFalse(_check_compressor_active(coord))
        self.assertEqual(_get_compressor_modulation(coord), 0.0)

        # 2. Prerun / Overrun where legacy CSV byte 4 ('modulation') is 4 or 31, but state_bytes is 08 00 00 00
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"comp_speed": {"value": 616}, "fan_speed": {"value": 15}, "modulation": {"value": 31}, "state_bytes": {"value": "08 00 00 00"}}',
        )
        self.assertFalse(_check_compressor_active(coord))
        self.assertEqual(_get_compressor_modulation(coord), 0.0)

        # 3. Active heating run where state_bytes is 09 00 00 66 (0x66 = 102% modulation)
        # Even if legacy CSV 'modulation' byte 4 is stuck at 4, _get_compressor_modulation reads 102.0%
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"comp_speed": {"value": 614}, "fan_speed": {"value": 26128}, "modulation": {"value": 4}, "state_bytes": {"value": "09 00 00 66"}}',
        )
        self.assertTrue(_check_compressor_active(coord))
        self.assertEqual(_get_compressor_modulation(coord), 102.0)

        # 4. Fallback to HMUStatusCode when state_bytes is absent
        coord._state.clear()
        coord._canonical_names.clear()
        push_mqtt("ebusd/hmux0/HMUStatusCode", '{"status": {"value": "standby"}}')
        self.assertFalse(_check_compressor_active(coord))
        push_mqtt("ebusd/hmux0/HMUStatusCode", '{"status": {"value": "heat_prerun"}}')
        self.assertFalse(_check_compressor_active(coord))
        push_mqtt("ebusd/hmux0/HMUStatusCode", '{"status": {"value": "heat_overrun"}}')
        self.assertFalse(_check_compressor_active(coord))
        push_mqtt(
            "ebusd/hmux0/HMUStatusCode",
            '{"status": {"value": "heat_compressor_active"}}',
        )
        self.assertTrue(_check_compressor_active(coord))

        # 5. Fallback to RunDataCompressorSpeed when StateCompressor and HMUStatusCode are absent
        coord._state.clear()
        coord._canonical_names.clear()
        push_mqtt("ebusd/hmux0/RunDataCompressorSpeed", '{"value": {"value": 0.0}}')
        self.assertFalse(_check_compressor_active(coord))
        push_mqtt("ebusd/hmux0/RunDataCompressorSpeed", '{"value": {"value": 50.0}}')
        self.assertTrue(_check_compressor_active(coord))

    def test_passive_scan_version_and_serial_detection(self) -> None:
        """Test passive detection of SW/HW versions and 28-char serial numbers from ebusd scan.*."""
        import sys

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {}

        dr_mod = sys.modules["homeassistant.helpers.device_registry"]
        dev_reg = MagicMock()
        dr_mod.async_get.return_value = dev_reg

        mock_device = MagicMock()
        mock_device.id = "mock_device_outdoor_id"
        dev_reg.async_get_device.return_value = mock_device

        coord = SaunierGeniaCoordinator(hass, entry)

        # 1. Baseline verification: verify initial defaults are populated before any scan packet
        self.assertEqual(coord.get_device_sw_version(DEVICE_OUTDOOR_UNIT), "0407")
        self.assertEqual(coord.get_device_hw_version(DEVICE_OUTDOOR_UNIT), "0504")
        self.assertIsNone(coord.get_device_serial_number(DEVICE_OUTDOOR_UNIT))

        self.assertEqual(coord.get_device_sw_version(DEVICE_CLIMATE_CONTROLLER), "0708")
        self.assertEqual(coord.get_device_hw_version(DEVICE_CLIMATE_CONTROLLER), "4304")

        self.assertEqual(
            coord.get_device_sw_version(DEVICE_HYDRAULIC_INTERFACE), "0500"
        )
        self.assertEqual(
            coord.get_device_hw_version(DEVICE_HYDRAULIC_INTERFACE), "0504"
        )

        self.assertEqual(
            coord.get_device_sw_version(DEVICE_WIRELESS_THERMOSTAT), "0129"
        )
        self.assertEqual(
            coord.get_device_hw_version(DEVICE_WIRELESS_THERMOSTAT), "0404"
        )

        # Initial DeviceInfo check
        dev_info_initial = build_device_info(coord, DEVICE_OUTDOOR_UNIT)
        self.assertEqual(dev_info_initial["sw_version"], "0407")
        self.assertEqual(dev_info_initial["hw_version"], "0504")
        self.assertIsNone(dev_info_initial.get("serial_number"))

        # Helper to push mock MQTT message
        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 2. Outdoor Unit (08): Semicolon root scan and semicolon Id packet
        push_mqtt("ebusd/scan.08", "Vaillant;HMUX0;0412;0508")
        self.assertEqual(coord.get_device_sw_version(DEVICE_OUTDOOR_UNIT), "0412")
        self.assertEqual(coord.get_device_hw_version(DEVICE_OUTDOOR_UNIT), "0508")

        push_mqtt("ebusd/Scan.08/Id", "21;24;10;0020123456;1234;567890;N1")
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_OUTDOOR_UNIT),
            "21241000201234561234567890N1",
        )

        # Verify device registry was updated with accumulated hardware info
        dev_reg.async_update_device.assert_called_with(
            mock_device.id,
            sw_version="0412",
            hw_version="0508",
            serial_number="21241000201234561234567890N1",
        )

        # Verify updated DeviceInfo
        dev_info_outdoor = build_device_info(coord, DEVICE_OUTDOOR_UNIT)
        self.assertEqual(dev_info_outdoor["sw_version"], "0412")
        self.assertEqual(dev_info_outdoor["hw_version"], "0508")
        self.assertEqual(
            dev_info_outdoor["serial_number"],
            "21241000201234561234567890N1",
        )

        # 3. Hydraulic Module (76): JSON root scan and JSON Id packet
        push_mqtt("ebusd/scan.76", '{"SW": "0510", "HW": "0505"}')
        self.assertEqual(
            coord.get_device_sw_version(DEVICE_HYDRAULIC_INTERFACE), "0510"
        )
        self.assertEqual(
            coord.get_device_hw_version(DEVICE_HYDRAULIC_INTERFACE), "0505"
        )

        push_mqtt(
            "ebusd/Scan.76/Id",
            '{"prefix": "21", "year": "24", "week": "11", "product": "0020654321", "supplier": "4321", "counter": "654321", "suffix": "N2"}',
        )
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_HYDRAULIC_INTERFACE),
            "21241100206543214321654321N2",
        )
        dev_info_hydraulic = build_device_info(coord, DEVICE_HYDRAULIC_INTERFACE)
        self.assertEqual(dev_info_hydraulic["sw_version"], "0510")
        self.assertEqual(dev_info_hydraulic["hw_version"], "0505")
        self.assertEqual(
            dev_info_hydraulic["serial_number"],
            "21241100206543214321654321N2",
        )

        # 4. Thermostat (04): Semicolon root scan and semicolon Id packet with leading semicolon
        push_mqtt("ebusd/scan.04", "Vaillant;NETX3;0135;0405")
        self.assertEqual(
            coord.get_device_sw_version(DEVICE_WIRELESS_THERMOSTAT), "0135"
        )
        self.assertEqual(
            coord.get_device_hw_version(DEVICE_WIRELESS_THERMOSTAT), "0405"
        )

        push_mqtt("ebusd/Scan.04/Id", ";21;24;12;0020987654;9876;543210;N3")
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_WIRELESS_THERMOSTAT),
            "21241200209876549876543210N3",
        )
        dev_info_thermostat = build_device_info(coord, DEVICE_WIRELESS_THERMOSTAT)
        self.assertEqual(dev_info_thermostat["sw_version"], "0135")
        self.assertEqual(dev_info_thermostat["hw_version"], "0405")
        self.assertEqual(
            dev_info_thermostat["serial_number"],
            "21241200209876549876543210N3",
        )

        # 5. Controller (15): Semicolon root scan
        push_mqtt("ebusd/scan.15", "Vaillant;BASS3;0712;4306")
        self.assertEqual(coord.get_device_sw_version(DEVICE_CLIMATE_CONTROLLER), "0712")
        self.assertEqual(coord.get_device_hw_version(DEVICE_CLIMATE_CONTROLLER), "4306")
        dev_info_controller = build_device_info(coord, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(dev_info_controller["sw_version"], "0712")
        self.assertEqual(dev_info_controller["hw_version"], "4306")

        # 6. Verify via_device_id topology mapping without deprecated via_device
        self.assertNotIn("via_device", dev_info_controller)
        self.assertNotIn("via_device", dev_info_hydraulic)
        self.assertNotIn("via_device", dev_info_thermostat)

        coord.set_outdoor_device_id("reg_outdoor_12345")
        dev_info_controller_linked = build_device_info(coord, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(
            dev_info_controller_linked.get("via_device_id"), "reg_outdoor_12345"
        )
        self.assertNotIn("via_device", dev_info_controller_linked)

        dev_info_hydraulic_linked = build_device_info(coord, DEVICE_HYDRAULIC_INTERFACE)
        self.assertEqual(
            dev_info_hydraulic_linked.get("via_device_id"), "reg_outdoor_12345"
        )
        self.assertNotIn("via_device", dev_info_hydraulic_linked)

        dev_info_thermostat_linked = build_device_info(
            coord, DEVICE_WIRELESS_THERMOSTAT
        )
        self.assertEqual(
            dev_info_thermostat_linked.get("via_device_id"), "reg_outdoor_12345"
        )
        self.assertNotIn("via_device", dev_info_thermostat_linked)

    def test_controller_circuit_aliasing_bass3_and_basv3(self) -> None:
        """Test bidirectional aliasing, scan detection, and routing between bass3 and basv3."""
        hass = MagicMock()
        entry_saunier = MagicMock()
        entry_saunier.entry_id = "test_saunier"
        entry_saunier.data = {CONF_MANUFACTURER: MANUFACTURER_SAUNIER_DUVAL}

        coord_saunier = SaunierGeniaCoordinator(hass, entry_saunier)
        self.assertEqual(coord_saunier.active_controller_circuit, CIRCUIT_BASS3)

        entry_vaillant = MagicMock()
        entry_vaillant.entry_id = "test_vaillant"
        entry_vaillant.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry_vaillant)
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASV3)

        # 1. Passive detection via scan.15 ID
        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # Send Saunier Duval scan -> should switch active controller circuit to bass3
        push_mqtt("ebusd/scan.15", "Saunier Duval;BASS3;0708;4304")
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASS3)

        # Send Vaillant scan JSON -> should switch active controller circuit to basv3
        push_mqtt(
            "ebusd/scan.15",
            '{"MF": "Vaillant", "ID": "BASV3", "SW": "0708", "HW": "4304"}',
        )
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASV3)

        # 2. Ingestion & Aliasing: Entity listens on CIRCUIT_BASS3, incoming arrives on CIRCUIT_BASV3
        callback_called = False

        def on_room_temp_updated() -> None:
            nonlocal callback_called
            callback_called = True

        coord.async_add_listener(CIRCUIT_BASS3, "Z1RoomTemp", on_room_temp_updated)

        push_mqtt("ebusd/basv3/Z1RoomTemp", '{"temp": {"value": 21.5}}')
        self.assertTrue(callback_called)
        self.assertEqual(coord.get_float(CIRCUIT_BASS3, "Z1RoomTemp", "temp"), 21.5)
        self.assertEqual(coord.get_float(CIRCUIT_BASV3, "Z1RoomTemp", "temp"), 21.5)

        # Reverse aliasing: Entity listens on CIRCUIT_BASV3, incoming arrives on CIRCUIT_BASS3
        rev_callback_called = False

        def on_day_temp_updated() -> None:
            nonlocal rev_callback_called
            rev_callback_called = True

        coord.async_add_listener(CIRCUIT_BASV3, "Z1DayTemp", on_day_temp_updated)

        push_mqtt("ebusd/bass3/Z1DayTemp", '{"temp": {"value": 22.0}}')
        self.assertTrue(rev_callback_called)
        self.assertEqual(coord.get_float(CIRCUIT_BASS3, "Z1DayTemp", "temp"), 22.0)
        self.assertEqual(coord.get_float(CIRCUIT_BASV3, "Z1DayTemp", "temp"), 22.0)
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASS3)

        # Switch back to basv3
        push_mqtt("ebusd/basv3/Z1DayTemp", '{"temp": {"value": 22.5}}')
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASV3)

        # 3. Parameter writing and active /get routing
        async def run_write_tests() -> None:
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new=AsyncMock(),
            ) as mock_pub:
                # When active circuit is basv3, calling async_write_parameter with CIRCUIT_BASS3 routes to basv3 topic
                await coord.async_write_parameter(CIRCUIT_BASS3, "Z1DayTemp", 23.0)
                mock_pub.assert_called_with(
                    hass, "ebusd/basv3/Z1DayTemp/set", "23.0", qos=0, retain=False
                )
                # Both circuits reflect optimistic update
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1DayTemp", "temp"), 23.0
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASV3, "Z1DayTemp", "temp"), 23.0
                )

                # async_request_get with CIRCUIT_BASS3 routes to basv3 topic
                await coord.async_request_get(CIRCUIT_BASS3, "Z1RoomTemp")
                mock_pub.assert_called_with(
                    hass, "ebusd/basv3/Z1RoomTemp/get", "", qos=0, retain=False
                )

        asyncio.run(run_write_tests())

    def test_controller_circuit_aliasing_ctlv2_and_ctlv3(self) -> None:
        """Test bidirectional aliasing, scan detection, and routing for CTLV2 and CTLV3."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_ctlv"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry)
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASV3)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Passive detection via scan.15 for CTLV2 (Falk's setup)
        push_mqtt(
            "ebusd/scan.15",
            '{"MF": "Vaillant", "ID": "CTLV2", "SW": "0514", "HW": "1104"}',
        )
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_CTLV2)
        dev_info_ctlv2 = build_device_info(coord, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(dev_info_ctlv2["model"], "sensoCOMFORT VRC 720 (CTLV2)")

        # Ingestion on ctlv2 aliases across all controller circuits
        callback_called = False

        def on_room_temp_updated() -> None:
            nonlocal callback_called
            callback_called = True

        coord.async_add_listener(CIRCUIT_BASS3, "Z1RoomTemp", on_room_temp_updated)
        push_mqtt("ebusd/ctlv2/Z1RoomTemp", '{"temp": {"value": 20.8}}')
        self.assertTrue(callback_called)
        self.assertEqual(coord.get_float(CIRCUIT_BASS3, "Z1RoomTemp", "temp"), 20.8)
        self.assertEqual(coord.get_float(CIRCUIT_CTLV2, "Z1RoomTemp", "temp"), 20.8)
        self.assertEqual(coord.get_float(CIRCUIT_BASV3, "Z1RoomTemp", "temp"), 20.8)
        self.assertEqual(coord.get_float(CIRCUIT_CTLV3, "Z1RoomTemp", "temp"), 20.8)

        # 2. Passive detection via scan.15 for CTLV3 (Wim's setup)
        push_mqtt("ebusd/scan.15", "Vaillant;CTLV3;0618;1104")
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_CTLV3)
        dev_info_ctlv3 = build_device_info(coord, DEVICE_CLIMATE_CONTROLLER)
        self.assertEqual(dev_info_ctlv3["model"], "sensoCOMFORT VRC 720 (CTLV3)")

        # Ingestion on ctlv3 aliases across all controller circuits
        push_mqtt("ebusd/ctlv3/Z1NightTemp", '{"temp": {"value": 18.5}}')
        self.assertEqual(coord.get_float(CIRCUIT_BASS3, "Z1NightTemp", "temp"), 18.5)
        self.assertEqual(coord.get_float(CIRCUIT_CTLV2, "Z1NightTemp", "temp"), 18.5)
        self.assertEqual(coord.get_float(CIRCUIT_BASV3, "Z1NightTemp", "temp"), 18.5)
        self.assertEqual(coord.get_float(CIRCUIT_CTLV3, "Z1NightTemp", "temp"), 18.5)

        # Parameter write and get routing to ctlv3
        async def run_write_tests() -> None:
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new=AsyncMock(),
            ) as mock_pub:
                await coord.async_write_parameter(CIRCUIT_BASS3, "Z1DayTemp", 21.5)
                mock_pub.assert_called_with(
                    hass, "ebusd/ctlv3/Z1DayTemp/set", "21.5", qos=0, retain=False
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1DayTemp", "temp"), 21.5
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_CTLV3, "Z1DayTemp", "temp"), 21.5
                )

                await coord.async_request_get(CIRCUIT_BASS3, "Z1NightTemp")
                mock_pub.assert_called_with(
                    hass, "ebusd/ctlv3/Z1NightTemp/get", "", qos=0, retain=False
                )

        asyncio.run(run_write_tests())

    def test_outdoor_circuit_aliasing_hmux0_and_hmu(self) -> None:
        """Test bidirectional aliasing, scan detection, and routing for HMU00 (HW=5103)."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_hmu"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry)
        self.assertEqual(coord.active_outdoor_circuit, CIRCUIT_HMUX0)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Passive detection via scan.08 for HMU00 / HW=5103
        push_mqtt(
            "ebusd/scan.08",
            '{"MF": "Vaillant", "ID": "HMU00", "SW": "0902", "HW": "5103"}',
        )
        self.assertEqual(coord.active_outdoor_circuit, CIRCUIT_HMU)

        # Ingestion on hmu aliases to hmux0
        callback_called = False

        def on_flow_temp_updated() -> None:
            nonlocal callback_called
            callback_called = True

        coord.async_add_listener(CIRCUIT_HMUX0, "RunDataFlowTemp", on_flow_temp_updated)
        push_mqtt("ebusd/hmu/RunDataFlowTemp", '{"value": {"value": 36.2}}')
        self.assertTrue(callback_called)
        self.assertEqual(
            coord.get_float(CIRCUIT_HMUX0, "RunDataFlowTemp", "value"), 36.2
        )
        self.assertEqual(coord.get_float(CIRCUIT_HMU, "RunDataFlowTemp", "value"), 36.2)

        # Ingestion of HW5103 FlowPressure
        push_mqtt("ebusd/hmu/FlowPressure", '{"value": {"value": 1.85}}')
        self.assertEqual(coord.get_float(CIRCUIT_HMUX0, "FlowPressure", "value"), 1.85)
        self.assertEqual(coord.get_float(CIRCUIT_HMU, "FlowPressure", "value"), 1.85)

        # Parameter write and get routing to hmu
        async def run_write_tests() -> None:
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new=AsyncMock(),
            ) as mock_pub:
                await coord.async_request_get(CIRCUIT_HMUX0, "FlowPressure")
                mock_pub.assert_called_with(
                    hass, "ebusd/hmu/FlowPressure/get", "", qos=0, retain=False
                )

        asyncio.run(run_write_tests())

    def test_traditional_ebusd_message_name_normalization(self) -> None:
        """Test normalization of traditional eBUSd message names (flowtemp, BuildingCircuitFlow, etc.)."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_norm"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. flowtemp -> RunDataFlowTemp
        push_mqtt("ebusd/hmu/flowtemp", '{"temp": {"value": 38.5}}')
        self.assertEqual(
            coord.get_float(CIRCUIT_HMUX0, "RunDataFlowTemp", "temp"), 38.5
        )
        self.assertEqual(coord.get_float(CIRCUIT_HMU, "RunDataFlowTemp", "temp"), 38.5)

        # 2. BuildingCircuitFlow -> RunDataFlowRate
        push_mqtt("ebusd/hmu/BuildingCircuitFlow", '{"flow_rate": {"value": 850}}')
        self.assertEqual(
            coord.get_float(CIRCUIT_HMUX0, "RunDataFlowRate", "flow_rate"), 850
        )
        self.assertEqual(
            coord.get_float(CIRCUIT_HMU, "RunDataFlowRate", "flow_rate"), 850
        )

        # 3. RunDataStatuscode -> HMUStatusCode
        push_mqtt(
            "ebusd/hmu/RunDataStatuscode",
            '{"status": {"value": "heat_compressor_active"}}',
        )
        self.assertEqual(
            coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status"),
            "heat_compressor_active",
        )
        self.assertEqual(
            coord.get_str(CIRCUIT_HMU, "HMUStatusCode", "status"),
            "heat_compressor_active",
        )

        # 4. PowerConsumptionHmu (kW) -> RunDataElectricPowerConsumption (W)
        push_mqtt("ebusd/hmu/PowerConsumptionHmu", '{"value": {"value": 1.45}}')
        self.assertEqual(
            coord.get_float(CIRCUIT_HMUX0, "RunDataElectricPowerConsumption", "power"),
            1450.0,
        )
        self.assertEqual(
            coord.get_float(CIRCUIT_HMU, "RunDataElectricPowerConsumption", "power"),
            1450.0,
        )

    def test_repair_issues_outdated_and_missing_csv_detection(self) -> None:
        """Test automatic Home Assistant Repair issue creation and clearing for CSV compatibility."""
        import sys

        ir_mod = sys.modules["homeassistant.helpers.issue_registry"]
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_repairs"
        entry.data = {}
        coord = SaunierGeniaCoordinator(hass, entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Legacy 08.hmux0.csv StateCompressor (with 'comp_speed') raises outdated_hmux0_csv
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"comp_speed": {"value": 598}, "fan_speed": {"value": 15}, "modulation": {"value": 0}, "state_bytes": {"value": "00 00 00 00"}}',
        )
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        # Upgrading 08.hmux0.csv ('flow_temp' present) automatically deletes outdated_hmux0_csv
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"flow_temp": {"value": 37.38}, "modulation": {"value": 0}, "mode_flags": {"value": 0}, "state_bytes": {"value": "00 00 00 00"}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_OUTDATED_HMUX0_CSV
        )

        # 1b. Legacy 15.bass3.csv / 15.basv3.csv (with 'Z1HolidayTemp') raises outdated_controller_csv
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()
        push_mqtt(
            "ebusd/bass3/Z1HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        # Upgrading 15.bass3.csv ('HolidayTemp' present) automatically deletes outdated_controller_csv
        push_mqtt(
            "ebusd/bass3/HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_OUTDATED_CONTROLLER_CSV
        )

        # Also works on basv3 (sensoCOMFORT)
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()
        push_mqtt(
            "ebusd/basv3/Z1HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        # HolidayStartDate with valid fields on v1.2.4+ also clears outdated_controller_csv
        # Note: clear Z1HolidayTemp across all aliased circuits to simulate ebusd restarting with updated CSV
        for c in CONTROLLER_CIRCUITS:
            coord._state.pop((c, "Z1HolidayTemp"), None)
            coord._canonical_names.pop((c, "z1holidaytemp"), None)
        push_mqtt(
            "ebusd/basv3/HolidayStartDate",
            '{"day": {"value": 1}, "month": {"value": 1}, "year": {"value": 15}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # Also works on ctlv2 and ctlv3
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()
        push_mqtt(
            "ebusd/ctlv2/Z1HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        push_mqtt(
            "ebusd/ctlv2/HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_OUTDATED_CONTROLLER_CSV
        )

        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()
        push_mqtt(
            "ebusd/ctlv3/Z1HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        push_mqtt(
            "ebusd/ctlv3/HolidayTemp",
            '{"value": {"value": 15.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_OUTDATED_CONTROLLER_CSV
        )

        # 2. Missing custom CSV / incomplete scan detection:
        #    If any of the 3 required circuits (08.hmux0, 15.bass3/basv3, 76.vwzio) fails to load after hydration,
        #    missing_custom_csv remains active until all 3 report telemetry.
        coord._state.clear()
        coord._canonical_names.clear()
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()

        push_mqtt("ebusd/global/signal", "true")
        coord._async_verify_custom_csv_after_hydration()
        self.assertIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        # Only 08.hmux0 and 15.bass3 loaded (e.g. scan config 76 timed out) -> still active
        push_mqtt("ebusd/hmux0/RunDataFlowTemp", '{"value": {"value": 35.5}}')
        push_mqtt("ebusd/bass3/Z1DayTemp", '{"value": {"value": 21.0}}')
        self.assertIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)

        # Once 76.vwzio also reports telemetry, missing_custom_csv clears automatically
        push_mqtt("ebusd/vwzio/Status01", '{"temp1": {"value": 35.5}}')
        self.assertNotIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_MISSING_CUSTOM_CSV
        )

        # 2c. Also works for aroTHERM HMU00 (HW5103) and CTLV2
        coord._state.clear()
        coord._canonical_names.clear()
        coord._active_repair_issues.clear()
        push_mqtt("ebusd/global/signal", "true")
        coord._async_verify_custom_csv_after_hydration()
        self.assertIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)

        # Ingestion of custom 08.hmu.HW5103, 15.ctlv2, and 76.vwzio clears missing_custom_csv
        push_mqtt("ebusd/hmu/RunDataFlowTemp", '{"value": {"value": 36.5}}')
        push_mqtt("ebusd/ctlv2/Z1DayTemp", '{"value": {"value": 21.0}}')
        push_mqtt("ebusd/vwzio/Status01", '{"temp1": {"value": 36.0}}')
        self.assertNotIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)

        # 2d. Also works for aroTHERM HMU00 (HW5103) and CTLV3
        coord._state.clear()
        coord._canonical_names.clear()
        coord._active_repair_issues.clear()
        push_mqtt("ebusd/global/signal", "true")
        coord._async_verify_custom_csv_after_hydration()
        self.assertIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)

        # Ingestion of custom 08.hmu.HW5103, 15.ctlv3, and 76.vwzio clears missing_custom_csv
        push_mqtt("ebusd/hmu/RunDataFlowTemp", '{"value": {"value": 36.5}}')
        push_mqtt("ebusd/ctlv3/Z1DayTemp", '{"value": {"value": 21.0}}')
        push_mqtt("ebusd/vwzio/Status01", '{"temp1": {"value": 36.0}}')
        self.assertNotIn(ISSUE_MISSING_CUSTOM_CSV, coord._active_repair_issues)

        # 3. No MQTT traffic on configured prefix after hydration raises no_ebusd_mqtt_traffic
        coord._state.clear()
        coord._canonical_names.clear()
        coord._active_repair_issues.clear()
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()

        coord._async_verify_custom_csv_after_hydration()
        self.assertIn(ISSUE_NO_EBUSD_MQTT_TRAFFIC, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

        # First incoming message clears no_ebusd_mqtt_traffic automatically
        push_mqtt("ebusd/global/signal", "true")
        self.assertNotIn(ISSUE_NO_EBUSD_MQTT_TRAFFIC, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_NO_EBUSD_MQTT_TRAFFIC
        )

        # 4. Plain-text semicolon multi-field payload raises mqttjson_not_enabled, JSON clears it
        push_mqtt("ebusd/hmux0/Status01", "37.0;35.0;20.5;-;50.0;on")
        self.assertIn(ISSUE_MQTTJSON_NOT_ENABLED, coord._active_repair_issues)

        push_mqtt("ebusd/hmux0/Status01", '{"temp1": {"value": 37.0}}')
        self.assertNotIn(ISSUE_MQTTJSON_NOT_ENABLED, coord._active_repair_issues)

        # 5. Legacy RunDataFlowRate ('value' JSON key from pre-v1.2.4 CSV, regardless of number)
        #    raises outdated_hmux0_csv, and v1.2.4+ ('flow_rate' key or RunDataNominalFlowRate) clears it
        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"value": {"value": 540}}')
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertEqual(coord.get_int("hmux0", "RunDataFlowRate", "value"), 540)

        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"flow_rate": {"value": 1450}}')
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertEqual(coord.get_int("hmux0", "RunDataFlowRate", "value"), 1450)

        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"value": {"value": 900}}')
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        push_mqtt("ebusd/hmux0/RunDataNominalFlowRate", '{"value": {"value": 900}}')
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)


if __name__ == "__main__":
    unittest.main()
