"""Unit tests for DateTime platform, Holiday Mode switch, and Cooling Period logic."""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.datetime import (
    SaunierGeniaCoolingEndDateTime,
    SaunierGeniaCoolingStartDateTime,
    SaunierGeniaHolidayEndDateTime,
    SaunierGeniaHolidayStartDateTime,
)
from custom_components.arotherm_genia_ebusd.switch import (
    SaunierGeniaCoolingSeasonSwitch,
    SaunierGeniaHolidayModeSwitch,
)


class MockCoordinatorForDatetime:
    """Mock coordinator for DateTime and Switch tests."""

    def __init__(self) -> None:
        self.entry = MagicMock(entry_id="test_entry_id", options={})
        self._state: dict = {}
        self.writes: list[tuple[str, str, Any]] = []
        self._custom_cooling_start_date: str | None = None
        self._custom_cooling_end_date: str | None = None
        self._preselected_holiday_start_datetime: datetime | None = None
        self._preselected_holiday_end_datetime: datetime | None = None
        self.auto_cooling_lock_bypass = True
        self.manufacturer = "Saunier Duval"
        self.outdoor_model = "GeniaAir Max ES 15"
        self.indoor_model = "HPIM 7 230V"
        self.has_wireless_room_unit = True

    def get_message(self, circuit: str, message: str) -> dict | None:
        return self._state.get((circuit.lower(), message.lower()))

    def get_str(self, circuit: str, message: str, field: str = "value") -> str | None:
        msg = self.get_message(circuit, message)
        return str(msg.get(field)) if msg and field in msg else None

    def get_int(self, circuit: str, message: str, field: str = "value") -> int | None:
        msg = self.get_message(circuit, message)
        try:
            return int(msg.get(field)) if msg and field in msg else None
        except (ValueError, TypeError):
            return None

    def get_float(
        self, circuit: str, message: str, field: str = "value"
    ) -> float | None:
        msg = self.get_message(circuit, message)
        try:
            return float(msg.get(field)) if msg and field in msg else None
        except (ValueError, TypeError):
            return None

    async def async_write_parameter(
        self, circuit: str, message: str, value: Any
    ) -> None:
        self.writes.append((circuit, message, value))

    @property
    def custom_cooling_start_date(self) -> str | None:
        return self._custom_cooling_start_date

    def set_custom_cooling_start_date(self, val: str | None) -> None:
        self._custom_cooling_start_date = val

    @property
    def custom_cooling_end_date(self) -> str | None:
        return self._custom_cooling_end_date

    def set_custom_cooling_end_date(self, val: str | None) -> None:
        self._custom_cooling_end_date = val

    @property
    def preselected_holiday_start_datetime(self) -> datetime | None:
        return self._preselected_holiday_start_datetime

    @preselected_holiday_start_datetime.setter
    def preselected_holiday_start_datetime(self, val: datetime | None) -> None:
        self._preselected_holiday_start_datetime = val

    @property
    def preselected_holiday_end_datetime(self) -> datetime | None:
        return self._preselected_holiday_end_datetime

    @preselected_holiday_end_datetime.setter
    def preselected_holiday_end_datetime(self, val: datetime | None) -> None:
        self._preselected_holiday_end_datetime = val

    def get_holiday_remaining_days(self) -> int:
        return 5

    def get_cooling_remaining_days(self) -> int | None:
        return 10

    async def async_activate_holiday_mode(self, **kwargs: Any) -> None:
        self.writes.append(("bass3", "HolidayModeActivated", True))

    async def async_cancel_holiday_mode(self) -> None:
        self.writes.append(("bass3", "HolidayModeCancelled", True))


