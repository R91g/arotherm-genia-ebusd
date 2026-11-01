"""Thermodynamic calculation engine for Saunier Duval GeniaAir Max ES."""

from __future__ import annotations

# Specific heat capacity constant:
# P (W) = FlowRate (l/h) * |Delta T (K)| * (4186 J/(kg*K) / 3600 s) = FlowRate * |Delta T| * 1.163
SPECIFIC_HEAT_WATER_FACTOR = 1.163
MIN_ACTIVE_ELECTRICAL_POWER_W = 60.0
MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH = 50.0


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

    if status_lower in ("standby", "deicing", "deicing_active") or (
        elec_power is not None and elec_power <= MIN_ACTIVE_ELECTRICAL_POWER_W
    ):
        return 0.0, False

    return None, False


def calculate_period_cop(
    thermal_energy: float | None,
    elec_energy: float | None,
    min_elec_energy: float = 0.0,
) -> float | None:
    """Calculate cumulative COP / EER for a given operating mode or total.

    Returns:
        - COP/EER rounded to 2 decimals if electrical energy exceeds the minimum threshold.
        - 0.0 if electrical energy is below threshold.
        - None if either metric is unavailable.
    """
    if thermal_energy is None or elec_energy is None:
        return None

    if elec_energy > min_elec_energy:
        return round(thermal_energy / elec_energy, 2)

    return 0.0


def calculate_combined_efficiency(
    thermal_parts: tuple[float | None, ...],
    elec_parts: tuple[float | None, ...],
    min_elec_energy: float = MIN_CUMULATIVE_ELECTRICAL_ENERGY_WH,
) -> float | None:
    """Calculate cumulative COP / EER across multiple hardware components or modes.

    Requires all component registers to be hydrated (non-None) before emitting
    to avoid transient distortions during initial staggered startup hydration.
    """
    if not thermal_parts or not elec_parts:
        return None
    if any(p is None for p in thermal_parts) or any(p is None for p in elec_parts):
        return None

    total_therm = sum(p for p in thermal_parts if p is not None)
    total_elec = sum(p for p in elec_parts if p is not None)
    return calculate_period_cop(
        total_therm, total_elec, min_elec_energy=min_elec_energy
    )


def calculate_combined_mode_energy(
    outdoor_wh: float | None,
    indoor_wh: float | None,
) -> float | None:
    """Combine outdoor unit (08.hmux0) and indoor hydraulic module (76.vwzio) energy in Wh.

    Strictly waits for both counters to be hydrated (non-None) so TOTAL_INCREASING
    statistics never record an artificial upward step during startup hydration.
    """
    if outdoor_wh is None or indoor_wh is None:
        return None
    return round(outdoor_wh + indoor_wh, 1)


def calculate_system_total_energy(
    heating_total_wh: float | None,
    dhw_total_wh: float | None,
    cooling_wh: float | None,
) -> float | None:
    """Calculate cumulative system electrical energy (Wh) across Heating + DHW + Cooling.

    Strictly requires all 3 service totals to be hydrated (non-None) so Home Assistant's
    Energy Dashboard never logs an artificial step when messages arrive out of order.
    """
    if heating_total_wh is None or dhw_total_wh is None or cooling_wh is None:
        return None
    return round(heating_total_wh + dhw_total_wh + cooling_wh, 1)
