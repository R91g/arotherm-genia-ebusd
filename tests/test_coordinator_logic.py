"""Unit tests for coordinator payload parsing and optimistic update mapping."""

import asyncio
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

# Ensure tests/ directory is on path to load setup_mocks
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hacs"))
)

from homeassistant.exceptions import HomeAssistantError

from custom_components.arotherm_genia_ebusd.__init__ import (
    _async_cleanup_deprecated_entities,
    _async_register_services,
)
from custom_components.arotherm_genia_ebusd.binary_sensor import (
    _check_compressor_active,
    _check_energy_integration,
)
from custom_components.arotherm_genia_ebusd.const import (
    CALC_CIRCUIT,
    CALC_COOL_EER,
    CALC_DELTA_T,
    CALC_DHW_TOTAL_ENERGY,
    CALC_GLOBAL_EFFICIENCY,
    CALC_HC_COP,
    CALC_HEATING_TOTAL_ENERGY,
    CALC_HWC_COP,
    CALC_LIVE_COP,
    CALC_SYSTEM_TOTAL_ENERGY,
    CALC_THERMAL_POWER,
    CIRCUIT_BASS3,
    CIRCUIT_BASV3,
    CIRCUIT_CTLV2,
    CIRCUIT_CTLV3,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMU,
    CIRCUIT_HMUX0,
    CIRCUIT_VWZIO,
    CONF_HAS_MIGO_LINK,
    CONF_MANUFACTURER,
    CONTROLLER_CIRCUITS,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    DOMAIN,
    EBUSD_TRAFFIC_TIMEOUT_SECONDS,
    HMU_HW5103_HYDRATION_MESSAGES,
    HMUX0_EXCLUSIVE_MESSAGES,
    ISSUE_EBUSD_SLOW_POLLING_SEED,
    ISSUE_MISSING_CUSTOM_CSV,
    ISSUE_MQTTJSON_NOT_ENABLED,
    ISSUE_NO_EBUSD_MQTT_TRAFFIC,
    ISSUE_OUTDATED_CONTROLLER_CSV,
    ISSUE_OUTDATED_HMU_CSV,
    ISSUE_OUTDATED_HMUX0_CSV,
    MANUFACTURER_SAUNIER_DUVAL,
    MANUFACTURER_VAILLANT,
    OUTDOOR_CIRCUITS,
    SERVICE_CANCEL_HOLIDAY_MODE,
    SERVICE_CANCEL_QUICK_VETO,
    SERVICE_CANCEL_VENTILATION_BOOST,
    SERVICE_FORCE_DHW_BOOST,
    SERVICE_QUICK_VETO,
    SERVICE_SET_HOLIDAY_MODE,
    SERVICE_SET_WEEKLY_TIMER,
    SERVICE_START_VENTILATION_BOOST,
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
from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
    SENSOR_DESCRIPTIONS,
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
        self.assertIsNone(_multi_field_layout("Z1CoolingManualTemp", {}))
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
        coord._apply_optimistic_update("bass3", "Z1CoolingManualTemp", 22.5)
        self.assertEqual(
            coord._state[("bass3", "Z1CoolingManualTemp")], {"value": 22.5}
        )

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

            def _optimistically_clear_z1_status(
                self, expected_status: str, *, force_off: bool = False
            ) -> None:
                return None

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
        """Test remaining days calculations: 0 (inactive), None (open-ended), and positive/same-day counts."""
        coord = SaunierGeniaCoordinator(MagicMock(), MagicMock())
        c_bass3 = CIRCUIT_BASS3.lower()

        # 1. Holiday mode inactive: returns 0 with is_active=False
        coord._state[(c_bass3, "Z1Status")] = {"value": "auto"}
        self.assertEqual(coord.get_holiday_remaining_days(), 0)
        attrs = coord.get_holiday_remaining_attributes()
        self.assertEqual(attrs["days_remaining"], 0)
        self.assertFalse(attrs["is_active"])
        self.assertFalse(attrs["is_open_ended"])

        # 2. Holiday mode active with open-ended date (year 99): returns None
        coord._state[(c_bass3, "Z1Status")] = {"value": "holidayaway"}
        coord._state[(c_bass3, "HolidayStartDate")] = {
            "day": 30,
            "month": 10,
            "year": 26,
        }
        coord._state[(c_bass3, "HolidayEndDate")] = {"day": 1, "month": 1, "year": 99}
        self.assertIsNone(coord.get_holiday_remaining_days())
        attrs = coord.get_holiday_remaining_attributes()
        self.assertIsNone(attrs["days_remaining"])
        self.assertIsNone(attrs["remaining_formatted"])
        self.assertTrue(attrs["is_active"])
        self.assertTrue(attrs["is_open_ended"])

        # 3. Holiday mode active with timed window (e.g. ~2 days 4h 30m in future)
        future_dt = (datetime.now() + timedelta(days=2, hours=4, minutes=30)).replace(
            second=0, microsecond=0
        )
        coord._state[(c_bass3, "HolidayStartTime")] = {
            "hours": 8,
            "minutes": 15,
            "seconds": 0,
        }
        coord._state[(c_bass3, "HolidayEndDate")] = {
            "day": future_dt.day,
            "month": future_dt.month,
            "year": future_dt.year % 100,
        }
        coord._state[(c_bass3, "HolidayEndTime")] = {
            "hours": future_dt.hour,
            "minutes": future_dt.minute,
            "seconds": future_dt.second,
        }
        expected_days = (future_dt.date() - datetime.now().date()).days
        self.assertEqual(coord.get_holiday_remaining_days(), expected_days)
        attrs = coord.get_holiday_remaining_attributes()
        self.assertEqual(attrs["days_remaining"], expected_days)
        self.assertEqual(attrs["start_time"], "08:15:00")
        self.assertEqual(
            attrs["end_time"],
            f"{future_dt.hour:02d}:{future_dt.minute:02d}:{future_dt.second:02d}",
        )
        self.assertEqual(attrs["remaining_hours"], 4)
        self.assertIn(attrs["remaining_minutes"], (29, 30))
        self.assertIsNotNone(attrs["remaining_formatted"])
        self.assertTrue(attrs["remaining_formatted"].startswith("2d 4h "))
        self.assertTrue(attrs["is_active"])
        self.assertFalse(attrs["is_open_ended"])

        # 3b. Same-day holiday ending later today (0 calendar days left, still active)
        today_end = datetime.now() + timedelta(minutes=90)
        if today_end.date() == datetime.now().date():
            coord._state[(c_bass3, "HolidayEndDate")] = {
                "day": today_end.day,
                "month": today_end.month,
                "year": today_end.year % 100,
            }
            coord._state[(c_bass3, "HolidayEndTime")] = {
                "hours": today_end.hour,
                "minutes": today_end.minute,
                "seconds": today_end.second,
            }
            self.assertEqual(coord.get_holiday_remaining_days(), 0)
            today_attrs = coord.get_holiday_remaining_attributes()
            self.assertTrue(today_attrs["is_active"])
            self.assertFalse(today_attrs["is_open_ended"])

        # 4. Cooling inactive (year 19 or release status off): returns 0 with is_active=False
        coord._state[(c_bass3, "CoolingEndDate")] = {"day": 1, "month": 1, "year": 19}
        self.assertEqual(coord.get_cooling_remaining_days(), 0)
        c_attrs = coord.get_cooling_remaining_attributes()
        self.assertEqual(c_attrs["days_remaining"], 0)
        self.assertFalse(c_attrs["is_active"])
        self.assertFalse(c_attrs["is_open_ended"])

        # 5. Cooling active with open-ended date (year 99): returns None
        coord._state[(c_bass3, "CoolingEndDate")] = {"day": 1, "month": 1, "year": 99}
        coord._state[(c_bass3, "CoolingReleaseStatus")] = {"value": "on"}
        coord._state[(c_bass3, "Z1OpModeCooling")] = {"value": "day"}
        self.assertIsNone(coord.get_cooling_remaining_days())
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

    def test_live_cop_prioritizes_rundataelectricpower_over_powerstatus(self) -> None:
        """Verify Live COP and instant power prioritize RunDataElectricPowerConsumption over PowerStatus."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Setup thermodynamic inputs: 1000 l/h, dt = 5K (35 - 30) -> 5815 W thermal power
        push_mqtt("ebusd/hmux0/RunDataFlowTemp", '{"value": {"value": 35.0}}')
        push_mqtt("ebusd/hmux0/RunDataReturnTemp", '{"value": {"value": 30.0}}')
        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"value": {"value": 1000}}')
        push_mqtt(
            "ebusd/hmux0/HMUStatusCode",
            '{"status": {"value": "heat_compressor_active"}}',
        )

        # 2. Receive fallback PowerStatus (e.g. from MiGo Link f1 periodic poll: 2000 W)
        push_mqtt(
            "ebusd/hmux0/PowerStatus",
            '{"status": {"value": "heating"}, "power": {"value": 2000.0}}',
        )
        # Live COP evaluates from PowerStatus fallback: 5815 / 2000 = 2.91
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 2.91)

        # 3. Receive fresh RunDataElectricPowerConsumption (from high-frequency r1 poll: 1450 W)
        push_mqtt(
            "ebusd/hmux0/RunDataElectricPowerConsumption",
            '{"power": {"value": 1450.0}}',
        )
        # RunDataElectricPowerConsumption MUST take precedence over the slower PowerStatus: 5815 / 1450 = 4.01
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 4.01)

        # 4. Also verify sensor subscription includes both RunDataElectricPowerConsumption and PowerStatus
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
        )

        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "electric_power_consumption"
        )
        sensor = SaunierGeniaSensor(coord, desc)
        # Subscriptions must cover both PowerStatus and RunDataElectricPowerConsumption
        expected_subs = {
            (CIRCUIT_HMUX0, "PowerStatus"),
            (CIRCUIT_HMUX0, "RunDataElectricPowerConsumption"),
            (CIRCUIT_HMU, "PowerStatus"),
            (CIRCUIT_HMU, "RunDataElectricPowerConsumption"),
        }
        self.assertTrue(expected_subs.issubset(set(sensor._subscriptions)))
        # Sensor native_value returns RunDataElectricPowerConsumption value (1450.0)
        self.assertEqual(sensor.native_value, 1450.0)

        # 5. Stale RunDataElectricPowerConsumption (> 180s) dynamically falls back to newer PowerStatus
        t_stale = time.time() - 250.0
        coord._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = t_stale
        coord._message_timestamps[(CIRCUIT_HMU, "rundataelectricpowerconsumption")] = (
            t_stale
        )

        # Push fresher PowerStatus (1500.0 W)
        push_mqtt(
            "ebusd/hmux0/PowerStatus",
            '{"status": {"value": "heating"}, "power": {"value": 1500.0}}',
        )
        # Live COP recalculates from fresh PowerStatus fallback: 5815 / 1500 = 3.88
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 3.88)
        self.assertEqual(coord.get_instantaneous_electric_power(), 1500.0)
        self.assertEqual(sensor.native_value, 1500.0)

        # 6. Fresh RunDataElectricPowerConsumption immediately reclaims precedence
        push_mqtt(
            "ebusd/hmux0/RunDataElectricPowerConsumption",
            '{"power": {"value": 1163.0}}',
        )
        # 5815 / 1163 = 5.00
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 5.0)
        self.assertEqual(coord.get_instantaneous_electric_power(), 1163.0)
        self.assertEqual(sensor.native_value, 1163.0)

    def test_instantaneous_electric_power_staleness_logic(self) -> None:
        """Unit test get_instantaneous_electric_power across all staleness branches."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        t0 = 1000.0
        # Neither available
        self.assertIsNone(coord.get_instantaneous_electric_power(now=t0))

        # Only PowerStatus available
        coord._state[(CIRCUIT_HMUX0, "PowerStatus")] = {"power": 1200.0}
        coord._message_timestamps[(CIRCUIT_HMUX0, "powerstatus")] = t0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0), 1200.0)

        # Both available: fresher reading wins regardless of 180s threshold
        coord._state[(CIRCUIT_HMUX0, "RunDataElectricPowerConsumption")] = {
            "power": 1350.0
        }
        coord._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = t0 + 50.0
        # PowerStatus updated at t0 + 60 is fresher than RunData at t0 + 50 -> PowerStatus wins
        coord._message_timestamps[(CIRCUIT_HMUX0, "powerstatus")] = t0 + 60.0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 80.0), 1200.0)

        # Tie (both at t0 + 60) prefers RunDataElectricPowerConsumption
        coord._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = t0 + 60.0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 80.0), 1350.0)

        # Newer RunData at t0 + 70 beats PowerStatus at t0 + 60
        coord._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = t0 + 70.0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 80.0), 1350.0)

        # Newer PowerStatus at t0 + 220 beats older RunData at t0 + 70
        coord._message_timestamps[(CIRCUIT_HMUX0, "powerstatus")] = t0 + 220.0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 250.0), 1200.0)

        # Older PowerStatus at t0 + 40 vs RunData at t0 + 70 -> RunData wins (within 600s)
        coord._message_timestamps[(CIRCUIT_HMUX0, "powerstatus")] = t0 + 40.0
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 500.0), 1350.0)

        # Both exceed 10 minutes (> 600s): RunData age 630s, PowerStatus age 660s -> None (unavailable)
        self.assertIsNone(coord.get_instantaneous_electric_power(now=t0 + 700.0))

    def test_split_hmu_cumulative_energy_and_efficiency(self) -> None:
        """Verify HMU / HMU00 (HW5103) units calculate energy and COP from 08.hmu + 15.* + 76.vwzio."""
        entry = MagicMock()
        entry.entry_id = "test_hmu_entry"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Simulate HMU00 detection on address 08 (aroTHERM Split / aroTHERM plus HW5103)
        push_mqtt("ebusd/scan.08/id", "hmu00")
        self.assertEqual(coord._active_outdoor_circuit, CIRCUIT_HMU)

        # 2. Push ONLY vwzio indoor standby/backup counters (e.g. uniTOWER 47713.9 == 47713.9 -> COP 1.0):
        # Must NOT emit bogus vwzio-only totals or a false 1.0 system COP!
        push_mqtt("ebusd/vwzio/PrEnergyElectricHc", '{"energy": {"value": 47713.9}}')
        push_mqtt("ebusd/vwzio/PrEnergyElectricHwc", '{"energy": {"value": 0.0}}')
        push_mqtt("ebusd/vwzio/PrEnergyThermalHc", '{"energy": {"value": 47713.9}}')
        push_mqtt("ebusd/vwzio/PrEnergyThermalHwc", '{"energy": {"value": 0.0}}')

        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HEATING_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_DHW_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_SYSTEM_TOTAL_ENERGY))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HC_COP))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_HWC_COP))
        self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_GLOBAL_EFFICIENCY))

        # 3. Push controller (ctlv2) mode electrical sums and HMU b51a yields & TotalEnergyUsage
        push_mqtt("ebusd/ctlv2/PrEnergySumHc", '{"value": {"value": 3735}}')
        push_mqtt("ebusd/ctlv2/PrEnergySumHwc", '{"value": {"value": 1362}}')
        push_mqtt("ebusd/hmu/YieldHc", '{"value": {"value": 12816}}')
        push_mqtt("ebusd/hmu/YieldHwc", '{"value": {"value": 3105}}')
        push_mqtt("ebusd/hmu/YieldCooling", '{"value": {"value": 0}}')
        push_mqtt("ebusd/hmu/TotalEnergyUsage", '{"value": {"value": 5285}}')

        # 4. Verify cumulative Wh totals and real COP/SCOP values (matching issue #3 dump)
        self.assertEqual(
            coord.get_float(CALC_CIRCUIT, CALC_HEATING_TOTAL_ENERGY), 3735000.0
        )
        self.assertEqual(
            coord.get_float(CALC_CIRCUIT, CALC_DHW_TOTAL_ENERGY), 1362000.0
        )
        self.assertEqual(
            coord.get_float(CALC_CIRCUIT, CALC_SYSTEM_TOTAL_ENERGY), 5332713.9
        )
        # Fallback mode COPs from (Yield + PrEnergySum) / PrEnergySum:
        # Heating COP: (12816 + 3735) / 3735 = 4.43; DHW COP: (3105 + 1362) / 1362 = 3.28
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_HC_COP), 4.43)
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_HWC_COP), 3.28)
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_COOL_EER), 0.0)
        # Global SCOP: ((12816 + 3105 + 0 + 5285)*1000 + 47713.9) / (5285*1000 + 47713.9) = 3.99
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_GLOBAL_EFFICIENCY), 3.99)

        # 5. Native HMU CopHc / CopHwc registers take precedence once hydrated (e.g. 4.5 on VWL 55/6 A)
        push_mqtt("ebusd/hmu/CopHc", '{"value": {"value": 4.5}}')
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_HC_COP), 4.5)

        # 6. Environmental yield & thermal sensors convert HMU yields + PrEnergySum (kWh -> Wh)
        env_hc_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "energy_env_yield_hc"
        )
        env_hwc_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "energy_env_yield_hwc"
        )
        therm_hc_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "energy_thermal_hc"
        )
        therm_hwc_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "energy_thermal_hwc"
        )
        therm_cool_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "energy_thermal_cool"
        )
        self.assertEqual(
            SaunierGeniaSensor(coord, env_hc_desc).native_value, 12816000.0
        )
        self.assertEqual(
            SaunierGeniaSensor(coord, env_hwc_desc).native_value, 3105000.0
        )
        self.assertEqual(
            SaunierGeniaSensor(coord, therm_hc_desc).native_value, 16551000.0
        )
        self.assertEqual(
            SaunierGeniaSensor(coord, therm_hwc_desc).native_value, 4467000.0
        )
        self.assertEqual(SaunierGeniaSensor(coord, therm_cool_desc).native_value, 0.0)

        # 7. Live COP on HMU via PowerStatus
        push_mqtt("ebusd/hmu/RunDataFlowTemp", '{"value": {"value": 35.0}}')
        push_mqtt("ebusd/hmu/RunDataReturnTemp", '{"value": {"value": 30.0}}')
        push_mqtt("ebusd/hmu/RunDataFlowRate", '{"value": {"value": 1200}}')
        push_mqtt(
            "ebusd/hmu/HMUStatusCode",
            '{"status": {"value": "heat_compressor_active"}}',
        )
        push_mqtt(
            "ebusd/hmu/PowerStatus",
            '{"status": {"value": "heating"}, "power": {"value": 1500.0}}',
        )
        # Thermal power = 1200 * 5.0 * 1.163 = 6978.0 W; Live COP = 6978 / 1500 = 4.65
        self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 4.65)

    def test_hmux0_only_entities_auto_disabled_on_hmu_detection(self) -> None:
        """Verify the 3 HMUX0-exclusive electrical sensors auto-disable on HMU and re-enable on HMUX0."""
        from homeassistant.helpers import entity_registry as er

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry_split_1"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}

        e_cool = MagicMock(
            entity_id="sensor.elec_cool",
            unique_id="entry_split_1_hmux0_prenergyelectriccool_energy",
            disabled_by=None,
        )
        e_hc = MagicMock(
            entity_id="sensor.elec_hc_out",
            unique_id="entry_split_1_hmux0_prenergyelectrichc_energy",
            disabled_by=None,
        )
        e_hwc_user = MagicMock(
            entity_id="sensor.elec_hwc_out",
            unique_id="entry_split_1_hmux0_prenergyelectrichwc_energy",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        e_other = MagicMock(
            entity_id="sensor.env_yield_hc",
            unique_id="entry_split_1_hmux0_prenergyenvyieldhc_energy",
            disabled_by=None,
        )
        mock_ent_reg = MagicMock()

        def _update_side_effect(entity_id: str, **kwargs: Any) -> None:
            for item in (e_cool, e_hc, e_hwc_user, e_other):
                if item.entity_id == entity_id and "disabled_by" in kwargs:
                    item.disabled_by = kwargs["disabled_by"]

        mock_ent_reg.async_update_entity.side_effect = _update_side_effect

        with (
            patch.object(er, "async_get", return_value=mock_ent_reg),
            patch.object(
                er,
                "async_entries_for_config_entry",
                return_value=[e_cool, e_hc, e_hwc_user, e_other],
            ),
        ):
            coord = SaunierGeniaCoordinator(hass, entry)
            msg = MagicMock()
            msg.topic = "ebusd/scan.08/id"
            msg.payload = "hmu00"
            coord._async_on_mqtt_message(msg)

            # Enabled HMUX0-only entities become disabled by INTEGRATION; USER and non-hmux0_only stay untouched
            self.assertEqual(e_cool.disabled_by, er.RegistryEntryDisabler.INTEGRATION)
            self.assertEqual(e_hc.disabled_by, er.RegistryEntryDisabler.INTEGRATION)
            self.assertEqual(e_hwc_user.disabled_by, er.RegistryEntryDisabler.USER)
            self.assertIsNone(e_other.disabled_by)

            # Switching back to HMUX0 re-enables INTEGRATION-disabled entities while preserving USER
            msg_hmux = MagicMock()
            msg_hmux.topic = "ebusd/scan.08/id"
            msg_hmux.payload = "hmux0"
            coord._async_on_mqtt_message(msg_hmux)

            self.assertIsNone(e_cool.disabled_by)
            self.assertIsNone(e_hc.disabled_by)
            self.assertEqual(e_hwc_user.disabled_by, er.RegistryEntryDisabler.USER)

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

        old_day_temp = MagicMock()
        old_day_temp.entity_id = "number.mipro_sense_controlador_de_clima_consigna_confort_calefaccion_zona_1_dia"
        old_day_temp.unique_id = "entry123_number_bass3_z1daytemp_value"

        old_cooling_desired = MagicMock()
        old_cooling_desired.entity_id = "number.mipro_sense_cooling_desired"
        old_cooling_desired.unique_id = (
            "entry123_number_bass3_z1coolingtempdesired_value"
        )

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
            old_day_temp,
            old_cooling_desired,
            active_entry,
        ]

        cfg_entry = MagicMock()
        cfg_entry.entry_id = "entry123"
        _async_cleanup_deprecated_entities(MagicMock(), cfg_entry)

        ent_reg.async_remove.assert_any_call("sensor.old_electric_today")
        ent_reg.async_remove.assert_any_call("sensor.old_daily_cop")
        ent_reg.async_remove.assert_any_call("sensor.old_comp_speed_rpm")
        ent_reg.async_remove.assert_any_call("binary_sensor.old_comp_active")
        ent_reg.async_remove.assert_any_call(
            "number.mipro_sense_controlador_de_clima_consigna_confort_calefaccion_zona_1_dia"
        )
        ent_reg.async_remove.assert_any_call("number.mipro_sense_cooling_desired")
        self.assertEqual(ent_reg.async_remove.call_count, 6)

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

        # 3. Active heating run where state_bytes is 09 00 00 66 (0x66 = 102 raw -> 51.0% modulation in 0.5% steps)
        # Even if legacy CSV 'modulation' byte 4 is stuck at 4, _get_compressor_modulation reads 51.0%
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"comp_speed": {"value": 614}, "fan_speed": {"value": 26128}, "modulation": {"value": 4}, "state_bytes": {"value": "09 00 00 66"}}',
        )
        self.assertTrue(_check_compressor_active(coord))
        self.assertEqual(_get_compressor_modulation(coord), 51.0)

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

        def strict_get_by_identifier(
            identifier: tuple[str, str], config_entry_id: str
        ) -> MagicMock:
            return mock_device

        dev_reg.async_get_device_by_identifier = MagicMock(
            side_effect=strict_get_by_identifier
        )

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

    def test_device_registry_lookup_scoped_and_legacy_fallback(self) -> None:
        """Verify HA 2026.8+ 2-arg async_get_device_by_identifier and legacy async_get_device fallback."""
        import sys

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry_xyz"
        entry.data = {}

        dr_mod = sys.modules["homeassistant.helpers.device_registry"]
        dev_reg = MagicMock()
        dr_mod.async_get.return_value = dev_reg
        mock_device = MagicMock()
        mock_device.id = "dev_id_xyz"

        def strict_get_by_identifier(
            identifier: tuple[str, str], config_entry_id: str
        ) -> MagicMock:
            return mock_device

        dev_reg.async_get_device_by_identifier = MagicMock(
            side_effect=strict_get_by_identifier
        )

        coord = SaunierGeniaCoordinator(hass, entry)
        self.assertEqual(coord.outdoor_device_id, "dev_id_xyz")
        dev_reg.async_get_device_by_identifier.assert_called_once_with(
            (DOMAIN, f"entry_xyz_{DEVICE_OUTDOOR_UNIT}"), "entry_xyz"
        )

        # Simulate pre-2026.8 Home Assistant without async_get_device_by_identifier
        legacy_reg = MagicMock(spec=["async_get_device", "async_update_device"])
        legacy_dev = MagicMock()
        legacy_dev.id = "legacy_dev_id"
        legacy_reg.async_get_device.return_value = legacy_dev
        dr_mod.async_get.return_value = legacy_reg

        coord._outdoor_device_id = None
        coord._async_update_device_registry(DEVICE_CLIMATE_CONTROLLER)
        legacy_reg.async_get_device.assert_called_with(
            identifiers={(DOMAIN, f"entry_xyz_{DEVICE_CLIMATE_CONTROLLER}")}
        )
        legacy_reg.async_update_device.assert_called_with(
            "legacy_dev_id", sw_version="0708", hw_version="4304"
        )
        self.assertEqual(coord.outdoor_device_id, "legacy_dev_id")

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

        coord.async_add_listener(
            CIRCUIT_BASV3, "Z1CoolingManualTemp", on_day_temp_updated
        )

        push_mqtt("ebusd/bass3/Z1CoolingManualTemp", '{"temp": {"value": 22.0}}')
        self.assertTrue(rev_callback_called)
        self.assertEqual(
            coord.get_float(CIRCUIT_BASS3, "Z1CoolingManualTemp", "temp"), 22.0
        )
        self.assertEqual(
            coord.get_float(CIRCUIT_BASV3, "Z1CoolingManualTemp", "temp"), 22.0
        )
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASS3)

        # Switch back to basv3
        push_mqtt("ebusd/basv3/Z1CoolingManualTemp", '{"temp": {"value": 22.5}}')
        self.assertEqual(coord.active_controller_circuit, CIRCUIT_BASV3)

        # 3. Parameter writing and active /get routing
        async def run_write_tests() -> None:
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new=AsyncMock(),
            ) as mock_pub:
                # When active circuit is basv3, calling async_write_parameter with CIRCUIT_BASS3 routes to basv3 topic
                await coord.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.0
                )
                mock_pub.assert_called_with(
                    hass,
                    "ebusd/basv3/Z1CoolingManualTemp/set",
                    "23.0",
                    qos=0,
                    retain=False,
                )
                # Both circuits reflect optimistic update
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1CoolingManualTemp", "temp"), 23.0
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASV3, "Z1CoolingManualTemp", "temp"), 23.0
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
                await coord.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", 21.5
                )
                mock_pub.assert_called_with(
                    hass,
                    "ebusd/ctlv3/Z1CoolingManualTemp/set",
                    "21.5",
                    qos=0,
                    retain=False,
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1CoolingManualTemp", "temp"), 21.5
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_CTLV3, "Z1CoolingManualTemp", "temp"), 21.5
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

    def test_hmu_and_hmux0_initial_hydration_queues(self) -> None:
        """Test that initial hydration filters incompatible b516 messages for HMU and keeps them for HMUX0."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_hydration"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        # 1. HMUX0 default queue
        coord_hmux0 = SaunierGeniaCoordinator(hass, entry)
        self.assertEqual(coord_hmux0.active_outdoor_circuit, CIRCUIT_HMUX0)

        with patch.object(coord_hmux0, "_async_run_hydration_queue") as mock_run_hmux0:
            coord_hmux0._async_start_initial_hydration(datetime.now())
            mock_run_hmux0.assert_called_once()
            hmux0_queue = mock_run_hmux0.call_args[0][0]

            # HMUX0 queue must include all 9 exclusive b516 messages
            for exclusive_msg in HMUX0_EXCLUSIVE_MESSAGES:
                self.assertIn(
                    (CIRCUIT_HMUX0, exclusive_msg),
                    hmux0_queue,
                    f"HMUX0 queue must contain {exclusive_msg}",
                )
            # HMUX0 queue must preserve vwzio messages
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyElectricHc"), hmux0_queue)

        # 2. HMU queue
        coord_hmu = SaunierGeniaCoordinator(hass, entry)
        # Simulate active HMU detection
        coord_hmu._active_outdoor_circuit = CIRCUIT_HMU

        with patch.object(coord_hmu, "_async_run_hydration_queue") as mock_run_hmu:
            coord_hmu._async_start_initial_hydration(datetime.now())
            mock_run_hmu.assert_called_once()
            hmu_queue = mock_run_hmu.call_args[0][0]

            # HMU queue must NOT contain any HMUX0 exclusive b516 messages
            for c, m in hmu_queue:
                if c in OUTDOOR_CIRCUITS:
                    self.assertNotIn(
                        m,
                        HMUX0_EXCLUSIVE_MESSAGES,
                        f"HMU queue must not contain incompatible message {m}",
                    )
            # HMU queue must contain all HMU_HW5103_HYDRATION_MESSAGES
            for hmu_msg in HMU_HW5103_HYDRATION_MESSAGES:
                self.assertIn(hmu_msg, hmu_queue)

            # HMU queue must strictly preserve vwzio messages
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyElectricHc"), hmu_queue)
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyThermalHc"), hmu_queue)

    def test_late_hmu_detection_updates_pending_hydration(self) -> None:
        """Test that late HMU detection purges incompatible messages and appends HMU messages."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_late_hmu"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry)
        self.assertEqual(coord.active_outdoor_circuit, CIRCUIT_HMUX0)

        # Pre-fill pending hydration queue as if HMUX0 initial hydration were running
        coord._pending_hydration = [
            (CIRCUIT_HMUX0, "RunDataFlowTemp"),
            (CIRCUIT_HMUX0, "PrEnergyElectricHc"),
            (CIRCUIT_HMUX0, "RunStatsAuxHeaterSwitches"),
            (CIRCUIT_VWZIO, "PrEnergyElectricHc"),
        ]
        mock_task = MagicMock()
        mock_task.done.return_value = False
        coord._hydration_task = mock_task

        # Late detection occurs via scan.08 packet
        msg = MagicMock()
        msg.topic = "ebusd/scan.08"
        msg.payload = '{"MF": "Vaillant", "ID": "HMU00", "SW": "0902", "HW": "5103"}'
        coord._async_on_mqtt_message(msg)

        self.assertEqual(coord.active_outdoor_circuit, CIRCUIT_HMU)

        # Incompatible outdoor messages must be purged from pending queue
        self.assertNotIn(
            (CIRCUIT_HMUX0, "PrEnergyElectricHc"), coord._pending_hydration
        )
        self.assertNotIn((CIRCUIT_HMU, "PrEnergyElectricHc"), coord._pending_hydration)
        self.assertNotIn(
            (CIRCUIT_HMUX0, "RunStatsAuxHeaterSwitches"), coord._pending_hydration
        )
        self.assertNotIn(
            (CIRCUIT_HMU, "RunStatsAuxHeaterSwitches"), coord._pending_hydration
        )

        # Common RunDataFlowTemp and vwzio PrEnergyElectricHc must be preserved
        self.assertIn((CIRCUIT_HMUX0, "RunDataFlowTemp"), coord._pending_hydration)
        self.assertIn((CIRCUIT_VWZIO, "PrEnergyElectricHc"), coord._pending_hydration)

        # HMU specific messages must have been appended
        for hmu_msg in HMU_HW5103_HYDRATION_MESSAGES:
            self.assertIn(hmu_msg, coord._pending_hydration)

    def test_fallback_poll_queues_for_hmu_and_hmux0(self) -> None:
        """Test periodic fallback poll queue construction for HMU vs HMUX0."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_fallback_poll"
        entry.data = {CONF_HAS_MIGO_LINK: False}
        entry.options = {}

        # 1. Fallback poll on HMUX0
        coord_hmux0 = SaunierGeniaCoordinator(hass, entry)
        coord_hmux0._active_outdoor_circuit = CIRCUIT_HMUX0

        with patch.object(
            coord_hmux0, "_async_force_poll_queue", return_value=None
        ) as mock_poll_hmux0:
            asyncio.run(coord_hmux0._async_run_fallback_poll(datetime.now()))
            mock_poll_hmux0.assert_called_once()
            hmux0_poll_queue = mock_poll_hmux0.call_args[0][0]

            self.assertIn((CIRCUIT_HMUX0, "PrEnergyElectricHc"), hmux0_poll_queue)
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyElectricHc"), hmux0_poll_queue)
            self.assertNotIn((CIRCUIT_HMU, "YieldHc"), hmux0_poll_queue)
            for msg in (
                "Z1SFMode",
                "Z1Status",
                "Z1OpMode",
                "Z1OpModeCooling",
                "Z1RoomTemp",
                "Z1ActualRoomTempDesired",
                "Z1CoolingTempDesired",
                "Z1CoolingTemp",
                "Z1HeatingState",
                "SystemOperatingState",
                "HwcOpMode",
                "HwcTempDesired",
                "HwcStatus",
                "HwcStorageTemp",
                "HwcLegionellaDay",
                "HwcLegionellaTime",
                "DisplayedOutsideTemp",
                "WaterPressure",
                "Hc1FlowTemp",
                "Hc1ActualFlowTempDesired",
                "Currenterror",
                "Hc1PumpStatus",
            ):
                self.assertIn((CIRCUIT_BASS3, msg), hmux0_poll_queue)

        # 2. Fallback poll on HMU
        coord_hmu = SaunierGeniaCoordinator(hass, entry)
        coord_hmu._active_outdoor_circuit = CIRCUIT_HMU

        with patch.object(
            coord_hmu, "_async_force_poll_queue", return_value=None
        ) as mock_poll_hmu:
            asyncio.run(coord_hmu._async_run_fallback_poll(datetime.now()))
            mock_poll_hmu.assert_called_once()
            hmu_poll_queue = mock_poll_hmu.call_args[0][0]

            # Incompatible b516 messages must NOT be polled on hmu
            self.assertNotIn((CIRCUIT_HMU, "PrEnergyElectricHc"), hmu_poll_queue)
            self.assertNotIn((CIRCUIT_HMUX0, "PrEnergyElectricHc"), hmu_poll_queue)

            # HMU energy messages must be polled
            self.assertIn((CIRCUIT_HMU, "YieldHc"), hmu_poll_queue)
            self.assertIn((CIRCUIT_HMU, "FlowPressure"), hmu_poll_queue)

            # vwzio energy messages must be preserved
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyElectricHc"), hmu_poll_queue)
            self.assertIn((CIRCUIT_VWZIO, "PrEnergyThermalHc"), hmu_poll_queue)

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

    def test_message_aliases_trigger_thermodynamics_recalculation(self) -> None:
        """Test that traditional eBUSd aliases trigger thermodynamic calculations immediately."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_alias_triggers"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}

        coord = SaunierGeniaCoordinator(hass, entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        with patch.object(
            coord,
            "_async_recalculate_thermodynamics",
            wraps=coord._async_recalculate_thermodynamics,
        ) as mock_recalc:
            # 1. Unrelated message must NOT trigger recalculation
            push_mqtt("ebusd/hmu/DateTime", '{"dcfstate": {"value": "valid"}}')
            mock_recalc.assert_not_called()

            # 2. Canonical message triggers recalculation exactly once
            push_mqtt("ebusd/hmu/RunDataReturnTemp", '{"value": {"value": 30.0}}')
            self.assertEqual(mock_recalc.call_count, 1)

            # 3. All 5 traditional aliases must each trigger recalculation exactly once
            # Alias 1: flowtemp -> RunDataFlowTemp
            push_mqtt("ebusd/hmu/flowtemp", '{"temp": {"value": 35.0}}')
            self.assertEqual(mock_recalc.call_count, 2)

            # Alias 2: buildingcircuitflow -> RunDataFlowRate
            push_mqtt("ebusd/hmu/buildingcircuitflow", '{"flow_rate": {"value": 1000}}')
            self.assertEqual(mock_recalc.call_count, 3)

            # Alias 3: waterthroughput -> RunDataFlowRate
            push_mqtt("ebusd/hmu/waterthroughput", '{"flow_rate": {"value": 1000}}')
            self.assertEqual(mock_recalc.call_count, 4)

            # Alias 4: rundatastatuscode -> HMUStatusCode
            push_mqtt(
                "ebusd/hmu/rundatastatuscode",
                '{"status": {"value": "heat_compressor_active"}}',
            )
            self.assertEqual(mock_recalc.call_count, 5)

            # Thermal power is now calculated: 1000 l/h * (35.0 - 30.0 K) * 1.163 = 5815.0 W
            self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_DELTA_T), 5.0)
            self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_THERMAL_POWER), 5815.0)
            # Live COP is still None because electric power consumption is not set yet
            self.assertIsNone(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP))

            # Alias 5: PowerConsumptionHmu -> RunDataElectricPowerConsumption (kW to W conversion)
            push_mqtt("ebusd/hmu/PowerConsumptionHmu", '{"value": {"value": 1.45}}')
            self.assertEqual(mock_recalc.call_count, 6)

            # 4. Full end-to-end verification:
            # Power converted: 1.45 kW -> 1450.0 W
            self.assertEqual(
                coord.get_float(
                    CIRCUIT_HMUX0, "RunDataElectricPowerConsumption", "power"
                ),
                1450.0,
            )
            # Live COP calculated immediately on PowerConsumptionHmu arrival:
            # 5815.0 W / 1450.0 W = 4.0103 -> 4.01
            self.assertEqual(coord.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 4.01)

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
        push_mqtt("ebusd/bass3/Z1CoolingManualTemp", '{"value": {"value": 21.0}}')
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
        push_mqtt("ebusd/ctlv2/Z1CoolingManualTemp", '{"value": {"value": 21.0}}')
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
        push_mqtt("ebusd/ctlv3/Z1CoolingManualTemp", '{"value": {"value": 21.0}}')
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

        # 5. Modern RunDataFlowRate supports both upstream 'value' and legacy 'flow_rate'
        #    without falsely raising outdated_hmux0_csv, and RunDataMaxResidualHead clears it
        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"value": {"value": 540}}')
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertEqual(coord.get_int("hmux0", "RunDataFlowRate", "value"), 540)

        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"flow_rate": {"value": 1450}}')
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertEqual(coord.get_int("hmux0", "RunDataFlowRate", "value"), 1450)

        push_mqtt("ebusd/hmux0/RunDataMaxResidualHead", '{"value": {"value": 900}}')
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertEqual(coord.get_int("hmux0", "RunDataMaxResidualHead", "value"), 900)

        # Legacy RunStatsHcStarts alias maps to RunStatsAuxHeaterSwitches
        push_mqtt("ebusd/hmux0/RunStatsHcStarts", '{"value": {"value": 42}}')
        self.assertEqual(
            coord.get_int("hmux0", "RunStatsAuxHeaterSwitches", "value"), 42
        )

        # 6. Legacy controller Z1DayTemp vs Z1CoolingManualTemp and SilentTimer_Slots
        push_mqtt("ebusd/bass3/Z1DayTemp", '{"temp": {"value": 22.0}}')
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        push_mqtt("ebusd/bass3/Z1CoolingManualTemp", '{"value": {"value": 22.0}}')
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # Missing SilentTimer_Slots (ERR: element not found) raises outdated_controller_csv
        push_mqtt("ebusd/bass3/SilentTimer_Slots", "ERR: element not found")
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        push_mqtt(
            "ebusd/bass3/SilentTimer_Slots",
            '{"mon": {"value": 1}, "tue": {"value": 1}, "wed": {"value": 0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # Missing Z1CoolingManualTemp (ERR: element not found) raises outdated_controller_csv
        push_mqtt("ebusd/bass3/Z1CoolingManualTemp", "ERR: element not found")
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # Unrelated modern telemetry does not falsely clear while Z1CoolingManualTemp is missing
        push_mqtt("ebusd/bass3/HolidayTemp", '{"value": {"value": 16.0}}')
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        push_mqtt("ebusd/bass3/Z1CoolingManualTemp", '{"value": {"value": 21.0}}')
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # Missing VentilationBoost (ERR: element not found) raises outdated_controller_csv
        # even when other v1.3.0 registers (SilentTimer_Slots, HolidayTemp) succeed
        push_mqtt("ebusd/bass3/VentilationBoost", "ERR: element not found")
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        push_mqtt("ebusd/bass3/HolidayTemp", '{"value": {"value": 16.0}}')
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        push_mqtt("ebusd/bass3/VentilationBoost", '{"value": {"value": "off"}}')
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # 7. CompressorSilentOperationLevel error vs valid on hmux0
        push_mqtt(
            "ebusd/hmux0/CompressorSilentOperationLevel", "ERR: element not found"
        )
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)

        push_mqtt(
            "ebusd/hmux0/CompressorSilentOperationLevel", '{"value": {"value": 0}}'
        )
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)

        # 8. HMU / HMU00 outdated vs custom detection (outdated_hmu_csv)
        # 8a. Default upstream Status01 (unmapped temp_1..temp_4) raises outdated_hmu_csv
        push_mqtt(
            "ebusd/hmu/Status01",
            '{"temp_1": {"value": 35.0}, "temp_2": {"value": 30.0}, "temp_3": {"value": 10.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        # Custom Status01 with flow_temp clears outdated_hmu_csv
        push_mqtt(
            "ebusd/hmu/Status01",
            '{"flow_temp": {"value": 35.0}, "return_temp": {"value": 30.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        # 8b. Default upstream ebusd.eu messages (waterthroughput) raise outdated_hmu_csv
        push_mqtt("ebusd/hmu/waterthroughput", '{"value": {"value": 850}}')
        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        push_mqtt(
            "ebusd/hmu/Status01",
            '{"flow_temp": {"value": 35.0}, "return_temp": {"value": 30.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        # 8c. CompressorSilentOperationLevel ERR on HMU raises outdated_hmu_csv
        #     and must NOT be falsely cleared by subsequent modern Status01 telemetry
        push_mqtt("ebusd/hmu/CompressorSilentOperationLevel", "ERR: element not found")
        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        push_mqtt(
            "ebusd/hmu/Status01",
            '{"flow_temp": {"value": 35.0}, "return_temp": {"value": 30.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        push_mqtt("ebusd/hmu/CompressorSilentOperationLevel", '{"value": {"value": 0}}')
        self.assertNotIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        # 8c-2. CompressorSilentOperationLevel ERR on HMUX0 must NOT be falsely cleared
        #       by subsequent modern StateCompressor / RunDataFlowRate / RunDataNominalFlowRate
        push_mqtt(
            "ebusd/hmux0/CompressorSilentOperationLevel", "ERR: element not found"
        )
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        push_mqtt(
            "ebusd/hmux0/StateCompressor",
            '{"flow_temp": {"value": 37.38}, "modulation": {"value": 0}}',
        )
        push_mqtt("ebusd/hmux0/RunDataFlowRate", '{"flow_rate": {"value": 1450}}')
        push_mqtt("ebusd/hmux0/RunDataNominalFlowRate", '{"value": {"value": 900}}')
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        push_mqtt(
            "ebusd/hmux0/CompressorSilentOperationLevel", '{"value": {"value": 40}}'
        )
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)

        # 8d. Also works on hmu00
        push_mqtt(
            "ebusd/hmu00/Status01",
            '{"temp_1": {"value": 35.0}, "temp_2": {"value": 30.0}}',
        )
        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

        push_mqtt(
            "ebusd/hmu00/Status01",
            '{"flow_temp": {"value": 35.0}, "return_temp": {"value": 30.0}}',
        )
        self.assertNotIn(ISSUE_OUTDATED_HMU_CSV, coord._active_repair_issues)

    def test_repair_issue_ebusd_slow_polling_seed(self) -> None:
        """Test detection and auto-clearing of slow polling issue (seed_mqtt_cfg)."""
        import sys

        ir_mod = sys.modules["homeassistant.helpers.issue_registry"]
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_slow_polling"
        entry.data = {"mqtt_prefix": "ebusd", CONF_HAS_MIGO_LINK: True}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload.encode("utf-8")
            coord._async_on_mqtt_message(msg)

        # Make ebus operational
        push_mqtt("ebusd/global/signal", '{"value": {"value": true}}')
        push_mqtt("ebusd/hmux0/Status01", '{"flow_temp": {"value": 35.0}}')
        self.assertTrue(coord.is_ebus_operational)

        # 1. First arrival of RunDataElectricPowerConsumption sets initial timestamp
        t0 = 1000.0
        with patch("time.monotonic", return_value=t0):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 450}}',
            )
        self.assertEqual(coord._last_power_consumption_receive_time, t0)
        self.assertNotIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)

        # 2. Arrival after 350s (>= 300s threshold) triggers slow polling issue
        t1 = t0 + 350.0
        with patch("time.monotonic", return_value=t1):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 460}}',
            )
        self.assertIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_with(
            hass,
            DOMAIN,
            ISSUE_EBUSD_SLOW_POLLING_SEED,
            is_fixable=False,
            severity=ANY,
            translation_key=ISSUE_EBUSD_SLOW_POLLING_SEED,
            translation_placeholders={"interval": "5.8"},
            learn_more_url="https://github.com/R91g/arotherm-genia-ebusd/blob/main/docs/installation.md#2-deploy-the-ebusd-csv-configuration",
        )

        # 3. Fast arrival (interval <= 60s) clears the issue automatically
        t2 = t1 + 20.0
        with patch("time.monotonic", return_value=t2):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 470}}',
            )
        self.assertNotIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_EBUSD_SLOW_POLLING_SEED
        )

        # 4. Watchdog trigger: power message is stale (>= 300s) while bus telemetry is active (<= 60s)
        ir_mod.async_create_issue.reset_mock()
        t3 = t2 + 350.0
        with patch("time.monotonic", return_value=t3):
            coord._last_telemetry_time = t3 - 10.0
            coord._async_check_watchdog(datetime.now())
        self.assertIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)
        ir_mod.async_create_issue.assert_called_once()

    def test_is_ebus_operational_and_running_binary_sensor(self) -> None:
        """Test is_ebus_operational gate and _check_ebusd_running binary sensor."""
        from custom_components.arotherm_genia_ebusd.binary_sensor import (
            _check_ebusd_running,
            _check_ebusd_signal,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        # 1. Unhydrated state -> not operational
        self.assertFalse(coord.is_ebus_operational)
        self.assertIsNone(_check_ebusd_signal(coord))
        self.assertIsNone(_check_ebusd_running(coord))

        # 2. Normal telemetry without global signal/running -> operational (optimistic)
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}
        self.assertTrue(coord.is_ebus_operational)

        # 3. ebusd/global/signal=false -> not operational
        coord._state[("global", "signal")] = {"value": "false"}
        self.assertFalse(coord.is_ebus_operational)
        self.assertFalse(_check_ebusd_signal(coord))

        # 4. signal recovers to true -> operational
        coord._state[("global", "signal")] = {"value": "true"}
        self.assertTrue(coord.is_ebus_operational)
        self.assertTrue(_check_ebusd_signal(coord))

        # 5. ebusd/global/running=off -> not operational
        coord._state[("global", "running")] = {"value": "off"}
        self.assertFalse(coord.is_ebus_operational)
        self.assertFalse(_check_ebusd_running(coord))

        # 6. running recovers to yes -> operational
        coord._state[("global", "running")] = {"value": "yes"}
        self.assertTrue(coord.is_ebus_operational)
        self.assertTrue(_check_ebusd_running(coord))

        # 7. Metadata-only state (e.g. ebusd/global/version = 26.1) without positive signal -> not operational
        coord_meta = SaunierGeniaCoordinator(MagicMock(), entry)
        coord_meta._state[("global", "version")] = {"value": "26.1"}
        self.assertFalse(coord_meta.is_ebus_operational)

        # 8. Communication silence timeout (> EBUSD_TRAFFIC_TIMEOUT_SECONDS) -> not operational
        coord._state.clear()
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}
        coord._last_telemetry_time = time.monotonic() - (
            EBUSD_TRAFFIC_TIMEOUT_SECONDS + 5
        )
        self.assertFalse(coord.is_ebus_operational)

        # 9. Watchdog notification triggers listeners on running/signal
        listener_called = False

        def _dummy_listener() -> None:
            nonlocal listener_called
            listener_called = True

        coord.async_add_listener("global", "running", _dummy_listener)
        coord._async_check_watchdog(datetime.now())
        self.assertTrue(listener_called)

        # 10. Receiving fresh message restores last_telemetry_time and operational status
        msg_payload = '{"temp1": {"value": 36.0}}'
        mqtt_msg = MagicMock(topic="ebusd/hmux0/Status01", payload=msg_payload)
        coord._async_on_mqtt_message(mqtt_msg)
        self.assertIsNotNone(coord._last_telemetry_time)
        self.assertGreater(
            coord._last_telemetry_time,  # type: ignore[operator]
            time.monotonic() - 2,
        )
        self.assertTrue(coord.is_ebus_operational)

    def test_services_guarded_by_is_ebus_operational(self) -> None:
        """Verify that domain services reject execution when is_ebus_operational is False."""
        from homeassistant.exceptions import HomeAssistantError

        hass = MagicMock()
        registered_services: dict[str, Any] = {}

        def mock_register(
            domain: str,
            service_name: str,
            handler: Any,
            schema: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            registered_services[service_name] = handler

        hass.services.has_service.return_value = False
        hass.services.async_register.side_effect = mock_register

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)
        # Empty state -> is_ebus_operational is False
        self.assertFalse(coord.is_ebus_operational)
        hass.data = {DOMAIN: {"entry_id": coord}}

        _async_register_services(hass)

        call = MagicMock()
        call.data = {
            "circuit_type": "heating",
            "day": "Monday",
            "slot": 1,
            "start_time": "08:00",
            "end_time": "12:00",
        }

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_SET_WEEKLY_TIMER](call))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_FORCE_DHW_BOOST](call))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_SET_HOLIDAY_MODE](call))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_CANCEL_HOLIDAY_MODE](call))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_QUICK_VETO](call))

        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_CANCEL_QUICK_VETO](call))

    def test_quick_veto_services_and_coordinator_integration(self) -> None:
        """Verify quick_veto and cancel_quick_veto actions and coordinator parameter cascade."""
        from custom_components.arotherm_genia_ebusd import _async_register_services

        registered_services: dict[str, Any] = {}

        def mock_register(
            domain: str, service: str, handler: Any, *args: Any, **kwargs: Any
        ) -> None:
            registered_services[service] = handler

        hass = MagicMock()
        hass.services.has_service = lambda domain, s: s in registered_services
        hass.services.async_register = mock_register
        hass.async_create_task.side_effect = lambda coro: coro.close()
        hass.data = {}

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)
        hass.data = {DOMAIN: {"entry_id": coord}}

        writes: list[tuple[str, str, Any]] = []

        async def mock_write(circuit: str, param: str, val: Any) -> bool:
            writes.append((circuit, param, val))
            coord._state[(circuit.lower(), param.lower())] = {"value": val}
            return True

        coord.async_write_parameter = mock_write
        # Make operational
        coord._state[("global", "signal")] = {"value": "true"}
        coord._state[("global", "running")] = {"value": "on"}
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}

        _async_register_services(hass)
        self.assertIn(SERVICE_QUICK_VETO, registered_services)
        self.assertIn(SERVICE_CANCEL_QUICK_VETO, registered_services)

        # 1. Starting from heating OFF
        coord._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "off"}
        coord._state[(CIRCUIT_BASS3.lower(), "z1manualtemp")] = {"value": 21.5}

        call = MagicMock()
        call.data = {"temperature": 23.5, "duration": 2.0}
        asyncio.run(registered_services[SERVICE_QUICK_VETO](call))

        # Expected writes: Z1OpMode auto -> Z1QuickVetoTemp 23.5 -> Z1QuickVetoDuration 2.0 -> Z1SFMode veto
        self.assertEqual(coord.pre_veto_opmode, "off")
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "auto"), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 23.5), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 2.0), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), writes)

        # 2. Cancel quick veto: writes ONLY Z1SFMode=auto (never Z1QuickVetoDuration=0.0) and restores off
        writes.clear()
        call.data = {}
        asyncio.run(registered_services[SERVICE_CANCEL_QUICK_VETO](call))
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "auto"), writes)
        self.assertNotIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 0.0), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1OpMode", "off"), writes)
        self.assertIsNone(coord.pre_veto_opmode)

        # 3. Starting from heating AUTO with default parameters
        writes.clear()
        coord._state[(CIRCUIT_BASS3.lower(), "z1opmode")] = {"value": "auto"}
        coord._state[(CIRCUIT_BASS3.lower(), "z1actualroomtempdesired")] = {
            "value": 20.0
        }
        coord._state[(CIRCUIT_BASS3.lower(), "z1quickvetoduration")] = {"value": 3.0}

        call.data = {}
        asyncio.run(registered_services[SERVICE_QUICK_VETO](call))
        # Default temperature is current + 3.0 = 23.0, default duration is 3.0
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 23.0), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), writes)

        # 4. Starting from heating AUTO with custom quick_veto_boost_delta
        writes.clear()
        coord.quick_veto_boost_delta = 4.5
        asyncio.run(registered_services[SERVICE_QUICK_VETO](call))
        # Custom delta 4.5 -> 20.0 + 4.5 = 24.5
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoTemp", 24.5), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 3.0), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1SFMode", "veto"), writes)

        # 5. Over-limit duration requested: clamped to 12.0 hours (hardware maximum)
        writes.clear()
        asyncio.run(coord.async_set_quick_veto(temperature=21.0, duration=20.0))
        self.assertIn((CIRCUIT_BASS3, "Z1QuickVetoDuration", 12.0), writes)

        # 6. Cooling Quick Veto: in cooling AUTO, outside slot (desired=99) -> takes manual temp (23.5), sets day
        writes.clear()
        coord._state[(CIRCUIT_BASS3.lower(), "z1opmodecooling")] = {"value": "auto"}
        coord._state[(CIRCUIT_BASS3.lower(), "coolingreleasestatus")] = {"value": "on"}
        coord._state[(CIRCUIT_BASS3.lower(), "z1coolingmanualtemp")] = {"value": 23.5}
        coord._state[(CIRCUIT_BASS3.lower(), "z1coolingtempdesired")] = {"value": 99.0}
        self.assertTrue(coord.is_cooling_active())

        call.data = {}
        asyncio.run(registered_services[SERVICE_QUICK_VETO](call))
        self.assertTrue(coord.cooling_quick_veto_active)
        self.assertEqual(coord.cooling_quick_veto_target_temp, 23.5)
        self.assertIn((CIRCUIT_BASS3, "Z1OpModeCooling", "day"), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.5), writes)
        self.assertIn((CIRCUIT_BASS3, "Z1CoolingTempDesired", 23.5), writes)

        # 7. Cancel cooling quick veto via service
        writes.clear()
        asyncio.run(registered_services[SERVICE_CANCEL_QUICK_VETO](call))
        self.assertFalse(coord.cooling_quick_veto_active)
        self.assertIn((CIRCUIT_BASS3, "Z1OpModeCooling", "auto"), writes)

        # 8. Start and cancel Intensive Ventilation Boost via services
        self.assertIn(SERVICE_START_VENTILATION_BOOST, registered_services)
        self.assertIn(SERVICE_CANCEL_VENTILATION_BOOST, registered_services)

        writes.clear()
        coord._state[("global", "signal")] = {"value": "false"}
        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered_services[SERVICE_START_VENTILATION_BOOST](call))

        coord._state[("global", "signal")] = {"value": "true"}
        asyncio.run(registered_services[SERVICE_START_VENTILATION_BOOST](call))
        self.assertIn((CIRCUIT_BASS3, "VentilationBoost", "on"), writes)
        self.assertTrue(coord.get_ventilation_remaining_attributes()["is_active"])
        self.assertGreater(coord.get_ventilation_remaining_minutes(), 0)

        writes.clear()
        asyncio.run(registered_services[SERVICE_CANCEL_VENTILATION_BOOST](call))
        self.assertIn((CIRCUIT_BASS3, "VentilationBoost", "off"), writes)
        self.assertFalse(coord.get_ventilation_remaining_attributes()["is_active"])
        self.assertEqual(coord.get_ventilation_remaining_minutes(), 0)

    def test_currenterror_sensors_outdoor_controller_and_vwzio(self) -> None:
        """Verify Currenterror diagnostic sensor parsing, fallback and subscriptions across all 3 devices."""
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
            _format_currenterror_msg,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        # 1. Test _format_currenterror_msg edge cases
        self.assertIsNone(_format_currenterror_msg(None))
        self.assertEqual(_format_currenterror_msg({}), None)
        self.assertEqual(_format_currenterror_msg({"error": 0, "error_1": "-"}), "OK")
        self.assertEqual(
            _format_currenterror_msg({"error": "65535", "error_1": "none"}), "OK"
        )
        self.assertEqual(
            _format_currenterror_msg({"error": "280", "error_1": "302"}), "280, 302"
        )

        # 2. Outdoor unit error sensor (hmu_current_error)
        hmu_desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "hmu_current_error")
        hmu_sensor = SaunierGeniaSensor(coord, hmu_desc)
        self.assertTrue(
            {(CIRCUIT_HMUX0, "Currenterror"), (CIRCUIT_HMU, "Currenterror")}.issubset(
                set(hmu_sensor._subscriptions)
            )
        )
        self.assertIsNone(hmu_sensor.native_value)

        # Push "OK" to HMUX0
        push_mqtt(
            "ebusd/hmux0/Currenterror",
            '{"error": {"value": 0}, "error_1": {"value": 0}}',
        )
        self.assertEqual(hmu_sensor.native_value, "OK")

        # Push error to HMU fallback
        coord._state.clear()
        push_mqtt(
            "ebusd/hmu/Currenterror",
            '{"error": {"value": 102}, "error_1": {"value": 0}}',
        )
        self.assertEqual(hmu_sensor.native_value, "102")

        # 3. Climate controller error sensor (controller_current_error)
        ctrl_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "controller_current_error"
        )
        ctrl_sensor = SaunierGeniaSensor(coord, ctrl_desc)
        expected_ctrl_subs = {(c, "Currenterror") for c in CONTROLLER_CIRCUITS}
        self.assertTrue(expected_ctrl_subs.issubset(set(ctrl_sensor._subscriptions)))

        coord._state.clear()
        self.assertIsNone(ctrl_sensor.native_value)
        push_mqtt(
            "ebusd/bass3/Currenterror",
            '{"error": {"value": 0}, "error_1": {"value": 0}}',
        )
        self.assertEqual(ctrl_sensor.native_value, "OK")

        # Push error to ctlv2 fallback
        coord._state.clear()
        push_mqtt(
            "ebusd/ctlv2/Currenterror",
            '{"error": {"value": 55}, "error_1": {"value": 0}}',
        )
        self.assertEqual(ctrl_sensor.native_value, "55")

        # 4. VWZIO error sensor (vwzio_current_error)
        vwzio_desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "vwzio_current_error"
        )
        vwzio_sensor = SaunierGeniaSensor(coord, vwzio_desc)
        coord._state.clear()
        self.assertIsNone(vwzio_sensor.native_value)
        push_mqtt(
            "ebusd/vwzio/Currenterror",
            '{"error": {"value": 0}, "error_1": {"value": 0}}',
        )
        self.assertEqual(vwzio_sensor.native_value, "OK")
        push_mqtt(
            "ebusd/vwzio/Currenterror",
            '{"error": {"value": 277}, "error_1": {"value": 280}}',
        )
        self.assertEqual(vwzio_sensor.native_value, "277, 280")

    def test_stats_compressor_hours_and_starts_fallback(self) -> None:
        """Verify stats_compressor_hours and stats_compressor_starts fallback to CompressorHours/Starts."""
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            coord._async_on_mqtt_message(msg)

        desc_h = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "stats_compressor_hours"
        )
        desc_s = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "stats_compressor_starts"
        )

        sensor_h = SaunierGeniaSensor(coord, desc_h)
        sensor_s = SaunierGeniaSensor(coord, desc_s)

        # Check subscriptions include fallback
        self.assertIn((CIRCUIT_HMU, "CompressorHours"), sensor_h._subscriptions)
        self.assertIn((CIRCUIT_HMU, "CompressorStarts"), sensor_s._subscriptions)

        # 1. Initially None
        self.assertIsNone(sensor_h.native_value)
        self.assertIsNone(sensor_s.native_value)

        # 2. Push Vaillant aroTHERM fallback messages (CompressorHours / CompressorStarts)
        push_mqtt("ebusd/hmu/CompressorHours", '{"value": 5885}')
        push_mqtt("ebusd/hmu/CompressorStarts", '{"value": 2444}')
        self.assertEqual(sensor_h.native_value, 5885)
        self.assertEqual(sensor_s.native_value, 2444)

        # 3. Push primary RunStats messages (Saunier Duval GeniaAir Max) -> takes precedence
        push_mqtt("ebusd/hmux0/RunStatsCompressorHours", '{"value": 6000}')
        push_mqtt("ebusd/hmux0/RunStatsCompressorStarts", '{"value": 2500}')
        self.assertEqual(sensor_h.native_value, 6000)
        self.assertEqual(sensor_s.native_value, 2500)

    def test_z1_room_humidity_legacy_alias_across_controller_circuits(self) -> None:
        """Verify legacy Z1MaxFlowTempDesired MQTT payloads normalize to Z1RoomHumidity across controller circuits."""
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "z1_room_humidity")
        sensor = SaunierGeniaSensor(coord, desc)
        self.assertIsNone(sensor.native_value)

        notified = False

        def on_humidity_update() -> None:
            nonlocal notified
            notified = True

        coord.async_add_listener(CIRCUIT_BASS3, "Z1RoomHumidity", on_humidity_update)

        msg = MagicMock()
        msg.topic = "ebusd/basv3/Z1MaxFlowTempDesired"
        msg.payload = '{"value": 63}'
        coord._async_on_mqtt_message(msg)

        self.assertTrue(notified)
        self.assertEqual(sensor.native_value, 63.0)
        for circ in (CIRCUIT_BASS3, CIRCUIT_BASV3, CIRCUIT_CTLV2, CIRCUIT_CTLV3):
            self.assertEqual(coord.get_float(circ, "Z1RoomHumidity", "value"), 63.0)

    def test_ebusd_tcp_polling_disabled_by_default(self) -> None:
        """Verify TCP polling returns early and does not connect when disabled in options."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        self.assertFalse(coord.is_ebusd_tcp_enabled)
        self.assertEqual(coord.ebusd_tcp_host, "127.0.0.1")
        self.assertEqual(coord.ebusd_tcp_port, 8888)

        with patch("asyncio.open_connection") as mock_conn:
            asyncio.run(coord._async_fetch_ebusd_tcp_info())
            mock_conn.assert_not_called()

    def test_ebusd_tcp_polling_fetches_and_populates_metrics(self) -> None:
        """Verify TCP polling connects, requests info, parses metrics, and notifies entities."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_EBUSD_TCP_HOST,
            CONF_EBUSD_TCP_PORT,
            CONF_ENABLE_EBUSD_TCP,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "192.168.1.55",
            CONF_EBUSD_TCP_PORT: 8889,
        }
        coord = SaunierGeniaCoordinator(MagicMock(), entry)
        self.assertTrue(coord.is_ebusd_tcp_enabled)

        sample_lines = [
            b"version: ebusd 26.1.26.1\n",
            b"device: /dev/ttyUSB0\n",
            b"signal: acquired\n",
            b"symbol rate: 29\n",
            b"max symbol rate: 98\n",
            b"min arbitration micros: 12\n",
            b"max arbitration micros: 45000\n",
            b"reconnects: 3\n",
            b"masters: 4\n",
            b"messages: 652\n",
            b"\n",
        ]

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=sample_lines)
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        notified_symbol_rate = False

        def on_symbol_rate() -> None:
            nonlocal notified_symbol_rate
            notified_symbol_rate = True

        coord.async_add_listener(CIRCUIT_GLOBAL, "symbol_rate", on_symbol_rate)

        with patch(
            "asyncio.open_connection", return_value=(mock_reader, mock_writer)
        ) as mock_conn:
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        mock_conn.assert_called_once_with("192.168.1.55", 8889)
        mock_writer.write.assert_any_call(b"info\n")
        mock_writer.write.assert_any_call(b"quit\n")
        mock_writer.close.assert_called_once()

        self.assertTrue(notified_symbol_rate)
        self.assertEqual(
            coord.get_str(CIRCUIT_GLOBAL, "version", "value"), "ebusd 26.1.26.1"
        )
        self.assertEqual(coord.get_int(CIRCUIT_GLOBAL, "symbol_rate", "value"), 29)
        self.assertEqual(coord.get_int(CIRCUIT_GLOBAL, "reconnects", "value"), 3)
        self.assertEqual(coord.get_int(CIRCUIT_GLOBAL, "masters", "value"), 4)
        self.assertEqual(
            coord.get_int(CIRCUIT_GLOBAL, "arbitration_latency", "value"), 45
        )

    def test_ebusd_tcp_polling_handles_connection_error_gracefully(self) -> None:
        """Verify TCP polling catches network errors cleanly without crashing."""
        from custom_components.arotherm_genia_ebusd.const import CONF_ENABLE_EBUSD_TCP

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {CONF_ENABLE_EBUSD_TCP: True}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        with patch("asyncio.open_connection", side_effect=OSError("Host unreachable")):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        # No error raised and state unpopulated
        self.assertIsNone(coord.get_int(CIRCUIT_GLOBAL, "symbol_rate", "value"))

    def test_ebusd_tcp_polling_falls_back_to_addon_hostname(self) -> None:
        """Verify TCP polling tries add-on hostnames before 127.0.0.1 and persists winner."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_EBUSD_TCP_HOST,
            CONF_ENABLE_EBUSD_TCP,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "127.0.0.1",
        }
        hass = MagicMock()
        hass.config.components = ()
        coord = SaunierGeniaCoordinator(hass, entry)

        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        mock_reader = AsyncMock()
        mock_reader.readline.side_effect = [
            b"version: ebusd 26.1\n",
            b"symbol rate: 22\n",
            b"",
        ]

        calls = []

        async def fake_open_connection(h: str, p: int):
            calls.append((h, p))
            if h == "b4d7ad18-ebusd":
                return mock_reader, mock_writer
            raise OSError("Connection refused")

        with patch("asyncio.open_connection", side_effect=fake_open_connection):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertEqual(calls, [("b4d7ad18-ebusd", 8888)])
        self.assertEqual(coord.get_int(CIRCUIT_GLOBAL, "symbol_rate", "value"), 22)
        self.assertEqual(coord.ebusd_tcp_host, "b4d7ad18-ebusd")

    def test_ebusd_tcp_polling_falls_back_to_loopback_after_addon_fails(self) -> None:
        """Verify TCP polling falls back to 127.0.0.1 if HA add-on hostnames fail."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_EBUSD_TCP_HOST,
            CONF_ENABLE_EBUSD_TCP,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "127.0.0.1",
        }
        hass = MagicMock()
        hass.config.components = ()
        coord = SaunierGeniaCoordinator(hass, entry)

        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        mock_reader = AsyncMock()
        mock_reader.readline.side_effect = [
            b"version: ebusd 26.1\n",
            b"symbol rate: 25\n",
            b"",
        ]

        calls = []

        async def fake_open_connection(h: str, p: int):
            calls.append((h, p))
            if h == "127.0.0.1":
                return mock_reader, mock_writer
            raise OSError("DNS/connection error")

        with patch("asyncio.open_connection", side_effect=fake_open_connection):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertEqual(
            calls,
            [
                ("b4d7ad18-ebusd", 8888),
                ("local-ebusd", 8888),
                ("ebusd", 8888),
                ("ebusd.local", 8888),
                ("127.0.0.1", 8888),
            ],
        )
        self.assertEqual(coord.get_int(CIRCUIT_GLOBAL, "symbol_rate", "value"), 25)

    def test_ebusd_daemon_sensors_disabled_by_default(self) -> None:
        """Verify physical metrics without MQTT route are disabled by default in registry."""
        from custom_components.arotherm_genia_ebusd.button import BUTTON_DESCRIPTIONS
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
        )

        disabled_keys = {
            "ebusd_symbol_rate",
            "ebusd_reconnects",
            "ebusd_masters",
            "ebusd_arbitration_latency",
            "ebusd_missing_csv_devices",
        }
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in disabled_keys:
                self.assertFalse(
                    desc.entity_registry_enabled_default,
                    f"Sensor '{desc.key}' should be disabled by default.",
                )

        for btn_desc in BUTTON_DESCRIPTIONS:
            self.assertFalse(
                btn_desc.entity_registry_enabled_default,
                f"Button '{btn_desc.key}' should be disabled by default.",
            )

    def test_ebusd_tcp_polling_detects_unloaded_csv_devices(self) -> None:
        """Verify TCP polling detects scanned devices without loaded CSV files."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_EBUSD_TCP_HOST,
            CONF_ENABLE_EBUSD_TCP,
        )

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "192.168.1.100",
        }
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        sample_lines = [
            b"version: ebusd 26.1.26.1\n",
            b'address 04: slave #25, scanned "MF=Vaillant;ID=NETX3;SW=0129;HW=0404", loaded "vaillant/04.netx3.csv"\n',
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 76: slave #9, scanned "MF=Vaillant;ID=VWZIO;SW=0500;HW=0504"\n',
            b'address f6: slave #10, scanned "MF=Vaillant;ID=NETX3;SW=0129;HW=0404", loaded "vaillant/f6.netx3.csv"\n',
            b"\n",
        ]

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=sample_lines)
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        state_data = coord._state.get((CIRCUIT_GLOBAL, "missing_csv_devices"))
        self.assertIsNotNone(state_data)
        assert state_data is not None
        self.assertEqual(state_data["value"], "VWZIO")
        self.assertEqual(state_data["missing_count"], 1)
        self.assertEqual(
            state_data["missing_devices"], ["VWZIO (addr: 76, SW: 0500, HW: 0504)"]
        )
        self.assertEqual(
            state_data["loaded_devices"],
            [
                "04: NETX3 (vaillant/04.netx3.csv)",
                "08: HMUX0 (vaillant/08.hmux0.csv)",
                "f6: NETX3 (vaillant/f6.netx3.csv)",
            ],
        )
        self.assertEqual(state_data["total_scanned"], 4)

    def test_ebusd_tcp_polling_missing_csv_ok_when_all_loaded(self) -> None:
        """Verify missing CSV device sensor reports 'OK' when all scanned devices have loaded CSVs."""
        from custom_components.arotherm_genia_ebusd.const import CONF_ENABLE_EBUSD_TCP

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {CONF_ENABLE_EBUSD_TCP: True}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        sample_lines = [
            b"version: ebusd 26.1.26.1\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 76: slave #9, scanned "MF=Vaillant;ID=VWZIO;SW=0500;HW=0504", loaded "vaillant/76.vwzio.csv"\n',
            b"\n",
        ]

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=sample_lines)
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        state_data = coord._state.get((CIRCUIT_GLOBAL, "missing_csv_devices"))
        self.assertIsNotNone(state_data)
        assert state_data is not None
        self.assertEqual(state_data["value"], "OK")
        self.assertEqual(state_data["missing_count"], 0)
        self.assertEqual(state_data["missing_devices"], [])
        self.assertEqual(
            state_data["loaded_devices"],
            ["08: HMUX0 (vaillant/08.hmux0.csv)", "76: VWZIO (vaillant/76.vwzio.csv)"],
        )
        self.assertEqual(state_data["total_scanned"], 2)

    def test_ebusd_tcp_reload_and_scan_commands(self) -> None:
        """Verify reload and scan TCP commands send exact payloads and refresh info."""
        from homeassistant.exceptions import HomeAssistantError

        from custom_components.arotherm_genia_ebusd.button import (
            BUTTON_DESCRIPTIONS,
            SaunierGeniaButton,
        )
        from custom_components.arotherm_genia_ebusd.const import CONF_ENABLE_EBUSD_TCP

        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {CONF_ENABLE_EBUSD_TCP: True}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        reload_btn = SaunierGeniaButton(coord, BUTTON_DESCRIPTIONS[0])
        scan_btn = SaunierGeniaButton(coord, BUTTON_DESCRIPTIONS[1])
        self.assertTrue(reload_btn.available)
        self.assertTrue(scan_btn.available)

        with (
            patch.object(
                coord, "_async_send_ebusd_tcp_command", new_callable=AsyncMock
            ) as mock_send,
            patch.object(
                coord, "_async_fetch_ebusd_tcp_info", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_send.return_value = "done"

            asyncio.run(reload_btn.async_press())
            mock_send.assert_called_once_with("reload\n")
            mock_fetch.assert_called_once()

            mock_send.reset_mock()
            mock_fetch.reset_mock()

            asyncio.run(scan_btn.async_press())
            mock_send.assert_called_once_with("scan config\n")
            mock_fetch.assert_called_once()

        # Connection error raises HomeAssistantError
        with (
            patch.object(
                coord,
                "_async_open_tcp_connection",
                side_effect=OSError("Network down"),
            ),
            self.assertRaises(HomeAssistantError),
        ):
            asyncio.run(coord.async_ebusd_tcp_reload())

        with (
            patch.object(
                coord,
                "_async_open_tcp_connection",
                side_effect=OSError("Network down"),
            ),
            self.assertRaises(HomeAssistantError),
        ):
            asyncio.run(coord.async_ebusd_tcp_scan())

    def test_async_sync_tcp_diagnostic_entities(self) -> None:
        """Verify dynamic entity registry synchronization when TCP option changes."""
        from homeassistant.helpers import entity_registry as er

        from custom_components.arotherm_genia_ebusd import (
            _async_sync_tcp_diagnostic_entities,
        )
        from custom_components.arotherm_genia_ebusd.const import CONF_ENABLE_EBUSD_TCP

        hass = MagicMock()
        mock_ent_reg = MagicMock()

        entry = MagicMock()
        entry.entry_id = "test_entry_123"
        entry.options = {CONF_ENABLE_EBUSD_TCP: True}

        mock_entity_disabled = MagicMock()
        mock_entity_disabled.unique_id = "vaillant_global_symbol_rate_value"
        mock_entity_disabled.entity_id = "sensor.ebusd_symbol_rate"
        mock_entity_disabled.disabled = True
        mock_entity_disabled.disabled_by = er.RegistryEntryDisabler.INTEGRATION

        mock_missing_disabled = MagicMock()
        mock_missing_disabled.unique_id = "vaillant_global_missing_csv_devices_value"
        mock_missing_disabled.entity_id = "sensor.ebusd_missing_csv_devices"
        mock_missing_disabled.disabled = True
        mock_missing_disabled.disabled_by = er.RegistryEntryDisabler.INTEGRATION

        mock_btn_disabled = MagicMock()
        mock_btn_disabled.unique_id = "vaillant_button_ebusd_reload_csv"
        mock_btn_disabled.entity_id = "button.ebusd_reload_csv"
        mock_btn_disabled.disabled = True
        mock_btn_disabled.disabled_by = er.RegistryEntryDisabler.INTEGRATION

        mock_user_disabled = MagicMock()
        mock_user_disabled.unique_id = "vaillant_ebusd_reconnects"
        mock_user_disabled.entity_id = "sensor.ebusd_reconnects"
        mock_user_disabled.disabled = True
        mock_user_disabled.disabled_by = er.RegistryEntryDisabler.USER

        mock_unrelated_disabled = MagicMock()
        mock_unrelated_disabled.unique_id = "vaillant_unrelated_sensor"
        mock_unrelated_disabled.entity_id = "sensor.unrelated"
        mock_unrelated_disabled.disabled = True
        mock_unrelated_disabled.disabled_by = er.RegistryEntryDisabler.INTEGRATION

        entries_phase1 = [
            mock_entity_disabled,
            mock_missing_disabled,
            mock_btn_disabled,
            mock_user_disabled,
            mock_unrelated_disabled,
        ]

        with (
            patch.object(er, "async_get", return_value=mock_ent_reg),
            patch.object(
                er, "async_entries_for_config_entry", return_value=entries_phase1
            ),
        ):
            # 1. TCP enabled: enables disabled TCP entities
            _async_sync_tcp_diagnostic_entities(hass, entry, reload_on_change=True)
            mock_ent_reg.async_update_entity.assert_any_call(
                "sensor.ebusd_symbol_rate", disabled_by=None
            )
            mock_ent_reg.async_update_entity.assert_any_call(
                "sensor.ebusd_missing_csv_devices", disabled_by=None
            )
            mock_ent_reg.async_update_entity.assert_any_call(
                "button.ebusd_reload_csv", disabled_by=None
            )
            # Unrelated entity remains untouched
            self.assertEqual(mock_ent_reg.async_update_entity.call_count, 3)
            hass.async_create_task.assert_called_once()

        # 2. TCP disabled: disables active TCP entities
        entry.options = {CONF_ENABLE_EBUSD_TCP: False}
        mock_entity_enabled = MagicMock()
        mock_entity_enabled.unique_id = "vaillant_ebusd_symbol_rate"
        mock_entity_enabled.entity_id = "sensor.ebusd_symbol_rate"
        mock_entity_enabled.disabled = False
        entries_phase2 = [mock_entity_enabled]
        mock_ent_reg.async_update_entity.reset_mock()

        with (
            patch.object(er, "async_get", return_value=mock_ent_reg),
            patch.object(
                er, "async_entries_for_config_entry", return_value=entries_phase2
            ),
        ):
            _async_sync_tcp_diagnostic_entities(hass, entry, reload_on_change=False)
            mock_ent_reg.async_update_entity.assert_called_once_with(
                "sensor.ebusd_symbol_rate",
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            )

    def test_real_coordinator_cooling_veto_preserves_manual_temp_and_timer_restore(
        self,
    ) -> None:
        """Verify real coordinator preserves Z1CoolingManualTemp in auto slots and restores via timeout without clobbering Desired."""

        async def _run() -> None:
            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="cool_veto_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "CoolingReleaseStatus")] = {
                "value": "on"
            }
            coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingManualTemp")] = {
                "value": 26.0
            }
            coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingTempDesired")] = {
                "value": 24.0
            }
            coord._state[(CIRCUIT_HMUX0.lower(), "Status01")] = {"temp1": 28.0}

            published: list[tuple[str, str]] = []
            scheduled_timers: list[tuple[float, Any]] = []

            async def _fake_publish(_h: Any, topic: str, payload: str, **kwargs: Any):
                published.append((topic, str(payload)))

            def _fake_call_later(_h: Any, delay: float, cb: Any):
                scheduled_timers.append((delay, cb))
                return MagicMock()

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=_fake_call_later,
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                # 1. Start cooling quick veto (auto slot is 24.0, but ManualTemp is 26.0)
                await coord.async_set_cooling_quick_veto(temperature=22.5, duration=3.0)

                self.assertTrue(coord.cooling_quick_veto_active)
                self.assertEqual(coord.pre_cooling_veto_opmode, "auto")
                self.assertEqual(coord.pre_cooling_veto_temp, 26.0)
                self.assertEqual(coord.cooling_quick_veto_target_temp, 22.5)
                self.assertEqual(len(scheduled_timers), 1)
                self.assertAlmostEqual(scheduled_timers[0][0], 10800.0)
                initial_end = coord._cooling_veto_end_time

                self.assertEqual(
                    published,
                    [
                        ("ebusd/bass3/Z1OpModeCooling/set", "day"),
                        ("ebusd/bass3/Z1CoolingManualTemp/set", "22.5"),
                        ("ebusd/bass3/Z1CoolingTempDesired/set", "22.5"),
                    ],
                )

                # Verify Store saved active veto
                saved = await coord._cooling_veto_store.async_load()
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved["active_temp"], 22.5)
                self.assertEqual(saved["pre_opmode"], "auto")
                self.assertEqual(saved["pre_temp"], 26.0)

                # 2. Update veto temp to 21.0: does NOT recreate timer, updates Store
                published.clear()
                await coord.async_update_cooling_quick_veto_temperature(21.0)
                self.assertEqual(coord.cooling_quick_veto_target_temp, 21.0)
                self.assertEqual(coord._cooling_veto_end_time, initial_end)
                self.assertEqual(len(scheduled_timers), 1)
                saved2 = await coord._cooling_veto_store.async_load()
                assert saved2 is not None
                self.assertEqual(saved2["active_temp"], 21.0)

                # 3. Simulate timer expiration firing
                published.clear()
                _, timeout_cb = scheduled_timers[0]
                timeout_cb(datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord.cooling_quick_veto_active)
                # ManualTemp MUST be restored to 26.0 (NOT 24.0!), Z1CoolingTempDesired must NOT be overwritten
                self.assertEqual(
                    published,
                    [
                        ("ebusd/bass3/Z1OpModeCooling/set", "auto"),
                        ("ebusd/bass3/Z1CoolingManualTemp/set", "26.0"),
                    ],
                )
                # Cached Boost Z1CoolingTempDesired is invalidated immediately before /get returns
                self.assertIsNone(
                    coord.get_message(CIRCUIT_BASS3, "Z1CoolingTempDesired")
                )
                # A /get confirmation read for Z1CoolingTempDesired must be scheduled
                self.assertEqual(len(scheduled_timers), 2)
                self.assertAlmostEqual(scheduled_timers[1][0], 1.5)
                scheduled_timers[1][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertIn(("ebusd/bass3/Z1CoolingTempDesired/get", ""), published)

                # Store cleared
                self.assertIsNone(await coord._cooling_veto_store.async_load())

        asyncio.run(_run())

    def test_real_coordinator_schedule_cooling_desired_refresh(self) -> None:
        """schedule_cooling_desired_refresh invalidates stale cache and schedules /get."""

        async def _run() -> None:
            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="cool_refresh_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingTempDesired")] = {
                "value": 21.0
            }
            coord._state[("ctlv3", "z1coolingtempdesired")] = {"value": 21.0}
            coord._state[(CIRCUIT_HMUX0.lower(), "Status01")] = {"temp1": 28.0}

            published: list[tuple[str, str]] = []
            scheduled_timers: list[tuple[float, Any]] = []

            async def _fake_publish(_h: Any, topic: str, payload: str, **kwargs: Any):
                published.append((topic, str(payload)))

            def _fake_call_later(_h: Any, delay: float, cb: Any):
                scheduled_timers.append((delay, cb))
                return MagicMock()

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=_fake_call_later,
                ),
            ):
                coord.schedule_cooling_desired_refresh()

                self.assertIsNone(
                    coord.get_message(CIRCUIT_BASS3, "Z1CoolingTempDesired")
                )
                self.assertIsNone(coord.get_message("ctlv3", "Z1CoolingTempDesired"))
                self.assertEqual(len(scheduled_timers), 1)
                self.assertAlmostEqual(scheduled_timers[0][0], 1.5)

                scheduled_timers[0][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertIn(("ebusd/bass3/Z1CoolingTempDesired/get", ""), published)

        asyncio.run(_run())

    def test_real_coordinator_cooling_veto_persistence_across_restart(self) -> None:
        """Verify active and expired persisted cooling quick veto recovery across HA restarts."""

        async def _run() -> None:
            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="persist_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            # --- Phase 1: Coordinator 1 starts veto, then "restarts" ---
            coord1 = SaunierGeniaCoordinator(hass, entry)
            coord1._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {
                "value": "auto"
            }
            coord1._state[(CIRCUIT_BASS3.lower(), "Z1CoolingManualTemp")] = {
                "value": 25.5
            }
            coord1._state[(CIRCUIT_BASS3.lower(), "Z1CoolingTempDesired")] = {
                "value": 23.0
            }
            coord1._state[(CIRCUIT_HMUX0.lower(), "Status01")] = {"temp1": 30.0}

            timers_p1: list[tuple[float, Any]] = []
            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    new_callable=AsyncMock,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p1.append((d, cb)) or MagicMock()
                    ),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await coord1.async_set_cooling_quick_veto(
                    temperature=21.5, duration=2.0
                )
                await coord1.async_unload()

            # --- Phase 2: Coordinator 2 boots on same hass -> active veto resumed ---
            coord2 = SaunierGeniaCoordinator(hass, entry)
            timers_p2: list[tuple[float, Any]] = []
            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p2.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord2.async_setup()
                await coord2.async_unload()

            self.assertTrue(coord2.cooling_quick_veto_active)
            self.assertEqual(coord2.cooling_quick_veto_target_temp, 21.5)
            self.assertEqual(coord2.pre_cooling_veto_opmode, "auto")
            self.assertEqual(coord2.pre_cooling_veto_temp, 25.5)
            self.assertGreater(timers_p2[0][0], 7100.0)

            # --- Phase 3: Seed expired veto -> boots offline -> restores once operational ---
            await coord2._cooling_veto_store.async_save(
                {
                    "end_timestamp": datetime.now().timestamp() - 120.0,
                    "end_time": (datetime.now() - timedelta(minutes=2)).isoformat(),
                    "active_temp": 21.5,
                    "pre_opmode": "auto",
                    "pre_temp": 25.5,
                }
            )
            coord3 = SaunierGeniaCoordinator(hass, entry)
            published_p3: list[tuple[str, str]] = []
            timers_p3: list[tuple[float, Any]] = []

            async def _fake_pub_p3(_h: Any, t: str, p: str, **kw: Any) -> None:
                published_p3.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub_p3,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p3.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await coord3.async_setup()
                self.assertFalse(coord3.cooling_quick_veto_active)
                self.assertTrue(coord3._pending_cooling_veto_restore)
                self.assertEqual(published_p3, [])

                # Telemetry arrives making bus operational -> schedules deferred restore
                msg = MagicMock()
                msg.topic = "ebusd/bass3/Z1OpModeCooling"
                msg.payload = b'{"value": {"value": "day"}}'
                coord3._async_on_mqtt_message(msg)

                # Trigger deferred restore callback
                restore_timers = [t for t in timers_p3 if abs(t[0] - 7.0) < 0.01]
                self.assertEqual(len(restore_timers), 1)
                restore_timers[0][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord3._pending_cooling_veto_restore)
                self.assertIn(("ebusd/bass3/Z1OpModeCooling/set", "auto"), published_p3)
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingManualTemp/set", "25.5"), published_p3
                )
                self.assertIsNone(await coord3._cooling_veto_store.async_load())
                await coord3.async_unload()

        asyncio.run(_run())

    def test_real_coordinator_holiday_away_blocks_and_cancels_cooling_veto(
        self,
    ) -> None:
        """Verify Holiday/Away blocks cooling/heating quick vetos and cancels running cooling veto."""

        async def _run() -> None:
            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="holiday_guard_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_HMUX0.lower(), "Status01")] = {"temp1": 28.0}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingManualTemp")] = {
                "value": 26.0
            }
            coord._state[(CIRCUIT_BASS3.lower(), "Z1Status")] = {"value": "holidayaway"}

            # 1. Attempting either quick veto during holidayaway raises HomeAssistantError
            with self.assertRaises(HomeAssistantError):
                await coord.async_set_cooling_quick_veto(temperature=22.0)
            with self.assertRaises(HomeAssistantError):
                await coord.async_set_quick_veto(temperature=22.0)

            # 2. If cooling veto is active and user activates holiday mode -> cancels veto cleanly first
            coord._state[(CIRCUIT_BASS3.lower(), "Z1Status")] = {"value": "normal"}
            published: list[tuple[str, str]] = []

            async def _fake_pub_hol(_h: Any, t: str, p: str, **kw: Any) -> None:
                published.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub_hol,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await coord.async_set_cooling_quick_veto(temperature=22.0)
                self.assertTrue(coord.cooling_quick_veto_active)

                published.clear()
                await coord.async_activate_holiday_mode(temp=15.0)
                self.assertFalse(coord.cooling_quick_veto_active)
                self.assertIn(("ebusd/bass3/Z1OpModeCooling/set", "auto"), published)
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingManualTemp/set", "26.0"), published
                )
                self.assertIn(("ebusd/bass3/HolidayTemp/set", "15.0"), published)

                # 3. If Z1Status becomes holidayaway via physical thermostat while veto active -> auto-cancels
                coord._state[(CIRCUIT_BASS3.lower(), "Z1Status")] = {"value": "normal"}
                coord._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {
                    "value": "auto"
                }
                coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingManualTemp")] = {
                    "value": 26.0
                }
                await coord.async_set_cooling_quick_veto(temperature=22.0)
                self.assertTrue(coord.cooling_quick_veto_active)

                published.clear()
                msg = MagicMock()
                msg.topic = "ebusd/bass3/Z1Status"
                msg.payload = b'{"value": {"value": "holidayaway"}}'
                coord._async_on_mqtt_message(msg)
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord.cooling_quick_veto_active)
                self.assertIn(("ebusd/bass3/Z1OpModeCooling/set", "auto"), published)
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingManualTemp/set", "26.0"), published
                )

        asyncio.run(_run())

    def test_real_coordinator_manual_mode_veto_restores_manual_both_seasons(
        self,
    ) -> None:
        """Verify Boost/Quick Veto starting from Manual ('day') keeps/restores Manual ('day') & exact prior setpoint in both Cooling and Heating."""

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock(entry_id="manual_restore_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_HMUX0.lower(), "Status01")] = {"temp1": 28.0}
            published: list[tuple[str, str]] = []

            async def _fake_pub(_h: Any, t: str, p: str, **kw: Any) -> None:
                published.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                # --- 1. Cooling Manual (day) at 25.0 °C -> Boost -> restore Manual (day) at 25.0 °C ---
                coord._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {
                    "value": "day"
                }
                coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingManualTemp")] = {
                    "value": 25.0
                }
                coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingTempDesired")] = {
                    "value": 25.0
                }
                published.clear()
                await coord.async_set_cooling_quick_veto()  # 25.0 - 2.0 = 23.0
                self.assertEqual(coord.pre_cooling_veto_opmode, "day")
                self.assertEqual(coord.pre_cooling_veto_temp, 25.0)
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingManualTemp/set", "23.0"), published
                )
                self.assertFalse(
                    any(
                        t == "ebusd/bass3/Z1OpModeCooling/set" and p != "day"
                        for t, p in published
                    )
                )

                published.clear()
                await coord.async_cancel_cooling_quick_veto(restore=True)
                self.assertEqual(
                    coord.get_str(CIRCUIT_BASS3, "Z1OpModeCooling", "value"), "day"
                )
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingManualTemp/set", "25.0"), published
                )
                self.assertIn(
                    ("ebusd/bass3/Z1CoolingTempDesired/set", "25.0"), published
                )
                self.assertFalse(
                    any(t == "ebusd/bass3/Z1OpModeCooling/set" for t, _ in published)
                )

                # --- 2. Heating Manual (day) at 21.0 °C -> Boost -> cancel keeps Z1OpMode='day' & Z1ManualTemp=21.0 ---
                coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "day"}
                coord._state[(CIRCUIT_BASS3.lower(), "Z1ManualTemp")] = {"value": 21.0}
                coord._state[(CIRCUIT_BASS3.lower(), "Z1ActualRoomTempDesired")] = {
                    "value": 21.0
                }
                published.clear()
                await coord.async_set_quick_veto()  # 21.0 + 3.0 = 24.0
                self.assertEqual(coord._pre_veto_opmode, "day")
                self.assertIn(("ebusd/bass3/Z1QuickVetoTemp/set", "24.0"), published)
                self.assertIn(("ebusd/bass3/Z1SFMode/set", "veto"), published)
                self.assertEqual(
                    coord.get_str(CIRCUIT_BASS3, "Z1OpMode", "value"), "day"
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "value"), 21.0
                )

                published.clear()
                await coord.async_cancel_quick_veto()
                self.assertIn(("ebusd/bass3/Z1SFMode/set", "auto"), published)
                # Z1OpMode MUST remain 'day' (NOT overwritten to 'auto') and Z1ManualTemp MUST remain 21.0
                self.assertFalse(
                    any(t == "ebusd/bass3/Z1OpMode/set" for t, _ in published)
                )
                self.assertEqual(
                    coord.get_str(CIRCUIT_BASS3, "Z1OpMode", "value"), "day"
                )
                self.assertEqual(
                    coord.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "value"), 21.0
                )

        asyncio.run(_run())

    def test_instantaneous_electric_power_10min_unavailable_and_watchdog(self) -> None:
        """Verify 10-minute expiration scales with 2x fallback poll and clears Live COP via watchdog."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_FALLBACK_POLL_INTERVAL,
            CONF_HAS_MIGO_LINK,
        )

        # 1. With has_migo_link=False and fallback_poll_interval=450s -> max age is 900s (2x)
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd", CONF_HAS_MIGO_LINK: False}
        entry.options = {CONF_FALLBACK_POLL_INTERVAL: 450}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)
        t0 = 1000.0
        coord._state[(CIRCUIT_HMUX0, "PowerStatus")] = {"power": 1100.0}
        coord._message_timestamps[(CIRCUIT_HMUX0, "powerstatus")] = t0
        # Age 700s <= 900s -> still valid
        self.assertEqual(coord.get_instantaneous_electric_power(now=t0 + 700.0), 1100.0)
        # Age 950s > 900s -> None
        self.assertIsNone(coord.get_instantaneous_electric_power(now=t0 + 950.0))

        # 2. Active compressor: watchdog clears CALC_LIVE_COP when power exceeds 600s
        entry2 = MagicMock()
        entry2.data = {"mqtt_prefix": "ebusd", CONF_HAS_MIGO_LINK: True}
        entry2.options = {}
        coord2 = SaunierGeniaCoordinator(MagicMock(), entry2)

        now_real = time.time()
        coord2._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {
            "status": "heat_compressor_active"
        }
        coord2._state[(CIRCUIT_HMUX0, "RunDataFlowTemp")] = {"value": 38.0}
        coord2._state[(CIRCUIT_HMUX0, "RunDataReturnTemp")] = {"value": 33.0}
        coord2._state[(CIRCUIT_HMUX0, "RunDataFlowRate")] = {"flow_rate": 1000.0}
        coord2._state[(CIRCUIT_HMUX0, "RunDataElectricPowerConsumption")] = {
            "power": 1400.0
        }
        coord2._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = now_real - 10.0

        # Live COP is calculated while power is fresh
        coord2._async_recalculate_thermodynamics()
        self.assertIsNotNone(coord2.get_float(CALC_CIRCUIT, CALC_LIVE_COP))

        # Now expire power timestamp past 600s and invoke 60s watchdog
        coord2._message_timestamps[
            (CIRCUIT_HMUX0, "rundataelectricpowerconsumption")
        ] = now_real - 650.0
        notified: list[tuple[str, str]] = []
        coord2.async_add_listener(
            CIRCUIT_HMUX0,
            "RunDataElectricPowerConsumption",
            lambda: notified.append((CIRCUIT_HMUX0, "RunDataElectricPowerConsumption")),
        )
        coord2._async_check_watchdog(datetime.now())
        self.assertIn((CIRCUIT_HMUX0, "RunDataElectricPowerConsumption"), notified)
        self.assertIsNone(coord2.get_float(CALC_CIRCUIT, CALC_LIVE_COP))

        # If in standby, Live COP still reports 0.0 cleanly even when power is unavailable
        coord2._state[(CIRCUIT_HMUX0, "HMUStatusCode")] = {"status": "standby"}
        coord2._async_recalculate_thermodynamics()
        self.assertEqual(coord2.get_float(CALC_CIRCUIT, CALC_LIVE_COP), 0.0)

    def test_ebusd_tcp_find_csv_verification_and_scan_status(self) -> None:
        """Verify TCP info parses scan status and `find` detects/clears outdated controller & outdoor CSVs."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_ENABLE_EBUSD_TCP,
        )

        entry = MagicMock()
        entry.entry_id = "tcp_find_entry"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {CONF_ENABLE_EBUSD_TCP: True}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        # 1. Missing definitions in controller & outdoor CSVs -> ERR: element not found
        tcp_responses_outdated = [
            b"version: ebusd 26.1.26.1\n",
            b"scan: finished\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 15: slave #12, scanned "MF=Vaillant;ID=BASS3;SW=0708;HW=4304", loaded "vaillant/15.bass3.csv"\n',
            b"\n",
            # find HwcLegionellaDay -> missing
            b"ERR: element not found\n",
            b"\n",
            # find SilentTimer_Slots -> missing
            b"ERR: element not found\n",
            b"\n",
            # find VentilationBoost -> missing
            b"ERR: element not found\n",
            b"\n",
            # find Z1QuickVetoEndTime -> missing
            b"ERR: element not found\n",
            b"\n",
            # find Hc1CoolingEnabled -> missing
            b"ERR: element not found\n",
            b"\n",
            # find -f CirculationTimer_Monday -> legacy IGN:2 without ffff
            b"w,bass3,CirculationTimer_Monday,Timer,,15,b555,a600030000,ign_end,m,IGN:2,,,\n",
            b"\n",
            # find CompressorSilentOperationLevel -> missing
            b"ERR: element not found\n",
            b"\n",
            # find RunDataElectricPowerConsumption -> present
            b"hmux0 RunDataElectricPowerConsumption = 450\n",
            b"\n",
            # find RunStatsAuxHeaterSwitches -> missing
            b"ERR: element not found\n",
            b"\n",
            # find SubcoolingTemp -> missing
            b"ERR: element not found\n",
            b"\n",
            # find -F type,circuit,name Status02 -> passive u
            b"u,hmux0,Status02\n",
            b"\n",
        ]
        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=tcp_responses_outdated)
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertEqual(coord.get_str(CIRCUIT_GLOBAL, "scan", "value"), "finished")
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        mock_writer.write.assert_any_call(b"find HwcLegionellaDay\n")
        mock_writer.write.assert_any_call(b"find SilentTimer_Slots\n")
        mock_writer.write.assert_any_call(b"find VentilationBoost\n")
        mock_writer.write.assert_any_call(b"find Z1QuickVetoEndTime\n")
        mock_writer.write.assert_any_call(b"find Hc1CoolingEnabled\n")
        mock_writer.write.assert_any_call(b"find -f CirculationTimer_Monday\n")
        mock_writer.write.assert_any_call(b"find CompressorSilentOperationLevel\n")
        mock_writer.write.assert_any_call(b"find RunDataElectricPowerConsumption\n")
        mock_writer.write.assert_any_call(b"find RunStatsAuxHeaterSwitches\n")
        mock_writer.write.assert_any_call(b"find SubcoolingTemp\n")
        mock_writer.write.assert_any_call(b"quit\n")

        # 2. After user updates CSVs -> TCP find returns valid messages -> repairs auto-cleared
        tcp_responses_updated = [
            b"version: ebusd 26.1.26.1\n",
            b"scan: finished\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 15: slave #12, scanned "MF=Vaillant;ID=BASS3;SW=0708;HW=4304", loaded "vaillant/15.bass3.csv"\n',
            b"\n",
            b"bass3 HwcLegionellaDay = off\n",
            b"\n",
            b"bass3 SilentTimer_Slots = 0\n",
            b"\n",
            b"bass3 VentilationBoost = off\n",
            b"\n",
            b"bass3 Z1QuickVetoEndTime = 00:00:00\n",
            b"\n",
            b"bass3 Hc1CoolingEnabled = on\n",
            b"\n",
            b"w,bass3,CirculationTimer_Monday,Timer,,15,b555,a600030000,ign_end,m,HEX:2,=ffff,,\n",
            b"\n",
            b"hmux0 CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmux0 RunDataElectricPowerConsumption = 450\n",
            b"\n",
            b"hmux0 RunStatsAuxHeaterSwitches = 8\n",
            b"\n",
            b"hmux0 SubcoolingTemp = 3.5\n",
            b"\n",
            b"u,hmux0,Status02\n",
            b"\n",
        ]
        mock_reader2 = AsyncMock()
        mock_reader2.readline = AsyncMock(side_effect=tcp_responses_updated)
        mock_writer2 = MagicMock()
        mock_writer2.drain = AsyncMock()
        mock_writer2.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection", return_value=(mock_reader2, mock_writer2)
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)
        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)

        # 3. Only CirculationTimer_Monday missing =ffff padding -> outdated_controller_csv raised
        tcp_responses_only_ffff_missing = [
            b"version: ebusd 26.1.26.1\n",
            b"scan: finished\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 15: slave #12, scanned "MF=Vaillant;ID=BASS3;SW=0708;HW=4304", loaded "vaillant/15.bass3.csv"\n',
            b"\n",
            b"bass3 HwcLegionellaDay = off\n",
            b"\n",
            b"bass3 SilentTimer_Slots = 0\n",
            b"\n",
            b"bass3 VentilationBoost = off\n",
            b"\n",
            b"bass3 Z1QuickVetoEndTime = 00:00:00\n",
            b"\n",
            b"bass3 Hc1CoolingEnabled = on\n",
            b"\n",
            b"w,bass3,CirculationTimer_Monday,Timer,,15,b555,a600030000,ign_end,m,IGN:2,,,\n",
            b"\n",
            b"hmux0 CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmux0 RunDataElectricPowerConsumption = 450\n",
            b"\n",
            b"hmux0 RunStatsAuxHeaterSwitches = 8\n",
            b"\n",
            b"hmux0 SubcoolingTemp = 3.5\n",
            b"\n",
            b"u,hmux0,Status02\n",
            b"\n",
        ]
        mock_reader3 = AsyncMock()
        mock_reader3.readline = AsyncMock(side_effect=tcp_responses_only_ffff_missing)
        mock_writer3 = MagicMock()
        mock_writer3.drain = AsyncMock()
        mock_writer3.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection", return_value=(mock_reader3, mock_writer3)
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

    def test_real_coordinator_dhw_boost_persistence_across_restart(self) -> None:
        """Verify forced DHW boost elevation persists across restarts, updates on manual override, and restores offline expiry."""

        async def _run() -> None:
            import time as _time

            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="dhw_persist_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {"force_dhw_boost": True}

            # --- Phase 1: Coordinator 1 triggers forced boost, then restarts ---
            coord1 = SaunierGeniaCoordinator(hass, entry)
            c = CIRCUIT_BASS3.lower()
            coord1._state[(c, "HwcStorageTemp")] = {"value": 55.0}
            coord1._state[(c, "HwcTempDesired")] = {"value": 50.0}
            coord1._state[(c, "CylinderChargeHyst")] = {"value": 5.0}
            coord1._state[(c, "HwcSFMode")] = {"value": "auto"}
            coord1._last_telemetry_time = _time.monotonic()

            pub1: list[tuple[str, str]] = []

            async def _fake_pub1(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub1.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub1,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await coord1.async_trigger_dhw_boost()
                await coord1.async_cancel_dhw_boost_tracking(52.5)
                await coord1.async_unload()

            self.assertIn(("ebusd/bass3/HwcTempDesired/set", "61.5"), pub1)
            saved = await coord1._dhw_boost_store.async_load()
            self.assertIsNotNone(saved)
            self.assertEqual(saved["saved_target_temp"], 52.5)

            # --- Phase 2: Coordinator 2 boots -> active boost resumed -> finishes on bus ---
            coord2 = SaunierGeniaCoordinator(hass, entry)
            timers_p2: list[tuple[float, Any]] = []
            pub2: list[tuple[str, str]] = []

            async def _fake_pub2(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub2.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub2,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p2.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord2.async_setup()
                self.assertTrue(coord2.dhw_boost_forced_active)
                self.assertEqual(coord2.saved_dhw_target_temp, 52.5)
                self.assertTrue(any(d > 3500.0 for d, _ in timers_p2))

                msg_load = MagicMock()
                msg_load.topic = "ebusd/bass3/HwcSFMode"
                msg_load.payload = b'{"value": {"value": "load"}}'
                coord2._async_on_mqtt_message(msg_load)

                msg_auto = MagicMock()
                msg_auto.topic = "ebusd/bass3/HwcSFMode"
                msg_auto.payload = b'{"value": {"value": "auto"}}'
                coord2._async_on_mqtt_message(msg_auto)

                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                await coord2.async_unload()

            self.assertFalse(coord2.dhw_boost_forced_active)
            self.assertIn(("ebusd/bass3/HwcTempDesired/set", "52.5"), pub2)
            self.assertIsNone(await coord2._dhw_boost_store.async_load())

            # --- Phase 3: Expired 60m boost while offline -> boots offline -> restores once operational ---
            await coord2._dhw_boost_store.async_save(
                {
                    "started_timestamp": datetime.now().timestamp() - 3720.0,
                    "end_timestamp": datetime.now().timestamp() - 120.0,
                    "end_time": (datetime.now() - timedelta(minutes=2)).isoformat(),
                    "saved_target_temp": 50.0,
                    "goal_temp": 50.0,
                    "seen_load": False,
                }
            )
            coord3 = SaunierGeniaCoordinator(hass, entry)
            timers_p3: list[tuple[float, Any]] = []
            pub3: list[tuple[str, str]] = []

            async def _fake_pub3(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub3.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub3,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p3.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord3.async_setup()
                self.assertFalse(coord3.dhw_boost_forced_active)
                self.assertTrue(coord3.pending_dhw_boost_restore)
                self.assertEqual(pub3, [])

                msg_op = MagicMock()
                msg_op.topic = "ebusd/bass3/HwcStorageTemp"
                msg_op.payload = b'{"value": {"value": 60.0}}'
                coord3._async_on_mqtt_message(msg_op)

                restore_timers = [t for t in timers_p3 if abs(t[0] - 7.0) < 0.01]
                self.assertEqual(len(restore_timers), 1)
                restore_timers[0][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord3.pending_dhw_boost_restore)
                self.assertIn(("ebusd/bass3/HwcTempDesired/set", "50.0"), pub3)
                self.assertIsNone(await coord3._dhw_boost_store.async_load())
                await coord3.async_unload()

        asyncio.run(_run())

    def test_real_coordinator_heating_veto_off_persistence_across_restart(
        self,
    ) -> None:
        """Verify heating quick veto from 'off' persists across restarts and guards Z1Status startup race."""

        async def _run() -> None:
            import time as _time

            hass = MagicMock()
            tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="heating_persist_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            # --- Phase 1: Zone starts OFF, activates quick veto, then HA restarts ---
            coord1 = SaunierGeniaCoordinator(hass, entry)
            c = CIRCUIT_BASS3.lower()
            coord1._state[(c, "Z1OpMode")] = {"value": "off"}
            coord1._state[(c, "Z1Status")] = {"value": "day"}
            coord1._state[(c, "Z1ManualTemp")] = {"value": 19.0}
            coord1._state[(c, "Z1SFMode")] = {"value": "auto"}
            coord1._last_telemetry_time = _time.monotonic()

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    new_callable=AsyncMock,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
                patch("asyncio.sleep", new_callable=AsyncMock),
            ):
                await coord1.async_set_quick_veto(temperature=21.0, duration=2.0)
                await coord1.async_unload()

            saved = await coord1._heating_veto_store.async_load()
            self.assertIsNotNone(saved)
            self.assertEqual(saved["pre_opmode"], "off")

            # --- Phase 2: Coordinator 2 boots -> Z1Status arrives before Z1SFMode (must NOT kill active veto) ---
            coord2 = SaunierGeniaCoordinator(hass, entry)
            timers_p2: list[tuple[float, Any]] = []
            pub2: list[tuple[str, str]] = []

            async def _fake_pub2(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub2.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub2,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p2.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord2.async_setup()
                self.assertEqual(coord2.pre_veto_opmode, "off")
                self.assertTrue(any(d > 7100.0 for d, _ in timers_p2))

                msg_status = MagicMock()
                msg_status.topic = "ebusd/bass3/Z1Status"
                msg_status.payload = b'{"value": {"value": "day"}}'
                coord2._async_on_mqtt_message(msg_status)
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertEqual(pub2, [])
                self.assertEqual(coord2.pre_veto_opmode, "off")

                msg_veto = MagicMock()
                msg_veto.topic = "ebusd/bass3/Z1SFMode"
                msg_veto.payload = b'{"value": {"value": "veto"}}'
                coord2._async_on_mqtt_message(msg_veto)
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertEqual(pub2, [])

                msg_auto = MagicMock()
                msg_auto.topic = "ebusd/bass3/Z1SFMode"
                msg_auto.payload = b'{"value": {"value": "auto"}}'
                coord2._async_on_mqtt_message(msg_auto)
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                await coord2.async_unload()

            self.assertIsNone(coord2.pre_veto_opmode)
            self.assertIn(("ebusd/bass3/Z1OpMode/set", "off"), pub2)
            self.assertIsNone(await coord2._heating_veto_store.async_load())

            # --- Phase 3: Expired veto while offline -> boots offline -> restores once operational ---
            await coord2._heating_veto_store.async_save(
                {
                    "pre_opmode": "off",
                    "end_timestamp": datetime.now().timestamp() - 120.0,
                    "end_time": (datetime.now() - timedelta(minutes=2)).isoformat(),
                }
            )
            coord3 = SaunierGeniaCoordinator(hass, entry)
            timers_p3: list[tuple[float, Any]] = []
            pub3: list[tuple[str, str]] = []

            async def _fake_pub3(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub3.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub3,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p3.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord3.async_setup()
                self.assertTrue(coord3._pending_heating_veto_restore)
                self.assertEqual(pub3, [])

                msg_op = MagicMock()
                msg_op.topic = "ebusd/bass3/Z1OpMode"
                msg_op.payload = b'{"value": {"value": "auto"}}'
                coord3._async_on_mqtt_message(msg_op)

                restore_timers = [t for t in timers_p3 if abs(t[0] - 7.0) < 0.01]
                self.assertEqual(len(restore_timers), 1)
                restore_timers[0][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                # Without Z1SFMode known yet, queries Z1SFMode/get and waits before restoring 'off'
                self.assertTrue(coord3._pending_heating_veto_restore)
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), pub3)
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), pub3)

                # Once controller confirms Z1SFMode='auto', next scheduled check completes restore
                msg_sf_auto = MagicMock()
                msg_sf_auto.topic = "ebusd/bass3/Z1SFMode"
                msg_sf_auto.payload = b'{"value": {"value": "auto"}}'
                coord3._async_on_mqtt_message(msg_sf_auto)
                restore_timers2 = [t for t in timers_p3 if abs(t[0] - 7.0) < 0.01]
                self.assertEqual(len(restore_timers2), 2)
                restore_timers2[1][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord3._pending_heating_veto_restore)
                self.assertIn(("ebusd/bass3/Z1OpMode/set", "off"), pub3)
                self.assertIsNone(await coord3._heating_veto_store.async_load())
                await coord3.async_unload()

            # --- Phase 4: Deadline passed offline, but wall controller reports Z1SFMode=veto still active ---
            await coord3._heating_veto_store.async_save(
                {
                    "pre_opmode": "off",
                    "end_timestamp": datetime.now().timestamp() - 60.0,
                    "end_time": (datetime.now() - timedelta(minutes=1)).isoformat(),
                }
            )
            coord4 = SaunierGeniaCoordinator(hass, entry)
            timers_p4: list[tuple[float, Any]] = []
            pub4: list[tuple[str, str]] = []

            async def _fake_pub4(_h: Any, t: str, p: str, **kw: Any) -> None:
                pub4.append((t, str(p)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_subscribe",
                    new_callable=AsyncMock,
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub4,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: (
                        timers_p4.append((d, cb)) or MagicMock()
                    ),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_track_time_interval",
                    return_value=MagicMock(),
                ),
            ):
                await coord4.async_setup()
                msg_still_veto = MagicMock()
                msg_still_veto.topic = "ebusd/bass3/Z1SFMode"
                msg_still_veto.payload = b'{"value": {"value": "veto"}}'
                coord4._async_on_mqtt_message(msg_still_veto)

                restore_timers4 = [t for t in timers_p4 if abs(t[0] - 7.0) < 0.01]
                self.assertEqual(len(restore_timers4), 1)
                restore_timers4[0][1](datetime.now())
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertFalse(coord4._pending_heating_veto_restore)
                self.assertEqual(coord4.pre_veto_opmode, "off")
                self.assertEqual(pub4, [])

                msg_end = MagicMock()
                msg_end.topic = "ebusd/bass3/Z1SFMode"
                msg_end.payload = b'{"value": {"value": "auto"}}'
                coord4._async_on_mqtt_message(msg_end)
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()

                self.assertIn(("ebusd/bass3/Z1OpMode/set", "off"), pub4)
                self.assertIsNone(await coord4._heating_veto_store.async_load())
                await coord4.async_unload()

        asyncio.run(_run())

    def test_coordinator_restore_write_failures_preserve_state_and_store(self) -> None:
        """Verify write failures during restore preserve memory state and store for retry."""

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock(entry_id="write_fail_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            # --- 1. DHW Boost write failure ---
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._saved_dhw_target_temp = 50.0
            coord._dhw_boost_active = True
            await coord._dhw_boost_store.async_save(
                {
                    "saved_target_temp": 50.0,
                    "end_timestamp": datetime.now().timestamp() + 3600.0,
                    "end_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                }
            )

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=HomeAssistantError("Broker unavailable"),
                ),
                self.assertRaises(HomeAssistantError),
            ):
                await coord._async_restore_dhw_target_temp("testing write failure")

            self.assertEqual(coord.saved_dhw_target_temp, 50.0)
            self.assertTrue(coord.pending_dhw_boost_restore)
            dhw_store = await coord._dhw_boost_store.async_load()
            self.assertIsNotNone(dhw_store)
            self.assertEqual(dhw_store.get("saved_target_temp"), 50.0)
            self.assertEqual(dhw_store.get("end_timestamp"), 0.0)

            # Retry succeeds
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ):
                await coord._async_restore_dhw_target_temp("retry success")
            self.assertIsNone(coord.saved_dhw_target_temp)
            self.assertFalse(coord.pending_dhw_boost_restore)
            self.assertIsNone(await coord._dhw_boost_store.async_load())

            # --- 2. Heating Veto write failure ---
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._pre_veto_opmode = "off"
            await coord._heating_veto_store.async_save(
                {
                    "pre_opmode": "off",
                    "end_timestamp": datetime.now().timestamp() + 3600.0,
                    "end_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                }
            )

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=HomeAssistantError("Broker unavailable"),
                ),
                self.assertRaises(HomeAssistantError),
            ):
                await coord._async_finish_heating_veto_off_restore(
                    "testing write failure"
                )

            self.assertEqual(coord.pre_veto_opmode, "off")
            self.assertTrue(coord._pending_heating_veto_restore)
            heating_store = await coord._heating_veto_store.async_load()
            self.assertIsNotNone(heating_store)
            self.assertEqual(heating_store.get("pre_opmode"), "off")
            self.assertEqual(heating_store.get("end_timestamp"), 0.0)

            # Retry succeeds
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ):
                await coord._async_finish_heating_veto_off_restore("retry success")
            self.assertIsNone(coord.pre_veto_opmode)
            self.assertFalse(coord._pending_heating_veto_restore)
            self.assertIsNone(await coord._heating_veto_store.async_load())

            # --- 3. Cooling Veto write failure ---
            coord._pre_cooling_veto_opmode = "night"
            coord._pre_cooling_veto_temp = 24.0
            await coord._cooling_veto_store.async_save(
                {
                    "pre_opmode": "night",
                    "pre_temp": 24.0,
                    "end_timestamp": datetime.now().timestamp() + 3600.0,
                    "end_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                }
            )

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=HomeAssistantError("Broker unavailable"),
                ),
                self.assertRaises(HomeAssistantError),
            ):
                await coord.async_cancel_cooling_quick_veto(restore=True)

            self.assertEqual(coord._pre_cooling_veto_opmode, "night")
            self.assertEqual(coord._pre_cooling_veto_temp, 24.0)
            self.assertTrue(coord._pending_cooling_veto_restore)
            cooling_store = await coord._cooling_veto_store.async_load()
            self.assertIsNotNone(cooling_store)
            self.assertEqual(cooling_store.get("pre_opmode"), "night")
            self.assertEqual(cooling_store.get("end_timestamp"), 0.0)

            # Retry succeeds
            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ):
                await coord.async_cancel_cooling_quick_veto(restore=True)
            self.assertIsNone(coord._pre_cooling_veto_opmode)
            self.assertIsNone(coord._pre_cooling_veto_temp)
            self.assertFalse(coord._pending_cooling_veto_restore)
            self.assertIsNone(await coord._cooling_veto_store.async_load())

            await coord.async_unload()

        asyncio.run(_run())

    def test_cooling_veto_cancel_restore_false_offline_and_failure_flow(self) -> None:
        """Verify cooling veto cancel with restore=False handles offline, failure, and expiry."""

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock(entry_id="cooling_preset_fail_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)

            # -------------------------------------------------------------
            # Condition 1: Bus not operational with restore=False, restore_temp=True
            # Must raise HomeAssistantError, keep veto in memory and store,
            # re-arm timer with max(0, remaining), and NOT set pending.
            # -------------------------------------------------------------
            future_end = datetime.now() + timedelta(hours=2)
            coord._cooling_veto_end_time = future_end
            coord._cooling_veto_active_temp = 19.0
            coord._pre_cooling_veto_opmode = "auto"
            coord._pre_cooling_veto_temp = 25.0
            await coord._cooling_veto_store.async_save(
                {
                    "end_timestamp": future_end.timestamp(),
                    "end_time": future_end.isoformat(),
                    "active_temp": 19.0,
                    "pre_opmode": "auto",
                    "pre_temp": 25.0,
                }
            )

            # Bus is offline (no operational status telemetry)
            self.assertFalse(coord.is_ebus_operational)

            with (
                patch.object(coord, "_arm_cooling_veto_timer") as mock_arm,
                self.assertRaises(HomeAssistantError),
            ):
                await coord.async_cancel_cooling_quick_veto(
                    restore=False, restore_temp=True
                )

            # Veto preserved in memory
            self.assertTrue(coord.cooling_quick_veto_active)
            self.assertEqual(coord._cooling_veto_end_time, future_end)
            self.assertEqual(coord._cooling_veto_active_temp, 19.0)
            self.assertEqual(coord._pre_cooling_veto_opmode, "auto")
            self.assertEqual(coord._pre_cooling_veto_temp, 25.0)
            self.assertFalse(coord._pending_cooling_veto_restore)

            # Timer re-armed with remaining > 0
            mock_arm.assert_called_once()
            armed_delay = mock_arm.call_args[0][0]
            self.assertGreater(armed_delay, 7000.0)

            # Store intact on disk
            persisted = await coord._cooling_veto_store.async_load()
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.get("active_temp"), 19.0)

            # -------------------------------------------------------------
            # Condition 2: Deadline passed during failed attempt (remaining < 0)
            # Must re-arm with max(0.0, remaining) = 0.0 to trigger natural expiry.
            # -------------------------------------------------------------
            past_end = datetime.now() - timedelta(seconds=10)
            coord._cooling_veto_end_time = past_end
            with (
                patch.object(coord, "_arm_cooling_veto_timer") as mock_arm_expired,
                self.assertRaises(HomeAssistantError),
            ):
                await coord.async_cancel_cooling_quick_veto(
                    restore=False, restore_temp=True
                )

            mock_arm_expired.assert_called_once_with(0.0)

            # -------------------------------------------------------------
            # Broker write failure with restore=False -> retry -> restart flow
            # -------------------------------------------------------------
            # Bring bus operational
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._last_telemetry_time = time.monotonic()
            self.assertTrue(coord.is_ebus_operational)

            coord._cooling_veto_end_time = future_end
            coord._cooling_veto_active_temp = 19.0
            coord._pre_cooling_veto_opmode = "auto"
            coord._pre_cooling_veto_temp = 25.0

            # Failed cancel
            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=HomeAssistantError("Broker write failed"),
                ),
                self.assertRaises(HomeAssistantError),
            ):
                await coord.async_cancel_cooling_quick_veto(
                    restore=False, restore_temp=True
                )

            # HA still shows veto active, store still intact
            self.assertTrue(coord.cooling_quick_veto_active)
            self.assertFalse(coord._pending_cooling_veto_restore)
            self.assertIsNotNone(await coord._cooling_veto_store.async_load())

            # User retry: climate checks was_cooling_veto = coordinator.cooling_quick_veto_active (True)
            # and retries async_cancel_cooling_quick_veto(restore=False, restore_temp=True)
            published = []

            async def _fake_publish(_h, topic, payload, **_k):
                published.append((topic, payload))

            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                side_effect=_fake_publish,
            ):
                await coord.async_cancel_cooling_quick_veto(
                    restore=False, restore_temp=True
                )
                # Emulate user setting manual mode + 26.0 °C
                await coord.async_write_parameter(
                    CIRCUIT_BASS3, "Z1OpModeCooling", "day"
                )
                await coord.async_write_parameter(
                    CIRCUIT_BASS3, "Z1CoolingManualTemp", 26.0
                )

            # Veto inactive in memory and store cleared
            self.assertFalse(coord.cooling_quick_veto_active)
            self.assertIsNone(coord._cooling_veto_end_time)
            self.assertIsNone(coord._pre_cooling_veto_opmode)
            self.assertIsNone(coord._pre_cooling_veto_temp)
            self.assertIsNone(await coord._cooling_veto_store.async_load())
            self.assertIn(("ebusd/bass3/Z1CoolingManualTemp/set", "25.0"), published)
            self.assertIn(("ebusd/bass3/Z1OpModeCooling/set", "day"), published)
            self.assertIn(("ebusd/bass3/Z1CoolingManualTemp/set", "26.0"), published)

            # Restart HA before the original veto end
            coord2 = SaunierGeniaCoordinator(hass, entry)
            coord2._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord2._last_telemetry_time = time.monotonic()
            await coord2._async_restore_persisted_cooling_veto()

            # No veto was restored because store was cleanly deleted
            self.assertFalse(coord2.cooling_quick_veto_active)
            self.assertIsNone(coord2._cooling_veto_end_time)
            self.assertIsNone(coord2._pre_cooling_veto_opmode)

            await coord.async_unload()
            await coord2.async_unload()

        asyncio.run(_run())

    def test_unified_quick_veto_remaining_heating_auto_and_cooling(self) -> None:
        """Unified quick_veto_remaining_time sensor tracks heating (any mode), duration changes, cooling, restarts, and expiration."""
        from custom_components.arotherm_genia_ebusd.const import (
            CALC_CIRCUIT,
            CIRCUIT_BASS3,
        )
        from custom_components.arotherm_genia_ebusd.coordinator import (
            SaunierGeniaCoordinator,
        )

        async def _run() -> None:
            created_tasks: list[asyncio.Task[Any]] = []
            hass = MagicMock()

            def _create_task(coro):
                task = asyncio.get_running_loop().create_task(coro)
                created_tasks.append(task)
                return task

            hass.async_create_task = _create_task
            entry = MagicMock(entry_id="unified_veto_test_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1QuickVetoTemp")] = {"value": 23.5}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpModeCooling")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1CoolingTempDesired")] = {
                "value": 24.0
            }
            coord._last_telemetry_time = time.monotonic()

            notifications: list[str] = []
            unsub = coord.async_add_listener(
                CALC_CIRCUIT,
                "QuickVetoRemaining",
                lambda: notifications.append("tick"),
            )

            # Inactive initially
            self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)
            attrs = coord.get_quick_veto_remaining_attributes()
            self.assertFalse(attrs["is_active"])
            self.assertIsNone(attrs["veto_type"])

            published: list[tuple[str, str]] = []

            async def _fake_publish(_h, topic, payload, **_k):
                published.append((topic, payload))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    new=AsyncMock(return_value=None),
                ),
            ):
                # 1. Activate heating quick veto from 'auto' with 2.5h
                await coord.async_set_quick_veto(temperature=23.5, duration=2.5)
                coord._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "veto"}

                rem = coord.get_quick_veto_remaining_minutes()
                self.assertEqual(rem, 150)
                attrs = coord.get_quick_veto_remaining_attributes()
                self.assertTrue(attrs["is_active"])
                self.assertEqual(attrs["veto_type"], "heating")
                self.assertEqual(attrs["target_temperature"], 23.5)
                self.assertGreaterEqual(len(notifications), 1)

                # 2. Adjust duration mid-veto to 1.0h
                await coord.async_refresh_heating_veto_duration(1.0)
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 60)

                # 3. Simulate HA restart preserving 'auto' heating countdown
                coord2 = SaunierGeniaCoordinator(hass, entry)
                coord2._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
                coord2._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "veto"}
                coord2._last_telemetry_time = time.monotonic()
                await coord2._async_restore_persisted_heating_veto()
                self.assertEqual(coord2._pre_veto_opmode, "auto")
                rem2 = coord2.get_quick_veto_remaining_minutes()
                assert rem2 is not None
                self.assertGreaterEqual(rem2, 59)

                # 4. Natural timer expiry from 'auto' clears state without forcing Z1OpMode='off'
                published.clear()
                coord2._async_on_heating_veto_timeout(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIsNone(coord2._heating_veto_end_time)
                self.assertIsNone(coord2._pre_veto_opmode)
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), published)
                coord2._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
                self.assertEqual(coord2.get_quick_veto_remaining_minutes(), 0)
                self.assertIsNone(await coord2._heating_veto_store.async_load())

                # 5. Cancel heating veto cleanly on coord -> 0, then activate cooling quick veto (2.0h) and cancel
                await coord.async_cancel_quick_veto()
                coord._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)

                await coord.async_set_cooling_quick_veto(temperature=19.0, duration=2.0)
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 120)
                cool_attrs = coord.get_quick_veto_remaining_attributes()
                self.assertTrue(cool_attrs["is_active"])
                self.assertEqual(cool_attrs["veto_type"], "cooling")
                self.assertEqual(cool_attrs["target_temperature"], 19.0)

                await coord.async_cancel_cooling_quick_veto(restore=True)
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)
                self.assertFalse(
                    coord.get_quick_veto_remaining_attributes()["is_active"]
                )

            unsub()
            await coord.async_unload()
            await coord2.async_unload()

        asyncio.run(_run())

    def test_unified_quick_veto_external_transition_and_watchdog(self) -> None:
        """Initial unknown Z1SFMode=veto reports None, while live Z1SFMode->veto starts countdown and watchdog notifies."""
        from types import SimpleNamespace

        from custom_components.arotherm_genia_ebusd.const import (
            CALC_CIRCUIT,
            CIRCUIT_BASS3,
        )
        from custom_components.arotherm_genia_ebusd.coordinator import (
            SaunierGeniaCoordinator,
        )

        async def _run() -> None:
            created_tasks: list[asyncio.Task[Any]] = []
            hass = MagicMock()

            def _create_task(coro):
                task = asyncio.get_running_loop().create_task(coro)
                created_tasks.append(task)
                return task

            hass.async_create_task = _create_task
            entry = MagicMock(entry_id="unified_veto_test_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1QuickVetoDuration")] = {
                "value": 1.5
            }

            ticks: list[int] = []
            unsub = coord.async_add_listener(
                CALC_CIRCUIT,
                "QuickVetoRemaining",
                lambda: ticks.append(1),
            )

            # First boot message already in veto -> unknown remaining (None)
            coord._async_on_mqtt_message(
                SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="veto")
            )
            self.assertIsNone(coord._heating_veto_end_time)
            self.assertIsNone(coord.get_quick_veto_remaining_minutes())
            attrs = coord.get_quick_veto_remaining_attributes()
            self.assertTrue(attrs["is_active"])
            self.assertEqual(attrs["veto_type"], "heating")
            self.assertIsNone(attrs["end_time"])

            # Clear back to auto -> 0
            coord._async_on_mqtt_message(
                SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="auto")
            )
            self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)

            # Live external transition auto -> veto starts 1.5h (90 min) countdown
            ticks.clear()
            coord._async_on_mqtt_message(
                SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="veto")
            )
            await asyncio.sleep(0)
            self.assertIsNotNone(coord._heating_veto_end_time)
            self.assertEqual(coord.get_quick_veto_remaining_minutes(), 90)
            self.assertGreaterEqual(len(ticks), 1)

            # Periodic 60s watchdog notifies countdown listener while active
            before_watchdog = len(ticks)
            coord._async_check_watchdog(datetime.now())
            self.assertEqual(len(ticks), before_watchdog + 1)

            # Live exit back to auto clears software timer cleanly
            coord._async_on_mqtt_message(
                SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="auto")
            )
            await asyncio.sleep(0)
            self.assertIsNone(coord._heating_veto_end_time)
            self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)

            unsub()
            await coord.async_unload()

        asyncio.run(_run())

    def test_heating_veto_external_duration_sync_and_z1status_unstick(self) -> None:
        """External Z1QuickVetoDuration change (0.5h) updates countdown, and Z1Status exiting 'veto' requests Z1SFMode."""
        from types import SimpleNamespace

        async def _run() -> None:
            created_tasks: list[asyncio.Task[Any]] = []
            hass = MagicMock()

            def _create_task(coro):
                task = asyncio.get_running_loop().create_task(coro)
                created_tasks.append(task)
                return task

            hass.async_create_task = _create_task
            entry = MagicMock(entry_id="veto_app_sync_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1Status")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1QuickVetoDuration")] = {
                "value": 3.0
            }
            coord._last_telemetry_time = time.monotonic()

            published: list[tuple[str, str]] = []

            async def _fake_publish(_h, topic, payload, **_k):
                published.append((topic, payload))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    new=AsyncMock(return_value=None),
                ),
            ):
                # 1. Start 3h boost from HA
                await coord.async_set_quick_veto(temperature=22.0, duration=3.0)
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="veto")
                )
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="veto")
                )
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 180)

                # 2. Official app adjusts duration to 0.5h over the bus
                coord._async_on_mqtt_message(
                    SimpleNamespace(
                        topic="ebusd/bass3/Z1QuickVetoDuration", payload="0.5"
                    )
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 30)

                # 2b. Controller r9 poll reads back static 3.0h default while Z1Status is STILL 'veto'
                #     -> must NOT overwrite the active 0.5h (30 min) countdown back to 3h!
                coord._async_on_mqtt_message(
                    SimpleNamespace(
                        topic="ebusd/bass3/Z1QuickVetoDuration", payload="3.0"
                    )
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                rem_after_r9 = coord.get_quick_veto_remaining_minutes()
                assert rem_after_r9 is not None
                self.assertLessEqual(rem_after_r9, 30)

                # 3. Hardware exits boost (Z1Status -> auto) while Z1SFMode stays stale 'veto'
                published.clear()
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="auto")
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), published)

                # 4. Controller resets Z1QuickVetoDuration back to 3.0 after exit -> must NOT re-arm 3h veto
                coord._async_on_mqtt_message(
                    SimpleNamespace(
                        topic="ebusd/bass3/Z1QuickVetoDuration", payload="3.0"
                    )
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                rem_before_reply = coord.get_quick_veto_remaining_minutes()
                assert rem_before_reply is not None
                self.assertLessEqual(rem_before_reply, 30)

                # 5. Controller reply Z1SFMode=auto clears everything cleanly
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="auto")
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIsNone(coord._heating_veto_end_time)
                self.assertEqual(coord.get_quick_veto_remaining_minutes(), 0)

                # 6. Also verify timeout requests /get Z1SFMode even without Z1Status
                await coord.async_set_quick_veto(temperature=22.0, duration=1.0)
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="veto")
                )
                published.clear()
                coord._async_on_heating_veto_timeout(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), published)

                # 7. Verify async_cancel_quick_veto clears Z1Status='veto' optimistically & schedules /get Z1Status,
                #    and restore_opmode=False leaves Z1OpMode untouched even when started from 'off'.
                coord._state[(CIRCUIT_BASS3, "z1opmode")] = {"value": "off"}
                await coord.async_set_quick_veto(temperature=22.0, duration=1.0)
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="veto")
                )
                self.assertEqual(coord.get_str(CIRCUIT_BASS3, "Z1Status"), "veto")
                published.clear()
                await coord.async_cancel_quick_veto(restore_opmode=False)
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), published)
                self.assertEqual(coord.get_str(CIRCUIT_BASS3, "Z1Status"), "auto")

                # External Z1Status='veto' while Z1SFMode is stale 'auto' requests /get Z1SFMode
                coord._last_z1_sfmode_sync_time = 0.0
                coord._state[(CIRCUIT_BASS3, "z1sfmode")] = {"value": "auto"}
                coord._state[(CIRCUIT_BASS3, "z1status")] = {"value": "auto"}
                published.clear()
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="veto")
                )
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), published)

            await coord.async_unload()

        asyncio.run(_run())

    def test_heating_veto_from_off_extended_to_default_3h_defers_off_restore(
        self,
    ) -> None:
        """Timeout verifies live controller state so app-extended 3.0h vetos still restore 'off' at true end."""
        from types import SimpleNamespace

        async def _run() -> None:
            hass = MagicMock()
            created_tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                created_tasks.append(asyncio.get_running_loop().create_task(coro))
                or created_tasks[-1]
            )
            entry = MagicMock(entry_id="test_heating_veto_off_ext_3h")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "off"}
            coord._last_telemetry_time = time.monotonic()

            published: list[tuple[str, str]] = []
            controller_veto_active = True

            async def _fake_publish(
                _hass: Any, topic: str, payload: str, **_kwargs: Any
            ) -> None:
                published.append((topic, str(payload)))
                if topic == "ebusd/bass3/Z1Status/get":
                    coord._async_on_mqtt_message(
                        SimpleNamespace(
                            topic="ebusd/bass3/Z1Status",
                            payload="veto" if controller_veto_active else "auto",
                        )
                    )
                elif topic == "ebusd/bass3/Z1SFMode/get":
                    coord._async_on_mqtt_message(
                        SimpleNamespace(
                            topic="ebusd/bass3/Z1SFMode",
                            payload="veto" if controller_veto_active else "auto",
                        )
                    )

            timers: list[tuple[float, Any]] = []

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=lambda _h, d, cb: timers.append((d, cb)) or MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    new=AsyncMock(return_value=None),
                ),
            ):
                # 1. Start 1.0h heating veto from 'off', then app extends it to 3.0h (default)
                await coord.async_set_quick_veto(temperature=22.0, duration=1.0)
                self.assertEqual(coord.pre_veto_opmode, "off")
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1SFMode", payload="veto")
                )
                coord._async_on_mqtt_message(
                    SimpleNamespace(
                        topic="ebusd/bass3/Z1QuickVetoDuration", payload="3.0"
                    )
                )

                # 2. Local 1.0h backup timer fires while hardware is STILL in 'veto':
                # must NOT force Z1OpMode='off' early; keeps pre_opmode='off' and arms 120s recheck
                published.clear()
                timers.clear()
                coord._async_on_heating_veto_timeout(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                self.assertIn(("ebusd/bass3/Z1Status/get", ""), published)
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), published)
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), published)
                self.assertEqual(coord.pre_veto_opmode, "off")
                self.assertIsNone(coord._heating_veto_end_time)
                self.assertTrue(
                    coord.get_quick_veto_remaining_attributes()["is_active"]
                )
                self.assertTrue(any(abs(d - 120.0) < 0.01 for d, _ in timers))
                saved = await coord._heating_veto_store.async_load()
                self.assertIsNotNone(saved)
                self.assertEqual(saved["pre_opmode"], "off")

                # 3. At 3.0h controller finishes veto -> next timeout recheck sees 'auto' & restores 'off'
                controller_veto_active = False
                published.clear()
                recheck_cb = [cb for d, cb in timers if abs(d - 120.0) < 0.01][-1]
                recheck_cb(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                self.assertIn(("ebusd/bass3/Z1OpMode/set", "off"), published)
                self.assertIsNone(coord.pre_veto_opmode)
                self.assertIsNone(await coord._heating_veto_store.async_load())

            await coord.async_unload()

        asyncio.run(_run())

    def test_real_coordinator_ventilation_boost_and_z1status_sync(self) -> None:
        """Verify VentilationBoost activation/cancellation and Z1ActualRoomTempDesired /get sync."""

        async def _run() -> None:
            hass = MagicMock()
            created_tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                created_tasks.append(asyncio.ensure_future(coro)) or created_tasks[-1]
            )
            entry = MagicMock()
            entry.entry_id = "test_vent_entry"
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)

            published: list[tuple[str, str]] = []
            scheduled_timers: list[tuple[float, Any]] = []

            async def _fake_publish(
                _hass: Any, topic: str, payload: str, **_kwargs: Any
            ) -> None:
                published.append((topic, payload))

            def _fake_call_later(_hass: Any, delay: float, action: Any) -> Any:
                scheduled_timers.append((delay, action))
                return lambda: None

            coord._state[("bass3", "Z1OpMode")] = {"value": "auto"}
            coord._canonical_names[("bass3", "z1opmode")] = "Z1OpMode"
            coord._state[("bass3", "Z1Status")] = {"value": "auto"}
            coord._canonical_names[("bass3", "z1status")] = "Z1Status"
            coord._ebus_connected = True
            coord._last_mqtt_message_time = 1e12

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=_fake_call_later,
                ),
            ):
                # 1. Activate sets VentilationBoost=on, Z1Status=ventilation, 30 min countdown, schedules /get
                await coord.async_activate_ventilation_boost()
                self.assertIn(("ebusd/bass3/VentilationBoost/set", "on"), published)
                self.assertEqual(
                    coord.get_str("bass3", "Z1Status", "value"), "ventilation"
                )
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 30)
                vent_attrs = coord.get_ventilation_remaining_attributes()
                self.assertTrue(vent_attrs["is_active"])
                self.assertEqual(vent_attrs["remaining_minutes"], 30)
                self.assertIsNotNone(vent_attrs["end_time"])
                for _, cb in scheduled_timers:
                    cb(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIn(("ebusd/bass3/Z1Status/get", ""), published)
                self.assertIn(
                    ("ebusd/bass3/Z1ActualRoomTempDesired/get", ""), published
                )

                # 2. Cancel sets VentilationBoost=off, clears Z1Status back to auto & clears countdown
                published.clear()
                scheduled_timers.clear()
                await coord.async_cancel_ventilation_boost()
                self.assertIn(("ebusd/bass3/VentilationBoost/set", "off"), published)
                self.assertEqual(coord.get_str("bass3", "Z1Status", "value"), "auto")
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 0)
                self.assertIsNone(coord._ventilation_end_time)
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                # 3. External Z1Status transition auto -> ventilation starts 30 min timer; ventilation -> auto clears it & /get desired temp
                published.clear()
                scheduled_timers.clear()
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="ventilation")
                )
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 30)
                self.assertIsNotNone(coord._ventilation_end_time)

                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="auto")
                )
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 0)
                self.assertIsNone(coord._ventilation_end_time)
                for _, cb in scheduled_timers:
                    cb(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()
                self.assertIn(
                    ("ebusd/bass3/Z1ActualRoomTempDesired/get", ""), published
                )

            await coord.async_unload()

        asyncio.run(_run())

    def test_quick_veto_from_off_ignores_mid_activation_stale_mqtt(self) -> None:
        """Stale Z1SFMode=auto/Z1Status arriving mid-activation from 'off' must not revert Z1OpMode to off."""

        async def _run() -> None:
            hass = MagicMock()
            created_tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                created_tasks.append(asyncio.ensure_future(coro)) or created_tasks[-1]
            )
            hass.data = {}
            entry = MagicMock()
            entry.entry_id = "test_veto_off_mid_activation_race"
            entry.data = {}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3.lower(), "Status01")] = {"temp1": 35.0}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1OpMode")] = {"value": "off"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1SFMode")] = {"value": "auto"}
            coord._state[(CIRCUIT_BASS3.lower(), "Z1Status")] = {"value": "off"}
            coord._last_telemetry_time = time.monotonic()

            published: list[tuple[str, str]] = []

            async def _fake_publish(
                _h: Any, topic: str, payload: str, **kw: Any
            ) -> None:
                published.append((topic, str(payload)))

            async def _sleep_with_stale_mqtt(_sec: float) -> None:
                # Simulate stale MQTT packets arriving during the inter-write 0.3s sleeps
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1SFMode", payload="auto")
                )
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="off")
                )

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    side_effect=_sleep_with_stale_mqtt,
                ),
            ):
                await coord.async_set_quick_veto(temperature=22.0, duration=1.5)
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

            self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), published)
            self.assertEqual(coord.pre_veto_opmode, "off")
            self.assertEqual(coord.get_str(CIRCUIT_BASS3, "Z1SFMode", "value"), "veto")
            self.assertEqual(coord.get_quick_veto_remaining_minutes(), 90)
            await coord.async_unload()

        asyncio.run(_run())

    def test_deferred_restore_epoch_iso_is_utc_and_platform_safe(self) -> None:
        """Deferred offline store payloads must not invoke naive datetime.fromtimestamp(0.0)."""
        from custom_components.arotherm_genia_ebusd.coordinator import (
            _DEFERRED_RESTORE_END_ISO,
        )

        self.assertEqual(_DEFERRED_RESTORE_END_ISO, "1970-01-01T00:00:00+00:00")
        self.assertEqual(
            SaunierGeniaCoordinator._parse_persisted_end_timestamp(
                {"end_time": _DEFERRED_RESTORE_END_ISO}
            ),
            0.0,
        )

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock()
            entry.entry_id = "test_deferred_utc_iso"
            entry.data = {}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._last_telemetry_time = 0.0
            coord._pre_veto_opmode = "off"
            saved_payloads: list[dict[str, Any]] = []

            async def _capture_save(
                _store: Any, data: dict[str, Any], _lbl: str
            ) -> None:
                saved_payloads.append(dict(data))

            with patch.object(coord, "_async_save_store", side_effect=_capture_save):
                await coord._async_finish_heating_veto_off_restore("offline_test")

            self.assertEqual(len(saved_payloads), 1)
            self.assertEqual(saved_payloads[0]["end_timestamp"], 0.0)
            self.assertEqual(saved_payloads[0]["end_time"], "1970-01-01T00:00:00+00:00")
            await coord.async_unload()

        asyncio.run(_run())

    def test_ventilation_grace_ignores_stale_status_and_starts_on_initial_ventilation(
        self,
    ) -> None:
        """Stale Z1Status='auto' right after HA activation must not wipe countdown; startup 'ventilation' starts countdown."""

        async def _run() -> None:
            hass = MagicMock()
            created_tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                created_tasks.append(asyncio.ensure_future(coro)) or created_tasks[-1]
            )
            hass.data = {}
            entry = MagicMock()
            entry.entry_id = "test_ventilation_race_and_startup"
            entry.data = {}
            entry.options = {}

            # 1. Startup with empty state receiving Z1Status='ventilation' -> starts 30 min countdown
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._ebus_connected = True
            coord._last_mqtt_message_time = 1e12
            coord._async_on_mqtt_message(
                MagicMock(topic="ebusd/bass3/Z1Status", payload="ventilation")
            )
            self.assertEqual(coord.get_ventilation_remaining_minutes(), 30)
            self.assertIsNotNone(coord._ventilation_end_time)

            # Clear to normal 'auto'
            coord._async_on_mqtt_message(
                MagicMock(topic="ebusd/bass3/Z1Status", payload="auto")
            )
            self.assertEqual(coord.get_ventilation_remaining_minutes(), 0)
            self.assertIsNone(coord._ventilation_end_time)

            # 2. Activate from HA, then receive stale Z1Status='auto' within grace window
            published: list[tuple[str, str]] = []

            async def _fake_publish(
                _h: Any, topic: str, payload: str, **kw: Any
            ) -> None:
                published.append((topic, str(payload)))

            scheduled_timers: list[tuple[float, Any]] = []

            def _fake_call_later(_h: Any, delay: float, cb: Any) -> Any:
                scheduled_timers.append((delay, cb))
                return lambda: None

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_publish,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    side_effect=_fake_call_later,
                ),
            ):
                await coord.async_activate_ventilation_boost()
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="auto")
                )
                self.assertIsNotNone(coord._ventilation_end_time)
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 30)
                self.assertEqual(
                    coord.get_str("bass3", "Z1Status", "value"), "ventilation"
                )

                # Once controller confirms 'ventilation', subsequent 'auto' clears immediately
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="ventilation")
                )
                coord._async_on_mqtt_message(
                    MagicMock(topic="ebusd/bass3/Z1Status", payload="auto")
                )
                self.assertIsNone(coord._ventilation_end_time)
                self.assertEqual(coord.get_ventilation_remaining_minutes(), 0)
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

            await coord.async_unload()

        asyncio.run(_run())

    def test_dhw_boost_offline_persists_deferred_restore_and_preserves_saved_temp(
        self,
    ) -> None:
        """Offline timeout/completion persists deferred restore and re-triggering preserves baseline target."""

        async def _run() -> None:
            hass = MagicMock()
            created_tasks: list[asyncio.Task[Any]] = []
            hass.async_create_task.side_effect = lambda coro: (
                created_tasks.append(asyncio.ensure_future(coro)) or created_tasks[-1]
            )
            hass.data = {}
            entry = MagicMock()
            entry.entry_id = "test_dhw_boost_offline"
            entry.data = {}
            entry.options = {"force_dhw_boost": True}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state = {
                ("bass3", "HwcTempDesired"): {"value": 56.0},
                ("bass3", "HwcStorageTemp"): {"value": 55.0},
                ("bass3", "CylinderChargeHyst"): {"value": 5.0},
                ("bass3", "HwcSFMode"): {"value": "auto"},
                ("bass3", "HwcStatus"): {"value": "load"},
            }

            saved_payloads: list[dict[str, Any]] = []

            async def _capture_save(
                _store: Any, data: dict[str, Any], _lbl: str
            ) -> None:
                saved_payloads.append(dict(data))

            with patch.object(coord, "_async_save_store", side_effect=_capture_save):
                # 1. Timeout while offline persists deferred payload
                coord._state[("global", "running")] = {"value": "false"}
                coord._dhw_boost_active = True
                coord._saved_dhw_target_temp = 48.0
                coord._async_on_dhw_boost_timeout(datetime.now())
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                self.assertFalse(coord._dhw_boost_active)
                self.assertTrue(coord._pending_dhw_boost_restore)
                self.assertEqual(len(saved_payloads), 1)
                self.assertEqual(saved_payloads[0]["saved_target_temp"], 48.0)
                self.assertEqual(saved_payloads[0]["end_timestamp"], 0.0)
                self.assertEqual(
                    saved_payloads[0]["end_time"], "1970-01-01T00:00:00+00:00"
                )

                # 2. Completion check while offline also persists deferred payload
                saved_payloads.clear()
                coord._dhw_boost_active = True
                coord._dhw_boost_seen_load = True
                coord._dhw_boost_started_at = 0.0
                coord._pending_dhw_boost_restore = False
                coord._async_check_dhw_boost_restoration()
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                self.assertFalse(coord._dhw_boost_active)
                self.assertTrue(coord._pending_dhw_boost_restore)
                self.assertEqual(len(saved_payloads), 1)
                self.assertEqual(saved_payloads[0]["saved_target_temp"], 48.0)
                self.assertEqual(saved_payloads[0]["end_timestamp"], 0.0)

                # 3. Re-triggering while _pending_dhw_boost_restore is True must not overwrite 48.0 with 56.0
                coord._state[("global", "running")] = {"value": "true"}
                coord._last_telemetry_time = time.monotonic()
                with (
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                        new=AsyncMock(),
                    ),
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                        return_value=lambda: None,
                    ),
                ):
                    await coord.async_trigger_dhw_boost()

                self.assertEqual(coord._saved_dhw_target_temp, 48.0)
                self.assertTrue(coord._dhw_boost_active)
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                    created_tasks.clear()

                # 4. Lowercase MQTT topic 'ebusd/bass3/hwcsfmode' triggers DHW boost restoration check
                coord._dhw_boost_active = True
                coord._dhw_boost_seen_load = True
                coord._dhw_boost_started_at = 0.0
                coord._saved_dhw_target_temp = 48.0
                with patch.object(
                    coord, "async_write_parameter", new=AsyncMock()
                ) as mock_write:
                    coord._async_on_mqtt_message(
                        MagicMock(topic="ebusd/bass3/hwcsfmode", payload="auto")
                    )
                    if created_tasks:
                        await asyncio.gather(*created_tasks)
                        created_tasks.clear()

                self.assertFalse(coord._dhw_boost_active)
                mock_write.assert_awaited_once_with("bass3", "HwcTempDesired", 48.0)

            await coord.async_unload()

        asyncio.run(_run())

    def test_deferred_restore_delay_waits_for_hydration_on_startup(self) -> None:
        """Deferred restore waits past INITIAL_HYDRATION_WAIT_SECONDS on startup and uses 1.5s post-hydration."""

        async def _run() -> None:
            hass = MagicMock()
            hass.data = {}
            entry = MagicMock()
            entry.entry_id = "test_deferred_restore_delay"
            entry.data = {}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._pending_heating_veto_restore = True
            scheduled: list[float] = []

            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                side_effect=lambda _h, delay, _cb: (
                    scheduled.append(delay) or MagicMock()
                ),
            ):
                coord._initial_hydration_started = False
                coord._async_schedule_pending_restores()
                coord._heating_veto_restore_unsub = None

                coord._initial_hydration_started = True
                coord._async_schedule_pending_restores()

            self.assertEqual(scheduled, [7.0, 1.5])
            await coord.async_unload()

        asyncio.run(_run())

    def test_repair_issue_clears_after_restart_and_without_migo(self) -> None:
        """Clearing issues works even before creation in session, and slow polling clears without MiGo."""
        import sys

        ir_mod = sys.modules["homeassistant.helpers.issue_registry"]
        ir_mod.async_create_issue.reset_mock()
        ir_mod.async_delete_issue.reset_mock()

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_repair_restart_and_no_migo"
        entry.data = {"mqtt_prefix": "ebusd", CONF_HAS_MIGO_LINK: False}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)

        # 1. Fresh coordinator calling active=False deletes any persisted registry issue once
        coord._async_set_repair_issue(ISSUE_EBUSD_SLOW_POLLING_SEED, active=False)
        ir_mod.async_delete_issue.assert_called_once_with(
            hass, DOMAIN, ISSUE_EBUSD_SLOW_POLLING_SEED
        )
        ir_mod.async_delete_issue.reset_mock()
        # Repeated active=False without re-raising is deduplicated
        coord._async_set_repair_issue(ISSUE_EBUSD_SLOW_POLLING_SEED, active=False)
        ir_mod.async_delete_issue.assert_not_called()

        # 2. Without MiGo (fallback_poll_interval=300), >=450s triggers and 300s clears
        def push_mqtt(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload.encode("utf-8")
            coord._async_on_mqtt_message(msg)

        push_mqtt("ebusd/global/signal", '{"value": {"value": true}}')
        push_mqtt("ebusd/hmux0/Status01", '{"flow_temp": {"value": 35.0}}')

        t0 = 1000.0
        with patch("time.monotonic", return_value=t0):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 450}}',
            )
        t1 = t0 + 500.0
        with patch("time.monotonic", return_value=t1):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 460}}',
            )
        self.assertIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)

        t2 = t1 + 300.0
        with patch("time.monotonic", return_value=t2):
            push_mqtt(
                "ebusd/hmux0/RunDataElectricPowerConsumption",
                '{"energy": {"value": 470}}',
            )
        self.assertNotIn(ISSUE_EBUSD_SLOW_POLLING_SEED, coord._active_repair_issues)
        ir_mod.async_delete_issue.assert_called_with(
            hass, DOMAIN, ISSUE_EBUSD_SLOW_POLLING_SEED
        )

    def test_scan_message_ignores_ebusd_err_payloads(self) -> None:
        """Ensure scan.* error responses (e.g. 'ERR: element not found') are never stored as serial/SW/HW."""
        entry = MagicMock()
        entry.entry_id = "test_scan_err_ignore"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        for topic, payload in (
            ("ebusd/scan.08/Id", "ERR: element not found"),
            ("ebusd/scan.08/Id", '{"serial": "ERR: element not found"}'),
            ("ebusd/scan.08/Id", "ERR: arbitration lost 123456"),
            ("ebusd/scan.08/", '{"sw": "ERR: read timeout"}'),
        ):
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload.encode("utf-8")
            coord._async_on_mqtt_message(msg)

        self.assertIsNone(coord.get_device_serial_number("hmu"))
        self.assertIsNone(coord.get_device_sw_version("hmu"))
        self.assertIsNone(coord.get_device_hw_version("hmu"))
        self.assertFalse(
            SaunierGeniaCoordinator._is_valid_serial_candidate(
                "ERR: element not found", min_len=20
            )
        )
        self.assertTrue(
            SaunierGeniaCoordinator._is_valid_serial_candidate(
                "21241000201234561234567890N1", exact_len=28
            )
        )

    def test_write_parameter_does_not_mutate_state_on_publish_failure(self) -> None:
        """Failed mqtt.async_publish must not apply optimistic state or notify listeners."""

        async def _run() -> None:
            entry = MagicMock()
            entry.entry_id = "test_write_no_optimistic_on_fail"
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(MagicMock(), entry)
            coord._state[(CIRCUIT_BASS3, "Z1ManualTemp")] = {"temp": 20.0}

            notified: list[tuple[str, str]] = []
            coord.async_add_listener(
                CIRCUIT_BASS3,
                "Z1ManualTemp",
                lambda: notified.append((CIRCUIT_BASS3, "Z1ManualTemp")),
            )

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=HomeAssistantError("Broker offline"),
                ),
                self.assertRaises(HomeAssistantError),
            ):
                await coord.async_write_parameter(CIRCUIT_BASS3, "Z1ManualTemp", 22.5)

            self.assertEqual(
                coord.get_float(CIRCUIT_BASS3, "Z1ManualTemp", "temp"), 20.0
            )
            self.assertEqual(notified, [])

        asyncio.run(_run())

    def test_ebus_operational_recovery_notifies_global_listeners(self) -> None:
        """Traffic recovery after watchdog silence notifies (global, running/signal) listeners."""
        entry = MagicMock()
        entry.entry_id = "test_ebus_recovery_listeners"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        running_notifs: list[bool] = []
        coord.async_add_listener(
            "global",
            "running",
            lambda: running_notifs.append(coord.is_ebus_operational),
        )

        with patch("time.monotonic", return_value=1000.0):
            coord._async_on_mqtt_message(
                MagicMock(topic="ebusd/hmux0/Status01", payload=b'{"flow_temp": 35.0}')
            )
            self.assertTrue(coord.is_ebus_operational)
        self.assertEqual(running_notifs, [True])

        # Silence timeout -> watchdog flips availability to False
        with patch("time.monotonic", return_value=1700.0):
            coord._async_check_watchdog(datetime.now())
            self.assertFalse(coord.is_ebus_operational)
        self.assertEqual(running_notifs, [True, False])

        # Recovery via normal circuit message (without global/running) notifies True
        with patch("time.monotonic", return_value=1705.0):
            coord._async_on_mqtt_message(
                MagicMock(topic="ebusd/hmux0/Status01", payload=b'{"flow_temp": 36.0}')
            )
            self.assertTrue(coord.is_ebus_operational)
        self.assertEqual(running_notifs, [True, False, True])

    def test_heating_veto_safety_guards_against_stale_cache_and_err_timeouts(
        self,
    ) -> None:
        """Ensure B1/B2a/B2b guards never force Z1OpMode='off' on stale cache, ERR: timeout, or missing Z1SFMode."""
        from types import SimpleNamespace

        async def _run() -> None:
            tasks: list[asyncio.Task[Any]] = []
            hass = MagicMock()
            hass.async_create_task.side_effect = lambda coro: (
                tasks.append(asyncio.get_running_loop().create_task(coro)) or tasks[-1]
            )
            entry = MagicMock(entry_id="test_veto_safety_guards")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._last_telemetry_time = time.monotonic()
            coord._state[(CIRCUIT_BASS3, "Status01")] = {"temp1": 35.0}
            coord._state[(CIRCUIT_BASS3, "Z1OpMode")] = {"value": "auto"}
            coord._pre_veto_opmode = "off"
            coord._heating_veto_end_time = datetime.now() + timedelta(hours=3)
            coord._heating_veto_started_mono = time.monotonic()

            writes: list[tuple[str, str]] = []

            async def _fake_pub(_h: Any, topic: str, payload: str, **_kw: Any) -> None:
                writes.append((topic, str(payload)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.async_call_later",
                    return_value=MagicMock(),
                ),
            ):
                # 1. B1: Fresh Z1Status='veto' must not trust cached Z1SFMode='auto'
                coord._state[(CIRCUIT_BASS3, "Z1SFMode")] = {"value": "auto"}
                coord._async_on_mqtt_message(
                    SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="veto")
                )
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), writes)
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), writes)

                # Fresh Z1SFMode='ERR: timeout' must also not be treated as veto finished
                writes.clear()
                coord._async_on_mqtt_message(
                    SimpleNamespace(
                        topic="ebusd/bass3/Z1SFMode", payload="ERR: timeout"
                    )
                )
                if tasks:
                    await asyncio.gather(*tasks)
                    tasks.clear()
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), writes)

                # 2. B2a: Timeout /get returning ERR: timeout on Z1Status with Z1SFMode='veto' defers restore
                writes.clear()
                coord._state[(CIRCUIT_BASS3, "Z1SFMode")] = {"value": "veto"}
                coord._state[(CIRCUIT_BASS3, "Z1Status")] = {"value": "veto"}

                async def _pub_b2a(
                    _h: Any, topic: str, payload: str, **_kw: Any
                ) -> None:
                    writes.append((topic, str(payload)))
                    if topic.endswith("Z1Status/get"):
                        coord._async_on_mqtt_message(
                            SimpleNamespace(
                                topic="ebusd/bass3/Z1Status", payload="ERR: timeout"
                            )
                        )
                    elif topic.endswith("Z1SFMode/get"):
                        coord._async_on_mqtt_message(
                            SimpleNamespace(
                                topic="ebusd/bass3/Z1SFMode", payload="veto"
                            )
                        )

                with (
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                        side_effect=_pub_b2a,
                    ),
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                        new=AsyncMock(return_value=None),
                    ),
                ):
                    coord._async_on_heating_veto_timeout(datetime.now())
                    if tasks:
                        await asyncio.gather(*tasks)
                        tasks.clear()
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), writes)
                self.assertEqual(coord.pre_veto_opmode, "off")

                # Both /get returning ERR: timeout also defers instead of guessing end of veto
                writes.clear()

                async def _pub_both_err(
                    _h: Any, topic: str, payload: str, **_kw: Any
                ) -> None:
                    writes.append((topic, str(payload)))
                    if topic.endswith("Z1Status/get"):
                        coord._async_on_mqtt_message(
                            SimpleNamespace(
                                topic="ebusd/bass3/Z1Status", payload="ERR: timeout"
                            )
                        )
                    elif topic.endswith("Z1SFMode/get"):
                        coord._async_on_mqtt_message(
                            SimpleNamespace(
                                topic="ebusd/bass3/Z1SFMode", payload="ERR: timeout"
                            )
                        )

                with (
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                        side_effect=_pub_both_err,
                    ),
                    patch(
                        "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                        new=AsyncMock(return_value=None),
                    ),
                ):
                    coord._async_on_heating_veto_timeout(datetime.now())
                    if tasks:
                        await asyncio.gather(*tasks)
                        tasks.clear()
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), writes)

                # 3. B2b: Pending restore on restart waits until controller Z1SFMode is known
                writes.clear()
                coord._state.clear()
                coord._state[("hmux0", "RunDataFlowTemp")] = {"value": 35}
                coord._pending_heating_veto_restore = True
                coord._last_z1_sfmode_sync_time = 0.0
                await coord._async_execute_pending_heating_veto_restore()
                self.assertNotIn(("ebusd/bass3/Z1OpMode/set", "off"), writes)
                self.assertIn(("ebusd/bass3/Z1SFMode/get", ""), writes)
                self.assertTrue(coord._pending_heating_veto_restore)

            await coord.async_unload()

        asyncio.run(_run())

    def test_holiday_and_cooling_windows_use_ha_timezone(self) -> None:
        """Holiday defaults and remaining calculations use HA timezone instead of OS local time."""
        from datetime import UTC, timezone

        ha_tz = timezone(timedelta(hours=5))
        fake_now_utc = datetime(2026, 11, 15, 23, 30, 0, tzinfo=UTC)
        fake_now_ha = fake_now_utc.astimezone(ha_tz)  # 2026-11-16 04:30:00+05:00

        async def _run() -> None:
            entry = MagicMock(entry_id="test_holiday_ha_tz")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(MagicMock(), entry)
            coord._last_telemetry_time = time.monotonic()
            coord._state[(CIRCUIT_BASS3, "Status01")] = {"temp1": 35.0}

            writes: list[tuple[str, str]] = []

            async def _fake_pub(_h: Any, topic: str, payload: str, **_kw: Any) -> None:
                writes.append((topic, str(payload)))

            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.dt_util.get_default_time_zone",
                    return_value=ha_tz,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.dt_util.now",
                    return_value=fake_now_ha,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.dt_util.as_local",
                    side_effect=lambda dt: dt.astimezone(ha_tz),
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                    side_effect=_fake_pub,
                ),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    new=AsyncMock(return_value=None),
                ),
            ):
                # 1. Default start date/time must reflect 2026-11-16 04:30:00 (+05:00), not UTC 15th 23:30
                await coord.async_activate_holiday_mode(temp=14.0)
                self.assertIn(("ebusd/bass3/HolidayStartDate/set", "16;11;26"), writes)
                self.assertIn(("ebusd/bass3/HolidayStartTime/set", "04;30;00"), writes)

                # 2. Preselected UTC-aware start datetime converts cleanly to HA local (+05:00)
                writes.clear()
                coord._preselected_holiday_start_datetime = datetime(
                    2026, 11, 20, 22, 15, 0, tzinfo=UTC
                )
                await coord.async_activate_holiday_mode(temp=14.0)
                self.assertIn(("ebusd/bass3/HolidayStartDate/set", "21;11;26"), writes)
                self.assertIn(("ebusd/bass3/HolidayStartTime/set", "03;15;00"), writes)
                coord._preselected_holiday_start_datetime = None

                # 3. Remaining holiday calculation evaluates end wall time in HA timezone (06:30 vs 04:30 = 2h)
                coord._state[(CIRCUIT_BASS3, "Z1Status")] = {"value": "holidayaway"}
                coord._state[(CIRCUIT_BASS3, "HolidayStartDate")] = {
                    "day": 15,
                    "month": 11,
                    "year": 26,
                }
                coord._state[(CIRCUIT_BASS3, "HolidayEndDate")] = {
                    "day": 16,
                    "month": 11,
                    "year": 26,
                }
                coord._state[(CIRCUIT_BASS3, "HolidayEndTime")] = {
                    "hours": 6,
                    "minutes": 30,
                    "seconds": 0,
                }
                attrs = coord.get_holiday_remaining_attributes()
                self.assertTrue(attrs["is_active"])
                self.assertEqual(attrs["days_remaining"], 0)
                self.assertEqual(attrs["remaining_hours"], 2)
                self.assertEqual(attrs["remaining_minutes"], 0)

                # 4. Cooling calendar day remaining also uses HA local date (16th -> 0 days)
                coord._state[(CIRCUIT_BASS3, "CoolingReleaseStatus")] = {"value": "on"}
                coord._state[(CIRCUIT_BASS3, "Z1OpModeCooling")] = {"value": "day"}
                coord._state[(CIRCUIT_BASS3, "CoolingEndDate")] = {
                    "day": 16,
                    "month": 11,
                    "year": 26,
                }
                self.assertEqual(coord.get_cooling_remaining_days(), 0)

            await coord.async_unload()

        asyncio.run(_run())

    def test_err_payloads_do_not_poison_state_getters_repairs_or_ventilation(
        self,
    ) -> None:
        """ERR: payloads must never overwrite valid state, cancel ventilation, or satisfy has_message."""

        async def _run() -> None:
            from types import SimpleNamespace

            from custom_components.arotherm_genia_ebusd import _async_register_services
            from custom_components.arotherm_genia_ebusd.const import (
                CIRCUIT_VWZIO,
                SERVICE_READ_PARAMETER,
            )

            hass = MagicMock()
            hass.async_create_task.side_effect = lambda coro: (
                asyncio.get_running_loop().create_task(coro)
            )
            services: dict[str, Any] = {}
            hass.services.has_service.return_value = False
            hass.services.async_register.side_effect = (
                lambda d, s, h, schema=None, *args, **kwargs: services.update({s: h})
            )
            entry = MagicMock(entry_id="err_guard_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            hass.data = {DOMAIN: {entry.entry_id: coord}}
            _async_register_services(hass)

            # 1. Start active ventilation >15s ago
            coord._state[(CIRCUIT_BASS3, "Z1Status")] = {"value": "ventilation"}
            coord._start_ventilation_countdown()
            coord._ventilation_ha_activated_mono = time.monotonic() - 30.0
            self.assertIsNotNone(coord._ventilation_end_time)

            # Push ERR: timeout on Z1Status: must NOT clear ventilation or poison Z1Status
            coord._async_on_mqtt_message(
                SimpleNamespace(topic="ebusd/bass3/Z1Status", payload="ERR: timeout")
            )
            self.assertIsNotNone(coord._ventilation_end_time)
            self.assertEqual(
                coord.get_str(CIRCUIT_BASS3, "Z1Status", "value"), "ventilation"
            )

            # 2. ERR: on unseen register must NOT satisfy has_message, get_field/get_str, or clear missing CSV
            coord._state[(CIRCUIT_HMUX0, "StateCompressor")] = {
                "flow_temp": 35.0,
                "modulation": 40,
            }
            coord._async_on_mqtt_message(
                SimpleNamespace(
                    topic="ebusd/vwzio/SecondaryCircuitStatus",
                    payload="ERR: element not found",
                )
            )
            self.assertFalse(coord.has_message(CIRCUIT_VWZIO, "SecondaryCircuitStatus"))
            self.assertIsNone(
                coord.get_str(CIRCUIT_VWZIO, "SecondaryCircuitStatus", "value")
            )
            self.assertIsNone(
                coord.get_field(CIRCUIT_VWZIO, "SecondaryCircuitStatus", "value")
            )
            self.assertFalse(coord._has_all_required_csv_circuits())

            # Defense-in-depth if ERR: exists directly in _state
            coord._state[(CIRCUIT_VWZIO, "DirectErr")] = {"value": "ERR: read error"}
            self.assertFalse(coord.has_message(CIRCUIT_VWZIO, "DirectErr"))
            self.assertIsNone(coord.get_field(CIRCUIT_VWZIO, "DirectErr", "value"))
            self.assertIsNone(coord.get_str(CIRCUIT_VWZIO, "DirectErr", "value"))

            # 3. read_parameter service still receives transient ERR: response without storing in _state
            async def _pub_err(_h: Any, topic: str, _p: str, **_kw: Any) -> None:
                if topic == "ebusd/bass3/UnknownReg/get":
                    coord._async_on_mqtt_message(
                        SimpleNamespace(
                            topic="ebusd/bass3/UnknownReg",
                            payload="ERR: element not found",
                        )
                    )

            with patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                side_effect=_pub_err,
            ):
                call = MagicMock()
                call.data = {
                    "circuit": CIRCUIT_BASS3,
                    "name": "UnknownReg",
                    "force": True,
                    "timeout": 1.0,
                }
                resp = await services[SERVICE_READ_PARAMETER](call)

            self.assertEqual(resp["value"], {"value": "ERR: element not found"})
            self.assertFalse(coord.has_message(CIRCUIT_BASS3, "UnknownReg"))

            coord._clear_ventilation_countdown()
            await coord.async_unload()

        asyncio.run(_run())

    def test_pending_veto_restores_cancelled_by_service_and_inflight_get(
        self,
    ) -> None:
        """Deferred veto restores do not clobber cancel_quick_veto or mid-await mode changes."""

        async def _run() -> None:
            from custom_components.arotherm_genia_ebusd import _async_register_services

            hass = MagicMock()
            hass.async_create_task.side_effect = lambda coro: (
                asyncio.get_running_loop().create_task(coro)
            )
            services: dict[str, Any] = {}
            hass.services.has_service.side_effect = lambda _d, name: name in services
            hass.services.async_register.side_effect = (
                lambda _d, name, handler, schema=None, *args, **kwargs: services.update(
                    {name: handler}
                )
            )
            entry = MagicMock(entry_id="entry_pending_race")
            entry.data = {"mqtt_prefix": "ebusd", "ebusd_host": "localhost"}
            entry.options = {}

            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3, "z1opmodecooling")] = {"value": "day"}
            coord._last_mqtt_message_time = time.monotonic()
            hass.data = {DOMAIN: {entry.entry_id: coord}}
            _async_register_services(hass)

            writes: list[tuple[str, str, Any]] = []

            async def _fake_write(circuit: str, name: str, value: Any) -> None:
                writes.append((circuit, name, value))

            # 1. Deferred cooling restore cancelled via cancel_quick_veto service
            unsub_called = 0

            def _cool_unsub() -> None:
                nonlocal unsub_called
                unsub_called += 1

            coord._pending_cooling_veto_restore = True
            coord._cooling_veto_restore_unsub = _cool_unsub
            coord._pre_cooling_veto_opmode = "night"
            coord._pre_cooling_veto_temp = 23.0

            with (
                patch.object(coord, "async_write_parameter", side_effect=_fake_write),
                patch.object(coord, "schedule_cooling_desired_refresh"),
                patch.object(coord, "_async_clear_cooling_veto_store"),
            ):
                await services["cancel_quick_veto"](MagicMock())

            self.assertEqual(unsub_called, 1)
            self.assertFalse(coord.pending_cooling_veto_restore)
            self.assertIn((CIRCUIT_BASS3, "Z1OpModeCooling", "night"), writes)
            self.assertIn((CIRCUIT_BASS3, "Z1CoolingManualTemp", 23.0), writes)
            self.assertNotIn((CIRCUIT_BASS3, "Z1SFMode", "auto"), writes)

            # 2. Deferred heating restore aborted if discarded during in-flight /get Z1SFMode
            writes.clear()
            coord._pending_heating_veto_restore = True
            coord._pre_veto_opmode = "off"
            coord._last_z1_sfmode_sync_time = 0.0

            async def _get_and_discard(circuit: str, name: str) -> None:
                coord._state[(circuit.lower(), name.lower())] = {"value": "auto"}
                await coord.async_discard_pending_heating_restore()

            with (
                patch.object(coord, "async_request_get", side_effect=_get_and_discard),
                patch.object(coord, "async_write_parameter", side_effect=_fake_write),
            ):
                await coord._async_execute_pending_heating_veto_restore()

            self.assertFalse(coord.pending_heating_veto_restore)
            self.assertEqual(writes, [])

            await coord.async_unload()

        asyncio.run(_run())

    def test_dhw_boost_trigger_and_cancel_serialized_by_lock(self) -> None:
        """Concurrent trigger and cancel DHW boost serialize writes without interleaving."""

        async def _run() -> None:
            hass = MagicMock()
            hass.async_create_task.side_effect = lambda coro: (
                asyncio.get_running_loop().create_task(coro)
            )
            entry = MagicMock(entry_id="dhw_lock_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {"force_dhw_boost": True}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3, "hwcstoragetemp")] = {"value": 47.0}
            coord._state[(CIRCUIT_BASS3, "hwctempdesired")] = {"value": 50.0}
            coord._last_mqtt_message_time = time.monotonic()

            writes: list[tuple[str, Any]] = []

            async def _record_write(_c: str, name: str, val: Any) -> None:
                writes.append((name, val))

            real_sleep = asyncio.sleep

            async def _short_sleep(_delay: float) -> None:
                await real_sleep(0.02)

            with (
                patch.object(coord, "async_write_parameter", side_effect=_record_write),
                patch.object(coord, "_async_save_dhw_boost_state"),
                patch.object(coord, "_async_clear_store"),
                patch(
                    "custom_components.arotherm_genia_ebusd.coordinator.asyncio.sleep",
                    side_effect=_short_sleep,
                ),
            ):
                trigger_task = asyncio.create_task(coord.async_trigger_dhw_boost())
                await real_sleep(0.005)
                cancel_task = asyncio.create_task(coord.async_cancel_dhw_boost())
                await asyncio.gather(trigger_task, cancel_task)

            self.assertEqual(
                writes,
                [
                    ("HwcTempDesired", 53.5),
                    ("HwcSFMode", "load"),
                    ("HwcSFMode", "auto"),
                    ("HwcTempDesired", 50.0),
                ],
            )
            self.assertFalse(coord.dhw_boost_forced_active)

            await coord.async_unload()

        asyncio.run(_run())

    def test_midnight_watchdog_notifies_cooling_and_weekly_schedules(self) -> None:
        """Crossing midnight in watchdog notifies CoolingEndDate, Holiday, and *_Slots."""
        from datetime import date

        hass = MagicMock()
        entry = MagicMock(entry_id="midnight_entry")
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)
        coord._last_watchdog_date = date(2026, 11, 15)

        notified: list[tuple[str, str]] = []
        with (
            patch.object(
                coord,
                "_async_notify_message_listeners",
                side_effect=lambda c, m: notified.append((c, m)),
            ),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.dt_util.now",
                return_value=datetime(2026, 11, 16, 0, 1),
            ),
        ):
            coord._async_check_watchdog(datetime(2026, 11, 16, 0, 1))

        self.assertIn((CIRCUIT_BASS3, "CoolingEndDate"), notified)
        self.assertIn((CIRCUIT_BASS3, "Z1Timer_Slots"), notified)
        self.assertIn((CIRCUIT_BASS3, "SilentTimer_Slots"), notified)
        self.assertEqual(coord._last_watchdog_date, date(2026, 11, 16))

    def test_cancel_quick_veto_preserves_tracking_on_write_failure(self) -> None:
        """async_cancel_quick_veto keeps tracking and re-arms timer if bus writes fail."""
        from datetime import timedelta

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock(entry_id="cancel_fail_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {}
            coord = SaunierGeniaCoordinator(hass, entry)
            coord._state[(CIRCUIT_BASS3, "z1sfmode")] = {"value": "veto"}
            coord._last_mqtt_message_time = time.monotonic()
            coord._pre_veto_opmode = "off"
            coord._heating_veto_end_time = datetime.now() + timedelta(hours=1)
            coord._last_heating_veto_duration = 1.0
            coord._heating_veto_started_mono = time.monotonic()

            with (
                patch.object(
                    coord,
                    "async_write_parameter",
                    side_effect=RuntimeError("MQTT timeout"),
                ),
                patch.object(coord, "_arm_heating_veto_timer") as mock_arm,
                patch.object(coord, "_async_clear_store") as mock_clear,
                self.assertRaises(RuntimeError),
            ):
                await coord.async_cancel_quick_veto()

            self.assertEqual(coord._pre_veto_opmode, "off")
            self.assertIsNotNone(coord._heating_veto_end_time)
            self.assertEqual(coord._last_heating_veto_duration, 1.0)
            self.assertGreater(coord._heating_veto_started_mono, 0.0)
            mock_arm.assert_called_once()
            mock_clear.assert_not_called()

            await coord.async_unload()

        asyncio.run(_run())

    def test_polish_21_tcp_single_info_startup_throttle_and_legionella_probe(
        self,
    ) -> None:
        """Verify TCP send avoids duplicate info call, -30s startup throttle, and hwclegionelladay ERR probe."""

        async def _run() -> None:
            hass = MagicMock()
            entry = MagicMock(entry_id="polish21_entry")
            entry.data = {"mqtt_prefix": "ebusd"}
            entry.options = {"enable_ebusd_tcp": True}
            coord = SaunierGeniaCoordinator(hass, entry)

            self.assertLessEqual(coord._last_z1_sfmode_sync_time, -30.0)

            coord._async_on_mqtt_message(
                MagicMock(
                    topic="ebusd/bass3/HwcLegionellaDay",
                    payload=b"ERR: element not found",
                )
            )
            self.assertIn("hwclegionelladay", coord._missing_controller_registers)

            writer = MagicMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            writer.drain = AsyncMock()
            reader = MagicMock()
            reader.readline = AsyncMock(return_value=b"done\n")

            with (
                patch.object(
                    coord,
                    "_async_open_tcp_connection",
                    AsyncMock(return_value=(reader, writer)),
                ),
                patch.object(
                    coord, "_async_fetch_ebusd_tcp_info", new_callable=AsyncMock
                ) as mock_info,
            ):
                resp = await coord.async_ebusd_tcp_reload()
                self.assertEqual(resp, "done")
                mock_info.assert_awaited_once()

            await coord.async_unload()

        asyncio.run(_run())

    def test_flow_pressure_skipped_when_hmu_sw_below_902(self) -> None:
        """Verify FlowPressure is skipped in hydration and poll when HMU SW < 0902."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_n5_legacy_sw"
        entry.data = {
            CONF_MANUFACTURER: MANUFACTURER_VAILLANT,
            CONF_HAS_MIGO_LINK: False,
        }
        entry.options = {}

        # 1. Late HMU detection with SW=0804 (< 0902) via scan.08
        coord_legacy = SaunierGeniaCoordinator(hass, entry)
        coord_legacy._pending_hydration = [
            (CIRCUIT_HMUX0, "RunDataFlowTemp"),
            (CIRCUIT_HMU, "FlowPressure"),
        ]
        mock_task = MagicMock()
        mock_task.done.return_value = False
        coord_legacy._hydration_task = mock_task

        coord_legacy._async_on_mqtt_message(
            MagicMock(
                topic="ebusd/scan.08",
                payload='{"MF": "Vaillant", "ID": "HMU00", "SW": "0804", "HW": "5103"}',
            )
        )
        self.assertEqual(coord_legacy.active_outdoor_circuit, CIRCUIT_HMU)
        self.assertNotIn((CIRCUIT_HMU, "FlowPressure"), coord_legacy._pending_hydration)
        self.assertIn((CIRCUIT_HMU, "YieldHc"), coord_legacy._pending_hydration)

        # 2. Initial hydration with SW=0804 skips FlowPressure
        coord_legacy._pending_hydration.clear()
        coord_legacy._hydration_task = None
        with patch.object(coord_legacy, "_async_run_hydration_queue") as mock_run:
            coord_legacy._async_start_initial_hydration(datetime.now())
            mock_run.assert_called_once()
            init_queue = mock_run.call_args[0][0]
            self.assertNotIn((CIRCUIT_HMU, "FlowPressure"), init_queue)
            self.assertIn((CIRCUIT_HMU, "YieldHc"), init_queue)

        # 3. Fallback poll with SW=0804 skips FlowPressure
        with patch.object(
            coord_legacy, "_async_force_poll_queue", return_value=None
        ) as mock_poll:
            asyncio.run(coord_legacy._async_run_fallback_poll(datetime.now()))
            mock_poll.assert_called_once()
            poll_queue = mock_poll.call_args[0][0]
            self.assertNotIn((CIRCUIT_HMU, "FlowPressure"), poll_queue)
            self.assertIn((CIRCUIT_HMU, "YieldHc"), poll_queue)

        # 4. Updating SW to 0902 enables FlowPressure in hydration and poll
        coord_legacy._async_on_mqtt_message(
            MagicMock(
                topic="ebusd/scan.08",
                payload='{"MF": "Vaillant", "ID": "HMU00", "SW": "0902", "HW": "5103"}',
            )
        )
        with patch.object(coord_legacy, "_async_run_hydration_queue") as mock_run_902:
            coord_legacy._async_start_initial_hydration(datetime.now())
            self.assertIn((CIRCUIT_HMU, "FlowPressure"), mock_run_902.call_args[0][0])

        with patch.object(
            coord_legacy, "_async_force_poll_queue", return_value=None
        ) as mock_poll_902:
            asyncio.run(coord_legacy._async_run_fallback_poll(datetime.now()))
            self.assertIn((CIRCUIT_HMU, "FlowPressure"), mock_poll_902.call_args[0][0])

        # 5. _async_run_hydration_queue skips pre-queued FlowPressure when SW < 902
        coord_queue = SaunierGeniaCoordinator(hass, entry)
        coord_queue._record_detected_outdoor_sw("0804")
        requested: list[tuple[str, str]] = []

        async def _capture_get(circuit: str, message: str) -> None:
            requested.append((circuit, message))

        with (
            patch.object(coord_queue, "async_request_get", side_effect=_capture_get),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.HYDRATION_STEP_DELAY_SECONDS",
                0.0,
            ),
        ):
            asyncio.run(
                coord_queue._async_run_hydration_queue(
                    [(CIRCUIT_HMU, "FlowPressure"), (CIRCUIT_HMU, "YieldHc")]
                )
            )
        self.assertEqual(requested, [(CIRCUIT_HMU, "YieldHc")])

    def test_flow_pressure_skipped_when_tcp_info_reports_sw_below_902(self) -> None:
        """Verify TCP info SW<902 on address 08 also gates FlowPressure polling."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_n5_tcp_sw"
        entry.data = {
            CONF_MANUFACTURER: MANUFACTURER_VAILLANT,
            CONF_HAS_MIGO_LINK: False,
        }
        entry.options = {"enable_ebusd_tcp": True}

        coord = SaunierGeniaCoordinator(hass, entry)
        coord._active_outdoor_circuit = CIRCUIT_HMU

        info_lines = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0804;HW=5103", loaded "vaillant/08.hmu.HW5103.csv"\n',
            b"\n",
        ]
        reader = MagicMock()
        reader.readline = AsyncMock(side_effect=info_lines)
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        async def _run() -> None:
            with (
                patch.object(
                    coord,
                    "_async_open_tcp_connection",
                    AsyncMock(return_value=(reader, writer)),
                ),
                patch.object(
                    coord, "_async_verify_csvs_via_tcp", new_callable=AsyncMock
                ),
            ):
                await coord._async_fetch_ebusd_tcp_info()

            self.assertEqual(coord._detected_outdoor_sw, "0804")

            with patch.object(
                coord, "_async_force_poll_queue", return_value=None
            ) as mock_poll:
                await coord._async_run_fallback_poll(datetime.now())
                poll_queue = mock_poll.call_args[0][0]
                self.assertNotIn((CIRCUIT_HMU, "FlowPressure"), poll_queue)

        asyncio.run(_run())

    def test_initial_hydration_expands_only_active_weekly_timer_slots(self) -> None:
        """Initial hydration must queue <prefix>_Slots and expand only days/slots with active counts."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_timer_hydration"
        entry.data = {CONF_MANUFACTURER: MANUFACTURER_VAILLANT}
        entry.options = {}

        coord = SaunierGeniaCoordinator(hass, entry)
        coord._active_outdoor_circuit = CIRCUIT_HMUX0
        coord._state[(CIRCUIT_BASS3, "Z1Timer_Slots")] = {
            "mon": 3,
            "tue": 1,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 0,
        }

        requested: list[tuple[str, str]] = []

        async def _capture_get(circuit: str, message: str) -> None:
            requested.append((circuit, message))
            if (circuit, message) == (CIRCUIT_BASS3, "HwcTimer_Slots"):
                coord._state[(CIRCUIT_BASS3, "HwcTimer_Slots")] = {
                    "mon": 2,
                    "tue": 0,
                    "wed": 0,
                    "thu": 0,
                    "fri": 0,
                    "sat": 0,
                    "sun": 0,
                }

        with (
            patch.object(coord, "async_request_get", side_effect=_capture_get),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.HYDRATION_STEP_DELAY_SECONDS",
                0.0,
            ),
        ):
            asyncio.run(
                coord._async_run_hydration_queue(
                    [
                        (CIRCUIT_BASS3, "OutsideTempAvg"),
                        (CIRCUIT_BASS3, "HydraulicScheme"),
                        (CIRCUIT_BASS3, "Z1Timer_Slots"),
                        (CIRCUIT_BASS3, "HwcTimer_Slots"),
                    ]
                )
            )

        self.assertIn((CIRCUIT_BASS3, "Z1Timer_Monday"), requested)
        self.assertIn((CIRCUIT_BASS3, "Z1Timer_Monday_Slot2"), requested)
        self.assertIn((CIRCUIT_BASS3, "Z1Timer_Monday_Slot3"), requested)
        self.assertIn((CIRCUIT_BASS3, "Z1Timer_Tuesday"), requested)
        self.assertNotIn((CIRCUIT_BASS3, "Z1Timer_Tuesday_Slot2"), requested)
        self.assertNotIn((CIRCUIT_BASS3, "Z1Timer_Wednesday"), requested)
        self.assertIn((CIRCUIT_BASS3, "HwcTimer_Monday"), requested)
        self.assertIn((CIRCUIT_BASS3, "HwcTimer_Monday_Slot2"), requested)
        self.assertNotIn((CIRCUIT_BASS3, "HwcTimer_Monday_Slot3"), requested)

    def test_tiered_fast_and_hourly_slow_fallback_polling(self) -> None:
        """Fast fallback polls live telemetry only; hourly slow fallback polls config, stats, and timers."""
        hass = MagicMock()
        hass.async_create_background_task.side_effect = lambda coro, name=None: (
            coro.close()
        )
        entry = MagicMock()
        entry.entry_id = "test_tiered_fallback"
        entry.data = {CONF_HAS_MIGO_LINK: False}
        entry.options = {}

        coord = SaunierGeniaCoordinator(hass, entry)
        coord._active_outdoor_circuit = CIRCUIT_HMUX0
        coord._state[(CIRCUIT_BASS3, "CoolingTimer_Slots")] = {
            "mon": 2,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 0,
        }

        # Fast cycle: operational & thermodynamic telemetry, no static config / legacy probes / RunStats
        with patch.object(
            coord, "_async_force_poll_queue", return_value=None
        ) as mock_fast:
            asyncio.run(coord._async_run_fallback_poll(datetime.now()))
            fast_queue = mock_fast.call_args[0][0]
            self.assertIn((CIRCUIT_BASS3, "OutsideTempAvg"), fast_queue)
            self.assertIn((CIRCUIT_HMUX0, "RunDataSuperheat"), fast_queue)
            self.assertIn((CIRCUIT_HMUX0, "PrEnergyEnvYieldCool"), fast_queue)
            self.assertNotIn((CIRCUIT_BASS3, "Hc1HeatCurve"), fast_queue)
            self.assertNotIn((CIRCUIT_BASS3, "Z1HolidayTemp"), fast_queue)
            self.assertNotIn((CIRCUIT_BASS3, "Z1DayTemp"), fast_queue)
            self.assertNotIn((CIRCUIT_BASS3, "PrEnergySumHcThisMonth"), fast_queue)
            self.assertNotIn((CIRCUIT_HMUX0, "RunStatsHMUHours"), fast_queue)

        # Hourly slow cycle (HMUX0): installation settings, monthly sums, RunStats, vwzio stats, active timers
        with patch.object(
            coord, "_async_force_poll_queue", return_value=None
        ) as mock_slow:
            asyncio.run(coord._async_run_fallback_slow_poll(datetime.now()))
            slow_queue = mock_slow.call_args[0][0]
            self.assertTrue(mock_slow.call_args[1].get("expand_timer_slots"))
            self.assertIn((CIRCUIT_BASS3, "Hc1HeatCurve"), slow_queue)
            self.assertIn((CIRCUIT_BASS3, "DewPointMonitoring"), slow_queue)
            self.assertIn((CIRCUIT_BASS3, "HydraulicScheme"), slow_queue)
            self.assertIn((CIRCUIT_BASS3, "Z1Timer_Slots"), slow_queue)
            self.assertIn((CIRCUIT_BASS3, "CoolingTimer_Monday"), slow_queue)
            self.assertIn((CIRCUIT_BASS3, "CoolingTimer_Monday_Slot2"), slow_queue)
            self.assertNotIn((CIRCUIT_BASS3, "CoolingTimer_Monday_Slot3"), slow_queue)
            self.assertIn((CIRCUIT_HMUX0, "RunStatsHMUHours"), slow_queue)
            self.assertIn((CIRCUIT_HMUX0, "RunStatsCompressorCool"), slow_queue)
            self.assertIn((CIRCUIT_VWZIO, "RunStatsHeaterEnergy"), slow_queue)
            self.assertNotIn((CIRCUIT_BASS3, "Z1HolidayTemp"), slow_queue)

        # HMU SW < 902 skips CompressorHc/Hwc/Cool in slow poll
        coord._active_outdoor_circuit = CIRCUIT_HMU
        coord._record_detected_outdoor_sw("0804")
        with patch.object(
            coord, "_async_force_poll_queue", return_value=None
        ) as mock_slow_hmu:
            asyncio.run(coord._async_run_fallback_slow_poll(datetime.now()))
            slow_hmu_queue = mock_slow_hmu.call_args[0][0]
            self.assertIn((CIRCUIT_HMU, "CompressorHours"), slow_hmu_queue)
            self.assertNotIn((CIRCUIT_HMU, "CompressorHc"), slow_hmu_queue)
            self.assertNotIn((CIRCUIT_HMUX0, "RunStatsCompressorCool"), slow_hmu_queue)

        # Skips cleanly when MiGo Link is enabled
        entry.data = {CONF_HAS_MIGO_LINK: True}
        with patch.object(
            coord, "_async_force_poll_queue", return_value=None
        ) as mock_migo:
            asyncio.run(coord._async_run_fallback_slow_poll(datetime.now()))
            mock_migo.assert_not_called()

    def test_external_heating_veto_prefers_hardware_end_time(self) -> None:
        """External veto tracking and passive Z1QuickVetoEndTime updates prefer hardware end time over 3h guess."""
        from homeassistant.util import dt as dt_util

        hass = MagicMock()
        hass.async_create_task = lambda coro: coro.close()
        entry = MagicMock()
        entry.entry_id = "test_hw_veto_sync"
        entry.data = {}
        entry.options = {}
        coord = SaunierGeniaCoordinator(hass, entry)

        tz = dt_util.get_default_time_zone()
        hw_30m = datetime.now(tz=tz) + timedelta(minutes=30)
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoDuration")] = {"value": 3.0}
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoEndDate")] = {
            "value": hw_30m.strftime("%d.%m.%Y")
        }
        coord._state[(CIRCUIT_BASS3, "Z1QuickVetoEndTime")] = {
            "value": hw_30m.strftime("%H:%M:%S")
        }
        coord._state[(CIRCUIT_BASS3, "Z1SFMode")] = {"value": "veto"}

        # 1. External tracking starts using hardware 30m end time instead of 3.0h (180m) default
        coord._async_start_external_heating_veto_tracking()
        rem = coord.get_quick_veto_remaining_minutes()
        self.assertIsNotNone(rem)
        assert rem is not None
        self.assertGreaterEqual(rem, 29)
        self.assertLessEqual(rem, 31)

        # 2. Passive Z1QuickVetoEndTime update (e.g. app changed veto to 90 min) re-syncs countdown
        hw_90m = datetime.now(tz=tz) + timedelta(minutes=90)
        msg_date = MagicMock()
        msg_date.topic = "ebusd/bass3/Z1QuickVetoEndDate"
        msg_date.payload = hw_90m.strftime("%d.%m.%Y")
        coord._async_on_mqtt_message(msg_date)

        msg_time = MagicMock()
        msg_time.topic = "ebusd/bass3/Z1QuickVetoEndTime"
        msg_time.payload = hw_90m.strftime("%H:%M:%S")
        coord._async_on_mqtt_message(msg_time)

        rem2 = coord.get_quick_veto_remaining_minutes()
        self.assertIsNotNone(rem2)
        assert rem2 is not None
        self.assertGreaterEqual(rem2, 89)
        self.assertLessEqual(rem2, 91)


if __name__ == "__main__":
    unittest.main()
