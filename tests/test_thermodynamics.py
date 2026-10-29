"""Unit tests for thermodynamics calculation engine."""

import os
import sys

# Ensure tests/ directory is on path to load setup_mocks
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

# Add hacs directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from custom_components.arotherm_genia_ebusd.thermodynamics import (
    SPECIFIC_HEAT_WATER_FACTOR,
    calculate_delta_t,
    calculate_live_cop,
    calculate_period_cop,
    calculate_thermal_power,
    calculate_total_energy,
)


class TestThermodynamics(unittest.TestCase):
    """Test thermodynamics functions under various operational states."""

    def test_calculate_delta_t(self) -> None:
        """Test delta T calculation and precision."""
        self.assertIsNone(calculate_delta_t(None, 25.0))
        self.assertIsNone(calculate_delta_t(35.0, None))
        self.assertAlmostEqual(calculate_delta_t(42.5, 37.2), 5.3, places=2)
        # Cooling mode (return > flow): delta_t is negative
        self.assertAlmostEqual(calculate_delta_t(12.0, 17.5), -5.5, places=2)

    def test_calculate_thermal_power(self) -> None:
        """Test thermal power calculation, standby clamping, and null handling."""
        # Standby status must return 0.0 W regardless of inputs
        self.assertEqual(calculate_thermal_power(1200.0, 5.0, "standby"), 0.0)
        self.assertEqual(calculate_thermal_power(None, None, "standby"), 0.0)

        # None inputs when not in standby
        self.assertIsNone(calculate_thermal_power(None, 5.0, "heat_compressor_active"))
        self.assertIsNone(
            calculate_thermal_power(1200.0, None, "heat_compressor_active")
        )

        # Normal active heating: 1200 l/h * 5.0 K * 1.163 = 6978.0 W
        expected = round(1200.0 * 5.0 * SPECIFIC_HEAT_WATER_FACTOR, 1)
        self.assertEqual(
            calculate_thermal_power(1200.0, 5.0, "heat_compressor_active"), expected
        )

        # Normal active cooling (negative delta T): absolute value used
        expected_cool = round(1000.0 * 4.5 * SPECIFIC_HEAT_WATER_FACTOR, 1)
        self.assertEqual(
            calculate_thermal_power(1000.0, -4.5, "cool_compressor_active"),
            expected_cool,
        )

    def test_calculate_live_cop(self) -> None:
        """Test COP/EER calculation, threshold filters, and compressor states."""
        active_statuses = frozenset(
            {
                "heat_compressor_active",
                "hwc_compressor_active",
                "cool_compressor_active",
            }
        )

        # Active compressor with power > 60 W: 4500 W / 1000 W = 4.5
        cop, is_active = calculate_live_cop(
            4500.0, 1000.0, "heat_compressor_active", active_statuses
        )
        self.assertEqual(cop, 4.5)
        self.assertTrue(is_active)

        # Standby or deicing: returns (0.0, False)
        cop, is_active = calculate_live_cop(4500.0, 1000.0, "standby", active_statuses)
        self.assertEqual(cop, 0.0)
        self.assertFalse(is_active)

        cop, is_active = calculate_live_cop(4500.0, 1000.0, "deicing", active_statuses)
        self.assertEqual(cop, 0.0)
        self.assertFalse(is_active)

        # Low electrical power (idle/standby consumption <= 60 W)
        cop, is_active = calculate_live_cop(
            0.0, 25.0, "heat_compressor_active", active_statuses
        )
        self.assertEqual(cop, 0.0)
        self.assertFalse(is_active)

    def test_calculate_period_cop(self) -> None:
        """Test cumulative period COP (daily, monthly, total historical)."""
        # None handling
        self.assertIsNone(calculate_period_cop(None, 500.0))
        self.assertIsNone(calculate_period_cop(1500.0, None))

        # Below electrical minimum (e.g. daily energy < 50 Wh)
        self.assertEqual(calculate_period_cop(100.0, 30.0, min_elec_energy=50.0), 0.0)

        # Normal calculation: 12000 Wh thermal / 3000 Wh elec = 4.0
        self.assertEqual(
            calculate_period_cop(12000.0, 3000.0, min_elec_energy=50.0), 4.0
        )
        self.assertEqual(calculate_period_cop(15420.0, 3855.0), 4.0)

    def test_calculate_total_energy(self) -> None:
        """Test total electrical energy combination (Heating + DHW + Cooling)."""
        # None inputs
        self.assertIsNone(calculate_total_energy(None, None, None))

        # Heating 27.6 kWh, DHW 69.5 kWh, Cooling 199300.0 Wh -> 296.4 kWh
        total = calculate_total_energy(27.6, 69.5, 199300.0)
        self.assertEqual(total, 296.4)

        # Partial missing metrics (e.g. no cooling in winter)
        self.assertEqual(calculate_total_energy(28.0, 69.0, None), 97.0)
        self.assertEqual(calculate_total_energy(None, 69.0, 199300.0), 268.3)


if __name__ == "__main__":
    unittest.main()
