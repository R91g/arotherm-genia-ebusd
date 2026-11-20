"""Unit tests for the weekly schedule calendar platform and options toggle."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.arotherm_genia_ebusd import (
    _async_sync_schedule_calendar_entities,
)
from custom_components.arotherm_genia_ebusd.calendar import (
    SCHEDULE_CALENDARS,
    SaunierGeniaScheduleCalendar,
    async_setup_entry,
)
from custom_components.arotherm_genia_ebusd.const import (
    CIRCUIT_BASS3,
    CONF_ENABLE_SCHEDULE_CALENDARS,
    DOMAIN,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator


class TestCalendarPlatform(unittest.IsolatedAsyncioTestCase):
    """Test read-only weekly schedule calendars and enable/disable options sync."""

    def setUp(self) -> None:
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "entry_cal_1"
        self.entry.data = {}
        self.entry.options = {}
        self.coordinator = SaunierGeniaCoordinator(self.hass, self.entry)
        self.hass.data = {DOMAIN: {self.entry.entry_id: self.coordinator}}

    async def test_setup_registers_five_calendars_with_expected_defaults(self) -> None:
        """Heating, DHW, and Cooling enabled by default; Circulation and Silent hidden."""
        added: list[SaunierGeniaScheduleCalendar] = []
        await async_setup_entry(self.hass, self.entry, added.extend)

        self.assertEqual(len(added), 5)
        enabled_map = {
            e._spec.translation_key: e._attr_entity_registry_enabled_default
            for e in added
        }
        self.assertEqual(
            enabled_map,
            {
                "z1_schedule_calendar": True,
                "hwc_schedule_calendar": True,
                "cooling_schedule_calendar": True,
                "circulation_schedule_calendar": False,
                "silent_mode_schedule_calendar": False,
            },
        )

    async def test_setup_respects_enable_schedule_calendars_false(self) -> None:
        """When enable_schedule_calendars is False, all 5 calendars default to disabled."""
        self.entry.options = {CONF_ENABLE_SCHEDULE_CALENDARS: False}
        added: list[SaunierGeniaScheduleCalendar] = []
        await async_setup_entry(self.hass, self.entry, added.extend)

        self.assertEqual(len(added), 5)
        for ent in added:
            self.assertFalse(ent._attr_entity_registry_enabled_default)

    async def test_get_events_projects_slots_midnight_and_temperature(self) -> None:
        """Verify multi-slot days, 24:00 boundary, zero-slot days, and cooling temp label."""
        tz = dt_util.get_default_time_zone()
        # Monday = 2026-11-16, Tuesday = 2026-11-17, Wednesday = 2026-11-18
        self.coordinator._state[(CIRCUIT_BASS3, "Z1Timer_Slots")] = {
            "mon": 2,
            "tue": 0,
            "wed": 1,
        }
        self.coordinator._state[(CIRCUIT_BASS3, "Z1Timer_Monday")] = {
            "from_hour": 7,
            "from_min": 0,
            "to_hour": 9,
            "to_min": 30,
        }
        self.coordinator._state[(CIRCUIT_BASS3, "Z1Timer_Monday_Slot2")] = {
            "from_hour": 18,
            "from_min": 0,
            "to_hour": 24,
            "to_min": 0,
        }
        # Tuesday has slot data in cache, but active count is 0 -> must produce no events
        self.coordinator._state[(CIRCUIT_BASS3, "Z1Timer_Tuesday")] = {
            "from_hour": 8,
            "from_min": 0,
            "to_hour": 10,
            "to_min": 0,
        }
        # Wednesday has empty 00:00 - 00:00 slot -> ignored
        self.coordinator._state[(CIRCUIT_BASS3, "Z1Timer_Wednesday")] = {
            "from_hour": 0,
            "from_min": 0,
            "to_hour": 0,
            "to_min": 0,
        }

        z1_spec = SCHEDULE_CALENDARS[0]
        cal = SaunierGeniaScheduleCalendar(
            self.coordinator, z1_spec, enabled_default=True
        )

        start = datetime(2026, 11, 16, 0, 0, tzinfo=tz)
        end = datetime(2026, 11, 19, 0, 0, tzinfo=tz)
        events = await cal.async_get_events(self.hass, start, end)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].start, datetime(2026, 11, 16, 7, 0, tzinfo=tz))
        self.assertEqual(events[0].end, datetime(2026, 11, 16, 9, 30, tzinfo=tz))
        self.assertEqual(events[0].summary, "Zone 1 Heating")
        self.assertEqual(events[1].start, datetime(2026, 11, 16, 18, 0, tzinfo=tz))
        self.assertEqual(events[1].end, datetime(2026, 11, 17, 0, 0, tzinfo=tz))

        # Cooling timer with slot temperature appends '(24.0 °C)' to summary
        self.coordinator._state[(CIRCUIT_BASS3, "CoolingTimer_Slots")] = {"mon": 1}
        self.coordinator._state[(CIRCUIT_BASS3, "CoolingTimer_Monday")] = {
            "from_hour": 13,
            "from_min": 0,
            "to_hour": 19,
            "to_min": 0,
            "cooling_temp": 24.0,
        }
        cool_cal = SaunierGeniaScheduleCalendar(
            self.coordinator, SCHEDULE_CALENDARS[2], enabled_default=True
        )
        cool_events = await cool_cal.async_get_events(self.hass, start, end)
        self.assertEqual(len(cool_events), 1)
        self.assertEqual(cool_events[0].summary, "Zone 1 Cooling (24.0 °C)")

    def test_event_property_returns_active_or_next_event(self) -> None:
        """event property returns the currently running slot or upcoming slot."""
        tz = dt_util.get_default_time_zone()
        fixed_now = datetime(2026, 11, 16, 8, 15, tzinfo=tz)  # Monday 08:15

        self.coordinator._state[(CIRCUIT_BASS3, "HwcTimer_Slots")] = {"mon": 1}
        self.coordinator._state[(CIRCUIT_BASS3, "HwcTimer_Monday")] = {
            "from_hour": 7,
            "from_min": 0,
            "to_hour": 9,
            "to_min": 0,
        }
        cal = SaunierGeniaScheduleCalendar(
            self.coordinator, SCHEDULE_CALENDARS[1], enabled_default=True
        )

        with patch.object(dt_util, "now", return_value=fixed_now):
            ev = cal.event
            self.assertIsNotNone(ev)
            assert ev is not None
            self.assertEqual(ev.start, datetime(2026, 11, 16, 7, 0, tzinfo=tz))
            self.assertEqual(ev.end, datetime(2026, 11, 16, 9, 0, tzinfo=tz))

        # After Monday's slot ends, next event is next Monday
        later_now = fixed_now + timedelta(hours=2)  # Monday 10:15
        with patch.object(dt_util, "now", return_value=later_now):
            next_ev = cal.event
            self.assertIsNotNone(next_ev)
            assert next_ev is not None
            self.assertEqual(next_ev.start, datetime(2026, 11, 23, 7, 0, tzinfo=tz))

    def test_sync_schedule_calendar_entities_toggles_registry(self) -> None:
        """Toggling enable_schedule_calendars disables all and re-enables only default 3."""
        ent_reg = MagicMock()
        mock_entries: list[Any] = []
        for sfx, disabled in (
            ("entry_cal_1_calendar_z1timer", False),
            ("entry_cal_1_calendar_hwctimer", False),
            ("entry_cal_1_calendar_coolingtimer", False),
            ("entry_cal_1_calendar_circulationtimer", True),
            ("entry_cal_1_calendar_silenttimer", True),
        ):
            reg = MagicMock()
            reg.unique_id = sfx
            reg.entity_id = f"calendar.{sfx}"
            reg.disabled = disabled
            reg.disabled_by = er.RegistryEntryDisabler.INTEGRATION if disabled else None
            mock_entries.append(reg)

        with (
            patch.object(er, "async_get", return_value=ent_reg),
            patch.object(
                er, "async_entries_for_config_entry", return_value=mock_entries
            ),
        ):
            # 1. Disable calendars option -> disables the 3 active ones
            self.entry.options = {CONF_ENABLE_SCHEDULE_CALENDARS: False}
            changed = _async_sync_schedule_calendar_entities(
                self.hass, self.entry, reload_on_change=False
            )
            self.assertTrue(changed)
            self.assertEqual(ent_reg.async_update_entity.call_count, 3)

            # Simulate all 5 now disabled by integration
            for reg in mock_entries:
                reg.disabled = True
                reg.disabled_by = er.RegistryEntryDisabler.INTEGRATION
            ent_reg.async_update_entity.reset_mock()

            # 2. Re-enable calendars option -> only default 3 re-enabled; hidden 2 stay disabled
            self.entry.options = {CONF_ENABLE_SCHEDULE_CALENDARS: True}
            changed_back = _async_sync_schedule_calendar_entities(
                self.hass, self.entry, reload_on_change=False
            )
            self.assertTrue(changed_back)
            re_enabled_ids = [
                call.args[0] for call in ent_reg.async_update_entity.call_args_list
            ]
            self.assertEqual(
                set(re_enabled_ids),
                {
                    "calendar.entry_cal_1_calendar_z1timer",
                    "calendar.entry_cal_1_calendar_hwctimer",
                    "calendar.entry_cal_1_calendar_coolingtimer",
                },
            )


if __name__ == "__main__":
    unittest.main()
