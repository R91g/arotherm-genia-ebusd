"""Unit tests for multi-slot weekly timer safety logic and CSV coverage."""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd import (
    _collect_upper_slots,
    _get_active_slot_count,
    upper_slots_to_writes,
)
from custom_components.arotherm_genia_ebusd.const import (
    TIMER_CIRCUIT_PREFIXES,
    WEEKDAYS_LIST,
)

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
        import custom_components.arotherm_genia_ebusd as integration

        class FakeError(Exception):
            """Stand-in for HomeAssistantError (mocked in tests)."""

        coord = FakeCoordinator({})
        with (
            patch.object(integration, "HomeAssistantError", FakeError),
            self.assertRaises(FakeError),
        ):
            _collect_upper_slots(coord, "Z1Timer", "Monday", 1, 2)

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

    def test_bass3_basv3_stay_identical(self) -> None:
        self.assertEqual(
            (CSV_DIR / "15.bass3.csv").read_bytes(),
            (CSV_DIR / "15.basv3.csv").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
