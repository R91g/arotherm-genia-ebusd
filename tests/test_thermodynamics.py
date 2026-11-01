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
    calculate_combined_efficiency,
    calculate_combined_mode_energy,
    calculate_delta_t,
    calculate_live_cop,
    calculate_period_cop,
    calculate_system_total_energy,
    calculate_thermal_power,
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

    def test_calculate_combined_mode_energy_and_system_total(self) -> None:
        """Test Wh mode totals (08.hmux0 + 76.vwzio) and partial-hydration guards."""
        # Partial hydration must strictly return None to protect TOTAL_INCREASING
        self.assertIsNone(calculate_combined_mode_energy(None, None))
        self.assertIsNone(calculate_combined_mode_energy(19876.6, None))
        self.assertIsNone(calculate_combined_mode_energy(None, 8375.9))

        # Verified hardware audit values (Wh):
        # Heating: 19876.6 (hmux0) + 8375.9 (vwzio) = 28252.5 Wh
        heating_wh = calculate_combined_mode_energy(19876.6, 8375.9)
        self.assertEqual(heating_wh, 28252.5)

        # DHW: 69524.0 (hmux0) + 0.0 (vwzio) = 69524.0 Wh
        dhw_wh = calculate_combined_mode_energy(69524.0, 0.0)
        self.assertEqual(dhw_wh, 69524.0)

        # System total partial hydration guards
        self.assertIsNone(calculate_system_total_energy(None, 69524.0, 218460.1))
        self.assertIsNone(calculate_system_total_energy(28252.5, None, 218460.1))
        self.assertIsNone(calculate_system_total_energy(28252.5, 69524.0, None))

        # System total: 28252.5 + 69524.0 + 218460.1 = 316236.6 Wh (Parent == sum of 3 Children)
        cool_wh = 218460.1
        total_wh = calculate_system_total_energy(heating_wh, dhw_wh, cool_wh)
        self.assertEqual(total_wh, 316236.6)
        self.assertEqual(total_wh, round(heating_wh + dhw_wh + cool_wh, 1))

    def test_calculate_combined_efficiency(self) -> None:
        """Test verified mode COP/EER and global efficiency across 08.hmux0 + 76.vwzio."""
        # Partial hydration must return None
        self.assertIsNone(
            calculate_combined_efficiency((46218.2, None), (19876.6, 8375.9))
        )
        self.assertIsNone(
            calculate_combined_efficiency((46218.2, 0.0), (19876.6, None))
        )

        # Below minimum threshold returns 0.0
        self.assertEqual(
            calculate_combined_efficiency(
                (40.0, 0.0), (20.0, 10.0), min_elec_energy=50.0
            ),
            0.0,
        )

        # Verified hardware audit values:
        # 1. Heating COP: 46218.2 / (19876.6 + 8375.9) = 1.64
        self.assertEqual(
            calculate_combined_efficiency((46218.2, 0.0), (19876.6, 8375.9)),
            1.64,
        )
        # 2. DHW COP: 246403.5 / (69524.0 + 0.0) = 3.54
        self.assertEqual(
            calculate_combined_efficiency((246403.5, 0.0), (69524.0, 0.0)),
            3.54,
        )
        # 3. Cooling EER: 981270.4 / 218460.1 = 4.49
        self.assertEqual(
            calculate_period_cop(981270.4, 218460.1, min_elec_energy=50.0),
            4.49,
        )
        # 4. Global Efficiency (Heating + DHW + Cooling): 1273892.1 / 316236.6 = 4.03
        self.assertEqual(
            calculate_combined_efficiency(
                (46218.2, 0.0, 246403.5, 0.0, 981270.4),
                (19876.6, 8375.9, 69524.0, 0.0, 218460.1),
            ),
            4.03,
        )


if __name__ == "__main__":
    unittest.main()
