"""Unit tests for manufacturer selection and unique ID brand-neutrality."""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.config_flow import (
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


if __name__ == "__main__":
    unittest.main()
