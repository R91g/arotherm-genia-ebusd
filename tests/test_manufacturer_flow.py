"""Unit tests for manufacturer selection and unique ID brand-neutrality."""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.config_flow import (
    SaunierGeniaConfigFlow,
    SaunierGeniaOptionsFlowHandler,
)
from custom_components.arotherm_genia_ebusd.const import (
    CONF_AUTO_COOLING_LOCK_BYPASS,
    CONF_EBUSD_TCP_HOST,
    CONF_EBUSD_TCP_PORT,
    CONF_ENABLE_EBUSD_TCP,
    CONF_ENABLE_SEND_HEX,
    CONF_FALLBACK_POLL_INTERVAL,
    CONF_FORCE_DHW_BOOST,
    CONF_MANUFACTURER,
    CONF_MQTT_PREFIX,
    CONF_PREREQUISITES_CONFIRMED,
    DEFAULT_MANUFACTURER,
    DEFAULT_OUTDOOR_MODEL_SAUNIER,
    DEFAULT_OUTDOOR_MODEL_VAILLANT,
    INDOOR_MODEL_SPECS,
    INDOOR_MODELS,
    INDOOR_MODELS_BY_MANUFACTURER,
    MANUFACTURER_SAUNIER_DUVAL,
    MANUFACTURER_VAILLANT,
    MANUFACTURERS,
    OUTDOOR_MODEL_SPECS,
    OUTDOOR_MODELS,
    OUTDOOR_MODELS_BY_MANUFACTURER,
)


class TestManufacturerTopology(unittest.TestCase):
    """Test manufacturer-based models and hardware specification bindings."""

    def test_manufacturer_options(self) -> None:
        """Verify both Saunier Duval and Vaillant are present in supported manufacturers."""
        self.assertIn(MANUFACTURER_SAUNIER_DUVAL, MANUFACTURERS)
        self.assertIn(MANUFACTURER_VAILLANT, MANUFACTURERS)
        self.assertEqual(DEFAULT_MANUFACTURER, MANUFACTURER_SAUNIER_DUVAL)

    def test_outdoor_models_partition(self) -> None:
        """Verify outdoor model dictionaries are correctly partitioned by manufacturer."""
        saunier_models = OUTDOOR_MODELS_BY_MANUFACTURER[MANUFACTURER_SAUNIER_DUVAL]
        vaillant_models = OUTDOOR_MODELS_BY_MANUFACTURER[MANUFACTURER_VAILLANT]

        self.assertIn("GeniaAir Max ES 15", saunier_models)
        self.assertIn("GeniaAir Max 4", saunier_models)
        self.assertIn("aroTHERM plus ES VWL 155/7.1 A 230V", vaillant_models)
        self.assertIn("aroTHERM pro VWL 55/7.1 A 230V", vaillant_models)
        self.assertIn("aroTHERM plus VWL 75/8.1 A 230V", vaillant_models)
        self.assertIn("aroTHERM plus VWL 35/6 A 230V", vaillant_models)
        self.assertEqual(DEFAULT_OUTDOOR_MODEL_SAUNIER, "GeniaAir Max ES 15")
        self.assertEqual(
            DEFAULT_OUTDOOR_MODEL_VAILLANT, "aroTHERM plus ES VWL 155/7.1 A 230V"
        )

    def test_indoor_models_partition(self) -> None:
        """Verify indoor hydraulic models are correctly partitioned by manufacturer."""
        saunier_indoor = INDOOR_MODELS_BY_MANUFACTURER[MANUFACTURER_SAUNIER_DUVAL]
        vaillant_indoor = INDOOR_MODELS_BY_MANUFACTURER[MANUFACTURER_VAILLANT]

        self.assertIn("HPIM 7 230V", saunier_indoor)
        self.assertIn("VWZ MEH 97/7", vaillant_indoor)
        self.assertIn("uniTOWER VIH QW 190/7", vaillant_indoor)

    def test_all_models_have_specs(self) -> None:
        """Verify all listed outdoor and indoor models have specifications defined."""
        for model in OUTDOOR_MODELS:
            self.assertIn(model, OUTDOOR_MODEL_SPECS)
        for model in INDOOR_MODELS:
            self.assertIn(model, INDOOR_MODEL_SPECS)


