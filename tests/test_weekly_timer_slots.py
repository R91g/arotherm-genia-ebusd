"""Unit tests for multi-slot weekly timer safety logic and CSV coverage."""

import asyncio
import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.exceptions import HomeAssistantError

from custom_components.arotherm_genia_ebusd import (
    _async_register_services,
    _collect_upper_slots,
    _get_active_slot_count,
    _parse_hhmm,
    _time_to_minutes,
    _validate_daily_schedule,
    upper_slots_to_writes,
)
from custom_components.arotherm_genia_ebusd.const import (
    CIRCUIT_BASS3,
    DOMAIN,
    SERVICE_SET_WEEKLY_TIMER,
    TIMER_CIRCUIT_PREFIXES,
    WEEKDAYS_LIST,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator

CSV_DIR = Path(__file__).parent.parent / "ebusd-configuration" / "vaillant"
CONTROLLER_CSVS = ("15.bass3.csv", "15.basv3.csv", "15.ctlv2.csv", "15.ctlv3.csv")


class FakeCoordinator:
    """Minimal coordinator exposing get_message."""

    def __init__(self, messages: dict[str, dict]) -> None:
        self._messages = messages

    def get_message(self, circuit: str, message: str):
        return self._messages.get(message)


def _slot(fh: int, fm: int, th: int, tm: int) -> dict:
    return {"from_hour": fh, "from_min": fm, "to_hour": th, "to_min": tm}


class TestWeeklyTimerSlots(unittest.TestCase):
    """Verify cascade rewrite helpers and CSV slot definitions."""

    def test_active_slot_count(self) -> None:
        coord = FakeCoordinator({"Z1Timer_Slots": {"mon": 2, "tue": 9}})
        self.assertEqual(_get_active_slot_count(coord, "Z1Timer", "Monday"), 2)
        self.assertIsNone(_get_active_slot_count(coord, "Z1Timer", "Tuesday"))
        self.assertIsNone(_get_active_slot_count(coord, "Z1Timer", "Sunday"))

    def test_collect_upper_slots_restores_in_ascending_order(self) -> None:
        coord = FakeCoordinator(
            {
                "Z1Timer_Monday_Slot2": _slot(10, 0, 12, 30),
                "Z1Timer_Monday_Slot3": _slot(18, 15, 22, 0),
            }
        )
        upper = _collect_upper_slots(coord, "Z1Timer", "Monday", 1, 3)
        self.assertEqual([n for n, _ in upper], [2, 3])
        writes = upper_slots_to_writes("Z1Timer", "Monday", upper)
        self.assertEqual(
            writes,
            [
                ("Z1Timer_Monday_Slot2", "10;0;12;30"),
                ("Z1Timer_Monday_Slot3", "18;15;22;0"),
            ],
        )

    def test_no_upper_slots_when_writing_highest(self) -> None:
        coord = FakeCoordinator({})
        self.assertEqual(_collect_upper_slots(coord, "Z1Timer", "Monday", 3, 3), [])
        self.assertEqual(_collect_upper_slots(coord, "Z1Timer", "Monday", 1, None), [])

    def test_unknown_upper_slot_data_aborts(self) -> None:
        coord = FakeCoordinator({})
        with self.assertRaises(HomeAssistantError):
            _collect_upper_slots(coord, "Z1Timer", "Monday", 1, 2)

    def test_time_parsing_and_minutes_conversion(self) -> None:
        """Verify time parsing, midnight rules, and minutes conversion."""
        # Normal times
        self.assertEqual(_parse_hhmm("08:30"), (8, 30))
        self.assertEqual(_time_to_minutes(8, 30), 510)

        # Start 00:00 -> 0 minutes
        self.assertEqual(_parse_hhmm("00:00", is_end=False), (0, 0))
        self.assertEqual(_time_to_minutes(0, 0, is_end=False), 0)

        # End 00:00 (with start > 0) -> 1440 minutes (24:00)
        self.assertEqual(_parse_hhmm("00:00", is_end=True), (0, 0))
        self.assertEqual(_time_to_minutes(0, 0, is_end=True), 1440)

        # End 24:00 -> 1440 minutes
        self.assertEqual(_parse_hhmm("24:00", is_end=True), (24, 0))
        self.assertEqual(_time_to_minutes(24, 0, is_end=True), 1440)

        # Invalid start 24:00
        with self.assertRaises(HomeAssistantError):
            _parse_hhmm("24:00", is_end=False)

        # Invalid 24:01 or negative/unsupported
        with self.assertRaises(HomeAssistantError):
            _parse_hhmm("24:01", is_end=True)
        with self.assertRaises(HomeAssistantError):
            _parse_hhmm("abc", is_end=False)

    def test_validate_daily_schedule_overlaps_and_order(self) -> None:
        """Verify non-overlapping, chronological order, and contiguous slots."""
        # Case 1: Valid separate slots (8:00-14:30 and 16:00-17:15)
        coord = FakeCoordinator({"Z1Timer_Monday": _slot(8, 0, 14, 30)})
        _validate_daily_schedule(
            coordinator=coord,
            prefix="Z1Timer",
            day_name="Monday",
            slot=2,
            from_minutes=960,  # 16:00
            to_minutes=1035,  # 17:15
            start_time_str="16:00",
            end_time_str="17:15",
            active_count=1,
        )

        # Case 2: Valid contiguous slots (8:00-14:30 and 14:30-17:15)
        _validate_daily_schedule(
            coordinator=coord,
            prefix="Z1Timer",
            day_name="Monday",
            slot=2,
            from_minutes=870,  # 14:30
            to_minutes=1035,  # 17:15
            start_time_str="14:30",
            end_time_str="17:15",
            active_count=1,
        )

        # Case 3: Invalid overlap (Slot 2 starts at 13:30 while Slot 1 ends at 14:30)
        with self.assertRaises(HomeAssistantError) as ctx:
            _validate_daily_schedule(
                coordinator=coord,
                prefix="Z1Timer",
                day_name="Monday",
                slot=2,
                from_minutes=810,  # 13:30
                to_minutes=1035,  # 17:15
                start_time_str="13:30",
                end_time_str="17:15",
                active_count=1,
            )
        self.assertIn("overlaps with slot 1", str(ctx.exception))

        # Case 4: Reverse overlap (Editing Slot 1 to end at 16:30 when Slot 2 starts at 16:00)
        coord2 = FakeCoordinator({"Z1Timer_Monday_Slot2": _slot(16, 0, 17, 15)})
        with self.assertRaises(HomeAssistantError) as ctx:
            _validate_daily_schedule(
                coordinator=coord2,
                prefix="Z1Timer",
                day_name="Monday",
                slot=1,
                from_minutes=480,  # 08:00
                to_minutes=990,  # 16:30
                start_time_str="08:00",
                end_time_str="16:30",
                active_count=2,
            )
        self.assertIn("overlaps with slot 1", str(ctx.exception))

        # Case 5: Out of order slots (Writing Slot 2 earlier than Slot 1)
        coord3 = FakeCoordinator({"Z1Timer_Monday": _slot(16, 0, 18, 0)})
        with self.assertRaises(HomeAssistantError) as ctx:
            _validate_daily_schedule(
                coordinator=coord3,
                prefix="Z1Timer",
                day_name="Monday",
                slot=2,
                from_minutes=480,  # 08:00
                to_minutes=600,  # 10:00
                start_time_str="08:00",
                end_time_str="10:00",
                active_count=1,
            )
        self.assertIn("overlaps with slot 1", str(ctx.exception))

        # Case 6: Missing slot data in memory aborts safely
        coord_empty = FakeCoordinator({})
        with self.assertRaises(HomeAssistantError) as ctx:
            _validate_daily_schedule(
                coordinator=coord_empty,
                prefix="Z1Timer",
                day_name="Monday",
                slot=2,
                from_minutes=960,
                to_minutes=1035,
                start_time_str="16:00",
                end_time_str="17:15",
                active_count=1,
            )
        self.assertIn("data of slot 1 is unknown", str(ctx.exception))

    def test_service_rejects_unknown_counter_and_invalid_slot(self) -> None:
        """Verify service rejects execution when active_count is None or slot is disconnected."""
        hass = MagicMock()
        services: dict[str, Any] = {}
        hass.services.has_service.return_value = False
        hass.services.async_register.side_effect = lambda d, s, h, schema=None: (
            services.update({s: h})
        )

        coord = SaunierGeniaCoordinator(hass, MagicMock(data={"mqtt_prefix": "ebusd"}))
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}  # operational
        hass.data = {DOMAIN: {"entry_id": coord}}
        _async_register_services(hass)

        call = MagicMock()
        call.data = {
            "circuit_type": "heating",
            "day": "Monday",
            "slot": 1,
            "start_time": "08:00",
            "end_time": "14:30",
        }

        # 1. Unknown counter -> HomeAssistantError
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call))
        self.assertIn(
            "active slot count (Z1Timer_Slots) is not known yet", str(ctx.exception)
        )

        # 2. Counter is 1, but user tries to write slot 3 directly
        coord.async_set_optimistic_active_slots("Z1Timer", "Monday", 1)
        call.data["slot"] = 3
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call))
        self.assertIn(
            "only 1 slot(s) are currently active. Fill slot 2 first", str(ctx.exception)
        )

    def test_service_consecutive_writes_restores_slots_and_updates_optimistic_counter(
        self,
    ) -> None:
        """Verify that adding Slot 2 and then editing Slot 1 restores Slot 2 using optimistic counter."""
        hass = MagicMock()
        services: dict[str, Any] = {}
        hass.services.has_service.return_value = False
        hass.services.async_register.side_effect = lambda d, s, h, schema=None: (
            services.update({s: h})
        )

        entry = MagicMock(data={"mqtt_prefix": "ebusd"})
        coord = SaunierGeniaCoordinator(hass, entry)
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}  # operational

        # Seed initial state: Monday has 1 slot (08:00 to 14:30)
        coord.async_set_optimistic_active_slots("Z1Timer", "Monday", 1)
        coord._state[(CIRCUIT_BASS3, "Z1Timer_Monday")] = _slot(8, 0, 14, 30)

        written_params: list[tuple[str, str, str]] = []

        async def mock_write(circuit: str, message: str, payload: str) -> None:
            written_params.append((circuit, message, payload))
            # Simulate optimistic update
            coord._apply_optimistic_update(circuit, message, payload)

        coord.async_write_parameter = AsyncMock(side_effect=mock_write)
        hass.data = {DOMAIN: {"entry_id": coord}}
        _async_register_services(hass)

        # Call 1: Write Monday Slot 2 (16:00 to 17:15)
        call1 = MagicMock()
        call1.data = {
            "circuit_type": "heating",
            "day": "Monday",
            "slot": 2,
            "start_time": "16:00",
            "end_time": "17:15",
        }
        asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call1))

        # Check writes for Call 1: Slot 2 written
        self.assertEqual(len(written_params), 1)
        self.assertEqual(
            written_params[0], (CIRCUIT_BASS3, "Z1Timer_Monday_Slot2", "16;0;17;15")
        )
        # Check optimistic counter updated to 2
        self.assertEqual(_get_active_slot_count(coord, "Z1Timer", "Monday"), 2)

        # Call 2: Edit Monday Slot 1 (07:00 to 14:00)
        written_params.clear()
        call2 = MagicMock()
        call2.data = {
            "circuit_type": "heating",
            "day": "Monday",
            "slot": 1,
            "start_time": "07:00",
            "end_time": "14:00",
        }
        asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call2))

        # Check writes for Call 2: Slot 1 written AND Slot 2 restored!
        self.assertEqual(len(written_params), 2)
        self.assertEqual(
            written_params[0], (CIRCUIT_BASS3, "Z1Timer_Monday", "7;0;14;0")
        )
        self.assertEqual(
            written_params[1], (CIRCUIT_BASS3, "Z1Timer_Monday_Slot2", "16;0;17;15")
        )
        # Counter remains 2
        self.assertEqual(_get_active_slot_count(coord, "Z1Timer", "Monday"), 2)

    def test_service_multi_day_prevalidation_aborts_before_first_write(self) -> None:
        """Verify that in multi-day calls, an error on day 2 prevents writing day 1."""
        hass = MagicMock()
        services: dict[str, Any] = {}
        hass.services.has_service.return_value = False
        hass.services.async_register.side_effect = lambda d, s, h, schema=None: (
            services.update({s: h})
        )

        coord = SaunierGeniaCoordinator(hass, MagicMock(data={"mqtt_prefix": "ebusd"}))
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}  # operational
        # Monday is valid, but Tuesday has no slot count
        coord.async_set_optimistic_active_slots("Z1Timer", "Monday", 1)
        coord._state[(CIRCUIT_BASS3, "Z1Timer_Monday")] = _slot(8, 0, 14, 30)

        coord.async_write_parameter = AsyncMock()
        hass.data = {DOMAIN: {"entry_id": coord}}
        _async_register_services(hass)

        call = MagicMock()
        call.data = {
            "circuit_type": "heating",
            "day": "Weekdays",
            "slot": 1,
            "start_time": "08:00",
            "end_time": "14:00",
        }

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call))

        self.assertIn("Tuesday", str(ctx.exception))
        # Ensure zero writes were made!
        coord.async_write_parameter.assert_not_called()

    def test_service_mid_cascade_failure_invalidates_cache(self) -> None:
        """Verify that failure during writing upper slots invalidates day's cached count."""
        hass = MagicMock()
        services: dict[str, Any] = {}
        hass.services.has_service.return_value = False
        hass.services.async_register.side_effect = lambda d, s, h, schema=None: (
            services.update({s: h})
        )

        coord = SaunierGeniaCoordinator(hass, MagicMock(data={"mqtt_prefix": "ebusd"}))
        coord._state[("hmux0", "status01")] = {"temp1": 35.0}  # operational

        # Seed initial state: Monday has 2 slots
        coord.async_set_optimistic_active_slots("Z1Timer", "Monday", 2)
        coord._state[(CIRCUIT_BASS3, "Z1Timer_Monday")] = _slot(8, 0, 12, 0)
        coord._state[(CIRCUIT_BASS3, "Z1Timer_Monday_Slot2")] = _slot(14, 0, 18, 0)

        # First write succeeds, second write (restoration) fails
        write_count = 0

        async def fail_second_write(circuit: str, message: str, payload: str) -> None:
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                raise ConnectionError("Bus collision on restoration")

        coord.async_write_parameter = AsyncMock(side_effect=fail_second_write)
        hass.data = {DOMAIN: {"entry_id": coord}}
        _async_register_services(hass)

        call = MagicMock()
        call.data = {
            "circuit_type": "heating",
            "day": "Monday",
            "slot": 1,
            "start_time": "07:00",
            "end_time": "11:00",
        }

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(services[SERVICE_SET_WEEKLY_TIMER](call))

        self.assertIn(
            "Cached slot count has been invalidated for safety", str(ctx.exception)
        )
        # Verify that Monday's slot count was invalidated from coordinator state
        self.assertIsNone(_get_active_slot_count(coord, "Z1Timer", "Monday"))

    def test_csv_defines_all_slots(self) -> None:
        """Every circuit/day/slot must have a read and write message with right IDs."""
        for fname in CONTROLLER_CSVS:
            text = (CSV_DIR / fname).read_text(encoding="utf-8")
            for prefix in TIMER_CIRCUIT_PREFIXES.values():
                for day in WEEKDAYS_LIST:
                    for slot_num in (1, 2, 3):
                        suffix = "" if slot_num == 1 else f"_Slot{slot_num}"
                        name = f"{prefix}_{day}{suffix}"
                        pattern = rf"^([uw]),,,{re.escape(name)},.*$"
                        rows = re.findall(pattern, text, flags=re.MULTILINE)
                        self.assertEqual(
                            sorted(rows), ["u", "w"], f"{fname}: {name} incomplete"
                        )
                        w_row = re.search(
                            rf"^w,,,{re.escape(name)},[^,]*,,,b555,(a6ff[0-9a-f]+),",
                            text,
                            flags=re.MULTILINE,
                        )
                        assert w_row is not None
                        # last byte of the write ID equals slot number (total_slots)
                        self.assertTrue(
                            w_row.group(1).endswith(f"{slot_num:02d}"), name
                        )

    def test_controller_csvs_stay_identical(self) -> None:
        """Verify that all 4 controller CSV variants (BASS3, BASV3, CTLV2, CTLV3) stay byte-for-byte identical."""
        bass3_bytes = (CSV_DIR / "15.bass3.csv").read_bytes()
        for fname in ("15.basv3.csv", "15.ctlv2.csv", "15.ctlv3.csv"):
            self.assertEqual(
                (CSV_DIR / fname).read_bytes(),
                bass3_bytes,
                f"{fname} must be byte-for-byte identical to 15.bass3.csv",
            )

    def test_csv_defines_all_passive_migo_slots(self) -> None:
        """Verify all 21 passive MiGo Link schedule write definitions exist in all controller CSVs."""
        for fname in CONTROLLER_CSVS:
            text = (CSV_DIR / fname).read_text(encoding="utf-8")
            for day_idx, day in enumerate(WEEKDAYS_LIST):
                for slot_num in (1, 2, 3):
                    slot_idx = slot_num - 1
                    suffix = "" if slot_num == 1 else f"_Slot{slot_num}"
                    name = f"Z1Timer_{day}{suffix}_Passive"
                    expected_id = f"a60000{day_idx:02x}{slot_idx:02x}"
                    pattern = (
                        rf"^u,,,{re.escape(name)},[^,]*,,,b555,{expected_id},"
                        rf"total_slots,m,UCH,,,,from_hour,m,UCH,,,,from_min,m,UCH,,,,"
                        rf"to_hour,m,UCH,,,,to_min,m,UCH,,,,temp,m,UIN,10,°C,"
                    )
                    self.assertTrue(
                        bool(re.search(pattern, text, flags=re.MULTILINE)),
                        f"{fname}: missing or invalid definition for {name} with ID {expected_id}",
                    )

    def test_migolink_captured_schedule_telegrams(self) -> None:
        """Verify regression matching and coordinator handling for the 4 MiGo Link captured telegrams.

        Empirical hardware captures from live bus (MiGo Link f1 -> 15 controller):
        1. Thursday Slot 1: f115b5550ca60000 03 00 01 0000 1600 c800 / 0100 (00:00 - 22:00, Total 1, 20.0 °C)
        2. Friday Slot 1:   f115b5550ca60000 04 00 02 0600 1600 c800 / 0100 (06:00 - 22:00, Total 2, 20.0 °C)
        3. Friday Slot 2:   f115b5550ca60000 04 01 02 1700 1800 c800 / 0100 (23:00 - 24:00, Total 2, 20.0 °C)
        4. Saturday Slot 1: f115b5550ca60000 05 00 01 0000 1800 c800 / 0100 (00:00 - 24:00, Total 1, 20.0 °C)
        """
        captured_frames = [
            {
                "raw": "f115b5550ca6000003000100001600c800",
                "passive_msg": "Z1Timer_Thursday_Passive",
                "canonical_msg": "Z1Timer_Thursday",
                "day_name": "Thursday",
                "expected": {
                    "total_slots": 1,
                    "from_hour": 0,
                    "from_min": 0,
                    "to_hour": 22,
                    "to_min": 0,
                    "temp": 20.0,
                },
                "expected_active_slots": 1,
            },
            {
                "raw": "f115b5550ca6000004000206001600c800",
                "passive_msg": "Z1Timer_Friday_Passive",
                "canonical_msg": "Z1Timer_Friday",
                "day_name": "Friday",
                "expected": {
                    "total_slots": 2,
                    "from_hour": 6,
                    "from_min": 0,
                    "to_hour": 22,
                    "to_min": 0,
                    "temp": 20.0,
                },
                "expected_active_slots": 2,
            },
            {
                "raw": "f115b5550ca6000004010217001800c800",
                "passive_msg": "Z1Timer_Friday_Slot2_Passive",
                "canonical_msg": "Z1Timer_Friday_Slot2",
                "day_name": "Friday",
                "expected": {
                    "total_slots": 2,
                    "from_hour": 23,
                    "from_min": 0,
                    "to_hour": 24,
                    "to_min": 0,
                    "temp": 20.0,
                },
                "expected_active_slots": 2,
            },
            {
                "raw": "f115b5550ca6000005000100001800c800",
                "passive_msg": "Z1Timer_Saturday_Passive",
                "canonical_msg": "Z1Timer_Saturday",
                "day_name": "Saturday",
                "expected": {
                    "total_slots": 1,
                    "from_hour": 0,
                    "from_min": 0,
                    "to_hour": 24,
                    "to_min": 0,
                    "temp": 20.0,
                },
                "expected_active_slots": 1,
            },
        ]

        # 1. Verify byte extraction against the 4 captured frames
        for frame in captured_frames:
            raw_hex = frame["raw"]
            data_bytes = bytes.fromhex(raw_hex)
            # Prefix: QQ(f1), ZZ(15), PB(b5), SB(55), NN(0c)
            self.assertEqual(data_bytes[:5], bytes.fromhex("f115b5550c"))
            # Command ID: a6 00 00 [day] [slot]
            cmd_id = data_bytes[5:10].hex()
            self.assertTrue(cmd_id.startswith("a60000"))
            # Master data fields
            total_slots = data_bytes[10]
            from_hour = data_bytes[11]
            from_min = data_bytes[12]
            to_hour = data_bytes[13]
            to_min = data_bytes[14]
            temp_raw = int.from_bytes(data_bytes[15:17], "little")
            temp = temp_raw / 10.0

            exp = frame["expected"]
            self.assertEqual(total_slots, exp["total_slots"])
            self.assertEqual(from_hour, exp["from_hour"])
            self.assertEqual(from_min, exp["from_min"])
            self.assertEqual(to_hour, exp["to_hour"])
            self.assertEqual(to_min, exp["to_min"])
            self.assertEqual(temp, exp["temp"])

        # 2. Verify coordinator handling via _async_on_mqtt_message
        hass = MagicMock()
        coord = SaunierGeniaCoordinator(hass, MagicMock(data={"mqtt_prefix": "ebusd"}))

        # Deliver each frame via MQTT to coordinator as ebusd would publish it
        for frame in captured_frames:
            passive_msg = frame["passive_msg"]
            exp = frame["expected"]
            # ebusd publishes JSON payload when decoding the telegram
            mqtt_payload = json.dumps(
                {
                    "total_slots": {"value": exp["total_slots"]},
                    "from_hour": {"value": exp["from_hour"]},
                    "from_min": {"value": exp["from_min"]},
                    "to_hour": {"value": exp["to_hour"]},
                    "to_min": {"value": exp["to_min"]},
                    "temp": {"value": exp["temp"]},
                }
            )
            msg = MagicMock()
            msg.topic = f"ebusd/bass3/{passive_msg}"
            msg.payload = mqtt_payload
            coord._async_on_mqtt_message(msg)

            canonical_msg = frame["canonical_msg"]
            # State must be mapped to the canonical timer message
            state_val = coord.get_message(CIRCUIT_BASS3, canonical_msg)
            self.assertIsNotNone(state_val)
            self.assertEqual(state_val["from_hour"], exp["from_hour"])
            self.assertEqual(state_val["to_hour"], exp["to_hour"])

            # Active slots must be updated immediately in Z1Timer_Slots
            active_slots = _get_active_slot_count(coord, "Z1Timer", frame["day_name"])
            self.assertEqual(active_slots, frame["expected_active_slots"])


if __name__ == "__main__":
    unittest.main()
