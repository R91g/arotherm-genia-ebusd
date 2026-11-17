"""Unit tests for eBUSd TCP endpoint discovery, Supervisor probing, and options autocomplete."""

from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.config_flow import (
    SaunierGeniaConfigFlow,
    SaunierGeniaOptionsFlowHandler,
)
from custom_components.arotherm_genia_ebusd.const import (
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_HAS_MIGO_LINK,
    CONF_HAS_WIRELESS_ROOM_UNIT,
    CONF_INDOOR_MODEL,
    CONF_OUTDOOR_MODEL,
    DEFAULT_EBUSD_TCP_HOST,
    ISSUE_EBUSD_EXTERNAL_SWEEP,
    SECTION_ADVANCED_OPTIONS,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator
from custom_components.arotherm_genia_ebusd.ebusd_tcp import (
    async_check_hassio_seed_mqtt_cfg,
    async_get_ebusd_tcp_candidates,
    async_probe_ebusd_tcp,
)


class TestEbusdTcpDiscovery(unittest.TestCase):
    """Test suite for automatic eBUSd TCP discovery and fallback ordering."""

    def test_custom_host_disables_fallback_chain(self) -> None:
        """Explicit non-loopback host returns only that endpoint."""
        hass = MagicMock()
        hass.config.components = ()
        candidates = asyncio.run(
            async_get_ebusd_tcp_candidates(hass, "192.168.1.55", 8899)
        )
        self.assertEqual(candidates, [("192.168.1.55", 8899)])

    def test_candidate_order_prioritizes_hassio_addons_and_includes_mqtt_broker(
        self,
    ) -> None:
        """Verify Supervisor add-on discovery runs first, then known hosts, loopback, MQTT broker."""
        hass = MagicMock()
        hass.config.components = {"hassio", "mqtt"}

        mqtt_entry = MagicMock()
        mqtt_entry.data = {"broker": "192.168.1.40"}
        mqtt_loopback = MagicMock()
        mqtt_loopback.data = {"broker": "127.0.0.1"}

        def fake_entries(domain: str):
            if domain == "mqtt":
                return [mqtt_loopback, mqtt_entry]
            return []

        hass.config_entries.async_entries.side_effect = fake_entries

        fake_hassio = types.ModuleType("homeassistant.components.hassio")
        fake_hassio.get_addons_info = MagicMock(  # type: ignore[attr-defined]
            return_value={
                "custom_ebusd_slug": {
                    "name": "Custom eBUSd Addon",
                    "state": "started",
                    "hostname": "custom-ebusd-host",
                    "ip_address": "172.30.33.9",
                    "network": {"8889/tcp": 8889},
                },
                "core_mosquitto": {
                    "name": "Mosquitto broker",
                    "state": "started",
                    "hostname": "core-mosquitto",
                },
            }
        )

        with patch.dict(sys.modules, {"homeassistant.components.hassio": fake_hassio}):
            candidates = asyncio.run(
                async_get_ebusd_tcp_candidates(hass, "127.0.0.1", 8888)
            )

        self.assertEqual(candidates[0], ("custom-ebusd-host", 8889))
        self.assertIn(("custom-ebusd-slug".replace("_", "-"), 8889), candidates)
        self.assertIn(("172.30.33.9", 8888), candidates)
        # Known HA add-on hostname appears before 127.0.0.1
        self.assertLess(
            candidates.index(("b4d7ad18-ebusd", 8888)),
            candidates.index(("127.0.0.1", 8888)),
        )
        # External MQTT broker host appears as last fallback after 127.0.0.1
        self.assertEqual(candidates[-1], ("192.168.1.40", 8888))

    def test_hassio_errors_are_swallowed_gracefully(self) -> None:
        """Broken or missing internal hassio helpers never break candidate resolution."""
        hass = MagicMock()
        hass.config.components = {"hassio"}
        hass.config_entries.async_entries.return_value = []

        broken_hassio = types.ModuleType("homeassistant.components.hassio")
        broken_hassio.get_addons_info = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules, {"homeassistant.components.hassio": broken_hassio}
        ):
            candidates = asyncio.run(
                async_get_ebusd_tcp_candidates(hass, "127.0.0.1", 8888)
            )

        self.assertEqual(
            candidates,
            [
                ("b4d7ad18-ebusd", 8888),
                ("local-ebusd", 8888),
                ("ebusd", 8888),
                ("ebusd.local", 8888),
                ("127.0.0.1", 8888),
            ],
        )

    def test_probe_verifies_ebusd_protocol_banner(self) -> None:
        """Probe rejects non-ebusd sockets and selects the first responding eBUSd."""
        hass = MagicMock()
        hass.config.components = ()
        hass.config_entries.async_entries.return_value = []

        non_ebusd_writer = MagicMock()
        non_ebusd_writer.drain = AsyncMock()
        non_ebusd_writer.wait_closed = AsyncMock()
        non_ebusd_reader = AsyncMock()
        non_ebusd_reader.readline.side_effect = [b"HTTP/1.1 400 Bad Request\r\n", b""]

        ebusd_writer = MagicMock()
        ebusd_writer.drain = AsyncMock()
        ebusd_writer.wait_closed = AsyncMock()
        ebusd_reader = AsyncMock()
        ebusd_reader.readline.side_effect = [
            b"version: ebusd 26.1.26.1\n",
            b"signal: acquired\n",
            b"",
        ]

        async def fake_open(host: str, port: int):
            if host == "b4d7ad18-ebusd":
                return non_ebusd_reader, non_ebusd_writer
            if host == "127.0.0.1":
                return ebusd_reader, ebusd_writer
            raise OSError("No route to host")

        with patch("asyncio.open_connection", side_effect=fake_open):
            result = asyncio.run(async_probe_ebusd_tcp(hass, DEFAULT_EBUSD_TCP_HOST))

        self.assertEqual(result, ("127.0.0.1", 8888))


