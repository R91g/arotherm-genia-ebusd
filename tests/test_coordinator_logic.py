"""Unit tests for coordinator payload parsing and optimistic update mapping."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure tests/ directory is on path to load setup_mocks
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hacs")))

import unittest

from custom_components.arotherm_genia_ebusd.coordinator import (
    SaunierGeniaCoordinator,
    parse_ebusd_payload,
    _coerce_scalar,
    _multi_field_layout,
    DATE_WRITE_FIELDS,
    TIMER_WRITE_FIELDS,
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
        payload_multi = '{"day": {"value": 15}, "month": {"value": 6}, "year": {"value": 24}}'
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

        # Timers
        self.assertEqual(_multi_field_layout("Z1Timer_Monday", {}), TIMER_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("HwcTimer_Sunday_Slot2", {}), TIMER_WRITE_FIELDS)
        self.assertEqual(_multi_field_layout("CoolingTimer_Friday_Slot3", {}), TIMER_WRITE_FIELDS)

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
        self.assertEqual(coord._state[("bass3", "CoolingEndDate")], {"day": 1, "month": 1, "year": 99})

        # 2. Date without previous state
        coord._apply_optimistic_update("bass3", "CoolingStartDate", "15;06;24")
        self.assertEqual(coord._state[("bass3", "CoolingStartDate")], {"day": 15, "month": 6, "year": 24})

        # 3. Weekly timer preserving read-only fields (e.g. cooling_temp)
        coord._state[("bass3", "Z1Timer_Monday")] = {
            "from_hour": 6, "from_min": 0, "to_hour": 22, "to_min": 0, "temp": 21.0
        }
        coord._apply_optimistic_update("bass3", "Z1Timer_Monday", "08;30;20;15")
        self.assertEqual(
            coord._state[("bass3", "Z1Timer_Monday")],
            {"from_hour": 8, "from_min": 30, "to_hour": 20, "to_min": 15, "temp": 21.0}
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


if __name__ == "__main__":
    unittest.main()
