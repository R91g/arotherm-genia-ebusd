"""Thermodynamic calculation engine for Saunier Duval GeniaAir Max ES."""

from __future__ import annotations

# Specific heat capacity constant:
# P (W) = FlowRate (l/h) * |Delta T (K)| * (4186 J/(kg*K) / 3600 s) = FlowRate * |Delta T| * 1.163
SPECIFIC_HEAT_WATER_FACTOR = 1.163
MIN_ACTIVE_ELECTRICAL_POWER_W = 60.0
MIN_DAILY_ELECTRICAL_ENERGY_WH = 50.0


def calculate_delta_t(
    flow_temp: float | None, return_temp: float | None
) -> float | None:
    """Calculate temperature difference between flow and return in Kelvin."""
    if flow_temp is None or return_temp is None:
        return None
    return round(flow_temp - return_temp, 2)


def calculate_thermal_power(
    flow_rate: float | None,
    delta_t: float | None,
    hmu_status: str,
) -> float | None:
    """Calculate instantaneous thermal power in Watts.

    When the unit is in standby, thermal output is strictly 0.0 W.
    Otherwise, P = FlowRate (l/h) * |Delta T| * 1.163 W.
    """
    status_lower = (hmu_status or "").lower()
    if status_lower == "standby":
        return 0.0

    if flow_rate is None or delta_t is None:
        return None

    return round(max(0.0, flow_rate * abs(delta_t) * SPECIFIC_HEAT_WATER_FACTOR), 1)


def calculate_live_cop(
    thermal_power: float | None,
    elec_power: float | None,
    hmu_status: str,
    active_compressor_statuses: frozenset[str],
) -> tuple[float | None, bool]:
    """Calculate instantaneous COP / EER.

    Returns:
        tuple[cop_value, is_active_heating_or_cooling]:
        - If compressor is active and electrical power > 60 W: (COP, True)
        - If standby or defrost: (0.0, False)
        - Otherwise: (None, False)
    """
    status_lower = (hmu_status or "").lower()

    if (
        elec_power is not None
        and elec_power > MIN_ACTIVE_ELECTRICAL_POWER_W
        and status_lower in active_compressor_statuses
        and thermal_power is not None
    ):
        cop = round(thermal_power / elec_power, 2)
        return cop, True

    if (
        status_lower in ("standby", "deicing", "deicing_active")
        or (elec_power is not None and elec_power <= MIN_ACTIVE_ELECTRICAL_POWER_W)
    ):
        return 0.0, False

    return None, False


def calculate_period_cop(
    thermal_energy: float | None,
    elec_energy: float | None,
    min_elec_energy: float = 0.0,
) -> float | None:
    """Calculate cumulative COP for a given time window (daily, monthly, or total historical SCOP).

    Returns:
        - COP rounded to 2 decimals if electrical energy exceeds the minimum threshold.
        - 0.0 if electrical energy is below threshold.
        - None if either metric is unavailable.
    """
    if thermal_energy is None or elec_energy is None:
        return None

    if elec_energy > min_elec_energy:
        return round(thermal_energy / elec_energy, 2)

    return 0.0


def calculate_total_energy(
    heating_kwh: float | None,
    dhw_kwh: float | None,
    cooling_wh: float | None,
) -> float | None:
    """Calculate cumulative total electrical energy (kWh) from heating, DHW, and cooling.

    Returns:
        - Sum in kWh rounded to 1 decimal place.
        - None if all inputs are None.
    """
    if heating_kwh is None and dhw_kwh is None and cooling_wh is None:
        return None

    h = heating_kwh if heating_kwh is not None else 0.0
    d = dhw_kwh if dhw_kwh is not None else 0.0
    c = (cooling_wh / 1000.0) if cooling_wh is not None else 0.0
    return round(h + d + c, 1)


