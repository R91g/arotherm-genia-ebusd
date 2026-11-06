"""Unit tests for diagnostic services (dump_mqtt_values and record_topic_changes)."""

import asyncio
import json
import os
import sys
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401
from homeassistant.exceptions import HomeAssistantError

from custom_components.arotherm_genia_ebusd import (
    _async_register_services,
    async_unload_entry,
)
from custom_components.arotherm_genia_ebusd.const import (
    DOMAIN,
    SERVICE_DUMP_MQTT_VALUES,
    SERVICE_READ_PARAMETER,
    SERVICE_RECORD_TOPIC_CHANGES,
    SERVICE_SEND_HEX_COMMAND,
    SERVICE_WRITE_PARAMETER,
)
from custom_components.arotherm_genia_ebusd.coordinator import SaunierGeniaCoordinator


class TestDiagnosticServices(unittest.TestCase):
    """Test suite for dump_mqtt_values and record_topic_changes services."""

    def setUp(self) -> None:
        """Set up test environment."""
        self.hass = MagicMock()
        self.registered_services: dict[str, Any] = {}
        self.service_kwargs: dict[str, dict[str, Any]] = {}

        def mock_register(
            domain: str,
            service_name: str,
            handler: Any,
            schema: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            self.registered_services[service_name] = handler
            self.service_kwargs[service_name] = kwargs

        self.hass.services.has_service.return_value = False
        self.hass.services.async_register.side_effect = mock_register

    def test_services_registered_with_supports_response_only(self) -> None:
        """Verify services register with SupportsResponse.ONLY."""
        from homeassistant.core import SupportsResponse

        _async_register_services(self.hass)

        self.assertIn(SERVICE_DUMP_MQTT_VALUES, self.registered_services)
        self.assertIn(SERVICE_RECORD_TOPIC_CHANGES, self.registered_services)
        self.assertIn(SERVICE_SEND_HEX_COMMAND, self.registered_services)
        self.assertIn(SERVICE_READ_PARAMETER, self.registered_services)
        self.assertIn(SERVICE_WRITE_PARAMETER, self.registered_services)
        self.assertEqual(
            self.service_kwargs[SERVICE_DUMP_MQTT_VALUES].get("supports_response"),
            SupportsResponse.ONLY,
        )
        self.assertEqual(
            self.service_kwargs[SERVICE_RECORD_TOPIC_CHANGES].get("supports_response"),
            SupportsResponse.ONLY,
        )
        self.assertEqual(
            self.service_kwargs[SERVICE_SEND_HEX_COMMAND].get("supports_response"),
            SupportsResponse.ONLY,
        )
        self.assertEqual(
            self.service_kwargs[SERVICE_READ_PARAMETER].get("supports_response"),
            SupportsResponse.ONLY,
        )
        self.assertEqual(
            self.service_kwargs[SERVICE_WRITE_PARAMETER].get("supports_response"),
            SupportsResponse.OPTIONAL,
        )

    def test_dump_mqtt_values_no_instances_raises(self) -> None:
        """Verify dump_mqtt_values raises HomeAssistantError when no coordinators exist."""
        self.hass.data = {DOMAIN: {}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_DUMP_MQTT_VALUES]

        call = MagicMock()
        call.data = {}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("No configured instances", str(ctx.exception))

    def test_dump_mqtt_values_single_instance(self) -> None:
        """Verify dump_mqtt_values returns structured dump for single coordinator."""
        from custom_components.arotherm_genia_ebusd.const import (
            CONF_INDOOR_MODEL,
            CONF_OUTDOOR_MODEL,
        )

        entry = MagicMock()
        entry.entry_id = "test_entry_1"
        entry.data = {
            "mqtt_prefix": "ebusd",
            CONF_OUTDOOR_MODEL: "aroTHERM plus VWL 55/6",
            CONF_INDOOR_MODEL: "MiPro Sense",
        }
        entry.options = {}

        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"
        coord._active_controller_circuit = "15.bass3"
        coord._state[("08.hmux0", "YieldThisYear")] = {"0": {"value": 1500.0}}
        coord._state[("15.bass3", "z1RoomTemp")] = {"temp": {"value": 21.5}}

        self.hass.data = {DOMAIN: {entry.entry_id: coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_DUMP_MQTT_VALUES]

        call = MagicMock()
        call.data = {}

        result = asyncio.run(handler(call))
        self.assertIsInstance(result, dict)
        self.assertEqual(result["domain"], DOMAIN)
        self.assertEqual(result["entry_id"], "test_entry_1")
        self.assertEqual(result["mqtt_prefix"], "ebusd")
        self.assertEqual(result["outdoor_model"], "aroTHERM plus VWL 55/6")
        self.assertEqual(result["indoor_model"], "MiPro Sense")
        self.assertEqual(result["active_outdoor_circuit"], "08.hmux0")
        self.assertEqual(result["active_controller_circuit"], "15.bass3")
        self.assertEqual(result["cached_messages_count"], 2)
        self.assertIn("08.hmux0", result["values"])
        self.assertIn("15.bass3", result["values"])
        self.assertEqual(
            result["values"]["08.hmux0"]["YieldThisYear"], {"0": {"value": 1500.0}}
        )

    def test_dump_mqtt_values_filtered_by_circuit(self) -> None:
        """Verify dump_mqtt_values filters results when circuit is specified."""
        entry = MagicMock()
        entry.entry_id = "test_entry_1"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}

        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"
        coord._active_controller_circuit = "15.bass3"
        coord._state[("08.hmux0", "YieldThisYear")] = {"0": {"value": 1500.0}}
        coord._state[("15.bass3", "z1RoomTemp")] = {"temp": {"value": 21.5}}

        self.hass.data = {DOMAIN: {entry.entry_id: coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_DUMP_MQTT_VALUES]

        call = MagicMock()
        call.data = {"circuit": "08"}

        result = asyncio.run(handler(call))
        self.assertIn("08.hmux0", result["values"])
        self.assertNotIn("15.bass3", result["values"])
        self.assertEqual(result["cached_messages_count"], 1)

    def test_dump_mqtt_values_multiple_instances(self) -> None:
        """Verify dump_mqtt_values returns keyed dictionary when multiple coordinators exist."""
        entry1 = MagicMock(
            entry_id="entry_1", data={"mqtt_prefix": "ebusd1"}, options={}
        )
        entry2 = MagicMock(
            entry_id="entry_2", data={"mqtt_prefix": "ebusd2"}, options={}
        )

        coord1 = SaunierGeniaCoordinator(self.hass, entry1)
        coord2 = SaunierGeniaCoordinator(self.hass, entry2)

        self.hass.data = {DOMAIN: {entry1.entry_id: coord1, entry2.entry_id: coord2}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_DUMP_MQTT_VALUES]

        call = MagicMock()
        call.data = {}

        result = asyncio.run(handler(call))
        self.assertIn("entry_1", result)
        self.assertIn("entry_2", result)
        self.assertEqual(result["entry_1"]["mqtt_prefix"], "ebusd1")
        self.assertEqual(result["entry_2"]["mqtt_prefix"], "ebusd2")

    def test_dump_mqtt_values_anonymization(self) -> None:
        """Verify dump_mqtt_values anonymizes long serial numbers when anonymize=True and preserves when False."""
        entry = MagicMock()
        entry.entry_id = "test_entry_anon"
        entry.data = {"mqtt_prefix": "ebusd"}
        entry.options = {}

        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"
        coord._active_controller_circuit = "15.bass3"
        raw_serial = "21210500100234560000001234N5"
        coord._state[("08.hmux0", "Scan.08")] = {"id": raw_serial}
        coord._state[("15.bass3", "z1RoomTemp")] = {"temp": {"value": 21.5}}

        self.hass.data = {DOMAIN: {entry.entry_id: coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_DUMP_MQTT_VALUES]

        # 1. Test with default anonymize=True
        call_anon = MagicMock()
        call_anon.data = {"anonymize": True}
        res_anon = asyncio.run(handler(call_anon))
        self.assertTrue(res_anon["anonymized"])
        masked_id = res_anon["values"]["08.hmux0"]["Scan.08"]["id"]
        self.assertNotEqual(masked_id, raw_serial)
        self.assertIn("************", masked_id)
        self.assertTrue(masked_id.startswith("212105001002"))
        self.assertTrue(masked_id.endswith("34N5"))

        # 2. Test with anonymize=False
        call_raw = MagicMock()
        call_raw.data = {"anonymize": False}
        res_raw = asyncio.run(handler(call_raw))
        self.assertFalse(res_raw["anonymized"])
        self.assertEqual(res_raw["values"]["08.hmux0"]["Scan.08"]["id"], raw_serial)

    def test_record_topic_changes_no_instances_raises(self) -> None:
        """Verify record_topic_changes raises HomeAssistantError when no coordinators exist."""
        self.hass.data = {DOMAIN: {}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_RECORD_TOPIC_CHANGES]

        call = MagicMock()
        call.data = {"duration": 5}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("No configured instances", str(ctx.exception))

    def test_record_topic_changes_captures_and_unsubscribes(self) -> None:
        """Verify record_topic_changes collects messages and unsubscribes cleanly."""
        entry = MagicMock(
            entry_id="test_entry", data={"mqtt_prefix": "ebusd"}, options={}
        )
        coord = SaunierGeniaCoordinator(self.hass, entry)
        self.hass.data = {DOMAIN: {entry.entry_id: coord}}

        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_RECORD_TOPIC_CHANGES]

        captured_callback = None
        mock_unsub = MagicMock()

        async def fake_subscribe(
            hass: Any, topic: str, msg_callback: Any, qos: int = 0
        ) -> Any:
            nonlocal captured_callback
            captured_callback = msg_callback
            return mock_unsub

        call = MagicMock()
        call.data = {"duration": 10}

        async def run_test() -> dict[str, Any]:
            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.mqtt.async_subscribe",
                    side_effect=fake_subscribe,
                ),
                patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            ):

                async def deliver_messages(duration: int) -> None:
                    # Deliver JSON message
                    msg1 = MagicMock()
                    msg1.topic = "ebusd/08/YieldThisYear"
                    msg1.payload = json.dumps({"value": 1200})
                    msg1.retain = True
                    msg1.qos = 0
                    captured_callback(msg1)

                    # Deliver raw text message
                    msg2 = MagicMock()
                    msg2.topic = "ebusd/global/status"
                    msg2.payload = "running;ok"
                    msg2.retain = False
                    msg2.qos = 1
                    captured_callback(msg2)

                    # Deliver bytes message
                    msg3 = MagicMock()
                    msg3.topic = "ebusd/15/temp"
                    msg3.payload = b"21.5"
                    msg3.retain = False
                    msg3.qos = 0
                    captured_callback(msg3)

                mock_sleep.side_effect = deliver_messages
                res = await handler(call)
                return res

        result = asyncio.run(run_test())

        self.assertEqual(result["duration_seconds"], 10)
        self.assertEqual(result["mqtt_prefixes"], "ebusd")
        self.assertEqual(result["message_count"], 3)
        self.assertEqual(len(result["records"]), 3)

        self.assertEqual(result["records"][0]["topic"], "ebusd/08/YieldThisYear")
        self.assertEqual(result["records"][0]["payload"], {"value": 1200})
        self.assertTrue(result["records"][0]["retained"])

        self.assertEqual(result["records"][1]["topic"], "ebusd/global/status")
        self.assertEqual(result["records"][1]["payload"], "running;ok")
        self.assertFalse(result["records"][1]["retained"])

        self.assertEqual(result["records"][2]["topic"], "ebusd/15/temp")
        self.assertEqual(
            result["records"][2]["payload"],
            21.5 if isinstance(result["records"][2]["payload"], float) else "21.5",
        )

        mock_unsub.assert_called_once()

    def test_record_topic_changes_filtered_by_circuit(self) -> None:
        """Verify record_topic_changes filters messages by circuit parameter."""
        entry = MagicMock(
            entry_id="test_entry", data={"mqtt_prefix": "ebusd"}, options={}
        )
        coord = SaunierGeniaCoordinator(self.hass, entry)
        self.hass.data = {DOMAIN: {entry.entry_id: coord}}

        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_RECORD_TOPIC_CHANGES]

        captured_callback = None
        mock_unsub = MagicMock()

        async def fake_subscribe(
            hass: Any, topic: str, msg_callback: Any, qos: int = 0
        ) -> Any:
            nonlocal captured_callback
            captured_callback = msg_callback
            return mock_unsub

        call = MagicMock()
        call.data = {"duration": 10, "circuit": "08"}

        async def run_test() -> dict[str, Any]:
            with (
                patch(
                    "custom_components.arotherm_genia_ebusd.mqtt.async_subscribe",
                    side_effect=fake_subscribe,
                ),
                patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            ):

                async def deliver_messages(duration: int) -> None:
                    # Message matching 08
                    msg1 = MagicMock(
                        topic="ebusd/08/temp", payload="45.0", retain=False, qos=0
                    )
                    captured_callback(msg1)

                    # Message on 15 (should be filtered out)
                    msg2 = MagicMock(
                        topic="ebusd/15/temp", payload="21.0", retain=False, qos=0
                    )
                    captured_callback(msg2)

                mock_sleep.side_effect = deliver_messages
                res = await handler(call)
                return res

        result = asyncio.run(run_test())
        self.assertEqual(result["message_count"], 1)
        self.assertEqual(result["records"][0]["topic"], "ebusd/08/temp")
        mock_unsub.assert_called_once()

    def test_record_topic_changes_subscribe_failure(self) -> None:
        """Verify record_topic_changes raises HomeAssistantError if subscription fails."""
        entry = MagicMock(
            entry_id="test_entry", data={"mqtt_prefix": "ebusd"}, options={}
        )
        coord = SaunierGeniaCoordinator(self.hass, entry)
        self.hass.data = {DOMAIN: {entry.entry_id: coord}}

        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_RECORD_TOPIC_CHANGES]

        call = MagicMock()
        call.data = {"duration": 5}

        async def run_test() -> None:
            with patch(
                "custom_components.arotherm_genia_ebusd.mqtt.async_subscribe",
                side_effect=RuntimeError("MQTT broker disconnected"),
            ):
                await handler(call)

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(run_test())
        self.assertIn("Error recording MQTT topics", str(ctx.exception))

    def test_services_unregistered_on_unload(self) -> None:
        """Verify services are removed when the last config entry is unloaded."""
        entry = MagicMock()
        entry.entry_id = "test_entry_1"
        self.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        coord = MagicMock()
        coord.async_unload = AsyncMock()
        self.hass.data = {DOMAIN: {entry.entry_id: coord}}

        success = asyncio.run(async_unload_entry(self.hass, entry))
        self.assertTrue(success)

        # Ensure all services including new diagnostic services were removed
        expected_removed = [
            SERVICE_DUMP_MQTT_VALUES,
            SERVICE_RECORD_TOPIC_CHANGES,
            SERVICE_SEND_HEX_COMMAND,
            SERVICE_READ_PARAMETER,
            SERVICE_WRITE_PARAMETER,
        ]
        for srv in expected_removed:
            self.hass.services.async_remove.assert_any_call(DOMAIN, srv)

    def test_send_hex_command_success(self) -> None:
        """Verify send_hex_command connects, sends hex with spaces stripped, and returns response."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"0aff021b2a0028003c0001\n")
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        call = MagicMock()
        call.data = {
            "command": "08 b5 1a 04 05 ff 34 28",
            "host": "192.168.1.50",
            "port": 8888,
            "timeout": 5.0,
        }

        with patch(
            "asyncio.open_connection", return_value=(mock_reader, mock_writer)
        ) as mock_connect:
            result = asyncio.run(handler(call))

        mock_connect.assert_called_once_with("192.168.1.50", 8888)
        mock_writer.write.assert_called_once_with(b"hex 08b51a0405ff3428\n")
        mock_writer.close.assert_called_once()
        self.assertEqual(result["command"], "08b51a0405ff3428")
        self.assertEqual(result["response"], "0aff021b2a0028003c0001")
        self.assertTrue(result["success"])
        self.assertEqual(result["host"], "192.168.1.50")
        self.assertEqual(result["port"], 8888)

    def test_send_hex_command_invalid_hex_raises(self) -> None:
        """Verify send_hex_command raises HomeAssistantError on non-hex characters."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        call = MagicMock()
        call.data = {"command": "08b51a0405ffZZ"}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("Invalid hexadecimal command", str(ctx.exception))

    def test_send_hex_command_empty_hex_raises(self) -> None:
        """Verify send_hex_command raises HomeAssistantError on empty string."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        call = MagicMock()
        call.data = {"command": "   "}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("Invalid hexadecimal command", str(ctx.exception))

    def test_send_hex_command_err_response(self) -> None:
        """Verify send_hex_command flags success=False when ebusd returns ERR."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"ERR: command not enabled\n")
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        call = MagicMock()
        call.data = {"command": "08b51a"}

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            result = asyncio.run(handler(call))

        self.assertFalse(result["success"])
        self.assertEqual(result["response"], "ERR: command not enabled")

    def test_send_hex_command_connection_error_raises(self) -> None:
        """Verify send_hex_command raises HomeAssistantError on TCP connection refusal."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        call = MagicMock()
        call.data = {"command": "08b51a", "host": "10.0.0.99"}

        with (
            patch("asyncio.open_connection", side_effect=OSError("Connection refused")),
            self.assertRaises(HomeAssistantError) as ctx,
        ):
            asyncio.run(handler(call))
        self.assertIn("Could not connect to eBUSd TCP daemon", str(ctx.exception))

    def test_send_hex_command_timeout_raises(self) -> None:
        """Verify send_hex_command raises HomeAssistantError on TCP timeout."""
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_SEND_HEX_COMMAND]

        call = MagicMock()
        call.data = {"command": "08b51a", "timeout": 2.0}

        with (
            patch("asyncio.open_connection", side_effect=TimeoutError()),
            self.assertRaises(HomeAssistantError) as ctx,
        ):
            asyncio.run(handler(call))
        self.assertIn("Timeout", str(ctx.exception))

    def test_read_parameter_no_instances_raises(self) -> None:
        """Verify read_parameter raises HomeAssistantError when no coordinators exist."""
        self.hass.data = {DOMAIN: {}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_READ_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "08", "name": "Status01"}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("No configured instances", str(ctx.exception))

    def test_read_parameter_empty_parameters_raises(self) -> None:
        """Verify read_parameter raises HomeAssistantError if circuit or name is empty."""
        entry = MagicMock()
        coord = SaunierGeniaCoordinator(self.hass, entry)
        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_READ_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "  ", "name": "Status01"}
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn(
            "Both 'circuit' and 'name' parameters must be non-empty", str(ctx.exception)
        )

        call.data = {"circuit": "08", "name": "  "}
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn(
            "Both 'circuit' and 'name' parameters must be non-empty", str(ctx.exception)
        )

    def test_read_parameter_returns_cached_value(self) -> None:
        """Verify read_parameter returns cached dictionary when force=False without publishing /get."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"
        coord._state[("08.hmux0", "Status01")] = {"temp1": 42.5, "return_temp": 38.0}
        coord.async_request_get = AsyncMock()

        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_READ_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "hmu", "name": "Status01", "force": False}

        result = asyncio.run(handler(call))
        self.assertEqual(result["circuit"], "hmu")
        self.assertEqual(result["target_circuit"], "08.hmux0")
        self.assertEqual(result["name"], "Status01")
        self.assertEqual(result["value"], {"temp1": 42.5, "return_temp": 38.0})
        self.assertTrue(result["cached"])
        coord.async_request_get.assert_not_called()

    def test_read_parameter_force_fetches_via_mqtt(self) -> None:
        """Verify read_parameter forces active request and resolves when listener is notified."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"

        async def fake_request_get(circuit: str, message: str) -> None:
            coord._state[("08.hmux0", "Status01")] = {"temp1": 45.0}
            coord._async_notify_message_listeners("08.hmux0", "Status01")

        coord.async_request_get = AsyncMock(side_effect=fake_request_get)

        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_READ_PARAMETER]

        call = MagicMock()
        call.data = {
            "circuit": "08",
            "name": "Status01",
            "force": True,
            "timeout": 2.0,
        }

        result = asyncio.run(handler(call))
        self.assertEqual(result["circuit"], "08")
        self.assertEqual(result["name"], "Status01")
        self.assertEqual(result["value"], {"temp1": 45.0})
        self.assertFalse(result["cached"])
        coord.async_request_get.assert_awaited_once_with("08", "Status01")

    def test_read_parameter_timeout_raises(self) -> None:
        """Verify read_parameter raises HomeAssistantError on timeout waiting for MQTT response."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_outdoor_circuit = "08.hmux0"
        coord.async_request_get = AsyncMock()

        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_READ_PARAMETER]

        call = MagicMock()
        call.data = {
            "circuit": "08",
            "name": "Status01",
            "force": True,
            "timeout": 0.05,
        }

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("Timeout waiting for eBUSd MQTT response", str(ctx.exception))

    def test_write_parameter_no_instances_raises(self) -> None:
        """Verify write_parameter raises HomeAssistantError when no coordinators exist."""
        self.hass.data = {DOMAIN: {}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_WRITE_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "08", "name": "Status01", "value": 1}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("No configured instances", str(ctx.exception))

    def test_write_parameter_empty_parameters_raises(self) -> None:
        """Verify write_parameter raises HomeAssistantError if circuit or name is empty."""
        entry = MagicMock()
        coord = SaunierGeniaCoordinator(self.hass, entry)
        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_WRITE_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "", "name": "Z1OpMode", "value": "night"}
        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn(
            "Both 'circuit' and 'name' parameters must be non-empty", str(ctx.exception)
        )

    def test_write_parameter_success(self) -> None:
        """Verify write_parameter invokes coordinator.async_write_parameter and returns status."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_controller_circuit = "15.bass3"
        coord.async_write_parameter = AsyncMock()

        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_WRITE_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "bass3", "name": "Z1OpMode", "value": "night"}

        result = asyncio.run(handler(call))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["circuit"], "bass3")
        self.assertEqual(result["target_circuit"], "15.bass3")
        self.assertEqual(result["name"], "Z1OpMode")
        self.assertEqual(result["value"], "night")
        self.assertEqual(result["topic"], "ebusd/15.bass3/Z1OpMode/set")
        coord.async_write_parameter.assert_awaited_once_with(
            "bass3", "Z1OpMode", "night"
        )

    def test_write_parameter_publish_error_raises(self) -> None:
        """Verify write_parameter raises HomeAssistantError when publishing fails."""
        entry = MagicMock()
        entry.data = {"mqtt_prefix": "ebusd"}
        coord = SaunierGeniaCoordinator(self.hass, entry)
        coord._active_controller_circuit = "15.bass3"
        coord.async_write_parameter = AsyncMock(
            side_effect=RuntimeError("MQTT connection lost")
        )

        self.hass.data = {DOMAIN: {"e1": coord}}
        _async_register_services(self.hass)
        handler = self.registered_services[SERVICE_WRITE_PARAMETER]

        call = MagicMock()
        call.data = {"circuit": "bass3", "name": "Z1OpMode", "value": "night"}

        with self.assertRaises(HomeAssistantError) as ctx:
            asyncio.run(handler(call))
        self.assertIn("Failed to publish write parameter", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