class TestDateTimeAndSwitches(unittest.TestCase):
    """Test suite for DateTime platform, Holiday Mode switch, and Cooling Period."""

    def setUp(self) -> None:
        self.coord = MockCoordinatorForDatetime()

    def test_holiday_start_datetime_read_and_write(self) -> None:
        """Test Holiday Start DateTime reads bus data and writes DD;MM;YY + HH;MM;SS."""
        entity = SaunierGeniaHolidayStartDateTime(self.coord)

        # 1. When bus has reset sentinel (year=15), returns None (or buffer)
        self.coord._state[("bass3", "holidaystartdate")] = {
            "day": 1,
            "month": 1,
            "year": 15,
        }
        self.coord._state[("bass3", "holidaystarttime")] = {
            "hours": 0,
            "minutes": 0,
            "seconds": 0,
        }
        self.assertIsNone(entity.native_value)

        # 2. When bus has active holiday start date (e.g. 30/10/26 10:33:38)
        self.coord._state[("bass3", "holidaystartdate")] = {
            "day": 30,
            "month": 10,
            "year": 26,
        }
        self.coord._state[("bass3", "holidaystarttime")] = {
            "hours": 10,
            "minutes": 33,
            "seconds": 38,
        }
        val = entity.native_value
        self.assertIsNotNone(val)
        self.assertEqual(val.year, 2026)
        self.assertEqual(val.month, 10)
        self.assertEqual(val.day, 30)
        self.assertEqual(val.hour, 10)
        self.assertEqual(val.minute, 33)

        # 3. Setting value writes both date and time to ebusd
        with patch("asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(entity.async_set_value(datetime(2026, 11, 5, 14, 30, 0)))

        self.assertIn(("bass3", "HolidayStartDate", "05;11;26"), self.coord.writes)
        self.assertIn(("bass3", "HolidayStartTime", "14;30;00"), self.coord.writes)

    def test_holiday_end_datetime_read_and_write(self) -> None:
        """Test Holiday End DateTime reads bus data and writes correctly."""
        entity = SaunierGeniaHolidayEndDateTime(self.coord)

        self.coord._state[("bass3", "holidayenddate")] = {
            "day": 10,
            "month": 11,
            "year": 26,
        }
        self.coord._state[("bass3", "holidayendtime")] = {
            "hours": 18,
            "minutes": 45,
            "seconds": 0,
        }
        val = entity.native_value
        self.assertIsNotNone(val)
        self.assertEqual(val.year, 2026)
        self.assertEqual(val.day, 10)
        self.assertEqual(val.hour, 18)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(entity.async_set_value(datetime(2026, 12, 1, 23, 59, 0)))

        self.assertIn(("bass3", "HolidayEndDate", "01;12;26"), self.coord.writes)
        self.assertIn(("bass3", "HolidayEndTime", "23;59;00"), self.coord.writes)

    def test_cooling_datetimes_read_and_write(self) -> None:
        """Test Cooling Start and End DateTime entities."""
        start_entity = SaunierGeniaCoolingStartDateTime(self.coord)
        end_entity = SaunierGeniaCoolingEndDateTime(self.coord)

        # Closed epoch 2019
        self.coord._state[("bass3", "coolingstartdate")] = {
            "day": 1,
            "month": 1,
            "year": 19,
        }
        self.coord._state[("bass3", "coolingenddate")] = {
            "day": 1,
            "month": 1,
            "year": 19,
        }
        self.assertEqual(start_entity.native_value.year, 2019)
        self.assertEqual(end_entity.native_value.year, 2019)

        # Write custom dates
        asyncio.run(start_entity.async_set_value(datetime(2026, 6, 15, 0, 0, 0)))
        asyncio.run(end_entity.async_set_value(datetime(2026, 8, 31, 0, 0, 0)))

        self.assertIn(("bass3", "CoolingStartDate", "15;06;26"), self.coord.writes)
        self.assertIn(("bass3", "CoolingEndDate", "31;08;26"), self.coord.writes)
        self.assertEqual(self.coord.custom_cooling_start_date, "15;06;26")
        self.assertEqual(self.coord.custom_cooling_end_date, "31;08;26")

    def test_holiday_mode_switch(self) -> None:
        """Test Holiday Mode switch activation, cancellation, and attributes."""
        sw = SaunierGeniaHolidayModeSwitch(self.coord)

        # Initially off
        self.coord._state[("bass3", "z1status")] = {"value": "auto"}
        self.coord._state[("bass3", "hwcstatus")] = {"value": "auto"}
        self.assertFalse(sw.is_on)

        # Turns on when controller reports holidayaway
        self.coord._state[("bass3", "z1status")] = {"value": "holidayaway"}
        self.assertTrue(sw.is_on)
        attrs = sw.extra_state_attributes
        self.assertTrue(attrs["holiday_ongoing"])
        self.assertEqual(attrs["holiday_remaining_days"], 5)

        # Switching turn_on activates holiday mode
        asyncio.run(sw.async_turn_on())
        self.assertIn(("bass3", "HolidayModeActivated", True), self.coord.writes)

        # Switching turn_off cancels holiday mode
        asyncio.run(sw.async_turn_off())
        self.assertIn(("bass3", "HolidayModeCancelled", True), self.coord.writes)

    def test_cooling_switch_custom_dates_vs_indefinite(self) -> None:
        """Test Cooling Season switch uses custom dates when pre-set, or 01;01;26/99 by default."""
        sw = SaunierGeniaCoolingSeasonSwitch(self.coord)

        # 1. Default (no custom dates set): opens indefinitely (01;01;26 to 01;01;99)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(sw.async_turn_on())
        self.assertIn(("bass3", "CoolingStartDate", "01;01;26"), self.coord.writes)
        self.assertIn(("bass3", "CoolingEndDate", "01;01;99"), self.coord.writes)

        # 2. When user pre-set custom dates
        self.coord.writes.clear()
        self.coord.set_custom_cooling_start_date("01;07;26")
        self.coord.set_custom_cooling_end_date("15;08;26")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(sw.async_turn_on())
        self.assertIn(("bass3", "CoolingStartDate", "01;07;26"), self.coord.writes)
        self.assertIn(("bass3", "CoolingEndDate", "15;08;26"), self.coord.writes)

    def test_sensor_dynamic_unit_of_measurement(self) -> None:
        """Test that sensor suppresses unit of measurement for string states (Inactivo, Final abierto)."""
        from custom_components.arotherm_genia_ebusd.sensor import SaunierGeniaSensor
        from custom_components.arotherm_genia_ebusd.sensor_descriptions import (
            SENSOR_DESCRIPTIONS,
        )

        desc = next(
            d for d in SENSOR_DESCRIPTIONS if d.key == "holiday_duration_remaining"
        )
        sensor = SaunierGeniaSensor(self.coord, desc)

        # 1. When coordinator returns int (e.g. 5 days remaining)
        self.coord.get_holiday_remaining_days = lambda: 5
        self.assertEqual(sensor.native_value, 5)
        self.assertEqual(sensor.native_unit_of_measurement, "d")

        # 2. When coordinator returns 'Inactivo'
        self.coord.get_holiday_remaining_days = lambda: "Inactivo"
        self.assertEqual(sensor.native_value, "Inactivo")
        self.assertIsNone(sensor.native_unit_of_measurement)

        # 3. When coordinator returns 'Final abierto'
        self.coord.get_holiday_remaining_days = lambda: "Final abierto"
        self.assertEqual(sensor.native_value, "Final abierto")
        self.assertIsNone(sensor.native_unit_of_measurement)


if __name__ == "__main__":
    unittest.main()
