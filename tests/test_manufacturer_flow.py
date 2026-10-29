"""Unit tests for manufacturer selection and unique ID brand-neutrality."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.const import (
    CONF_MANUFACTURER,
    DEFAULT_MANUFACTURER,
    DEFAULT_OUTDOOR_MODEL_SAUNIER,
    DEFAULT_OUTDOOR_MODEL_VAILLANT,
    INDOOR_MODELS_BY_MANUFACTURER,
    MANUFACTURERS,
    MANUFACTURER_SAUNIER_DUVAL,
    MANUFACTURER_VAILLANT,
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
        self.assertIn("GeniaAir Max 4 (Legacy)", saunier_models)
        self.assertIn("aroTHERM plus ES VWL 155/7.1 A 230V", vaillant_models)
        self.assertIn("aroTHERM plus VWL 35/6 A 230V (Legacy)", vaillant_models)
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


if __name__ == "__main__":
    unittest.main()