class TestOptionsFlow(unittest.TestCase):
    """Test suite for integration options flow."""

    def test_options_flow_init_schema_contains_advanced_tcp_options(self) -> None:
        """Verify options flow schema includes advanced TCP section and settings."""
        from custom_components.arotherm_genia_ebusd.const import (
            SECTION_ADVANCED_OPTIONS,
        )

        handler = SaunierGeniaOptionsFlowHandler()
        entry = MagicMock()
        entry.options = {}
        handler.config_entry = entry

        result = asyncio.run(handler.async_step_init())
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")
        schema_keys = [k.schema for k in result["data_schema"].schema]
        self.assertIn(CONF_FORCE_DHW_BOOST, schema_keys)
        self.assertIn(CONF_AUTO_COOLING_LOCK_BYPASS, schema_keys)
        self.assertIn(CONF_FALLBACK_POLL_INTERVAL, schema_keys)
        self.assertIn(SECTION_ADVANCED_OPTIONS, schema_keys)

    def test_options_flow_save_cleans_inputs_and_flattens_section(self) -> None:
        """Verify user input submission cleans host string, casts port, and flattens section."""
        from custom_components.arotherm_genia_ebusd.const import (
            SECTION_ADVANCED_OPTIONS,
        )

        handler = SaunierGeniaOptionsFlowHandler()
        entry = MagicMock()
        entry.options = {}
        handler.config_entry = entry

        user_input = {
            CONF_FORCE_DHW_BOOST: True,
            CONF_AUTO_COOLING_LOCK_BYPASS: False,
            CONF_FALLBACK_POLL_INTERVAL: 180,
            SECTION_ADVANCED_OPTIONS: {
                CONF_ENABLE_EBUSD_TCP: True,
                CONF_EBUSD_TCP_HOST: "  192.168.1.100  ",
                CONF_EBUSD_TCP_PORT: "8888",
                CONF_ENABLE_SEND_HEX: True,
            },
        }

        result = asyncio.run(handler.async_step_init(user_input))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"][CONF_EBUSD_TCP_HOST], "192.168.1.100")
        self.assertEqual(result["data"][CONF_EBUSD_TCP_PORT], 8888)
        self.assertTrue(result["data"][CONF_ENABLE_EBUSD_TCP])
        self.assertTrue(result["data"][CONF_ENABLE_SEND_HEX])

        # Blank host string falls back to default 127.0.0.1
        user_input_empty_host = {
            CONF_FORCE_DHW_BOOST: True,
            CONF_AUTO_COOLING_LOCK_BYPASS: False,
            CONF_FALLBACK_POLL_INTERVAL: 180,
            SECTION_ADVANCED_OPTIONS: {
                CONF_ENABLE_EBUSD_TCP: True,
                CONF_EBUSD_TCP_HOST: "   ",
                CONF_EBUSD_TCP_PORT: 8888,
                CONF_ENABLE_SEND_HEX: False,
            },
        }
        result_empty = asyncio.run(handler.async_step_init(user_input_empty_host))
        self.assertEqual(result_empty["data"][CONF_EBUSD_TCP_HOST], "127.0.0.1")


class TestConfigFlowPrerequisites(unittest.TestCase):
    """Test mandatory initial eBUSd CSV and add-on prerequisites step."""

    def test_user_step_requires_confirmation_before_mqtt_and_models(self) -> None:
        """Initial user step blocks progression until prerequisites are accepted."""
        from unittest.mock import AsyncMock

        flow = SaunierGeniaConfigFlow()
        flow.hass = MagicMock()
        flow.hass.config.components = {"mqtt"}
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        res_init = asyncio.run(flow.async_step_user())
        self.assertEqual(res_init["type"], "form")
        self.assertEqual(res_init["step_id"], "user")
        schema_keys = [k.schema for k in res_init["data_schema"].schema]
        self.assertIn(CONF_PREREQUISITES_CONFIRMED, schema_keys)

        res_rejected = asyncio.run(
            flow.async_step_user({CONF_PREREQUISITES_CONFIRMED: False})
        )
        self.assertEqual(res_rejected["type"], "form")
        self.assertEqual(res_rejected["step_id"], "user")
        self.assertEqual(
            res_rejected["errors"],
            {CONF_PREREQUISITES_CONFIRMED: "prerequisites_not_confirmed"},
        )

        res_accepted = asyncio.run(
            flow.async_step_user({CONF_PREREQUISITES_CONFIRMED: True})
        )
        self.assertEqual(res_accepted["type"], "form")
        self.assertEqual(res_accepted["step_id"], "mqtt")

        res_mqtt = asyncio.run(
            flow.async_step_mqtt(
                {
                    CONF_MQTT_PREFIX: "ebusd",
                    CONF_MANUFACTURER: MANUFACTURER_VAILLANT,
                }
            )
        )
        self.assertEqual(res_mqtt["type"], "form")
        self.assertEqual(res_mqtt["step_id"], "models")


if __name__ == "__main__":
    unittest.main()
