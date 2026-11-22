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
    CIRCUIT_CTLV3,
    CIRCUIT_HMU,
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_HAS_MIGO_LINK,
    CONF_HAS_WIRELESS_ROOM_UNIT,
    CONF_INDOOR_MODEL,
    CONF_OUTDOOR_MODEL,
    DEFAULT_EBUSD_TCP_HOST,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    ISSUE_EBUSD_EXTERNAL_SWEEP,
    ISSUE_OUTDATED_HMU_CSV,
    ISSUE_OUTDATED_HMUX0_CSV,
    ISSUE_OUTDATED_VWZIO_CSV,
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
        """New setup transitions to ebusd_tcp step, prefills detected add-on, and saves it."""
        flow = SaunierGeniaConfigFlow()
        flow.hass = MagicMock()
        flow.async_create_entry = MagicMock(
            side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
        )

        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ) as mock_probe:
            step_tcp = asyncio.run(
                flow.async_step_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: False,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )
            self.assertEqual(step_tcp["type"], "form")
            self.assertEqual(step_tcp["step_id"], "ebusd_tcp")
            defaults = {k.schema: k.default for k in step_tcp["data_schema"].schema}
            self.assertTrue(defaults[CONF_ENABLE_EBUSD_TCP])
            self.assertEqual(defaults[CONF_EBUSD_TCP_HOST], "b4d7ad18-ebusd")
            self.assertEqual(defaults[CONF_EBUSD_TCP_PORT], 8888)

            res = asyncio.run(
                flow.async_step_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: True,
                        CONF_EBUSD_TCP_HOST: "b4d7ad18-ebusd",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )

        # Already verified on form render; submitting unchanged detected endpoint skips redundant probe
        mock_probe.assert_awaited_once()
        self.assertEqual(res["type"], "create_entry")
        self.assertTrue(res["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertEqual(res["options"][CONF_EBUSD_TCP_HOST], "b4d7ad18-ebusd")
        self.assertEqual(res["options"][CONF_EBUSD_TCP_PORT], 8888)

    def test_config_flow_tcp_optional_skip_and_manual_validation(self) -> None:
        """Setup allows leaving TCP blank/disabled, auto-enables manual host, and handles probe errors."""
        # 1. Nothing auto-detected -> defaults disabled & blank host; submitting skips TCP cleanly
        flow_skip = SaunierGeniaConfigFlow()
        flow_skip.hass = MagicMock()
        flow_skip.async_create_entry = MagicMock(
            side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
        )
        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=None),
        ):
            step_tcp = asyncio.run(
                flow_skip.async_step_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: False,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )
            defaults = {k.schema: k.default for k in step_tcp["data_schema"].schema}
            self.assertFalse(defaults[CONF_ENABLE_EBUSD_TCP])
            self.assertEqual(defaults[CONF_EBUSD_TCP_HOST], "")
            self.assertEqual(defaults[CONF_EBUSD_TCP_PORT], 8888)

            res_skip = asyncio.run(
                flow_skip.async_step_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: False,
                        CONF_EBUSD_TCP_HOST: "",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )
        self.assertEqual(res_skip["type"], "create_entry")
        self.assertFalse(res_skip["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertNotIn(CONF_EBUSD_TCP_HOST, res_skip["options"])

        # 2. Manual host entry verifies connectivity; unreachable host shows error; disabling recovers
        flow_manual = SaunierGeniaConfigFlow()
        flow_manual.hass = MagicMock()
        flow_manual.async_create_entry = MagicMock(
            side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
        )
        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(side_effect=[None, None, ("192.168.1.50", 8889)]),
        ):
            asyncio.run(
                flow_manual.async_step_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: True,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )
            # User types IP into initially-empty host without flipping switch -> probed & shows error
            res_err = asyncio.run(
                flow_manual.async_step_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: False,
                        CONF_EBUSD_TCP_HOST: "192.168.1.99",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )
            self.assertEqual(res_err["type"], "form")
            self.assertEqual(res_err["errors"], {"base": "cannot_connect_ebusd_tcp"})

            # Enabling TCP with empty host -> field error
            res_empty_err = asyncio.run(
                flow_manual.async_step_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: True,
                        CONF_EBUSD_TCP_HOST: "   ",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )
            self.assertEqual(res_empty_err["type"], "form")
            self.assertEqual(
                res_empty_err["errors"],
                {CONF_EBUSD_TCP_HOST: "invalid_ebusd_tcp_host"},
            )

            # Valid remote IP succeeds and saves host/port
            res_ok = asyncio.run(
                flow_manual.async_step_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: True,
                        CONF_EBUSD_TCP_HOST: "192.168.1.50",
                        CONF_EBUSD_TCP_PORT: 8889,
                    }
                )
            )
        self.assertEqual(res_ok["type"], "create_entry")
        self.assertTrue(res_ok["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertEqual(res_ok["options"][CONF_EBUSD_TCP_HOST], "192.168.1.50")
        self.assertEqual(res_ok["options"][CONF_EBUSD_TCP_PORT], 8889)

    def test_reconfigure_flow_includes_optional_tcp_and_preserves_other_options(
        self,
    ) -> None:
        """Reconfigure step 3 preserves non-TCP options, probes when needed, and avoids blocking unchanged hosts."""
        entry = MagicMock()
        entry.data = {
            "mqtt_prefix": "ebusd",
            "manufacturer": "Saunier Duval",
            CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
            CONF_INDOOR_MODEL: "HPIM 7 230V",
            CONF_HAS_WIRELESS_ROOM_UNIT: True,
            CONF_HAS_MIGO_LINK: True,
        }
        entry.options = {
            "force_dhw_boost": False,
            "fallback_poll_interval": 180,
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "192.168.1.50",
            CONF_EBUSD_TCP_PORT: 8888,
        }

        flow = SaunierGeniaConfigFlow()
        flow.hass = MagicMock()
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_update_reload_and_abort = MagicMock(
            side_effect=lambda target, **kwargs: {
                "type": "abort",
                "reason": "reconfigure_successful",
                "entry": target,
                **kwargs,
            }
        )

        # 1. Existing custom host is NOT overwritten on render and NOT blocked when unchanged
        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=None),
        ) as mock_probe:
            asyncio.run(flow.async_step_reconfigure({"manufacturer": "Saunier Duval"}))
            step_tcp = asyncio.run(
                flow.async_step_reconfigure_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 12",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: True,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )
            self.assertEqual(step_tcp["type"], "form")
            self.assertEqual(step_tcp["step_id"], "reconfigure_ebusd_tcp")
            defaults = {k.schema: k.default for k in step_tcp["data_schema"].schema}
            self.assertTrue(defaults[CONF_ENABLE_EBUSD_TCP])
            self.assertEqual(defaults[CONF_EBUSD_TCP_HOST], "192.168.1.50")

            res = asyncio.run(
                flow.async_step_reconfigure_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: True,
                        CONF_EBUSD_TCP_HOST: "192.168.1.50",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )
        mock_probe.assert_not_awaited()
        self.assertEqual(res["type"], "abort")
        self.assertEqual(res["data"][CONF_OUTDOOR_MODEL], "GeniaAir Max ES 12")
        self.assertFalse(res["options"]["force_dhw_boost"])
        self.assertEqual(res["options"]["fallback_poll_interval"], 180)
        self.assertTrue(res["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertEqual(res["options"][CONF_EBUSD_TCP_HOST], "192.168.1.50")

        # 2. Unconfigured entry auto-detects add-on during reconfigure
        entry_unconf = MagicMock()
        entry_unconf.data = dict(entry.data)
        entry_unconf.options = {"force_dhw_boost": True}
        flow2 = SaunierGeniaConfigFlow()
        flow2.hass = MagicMock()
        flow2._get_reconfigure_entry = MagicMock(return_value=entry_unconf)
        flow2.async_update_reload_and_abort = MagicMock(
            side_effect=lambda target, **kwargs: {"type": "abort", **kwargs}
        )
        with patch(
            "custom_components.arotherm_genia_ebusd.config_flow.async_probe_ebusd_tcp",
            new=AsyncMock(return_value=("b4d7ad18-ebusd", 8888)),
        ):
            asyncio.run(flow2.async_step_reconfigure({"manufacturer": "Saunier Duval"}))
            step_tcp2 = asyncio.run(
                flow2.async_step_reconfigure_models(
                    {
                        CONF_OUTDOOR_MODEL: "GeniaAir Max ES 15",
                        CONF_INDOOR_MODEL: "HPIM 7 230V",
                        CONF_HAS_WIRELESS_ROOM_UNIT: True,
                        CONF_HAS_MIGO_LINK: True,
                    }
                )
            )
            defaults2 = {k.schema: k.default for k in step_tcp2["data_schema"].schema}
            self.assertTrue(defaults2[CONF_ENABLE_EBUSD_TCP])
            self.assertEqual(defaults2[CONF_EBUSD_TCP_HOST], "b4d7ad18-ebusd")

            # User explicitly opts out during reconfigure
            res2 = asyncio.run(
                flow2.async_step_reconfigure_ebusd_tcp(
                    {
                        CONF_ENABLE_EBUSD_TCP: False,
                        CONF_EBUSD_TCP_HOST: "b4d7ad18-ebusd",
                        CONF_EBUSD_TCP_PORT: 8888,
                    }
                )
            )
        self.assertFalse(res2["options"][CONF_ENABLE_EBUSD_TCP])
        self.assertTrue(res2["options"]["force_dhw_boost"])

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


class TestEbusdTcpScanMetadata(unittest.TestCase):
    """Test device ID, SW/HW, circuit detection, and serial extraction via eBUSd TCP."""

    @staticmethod
    def _make_coord() -> SaunierGeniaCoordinator:
        entry = MagicMock()
        entry.entry_id = "entry_tcp_scan"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            CONF_ENABLE_EBUSD_TCP: True,
            CONF_EBUSD_TCP_HOST: "192.168.1.50",
            CONF_EBUSD_TCP_PORT: 8888,
        }
        return SaunierGeniaCoordinator(MagicMock(), entry)

    def test_tcp_scan_result_extracts_serials_circuits_and_versions(self) -> None:
        """TCP info + scan result populates SW/HW, circuits, and 28-char serials without MQTT scan.*."""
        coord = self._make_coord()
        fake_dev_reg = MagicMock()
        fake_dev_reg.async_get_device.side_effect = lambda identifiers: MagicMock(
            id=f"dev_{next(iter(identifiers))[1]}"
        )

        # No loaded CSVs on info lines so _async_verify_csvs_via_tcp sends no `find` queries
        tcp_lines = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0902;HW=5103"\n',
            b'address 15: slave #4, scanned "MF=Vaillant;ID=CTLV3;SW=0614;HW=4304"\n',
            b'address 76: slave #5, scanned "MF=Vaillant;ID=VWZIO;SW=0904;HW=5103"\n',
            b"\n",
            # scan result response (12 semicolon fields: addr;MF;ID;SW;HW + 7 serial tokens)
            b"08;Vaillant;HMU00;0902;5103;21;21;24;0010022010;0001;007815;N8\n",
            b"15;Vaillant;CTLV3;0614;4304;21;22;11;0020260921;0002;011223;N1\n",
            b"76;Vaillant;VWZIO;0904;5103;21;21;24;0010022011;0001;009988;N8\n",
            b"\n",
        ]
        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=tcp_lines)
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=fake_dev_reg,
            ),
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertEqual(coord._active_outdoor_circuit, CIRCUIT_HMU)
        self.assertEqual(coord._active_controller_circuit, CIRCUIT_CTLV3)
        self.assertEqual(coord.get_device_sw_version(DEVICE_OUTDOOR_UNIT), "0902")
        self.assertEqual(coord.get_device_hw_version(DEVICE_OUTDOOR_UNIT), "5103")
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_OUTDOOR_UNIT),
            "21212400100220100001007815N8",
        )
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_CLIMATE_CONTROLLER),
            "21221100202609210002011223N1",
        )
        self.assertEqual(
            coord.get_device_serial_number(DEVICE_HYDRAULIC_INTERFACE),
            "21212400100220110001009988N8",
        )
        # All serials resolved via `scan result`; no `read -c scan.<addr> id` needed
        written_cmds = [c.args[0] for c in mock_writer.write.call_args_list]
        self.assertIn(b"scan result\n", written_cmds)
        self.assertFalse(
            any(cmd.startswith(b"read -c scan.") for cmd in written_cmds),
            f"Unexpected per-address scan reads: {written_cmds}",
        )
        self.assertTrue(fake_dev_reg.async_update_device.called)

    def test_tcp_scan_falls_back_to_read_id_and_caches_subsequent_polls(self) -> None:
        """When scan result lacks serial tokens, fallback reads `read -c scan.<addr> id` once."""
        coord = self._make_coord()

        # First cycle: scan result only has 5 fields -> falls back to `read -c scan.<addr> id`
        tcp_lines_first = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0902;HW=5103"\n',
            b'address 76: slave #5, scanned "MF=Vaillant;ID=VWZIO;SW=0904;HW=5103"\n',
            b"\n",
            b"08;Vaillant;HMU00;0902;5103\n",
            b"76;Vaillant;VWZIO;0904;5103\n",
            b"\n",
            # read -c scan.08 id -> valid 7-part Vaillant serial
            b"21;21;24;0010022010;0001;007815;N8\n",
            b"\n",
            # read -c scan.76 id -> ERR (accessory without extended ID)
            b"ERR: element not found\n",
            b"\n",
        ]
        reader1 = AsyncMock()
        reader1.readline = AsyncMock(side_effect=tcp_lines_first)
        writer1 = MagicMock()
        writer1.drain = AsyncMock()
        writer1.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(reader1, writer1)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertEqual(
            coord.get_device_serial_number(DEVICE_OUTDOOR_UNIT),
            "21212400100220100001007815N8",
        )
        self.assertIsNone(coord.get_device_serial_number(DEVICE_HYDRAULIC_INTERFACE))
        cmds1 = [c.args[0] for c in writer1.write.call_args_list]
        self.assertIn(b"read -c scan.08 id\n", cmds1)
        self.assertIn(b"read -c scan.76 id\n", cmds1)

        # Second cycle: 08 already has serial and 76 already attempted -> no repeat `read -c scan.* id`
        tcp_lines_second = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0902;HW=5103"\n',
            b'address 76: slave #5, scanned "MF=Vaillant;ID=VWZIO;SW=0904;HW=5103"\n',
            b"\n",
            b"08;Vaillant;HMU00;0902;5103\n",
            b"76;Vaillant;VWZIO;0904;5103\n",
            b"\n",
        ]
        reader2 = AsyncMock()
        reader2.readline = AsyncMock(side_effect=tcp_lines_second)
        writer2 = MagicMock()
        writer2.drain = AsyncMock()
        writer2.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(reader2, writer2)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        cmds2 = [c.args[0] for c in writer2.write.call_args_list]
        self.assertIn(b"scan result\n", cmds2)
        self.assertFalse(any(cmd.startswith(b"read -c scan.") for cmd in cmds2))

    def test_tcp_verifies_passive_v131_csv_definitions_and_vwzio(self) -> None:
        """TCP find/-F/-f flags v1.3.1/v1.3.2 regressions on HMUX0, HMU00, and VWZIO."""
        coord = self._make_coord()
        tcp_legacy = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 76: slave #9, scanned "MF=Vaillant;ID=VWZIO;SW=0904;HW=5103", loaded "vaillant/76.vwzio.csv"\n',
            b"\n",
            # Existing outdoor checks pass, but Status02 still has active `r`
            b"hmux0 CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmux0 RunDataElectricPowerConsumption = 300\n",
            b"\n",
            b"hmux0 RunStatsAuxHeaterSwitches = 8\n",
            b"\n",
            b"hmux0 SubcoolingTemp = 3.0\n",
            b"\n",
            b"r,hmux0,Status02\n",
            b"u,hmux0,Status02\n",
            b"\n",
            # SecondaryCircuitStatus still has active `r` (pre-v1.3.1) and ImmersionHeaterPower missing
            b"r,vwzio,SecondaryCircuitStatus\n",
            b"\n",
            b"ERR: element not found\n",
            b"\n",
        ]
        r1 = AsyncMock()
        r1.readline = AsyncMock(side_effect=tcp_legacy)
        w1 = MagicMock()
        w1.drain = AsyncMock()
        w1.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(r1, w1)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertIn(ISSUE_OUTDATED_VWZIO_CSV, coord._active_repair_issues)

        # Updating CSVs to v1.3.2 definitions clears both repairs cleanly
        tcp_updated = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #11, scanned "MF=Vaillant;ID=HMUX0;SW=0407;HW=0504", loaded "vaillant/08.hmux0.csv"\n',
            b'address 76: slave #9, scanned "MF=Vaillant;ID=VWZIO;SW=0904;HW=5103", loaded "vaillant/76.vwzio.csv"\n',
            b"\n",
            b"hmux0 CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmux0 RunDataElectricPowerConsumption = 300\n",
            b"\n",
            b"hmux0 RunStatsAuxHeaterSwitches = 8\n",
            b"\n",
            b"hmux0 SubcoolingTemp = 3.0\n",
            b"\n",
            b"u,hmux0,Status02\n",
            b"\n",
            b"u,vwzio,SecondaryCircuitStatus\n",
            b"\n",
            b"vwzio ImmersionHeaterPower = 0.0\n",
            b"\n",
        ]
        r2 = AsyncMock()
        r2.readline = AsyncMock(side_effect=tcp_updated)
        w2 = MagicMock()
        w2.drain = AsyncMock()
        w2.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(r2, w2)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord._async_fetch_ebusd_tcp_info())

        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertNotIn(ISSUE_OUTDATED_VWZIO_CSV, coord._active_repair_issues)

        # Verify HMU00 Status01 missing 8=venting (v1.3.1 CSV) triggers ISSUE_OUTDATED_HMU_CSV and clears on v1.3.2
        coord_hmu = self._make_coord()
        tcp_hmu_v131 = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0902;HW=5103", loaded "vaillant/08.hmu.HW5103.csv"\n',
            b"\n",
            b"hmu CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmu RunDataElectricPowerConsumption = 300\n",
            b"\n",
            b"u,hmu,RunDataDiag000b\n",
            b"\n",
            b"r,hmu,Status01,temps,,08,b511,01,pumpstate,s,UCH,0=off;1=on;2=overrun;4=hwc,,\n",
            b"\n",
        ]
        r3 = AsyncMock()
        r3.readline = AsyncMock(side_effect=tcp_hmu_v131)
        w3 = MagicMock()
        w3.drain = AsyncMock()
        w3.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(r3, w3)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord_hmu._async_fetch_ebusd_tcp_info())

        self.assertIn(ISSUE_OUTDATED_HMU_CSV, coord_hmu._active_repair_issues)

        tcp_hmu_v132 = [
            b"version: ebusd 26.1\n",
            b'address 08: slave #3, scanned "MF=Vaillant;ID=HMU00;SW=0902;HW=5103", loaded "vaillant/08.hmu.HW5103.csv"\n',
            b"\n",
            b"hmu CompressorSilentOperationLevel = 0\n",
            b"\n",
            b"hmu RunDataElectricPowerConsumption = 300\n",
            b"\n",
            b"u,hmu,RunDataDiag000b\n",
            b"\n",
            b"r,hmu,Status01,temps,,08,b511,01,pumpstate,s,UCH,0=off;1=on;2=overrun;4=hwc;8=venting,,\n",
            b"\n",
        ]
        r4 = AsyncMock()
        r4.readline = AsyncMock(side_effect=tcp_hmu_v132)
        w4 = MagicMock()
        w4.drain = AsyncMock()
        w4.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(r4, w4)),
            patch(
                "homeassistant.helpers.device_registry.async_get",
                return_value=MagicMock(),
            ),
        ):
            asyncio.run(coord_hmu._async_fetch_ebusd_tcp_info())

        self.assertNotIn(ISSUE_OUTDATED_HMU_CSV, coord_hmu._active_repair_issues)

    def test_mqtt_detects_v132_missing_registers_without_tcp(self) -> None:
        """MQTT ERR responses on v1.3.2 registers trigger and clear HMUX0, VWZIO, and controller repairs."""
        from custom_components.arotherm_genia_ebusd.const import (
            ISSUE_OUTDATED_CONTROLLER_CSV,
        )

        entry = MagicMock()
        entry.entry_id = "mqtt_v132_repairs"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}
        coord = SaunierGeniaCoordinator(MagicMock(), entry)

        def _pub(topic: str, payload: str) -> None:
            msg = MagicMock()
            msg.topic = topic
            msg.payload = payload.encode("utf-8")
            msg.retain = False
            coord._async_on_mqtt_message(msg)

        # 1. Missing v1.3.2 registers over MQTT activate repairs
        _pub("ebusd/hmux0/RunStatsAuxHeaterSwitches", "ERR: element not found")
        _pub("ebusd/vwzio/RunStatsAuxHeaterSwitches", "ERR: element not found")
        _pub("ebusd/bass3/Z1QuickVetoEndTime", "ERR: element not found")

        self.assertIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertIn(ISSUE_OUTDATED_VWZIO_CSV, coord._active_repair_issues)
        self.assertIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

        # 2. Valid JSON payloads clear repairs cleanly
        _pub("ebusd/hmux0/RunStatsAuxHeaterSwitches", '{"value": {"value": 8}}')
        _pub("ebusd/vwzio/RunStatsAuxHeaterSwitches", '{"value": {"value": 8}}')
        _pub("ebusd/bass3/Z1QuickVetoEndTime", '{"value": {"value": "00:00:00"}}')

        self.assertNotIn(ISSUE_OUTDATED_HMUX0_CSV, coord._active_repair_issues)
        self.assertNotIn(ISSUE_OUTDATED_VWZIO_CSV, coord._active_repair_issues)
        self.assertNotIn(ISSUE_OUTDATED_CONTROLLER_CSV, coord._active_repair_issues)

    def test_tcp_write_confirmed_and_retries_on_transient_errors(self) -> None:
        """TCP write succeeds on retry after transient bus errors without MQTT /set fallback."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "tcp_write_test"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            "enable_ebusd_tcp": True,
            "ebusd_host": "192.168.1.50",
            "ebusd_port": 8888,
        }
        coord = SaunierGeniaCoordinator(hass, entry)
        coord._tcp_write_available = True
        coord._state[("bass3", "Z1OpMode")] = {"value": "auto"}

        def _make_conn(resp_bytes: bytes):
            r = AsyncMock()
            r.readline = AsyncMock(side_effect=[resp_bytes, b"\n"])
            w = MagicMock()
            w.drain = AsyncMock()
            w.wait_closed = AsyncMock()
            return r, w

        conns = [
            _make_conn(b"ERR: read timeout\n"),
            _make_conn(b"ERR: SYN received\n"),
            _make_conn(b"done\n"),
        ]
        written_cmds: list[bytes] = []

        async def _fake_open(_host, _port, timeout=3.0):
            r, w = conns.pop(0)
            orig_write = w.write

            def _capture(data: bytes):
                written_cmds.append(data)
                return orig_write(data)

            w.write = _capture
            return r, w

        with (
            patch.object(coord, "_async_open_tcp_connection", side_effect=_fake_open),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ) as mock_pub,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            ok = asyncio.run(coord.async_write_parameter("bass3", "Z1OpMode", "off"))

        self.assertTrue(ok)
        self.assertEqual(mock_pub.await_count, 0)
        self.assertEqual(mock_sleep.await_count, 2)
        self.assertEqual(coord.get_str("bass3", "Z1OpMode", "value"), "off")
        self.assertEqual(
            [c for c in written_cmds if c.startswith(b"write ")],
            [b"write -c bass3 Z1OpMode off\n"] * 3,
        )

    def test_tcp_write_exhausted_retries_does_not_fake_optimistic_state(self) -> None:
        """When all 3 TCP write attempts fail with transient bus errors, state stays unchanged and False is returned."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "tcp_write_fail"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            "enable_ebusd_tcp": True,
            "ebusd_host": "192.168.1.50",
            "ebusd_port": 8888,
        }
        coord = SaunierGeniaCoordinator(hass, entry)
        coord._tcp_write_available = True
        coord._state[("bass3", "Z1OpMode")] = {"value": "auto"}
        notified: list[bool] = []
        coord.async_add_listener("bass3", "Z1OpMode", lambda: notified.append(True))

        async def _fake_open(_host, _port, timeout=3.0):
            r = AsyncMock()
            r.readline = AsyncMock(side_effect=[b"ERR: read timeout\n", b"\n"])
            w = MagicMock()
            w.drain = AsyncMock()
            w.wait_closed = AsyncMock()
            return r, w

        with (
            patch.object(coord, "_async_open_tcp_connection", side_effect=_fake_open),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ) as mock_pub,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            ok = asyncio.run(coord.async_write_parameter("bass3", "Z1OpMode", "off"))

        self.assertFalse(ok)
        self.assertEqual(mock_pub.await_count, 0)
        self.assertEqual(mock_sleep.await_count, 2)
        self.assertEqual(coord.get_str("bass3", "Z1OpMode", "value"), "auto")
        self.assertTrue(notified)

    def test_tcp_write_socket_error_and_non_transient_fallback_to_mqtt(self) -> None:
        """Socket errors or non-transient TCP errors fall back cleanly to MQTT /set."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "tcp_write_fallback"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {
            "enable_ebusd_tcp": True,
            "ebusd_host": "192.168.1.50",
            "ebusd_port": 8888,
        }
        coord = SaunierGeniaCoordinator(hass, entry)
        coord._tcp_write_available = True
        coord._state[("bass3", "Z1OpMode")] = {"value": "auto"}

        # 1. Socket error disables _tcp_write_available and falls back to MQTT /set
        with (
            patch.object(
                coord,
                "_async_open_tcp_connection",
                side_effect=OSError("Connection refused"),
            ),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ) as mock_pub,
        ):
            ok1 = asyncio.run(coord.async_write_parameter("bass3", "Z1OpMode", "off"))

        self.assertTrue(ok1)
        self.assertFalse(coord._tcp_write_available)
        mock_pub.assert_awaited_once_with(
            hass, "ebusd/bass3/Z1OpMode/set", "off", qos=0, retain=False
        )
        self.assertEqual(coord.get_str("bass3", "Z1OpMode", "value"), "off")

        # 2. Non-transient ERR (e.g. element not found) logs warning and falls back to MQTT without retrying
        coord._tcp_write_available = True

        async def _fake_open_err(_host, _port, timeout=3.0):
            r = AsyncMock()
            r.readline = AsyncMock(side_effect=[b"ERR: element not found\n", b"\n"])
            w = MagicMock()
            w.drain = AsyncMock()
            w.wait_closed = AsyncMock()
            return r, w

        with (
            patch.object(
                coord, "_async_open_tcp_connection", side_effect=_fake_open_err
            ),
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ) as mock_pub2,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep2,
            self.assertLogs(
                "custom_components.arotherm_genia_ebusd.coordinator", level="WARNING"
            ) as cm,
        ):
            ok2 = asyncio.run(coord.async_write_parameter("bass3", "Z1OpMode", "auto"))

        self.assertTrue(ok2)
        self.assertTrue(any("ERR: element not found" in msg for msg in cm.output))
        self.assertEqual(mock_sleep2.await_count, 0)
        mock_pub2.assert_awaited_once_with(
            hass, "ebusd/bass3/Z1OpMode/set", "auto", qos=0, retain=False
        )
        self.assertEqual(coord.get_str("bass3", "Z1OpMode", "value"), "auto")

        # 3. Payload with spaces bypasses TCP CLI and goes straight to MQTT /set
        with (
            patch.object(
                coord, "_async_open_tcp_connection", new_callable=AsyncMock
            ) as mock_open3,
            patch(
                "custom_components.arotherm_genia_ebusd.coordinator.mqtt.async_publish",
                new_callable=AsyncMock,
            ) as mock_pub3,
        ):
            asyncio.run(coord.async_write_parameter("bass3", "Z1Name1", "Zone 1"))

        mock_open3.assert_not_awaited()
        mock_pub3.assert_awaited_once_with(
            hass, "ebusd/bass3/Z1Name1/set", "Zone 1", qos=0, retain=False
        )


if __name__ == "__main__":
    unittest.main()