class TestEbusdTcpAutocompleteFlows(unittest.TestCase):
    """Test ConfigFlow, OptionsFlow, and Coordinator TCP auto-configuration."""

    def test_config_flow_autodetects_and_enables_tcp_on_new_entry(self) -> None:
        """New setup enables and stores detected eBUSd TCP endpoint automatically."""
        flow = SaunierGeniaConfigFlow()
        flow.hass = MagicMock()
        flow.async_create_entry = MagicMock(
            side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
        )

        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ):
            res = asyncio.run(
                flow.async_step_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: False,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )

        self.assertTrue(res["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertEqual(res["options"][CONF_EBUSD_TCP_HOST], "b4d7ad18-ebusd")
        self.assertEqual(res["options"][CONF_EBUSD_TCP_PORT], 8888)

    def test_options_flow_autocompletes_unconfigured_host_only_when_detected(
        self,
    ) -> None:
        """OptionsFlow probes when unconfigured/default and keeps explicit custom hosts."""
        handler = SaunierGeniaOptionsFlowHandler()
        handler.hass = MagicMock()
        entry = MagicMock()
        entry.options = {}
        handler.config_entry = entry

        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ) as mock_probe:
            res = asyncio.run(handler.async_step_init())

        mock_probe.assert_awaited_once()
        adv_key = next(
            k
            for k in res["data_schema"].schema
            if getattr(k, "schema", None) == SECTION_ADVANCED_OPTIONS
        )
        self.assertIsNotNone(adv_key)

        # Explicit custom IP should NOT trigger probe overwrite
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "192.168.1.99",
            CONF_EBUSD_TCP_PORT: 8888,
        }
        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ) as mock_probe_custom:
            asyncio.run(handler.async_step_init())
        mock_probe_custom.assert_not_awaited()

    def test_coordinator_startup_autodiscover_persists_options_and_respects_explicit_false(
        self,
    ) -> None:
        """Coordinator auto-enables unconfigured TCP if found, and skips when explicitly False."""
        entry = MagicMock()
        entry.entry_id = "entry_auto"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        hass = MagicMock()
        coord = SaunierGeniaCoordinator(hass, entry)

        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ):
            asyncio.run(coord._async_autodiscover_ebusd_tcp())

        self.assertTrue(coord.is_ebusd_tcp_enabled)
        self.assertEqual(coord.ebusd_tcp_host, "b4d7ad18-ebusd")
        self.assertEqual(coord.ebusd_tcp_port, 8888)
        hass.config_entries.async_update_entry.assert_called_once()
        saved_opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
        self.assertTrue(saved_opts[CONF_ENABLE_EBUSD_TCP])
        self.assertEqual(saved_opts[CONF_EBUSD_TCP_HOST], "b4d7ad18-ebusd")

        # Explicit False must NOT be overridden
        entry_off = MagicMock()
        entry_off.entry_id = "entry_off"
        entry_off.data = {"mqtt_prefix": "ebusd"}
        entry_off.options = {CONF_ENABLE_EBUSD_TCP: False}
        hass_off = MagicMock()
        coord_off = SaunierGeniaCoordinator(hass_off, entry_off)

        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ) as mock_probe_off:
            asyncio.run(coord_off._async_autodiscover_ebusd_tcp())

        mock_probe_off.assert_not_awaited()
        self.assertFalse(coord_off.is_ebusd_tcp_enabled)
        hass_off.config_entries.async_update_entry.assert_not_called()


