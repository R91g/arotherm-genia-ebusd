"""Unit tests for read_time_program and write_time_program services."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.arotherm_genia_ebusd import (
    _async_register_services,
    async_unload_entry,
    time_programs,
)
from custom_components.arotherm_genia_ebusd.const import (
    CIRCUIT_BASS3,
    CIRCUIT_GLOBAL,
    DOMAIN,
    SERVICE_READ_TIME_PROGRAM,
    SERVICE_WRITE_TIME_PROGRAM,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator


def _make_mqtt_msg(topic: str, payload: dict[str, Any] | str) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    msg.payload = json.dumps(payload) if isinstance(payload, dict) else payload
    msg.retain = False
    msg.qos = 0
    return msg


def _make_hass_and_coordinator(
    entry_id: str = "entry_1",
    circuit: str = "bass3",
) -> tuple[MagicMock, SaunierGeniaCoordinator, dict[str, Any]]:
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.async_create_task = MagicMock(
        side_effect=lambda coro: asyncio.create_task(coro)
    )
    hass.async_create_background_task = MagicMock(
        side_effect=lambda coro, name="": asyncio.create_task(coro)
    )

    registered: dict[str, dict[str, Any]] = {}

    def _register(
        domain: str,
        service: str,
        handler: Any,
        schema: Any = None,
        supports_response: Any = None,
    ) -> None:
        registered[service] = {
            "handler": handler,
            "schema": schema,
            "supports_response": supports_response,
        }

    hass.services = MagicMock()
    hass.services.has_service = MagicMock(side_effect=lambda _d, s: s in registered)
    hass.services.async_register = MagicMock(side_effect=_register)
    hass.services.async_remove = MagicMock(
        side_effect=lambda _d, s: registered.pop(s, None)
    )

    entry = MagicMock()
    entry.entry_id = entry_id
    entry.domain = DOMAIN
    entry.data = {
        "mqtt_prefix": "ebusd",
        "manufacturer": "Saunier Duval",
    }
    entry.options = {}

    coord = SaunierGeniaCoordinator(hass, entry)
    coord._active_controller_circuit = circuit
    # Mark bus operational with basic telemetry
    coord._async_on_mqtt_message(
        _make_mqtt_msg(f"ebusd/{circuit}/Z1OpMode", {"value": {"value": "auto"}})
    )
    hass.data[DOMAIN][entry_id] = coord
    return hass, coord, registered


class TestTimeProgramServices(unittest.IsolatedAsyncioTestCase):
    """Tests for arotherm_genia_ebusd.read_time_program and write_time_program."""

    def setUp(self) -> None:
        """Speed up bus pacing constants for unit tests."""
        self._patches = [
            patch.object(time_programs, "WRITE_PACING_SECONDS", 0.0),
            patch.object(time_programs, "READBACK_SETTLE_SECONDS", 0.0),
            patch.object(time_programs, "READBACK_STEP_DELAY_SECONDS", 0.0),
            patch.object(time_programs, "BUS_READ_TIMEOUT_SECONDS", 0.15),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        """Restore patched constants."""
        for p in reversed(self._patches):
            p.stop()

    async def test_services_registered_with_response_only_and_unloaded(self) -> None:
        """Both services register with SupportsResponse.ONLY and unload cleanly."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        self.assertIn(SERVICE_READ_TIME_PROGRAM, registered)
        self.assertIn(SERVICE_WRITE_TIME_PROGRAM, registered)
        self.assertEqual(
            registered[SERVICE_READ_TIME_PROGRAM]["supports_response"],
            SupportsResponse.ONLY,
        )
        self.assertEqual(
            registered[SERVICE_WRITE_TIME_PROGRAM]["supports_response"],
            SupportsResponse.ONLY,
        )

        hass.config_entries = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        coord.async_unload = AsyncMock()
        entry = coord.entry
        await async_unload_entry(hass, entry)

        self.assertNotIn(SERVICE_READ_TIME_PROGRAM, registered)
        self.assertNotIn(SERVICE_WRITE_TIME_PROGRAM, registered)

    async def test_read_z1_timer_from_cache(self) -> None:
        """read_time_program returns all 7 days, temperature=True, and 24:00 normalization."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/Z1Timer_Slots",
                {
                    "mon": {"value": 2},
                    "tue": {"value": 1},
                    "wed": {"value": 0},
                    "thu": {"value": 0},
                    "fri": {"value": 0},
                    "sat": {"value": 1},
                    "sun": {"value": 0},
                },
            )
        )
        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/Z1Timer_Monday",
                {
                    "from_hour": {"value": 6},
                    "from_min": {"value": 0},
                    "to_hour": {"value": 9},
                    "to_min": {"value": 30},
                    "temp": {"value": 21.0},
                },
            )
        )
        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/Z1Timer_Monday_Slot2",
                {
                    "from_hour": {"value": 17},
                    "from_min": {"value": 0},
                    "to_hour": {"value": 0},
                    "to_min": {"value": 0},
                    "temp": {"value": 20.5},
                },
            )
        )
        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/Z1Timer_Tuesday",
                {
                    "from_hour": {"value": 0},
                    "from_min": {"value": 0},
                    "to_hour": {"value": 24},
                    "to_min": {"value": 0},
                    "temp": {"value": 21.5},
                },
            )
        )
        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/Z1Timer_Saturday",
                {
                    "from_hour": {"value": 14},
                    "from_min": {"value": 0},
                    "to_hour": {"value": 22},
                    "to_min": {"value": 0},
                    "temp": {"value": 21.0},
                },
            )
        )

        call = MagicMock()
        call.data = {"program": "Z1Timer"}
        res = await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call)

        self.assertEqual(res["program"], "Z1Timer")
        self.assertEqual(res["circuit"], "bass3")
        self.assertIs(res["temperature"], True)
        self.assertNotIn("incomplete", res)
        self.assertEqual(
            res["days"]["monday"],
            [
                {"start": "06:00", "end": "09:30", "temperature": 21.0},
                {"start": "17:00", "end": "24:00", "temperature": 20.5},
            ],
        )
        self.assertEqual(
            res["days"]["tuesday"],
            [{"start": "00:00", "end": "24:00", "temperature": 21.5}],
        )
        self.assertEqual(res["days"]["wednesday"], [])
        self.assertEqual(
            res["days"]["saturday"],
            [{"start": "14:00", "end": "22:00", "temperature": 21.0}],
        )

    async def test_read_circulation_omits_temperature_and_hydrates_missing_slot(
        self,
    ) -> None:
        """CirculationTimer returns temperature=False without temperature keys and fetches missing slots."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        async def _fake_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "CirculationTimer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/CirculationTimer_Slots",
                        {
                            "mon": {"value": 1},
                            "tue": {"value": 1},
                            "wed": {"value": 0},
                            "thu": {"value": 0},
                            "fri": {"value": 0},
                            "sat": {"value": 0},
                            "sun": {"value": 0},
                        },
                    )
                )
            elif msg_name == "CirculationTimer_Monday":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/CirculationTimer_Monday",
                        {
                            "from_hour": {"value": 6},
                            "from_min": {"value": 30},
                            "to_hour": {"value": 8},
                            "to_min": {"value": 0},
                        },
                    )
                )
            # Tuesday intentionally times out to test incomplete reporting

        coord.async_request_get = AsyncMock(side_effect=_fake_get)

        call = MagicMock()
        call.data = {"program": "CirculationTimer"}
        res = await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call)

        self.assertEqual(res["program"], "CirculationTimer")
        self.assertIs(res["temperature"], False)
        self.assertEqual(
            res["days"]["monday"],
            [{"start": "06:30", "end": "08:00"}],
        )
        self.assertNotIn("temperature", res["days"]["monday"][0])
        self.assertEqual(res["days"]["tuesday"], [])
        self.assertEqual(res["incomplete"], ["tuesday"])

    async def test_read_cooling_timer_reads_cooling_temp_field(self) -> None:
        """CoolingTimer decodes cooling_temp field cleanly."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/CoolingTimer_Slots",
                {
                    "mon": {"value": 1},
                    "tue": {"value": 0},
                    "wed": {"value": 0},
                    "thu": {"value": 0},
                    "fri": {"value": 0},
                    "sat": {"value": 0},
                    "sun": {"value": 0},
                },
            )
        )
        coord._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd/bass3/CoolingTimer_Monday",
                {
                    "from_hour": {"value": 12},
                    "from_min": {"value": 0},
                    "to_hour": {"value": 20},
                    "to_min": {"value": 0},
                    "cooling_temp": {"value": 23.5},
                },
            )
        )

        call = MagicMock()
        call.data = {"program": "CoolingTimer"}
        res = await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call)

        self.assertEqual(res["program"], "CoolingTimer")
        self.assertIs(res["temperature"], True)
        self.assertEqual(
            res["days"]["monday"],
            [{"start": "12:00", "end": "20:00", "temperature": 23.5}],
        )

    async def test_unsupported_program_error_matches_card_contract(self) -> None:
        """Unsupported programs (e.g. Z2Timer) raise 'not available on this controller'."""
        hass, _coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        call = MagicMock()
        call.data = {"program": "Z2Timer"}
        with self.assertRaises(HomeAssistantError) as ctx:
            await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call)
        self.assertIn("not available on this controller", str(ctx.exception))

        call_w = MagicMock()
        call_w.data = {"program": "Z3Timer", "days": ["monday"], "slots": []}
        with self.assertRaises(HomeAssistantError) as ctx_w:
            await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call_w)
        self.assertIn("not available on this controller", str(ctx_w.exception))

    async def test_entry_id_selection(self) -> None:
        """entry_id targets the requested config entry or raises if unknown."""
        hass, _coord1, registered = _make_hass_and_coordinator(
            entry_id="entry_a", circuit="bass3"
        )
        entry_b = MagicMock()
        entry_b.entry_id = "entry_b"
        entry_b.domain = DOMAIN
        entry_b.data = {"mqtt_prefix": "ebusd2", "manufacturer": "Vaillant"}
        entry_b.options = {}
        coord2 = SaunierGeniaCoordinator(hass, entry_b)
        coord2._active_controller_circuit = "basv3"
        coord2._async_on_mqtt_message(
            _make_mqtt_msg("ebusd2/basv3/Z1OpMode", {"value": {"value": "auto"}})
        )
        coord2._async_on_mqtt_message(
            _make_mqtt_msg(
                "ebusd2/basv3/SilentTimer_Slots",
                {
                    "mon": {"value": 0},
                    "tue": {"value": 0},
                    "wed": {"value": 0},
                    "thu": {"value": 0},
                    "fri": {"value": 0},
                    "sat": {"value": 0},
                    "sun": {"value": 0},
                },
            )
        )
        hass.data[DOMAIN]["entry_b"] = coord2
        _async_register_services(hass)

        call = MagicMock()
        call.data = {"program": "SilentTimer", "entry_id": "entry_b"}
        res = await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call)
        self.assertEqual(res["circuit"], "basv3")
        self.assertIs(res["temperature"], False)

        call_bad = MagicMock()
        call_bad.data = {"program": "SilentTimer", "entry_id": "missing_entry"}
        with self.assertRaises(HomeAssistantError):
            await registered[SERVICE_READ_TIME_PROGRAM]["handler"](call_bad)

    async def test_write_time_program_writes_and_confirms_readback(self) -> None:
        """write_time_program writes b5 55 payloads and verifies bus read-back."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        written: list[tuple[str, str, str]] = []
        bus_slots_state: dict[str, dict[str, Any]] = {}
        bus_counts: dict[str, int] = {
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 0,
        }

        async def _fake_write(circuit: str, msg_name: str, payload: str) -> None:
            written.append((circuit, msg_name, payload))
            parts = payload.split(";")
            total = int(parts[0])
            day_token = msg_name.split("_")[1][:3].lower()
            bus_counts[day_token] = total
            if total > 0:
                bus_slots_state[msg_name] = {
                    "from_hour": {"value": int(parts[1])},
                    "from_min": {"value": int(parts[2])},
                    "to_hour": {"value": int(parts[3])},
                    "to_min": {"value": int(parts[4])},
                    "temp": {"value": float(parts[5])},
                }

        async def _fake_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "Z1Timer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/Z1Timer_Slots",
                        {k: {"value": v} for k, v in bus_counts.items()},
                    )
                )
            elif msg_name in bus_slots_state:
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        f"ebusd/bass3/{msg_name}",
                        bus_slots_state[msg_name],
                    )
                )

        coord.async_write_parameter = AsyncMock(side_effect=_fake_write)
        coord.async_request_get = AsyncMock(side_effect=_fake_get)

        call = MagicMock()
        call.data = {
            "program": "Z1Timer",
            "days": ["monday", "tuesday"],
            "slots": [
                {"start": "17:00", "end": "24:00", "temperature": 20.5},
                {"start": "06:00", "end": "09:00", "temperature": 21.0},
            ],
        }
        res = await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)

        # Slots are sorted chronologically before writing
        self.assertEqual(
            written,
            [
                (CIRCUIT_BASS3, "Z1Timer_Monday", "2;6;0;9;0;21.0"),
                (CIRCUIT_BASS3, "Z1Timer_Monday_Slot2", "2;17;0;24;0;20.5"),
                (CIRCUIT_BASS3, "Z1Timer_Tuesday", "2;6;0;9;0;21.0"),
                (CIRCUIT_BASS3, "Z1Timer_Tuesday_Slot2", "2;17;0;24;0;20.5"),
            ],
        )
        self.assertEqual(res["program"], "Z1Timer")
        self.assertEqual(res["circuit"], "bass3")
        expected_day = [
            {"start": "06:00", "end": "09:00", "temperature": 21.0},
            {"start": "17:00", "end": "24:00", "temperature": 20.5},
        ]
        self.assertEqual(res["days"], {"monday": expected_day, "tuesday": expected_day})

    async def test_write_time_program_clear_day_with_empty_slots(self) -> None:
        """Passing slots=[] clears the day (0;0;0;0;0) and confirms count == 0."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        written: list[tuple[str, str, str]] = []

        async def _fake_write(circuit: str, msg_name: str, payload: str) -> None:
            written.append((circuit, msg_name, payload))

        async def _fake_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "CirculationTimer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/CirculationTimer_Slots",
                        {
                            "mon": {"value": 0},
                            "tue": {"value": 0},
                            "wed": {"value": 0},
                            "thu": {"value": 0},
                            "fri": {"value": 0},
                            "sat": {"value": 0},
                            "sun": {"value": 0},
                        },
                    )
                )

        coord.async_write_parameter = AsyncMock(side_effect=_fake_write)
        coord.async_request_get = AsyncMock(side_effect=_fake_get)

        call = MagicMock()
        call.data = {
            "program": "CirculationTimer",
            "days": ["monday"],
            "slots": [],
        }
        res = await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)

        self.assertEqual(
            written,
            [(CIRCUIT_BASS3, "CirculationTimer_Monday", "0;0;0;0;0")],
        )
        self.assertEqual(res["days"], {"monday": []})

    async def test_write_time_program_readback_mismatch_raises(self) -> None:
        """If controller read-back disagrees with written slots, HomeAssistantError is raised."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        coord.async_write_parameter = AsyncMock()

        async def _stale_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "HwcTimer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/HwcTimer_Slots",
                        {
                            "mon": {"value": 1},
                            "tue": {"value": 0},
                            "wed": {"value": 0},
                            "thu": {"value": 0},
                            "fri": {"value": 0},
                            "sat": {"value": 0},
                            "sun": {"value": 0},
                        },
                    )
                )
            elif msg_name == "HwcTimer_Monday":
                # Controller still has old window 05:00-07:00 instead of 13:00-15:00
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/HwcTimer_Monday",
                        {
                            "from_hour": {"value": 5},
                            "from_min": {"value": 0},
                            "to_hour": {"value": 7},
                            "to_min": {"value": 0},
                            "temp": {"value": 50.0},
                        },
                    )
                )

        coord.async_request_get = AsyncMock(side_effect=_stale_get)

        call = MagicMock()
        call.data = {
            "program": "HwcTimer",
            "days": ["monday"],
            "slots": [{"start": "13:00", "end": "15:00"}],
        }
        with self.assertRaises(HomeAssistantError) as ctx:
            await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)
        self.assertIn("mismatch", str(ctx.exception).lower())

    async def test_hwc_timer_reports_no_per_slot_temp_and_writes_noop_sentinel(
        self,
    ) -> None:
        """HwcTimer reports temperature=False and writes '-' (0xFFFF) to preserve HwcTempDesired."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        written: list[tuple[str, str, str]] = []

        async def _fake_write(circuit: str, msg_name: str, payload: str) -> None:
            written.append((circuit, msg_name, payload))

        async def _fake_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "HwcTimer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/HwcTimer_Slots",
                        {
                            "mon": {"value": 1},
                            "tue": {"value": 0},
                            "wed": {"value": 0},
                            "thu": {"value": 0},
                            "fri": {"value": 0},
                            "sat": {"value": 0},
                            "sun": {"value": 0},
                        },
                    )
                )
            elif msg_name == "HwcTimer_Monday":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/HwcTimer_Monday",
                        {
                            "from_hour": {"value": 13},
                            "from_min": {"value": 10},
                            "to_hour": {"value": 14},
                            "to_min": {"value": 50},
                            "temp": {"value": 50.0},
                        },
                    )
                )

        coord.async_write_parameter = AsyncMock(side_effect=_fake_write)
        coord.async_request_get = AsyncMock(side_effect=_fake_get)

        write_call = MagicMock()
        write_call.data = {
            "program": "HwcTimer",
            "days": ["monday"],
            "slots": [{"start": "13:10", "end": "14:50"}],
        }
        w_res = await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](write_call)

        self.assertEqual(
            written,
            [(CIRCUIT_BASS3, "HwcTimer_Monday", "1;13;10;14;50;-")],
        )
        self.assertEqual(
            w_res["days"]["monday"],
            [{"start": "13:10", "end": "14:50", "temperature": 50.0}],
        )

        read_call = MagicMock()
        read_call.data = {"program": "HwcTimer"}
        r_res = await registered[SERVICE_READ_TIME_PROGRAM]["handler"](read_call)
        self.assertIs(r_res["temperature"], True)
        self.assertEqual(
            r_res["days"]["monday"],
            [{"start": "13:10", "end": "14:50", "temperature": 50.0}],
        )

        # Explicit temperature on HwcTimer is written and verified
        written.clear()
        write_temp_call = MagicMock()
        write_temp_call.data = {
            "program": "HwcTimer",
            "days": ["monday"],
            "slots": [{"start": "13:10", "end": "14:50", "temperature": 50.0}],
        }
        w_temp_res = await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](
            write_temp_call
        )
        self.assertEqual(
            written,
            [(CIRCUIT_BASS3, "HwcTimer_Monday", "1;13;10;14;50;50.0")],
        )
        self.assertEqual(
            w_temp_res["days"]["monday"],
            [{"start": "13:10", "end": "14:50", "temperature": 50.0}],
        )

    async def test_write_accepts_one_minute_resolution(self) -> None:
        """b5 55 hardware supports 1-minute resolution (e.g. 17:22-19:58)."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)

        written: list[tuple[str, str, str]] = []

        async def _fake_write(circuit: str, msg_name: str, payload: str) -> None:
            written.append((circuit, msg_name, payload))

        async def _fake_get(_circuit: str, msg_name: str) -> None:
            if msg_name == "Z1Timer_Slots":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/Z1Timer_Slots",
                        {
                            "mon": {"value": 1},
                            "tue": {"value": 0},
                            "wed": {"value": 0},
                            "thu": {"value": 0},
                            "fri": {"value": 0},
                            "sat": {"value": 0},
                            "sun": {"value": 0},
                        },
                    )
                )
            elif msg_name == "Z1Timer_Monday":
                coord._async_on_mqtt_message(
                    _make_mqtt_msg(
                        "ebusd/bass3/Z1Timer_Monday",
                        {
                            "from_hour": {"value": 17},
                            "from_min": {"value": 22},
                            "to_hour": {"value": 19},
                            "to_min": {"value": 58},
                            "temp": {"value": 21.0},
                        },
                    )
                )

        coord.async_write_parameter = AsyncMock(side_effect=_fake_write)
        coord.async_request_get = AsyncMock(side_effect=_fake_get)

        call = MagicMock()
        call.data = {
            "program": "Z1Timer",
            "days": ["monday"],
            "slots": [{"start": "17:22", "end": "19:58", "temperature": 21.0}],
        }
        res = await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)
        self.assertEqual(
            written,
            [(CIRCUIT_BASS3, "Z1Timer_Monday", "1;17;22;19;58;21.0")],
        )
        self.assertEqual(
            res["days"]["monday"],
            [{"start": "17:22", "end": "19:58", "temperature": 21.0}],
        )

    async def test_write_validation_rejects_bad_grid_overlaps_count_and_temp(
        self,
    ) -> None:
        """Validation rejects >3 slots, off-grid times, overlaps, and out-of-range temperatures."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)
        coord.async_write_parameter = AsyncMock()

        invalid_payloads = [
            # Invalid time format / out of bounds
            {
                "program": "Z1Timer",
                "days": ["monday"],
                "slots": [{"start": "25:00", "end": "24:00", "temperature": 21.0}],
            },
            # Conflicting temperatures on shared-setpoint HwcTimer
            {
                "program": "HwcTimer",
                "days": ["monday"],
                "slots": [
                    {"start": "13:00", "end": "14:00", "temperature": 50.0},
                    {"start": "15:00", "end": "16:00", "temperature": 55.0},
                ],
            },
            # Overlapping slots
            {
                "program": "Z1Timer",
                "days": ["monday"],
                "slots": [
                    {"start": "06:00", "end": "10:00", "temperature": 21.0},
                    {"start": "09:30", "end": "12:00", "temperature": 21.0},
                ],
            },
            # > 3 slots
            {
                "program": "Z1Timer",
                "days": ["monday"],
                "slots": [
                    {"start": "01:00", "end": "02:00", "temperature": 20.0},
                    {"start": "03:00", "end": "04:00", "temperature": 20.0},
                    {"start": "05:00", "end": "06:00", "temperature": 20.0},
                    {"start": "07:00", "end": "08:00", "temperature": 20.0},
                ],
            },
            # Out-of-range temperature for Z1Timer
            {
                "program": "Z1Timer",
                "days": ["monday"],
                "slots": [{"start": "06:00", "end": "09:00", "temperature": 45.0}],
            },
            # Empty days
            {
                "program": "Z1Timer",
                "days": [],
                "slots": [{"start": "06:00", "end": "09:00", "temperature": 21.0}],
            },
            # Invalid day
            {
                "program": "Z1Timer",
                "days": ["funday"],
                "slots": [],
            },
            # Start >= End
            {
                "program": "Z1Timer",
                "days": ["monday"],
                "slots": [{"start": "12:00", "end": "12:00", "temperature": 20.0}],
            },
        ]

        for payload in invalid_payloads:
            call = MagicMock()
            call.data = payload
            with self.assertRaises(HomeAssistantError):
                await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)

        coord.async_write_parameter.assert_not_called()

    async def test_write_fails_when_ebus_offline(self) -> None:
        """Writing when eBUS signal is offline fails immediately without writing."""
        hass, coord, registered = _make_hass_and_coordinator()
        _async_register_services(hass)
        coord._async_on_mqtt_message(
            _make_mqtt_msg(f"ebusd/{CIRCUIT_GLOBAL}/signal", "false")
        )
        coord.async_write_parameter = AsyncMock()

        call = MagicMock()
        call.data = {
            "program": "Z1Timer",
            "days": ["monday"],
            "slots": [{"start": "06:00", "end": "09:00", "temperature": 21.0}],
        }
        with self.assertRaises(HomeAssistantError):
            await registered[SERVICE_WRITE_TIME_PROGRAM]["handler"](call)
        coord.async_write_parameter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