class TestExternalSweepDetection(unittest.TestCase):
    """Test Supervisor seed_mqtt_cfg and MQTT canary sweep repair detection."""

    def test_hassio_seed_mqtt_cfg_reads_addon_options_safely(self) -> None:
        """Verify async_check_hassio_seed_mqtt_cfg inspects options and handles failures."""
        hass = MagicMock()
        hass.config.components = {"hassio"}

        client = MagicMock()
        client.addons.list = AsyncMock(
            return_value=[
                {"slug": "b4d7ad18_ebusd", "name": "eBUSd", "state": "started"}
            ]
        )
        client.addons.addon_info = AsyncMock(
            return_value={"options": {"seed_mqtt_cfg": True}}
        )
        fake_hassio = types.ModuleType("homeassistant.components.hassio")
        fake_hassio.get_supervisor_client = MagicMock(return_value=client)  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"homeassistant.components.hassio": fake_hassio}):
            self.assertIs(asyncio.run(async_check_hassio_seed_mqtt_cfg(hass)), True)

            client.addons.addon_info = AsyncMock(
                return_value={"options": {"seed_mqtt_cfg": False}}
            )
            self.assertIs(asyncio.run(async_check_hassio_seed_mqtt_cfg(hass)), False)

            client.addons.list = AsyncMock(side_effect=RuntimeError("supervisor error"))
            self.assertIsNone(asyncio.run(async_check_hassio_seed_mqtt_cfg(hass)))

    def test_canary_sweep_triggers_and_ignores_retained_or_self_get(self) -> None:
        """Coordinator creates ebusd_external_sweep after >=3 non-retained unsolicited canaries."""
        entry = MagicMock()
        entry.entry_id = "entry_sweep"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        hass = MagicMock()
        coord = SaunierGeniaCoordinator(hass, entry)

        # 1. Retained startup messages must be ignored
        retained_msg = MagicMock()
        retained_msg.topic = "ebusd/hmu/YieldHcDay"
        retained_msg.payload = b'{"value": {"value": 100}}'
        retained_msg.retain = True
        coord._async_on_mqtt_message(retained_msg)
        self.assertEqual(coord._external_sweep_canaries, {})

        # 2. Explicit integration /get requests must be ignored
        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
            new=AsyncMock(),
        ):
            asyncio.run(coord.async_request_get("hmu", "YieldCoolDay"))
        self_msg = MagicMock()
        self_msg.topic = "ebusd/hmu/YieldCoolDay"
        self_msg.payload = b'{"value": {"value": 0}}'
        self_msg.retain = False
        coord._async_on_mqtt_message(self_msg)
        self.assertEqual(coord._external_sweep_canaries, {})
        self.assertNotIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

        # 3. Single one-off pass of three canaries does NOT trigger yet
        for topic, payload in (
            ("ebusd/hmu/YieldHcDay", b'{"value": {"value": 120}}'),
            ("ebusd/hmu/YieldHwcDay", b'{"value": {"value": 30}}'),
            ("ebusd/bass3/YieldTotal", b'{"value": {"value": 4500}}'),
        ):
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            msg.retain = False
            with patch("time.monotonic", return_value=100.0):
                coord._async_on_mqtt_message(msg)

        self.assertNotIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

        # Duplicate burst <60s later still does not count as a second sweep cycle
        for topic, payload in (
            ("ebusd/hmu/YieldHcDay", b'{"value": {"value": 120}}'),
            ("ebusd/hmu/YieldHwcDay", b'{"value": {"value": 30}}'),
            ("ebusd/bass3/YieldTotal", b'{"value": {"value": 4500}}'),
        ):
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            msg.retain = False
            with patch("time.monotonic", return_value=120.0):
                coord._async_on_mqtt_message(msg)

        self.assertNotIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

        # 4. Second sweep pass >=60s later confirms periodic external sweep and triggers Repair
        for topic, payload in (
            ("ebusd/hmu/YieldHcDay", b'{"value": {"value": 120}}'),
            ("ebusd/hmu/YieldHwcDay", b'{"value": {"value": 30}}'),
            ("ebusd/bass3/YieldTotal", b'{"value": {"value": 4500}}'),
        ):
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload
            msg.retain = False
            with patch("time.monotonic", return_value=900.0):
                coord._async_on_mqtt_message(msg)

        self.assertIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

        # 5. Watchdog auto-clears after canary window (2400s) expires
        with patch("time.monotonic", return_value=5000.0):
            coord._async_evaluate_external_sweep_issue(5000.0)
        self.assertNotIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

    def test_hassio_seed_mqtt_cfg_triggers_and_clears_repair(self) -> None:
        """Supervisor seed_mqtt_cfg=True activates ebusd_external_sweep directly."""
        entry = MagicMock()
        entry.entry_id = "entry_seed"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.async_check_hassio_seed_mqtt_cfg",
            new=AsyncMock(return_value=True),
        ):
            asyncio.run(coord._async_check_seed_mqtt_cfg())
        self.assertIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)

        with patch(
            "custom_components.arotherm_genia_ebusd.coordinator.async_check_hassio_seed_mqtt_cfg",
            new=AsyncMock(return_value=False),
        ):
            asyncio.run(coord._async_check_seed_mqtt_cfg())
        self.assertNotIn(ISSUE_EBUSD_EXTERNAL_SWEEP, coord._active_repair_issues)


if __name__ == "__main__":
    unittest.main()
