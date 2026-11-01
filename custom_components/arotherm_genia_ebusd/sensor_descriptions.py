"""Sensor entity descriptions for Saunier Duval GeniaAir Max ES & MiPro Sense.

Entity Organization & Device Architecture:
- Section A: Synthetic Thermodynamic & Energy Calculations (CALC_CIRCUIT -> DEVICE_OUTDOOR_UNIT)
  Delta T, instantaneous thermal power (1.163 factor), Live COP, Historical COP/EER, and Combined Wh Totals.
- Section B: Outdoor Unit Sensors (08.hmux0 -> DEVICE_OUTDOOR_UNIT)
  Refrigeration circuit, compressor modulation, temperatures, high pressure, flow rates, and operating statistics.
- Section C: Climate Controller Sensors (15.bass3 -> DEVICE_CLIMATE_CONTROLLER)
  Zone temperatures, weekly timer schedules, heating curves, seasonal windows, and water pressure.
- Section D: Hydraulic Interface (76.vwzio -> DEVICE_HYDRAULIC_INTERFACE)
  Secondary circulation pump states, backup immersion heater runtime, and hydraulic error logs.
- Section E: Wireless Room Thermostat (04.netx3 / f6.netx3 -> DEVICE_WIRELESS_THERMOSTAT)
  Ambient room temperature and RF dial status.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)

from .const import (
    CALC_CIRCUIT,
    CALC_COOL_EER,
    CALC_DELTA_T,
    CALC_DHW_TOTAL_ENERGY,
    CALC_GLOBAL_EFFICIENCY,
    CALC_HC_COP,
    CALC_HEATING_TOTAL_ENERGY,
    CALC_HWC_COP,
    CALC_LIVE_COP,
    CALC_SYSTEM_TOTAL_ENERGY,
    CALC_THERMAL_POWER,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_HMUX0,
    CIRCUIT_NETX3,
    CIRCUIT_NETX3_ALT,
    CIRCUIT_VWZIO,
    DEFAULT_COMFORT_TEMP,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    HMU_STATUS_CODES,
    HWC_STATUS_OPTIONS,
    SENTINEL_HEATING_THRESHOLD,
    SETMODE_HC_MODES,
    SYSTEM_OPERATING_STATES,
    VWZIO_SECONDARY_HWC_OPTIONS,
    VWZIO_SECONDARY_STATUS_OPTIONS,
    Z1_STATUS_OPTIONS,
)
from .coordinator import SaunierGeniaCoordinator

TEMP_DELTA_DEVICE_CLASS = getattr(SensorDeviceClass, "TEMPERATURE_DELTA", None)


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaSensorEntityDescription(SensorEntityDescription):
    """Describe a Saunier Duval eBUSd Sensor entity."""

    device_key: str
    circuit: str
    message: str
    field: str = "value"
    fallback_circuit: str | None = None
    fallback_message: str | None = None
    fallback_field: str | None = None
    is_integer: bool = False
    value_fn: Callable[[SaunierGeniaCoordinator], Any] | None = None
    attr_fn: Callable[[SaunierGeniaCoordinator], dict[str, Any]] | None = None
    requires_wireless_unit: bool = False


def _format_bass3_date(coord: SaunierGeniaCoordinator, message: str) -> str | None:
    """Format CoolingStartDate / CoolingEndDate (day;month;year) into a readable string."""
    msg = coord.get_message(CIRCUIT_BASS3, message)
    if not msg:
        return None
    day = msg.get("day")
    month = msg.get("month")
    year = msg.get("year")
    if day is not None and month is not None and year is not None:
        try:
            return f"{int(day):02d};{int(month):02d};{int(year):02d}"
        except (ValueError, TypeError):
            pass
    val = msg.get("value")
    return str(val) if val is not None else None


def _get_vwzio_error(coord: SaunierGeniaCoordinator) -> str | None:
    """Format vwzio Currenterror (error..error_4), returning 'OK' when all slots are '-' or 0."""
    msg = coord.get_message(CIRCUIT_VWZIO, "Currenterror")
    if not msg:
        return None
    errors: list[str] = []
    for key in ("error", "error_0", "error_1", "error_2", "error_3", "error_4"):
        if key in msg and msg[key] is not None:
            val_str = str(msg[key]).strip()
            if val_str and val_str not in ("-", "0", "65535", "none", "None"):
                errors.append(val_str)
    return ", ".join(errors) if errors else "OK"


def _get_vwzio_secondary_status(coord: SaunierGeniaCoordinator) -> str | None:
    """Return secondary circuit pump / heating state from vwzio in human-readable enum."""
    # 1. First priority: Status01 pumpstate from HPIM 7
    pumpstate = coord.get_str(CIRCUIT_VWZIO, "Status01", "pumpstate")
    if pumpstate is not None:
        p_lower = pumpstate.lower().strip()
        if p_lower in ("off", "0"):
            return "standby"
        if p_lower in ("overrun", "2"):
            return "overrun"
        if p_lower in ("hwc", "4"):
            return "dhw"
        if p_lower in ("on", "1"):
            cooling_rel = coord.get_str(CIRCUIT_BASS3, "CoolingReleaseStatus", "value")
            if cooling_rel and cooling_rel.lower().strip() == "on":
                return "cooling"
            return "heating"

    # 2. Second priority: inspect byte 0 of SecondaryCircuitStatus (HEX:7)
    val = coord.get_str(CIRCUIT_VWZIO, "SecondaryCircuitStatus", "status")
    if val is not None:
        parts = val.strip().split()
        if parts:
            try:
                b0 = int(parts[0], 16)
                if b0 >= 0x20:
                    cooling_rel = coord.get_str(
                        CIRCUIT_BASS3, "CoolingReleaseStatus", "value"
                    )
                    if cooling_rel and cooling_rel.lower().strip() == "on":
                        return "cooling"
                    return "heating"
                return "standby"
            except ValueError:
                pass

    # 3. Third priority: Hc1PumpStatus from regulator
    hc1_pump = coord.get_int(CIRCUIT_BASS3, "Hc1PumpStatus", "value")
    if hc1_pump == 1:
        return "heating"
    if hc1_pump == 0:
        return "standby"

    return "standby"


def _get_vwzio_secondary_attrs(
    coord: SaunierGeniaCoordinator,
) -> dict[str, Any]:
    """Return extra attributes for vwzio secondary circuit status."""
    msg = coord.get_message(CIRCUIT_VWZIO, "SecondaryCircuitStatus") or {}
    status01 = coord.get_message(CIRCUIT_VWZIO, "Status01") or {}
    attrs: dict[str, Any] = {
        "valvestate": msg.get("valvestate"),
        "raw_status": msg.get("status"),
        "pumpstate": status01.get("pumpstate"),
        "flow_temp": status01.get("flow_temp", status01.get("temp")),
        "return_temp": status01.get("return_temp", status01.get("temp_1")),
        "storage_temp": status01.get("storage_temp", status01.get("temp_4")),
    }
    val = msg.get("status")
    if val and isinstance(val, str):
        parts = val.strip().split()
        if len(parts) >= 2:
            try:
                b0 = int(parts[0], 16)
                b1 = int(parts[1], 16)
                attrs["raw_int16"] = b0 + (b1 << 8)
            except ValueError:
                pass
    return {k: v for k, v in attrs.items() if v is not None}


def _get_vwzio_secondary_hwc_status(coord: SaunierGeniaCoordinator) -> str | None:
    """Return secondary circuit DHW state."""
    pumpstate = coord.get_str(CIRCUIT_VWZIO, "Status01", "pumpstate")
    if pumpstate is not None:
        p_lower = pumpstate.lower().strip()
        if p_lower in ("hwc", "4"):
            return "dhw"
        if p_lower in ("off", "0", "on", "1", "overrun", "2"):
            return "standby"

    msg = coord.get_str(CIRCUIT_VWZIO, "SecondaryCircuitStatusHwc", "status")
    if msg:
        parts = msg.strip().split()
        if parts:
            try:
                b0 = int(parts[0], 16)
                if b0 >= 0x20:
                    return "dhw"
            except ValueError:
                pass
        return "dhw"
    return "standby"


def _get_vwzio_secondary_hwc_attrs(
    coord: SaunierGeniaCoordinator,
) -> dict[str, Any]:
    """Return extra attributes for vwzio secondary circuit DHW status."""
    msg = coord.get_message(CIRCUIT_VWZIO, "SecondaryCircuitStatusHwc") or {}
    return {
        "raw_status": msg.get("status"),
    }


def _get_broadcast_datetime(coord: SaunierGeniaCoordinator) -> str | None:
    """Combine Broadcast/Vdatetime date and time."""
    msg = coord.get_message(CIRCUIT_BROADCAST, "Vdatetime")
    if not msg:
        msg = coord.get_message(CIRCUIT_BROADCAST, "Datetime")
    if not msg:
        return None
    date_val = msg.get("date")
    time_val = msg.get("time")
    if date_val and time_val:
        return f"{date_val} {time_val}"
    return str(date_val or time_val) if (date_val or time_val) else None


def _get_z1_actual_desired_filtered(
    coord: SaunierGeniaCoordinator,
) -> float | None:
    """Return Z1ActualRoomTempDesired filtering the 5.0°C off sentinel."""
    val = coord.get_float(CIRCUIT_BASS3, "Z1ActualRoomTempDesired", "value")
    if val is None:
        return None
    if val <= SENTINEL_HEATING_THRESHOLD:
        op_mode = (coord.get_str(CIRCUIT_BASS3, "Z1OpMode", "value") or "").lower()
        if op_mode == "off":
            day_temp = coord.get_float(CIRCUIT_BASS3, "Z1DayTemp", "value")
            return day_temp if day_temp is not None else DEFAULT_COMFORT_TEMP
    return round(val, 2)


def _get_live_cop_attrs(coord: SaunierGeniaCoordinator) -> dict[str, Any]:
    """Return last_active_cop attribute for calculated_live_cop."""
    return {"last_active_cop": coord.last_active_cop}


SENSOR_DESCRIPTIONS: tuple[SaunierGeniaSensorEntityDescription, ...] = (
    # =========================================================================
    # B) Outdoor Unit Sensors (08.hmux0 -> DEVICE_OUTDOOR_UNIT)
    # =========================================================================
    SaunierGeniaSensorEntityDescription(
        key="hmu_status_code",
        translation_key="hmu_status_code",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="HMUStatusCode",
        field="status",
        device_class=SensorDeviceClass.ENUM,
        options=HMU_STATUS_CODES,
    ),
    SaunierGeniaSensorEntityDescription(
        key="electric_power_consumption",
        translation_key="electric_power_consumption",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataElectricPowerConsumption",
        field="power",
        fallback_circuit=CIRCUIT_HMUX0,
        fallback_message="PowerStatus",
        fallback_field="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_thermal_power",
        translation_key="calculated_thermal_power",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_THERMAL_POWER,
        field="value",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_delta_t",
        translation_key="calculated_delta_t",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_DELTA_T,
        field="value",
        native_unit_of_measurement="K",
        device_class=TEMP_DELTA_DEVICE_CLASS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_live_cop",
        translation_key="calculated_live_cop",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_LIVE_COP,
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        attr_fn=_get_live_cop_attrs,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_hc_cop",
        translation_key="calculated_hc_cop",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_HC_COP,
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_hwc_cop",
        translation_key="calculated_hwc_cop",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_HWC_COP,
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_cool_eer",
        translation_key="calculated_cool_eer",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_COOL_EER,
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_global_efficiency",
        translation_key="calculated_global_efficiency",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_GLOBAL_EFFICIENCY,
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_system_total_energy",
        translation_key="calculated_system_total_energy",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_SYSTEM_TOTAL_ENERGY,
        field="value",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_heating_total_energy",
        translation_key="calculated_heating_total_energy",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_HEATING_TOTAL_ENERGY,
        field="value",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="calculated_dhw_total_energy",
        translation_key="calculated_dhw_total_energy",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message=CALC_DHW_TOTAL_ENERGY,
        field="value",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="primary_flow_rate",
        translation_key="primary_flow_rate",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataFlowRate",
        field="value",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="refrigerant_high_pressure",
        translation_key="refrigerant_high_pressure",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataHighPressure",
        field="press",
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="flow_temp_precision",
        translation_key="flow_temp_precision",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataFlowTemp",
        field="value",
        fallback_circuit=CIRCUIT_HMUX0,
        fallback_message="Status01",
        fallback_field="temp1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="return_temp_precision",
        translation_key="return_temp_precision",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataReturnTemp",
        field="value",
        fallback_circuit=CIRCUIT_HMUX0,
        fallback_message="Status01",
        fallback_field="return_temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="air_inlet_temp",
        translation_key="air_inlet_temp",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataAirInletTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="compressor_inlet_temp",
        translation_key="compressor_inlet_temp",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataCompressorInletTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="compressor_outlet_temp",
        translation_key="compressor_outlet_temp",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataCompressorOutletTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="eev_outlet_temp",
        translation_key="eev_outlet_temp",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataEEVOutletTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="condenser_out_temp",
        translation_key="condenser_out_temp",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataCondenserOutTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="building_cpump_power",
        translation_key="building_cpump_power",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataBuildingCPumpPower",
        field="value",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="compressor_speed_rpm",
        translation_key="compressor_speed_rpm",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="StateCompressor",
        field="comp_speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="compressor_speed_rps",
        translation_key="compressor_speed_rps",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataCompressorSpeed",
        field="value",
        native_unit_of_measurement="rps",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="compressor_modulation",
        translation_key="compressor_modulation",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="StateCompressor",
        field="modulation",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="fan1_speed",
        translation_key="fan1_speed",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataFan1Speed",
        field="value",
        fallback_circuit=CIRCUIT_HMUX0,
        fallback_message="StateCompressor",
        fallback_field="fan_speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="fan2_speed",
        translation_key="fan2_speed",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataFan2Speed",
        field="value",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
        entity_registry_enabled_default=False,
    ),
    SaunierGeniaSensorEntityDescription(
        key="eev_position_abs",
        translation_key="eev_position_abs",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunDataEEVPositionAbs",
        field="value",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="setmode_flow_temp_desired",
        translation_key="setmode_flow_temp_desired",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="SetMode",
        field="flowtempdesired",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="setmode_hc_mode",
        translation_key="setmode_hc_mode",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="SetMode",
        field="hcmode",
        device_class=SensorDeviceClass.ENUM,
        options=SETMODE_HC_MODES,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_electric_cool",
        translation_key="energy_electric_cool",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyElectricCool",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_thermal_hc",
        translation_key="energy_thermal_hc",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyThermalHc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_thermal_hwc",
        translation_key="energy_thermal_hwc",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyThermalHwc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_thermal_cool",
        translation_key="energy_thermal_cool",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyThermalCool",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_env_yield_hc",
        translation_key="energy_env_yield_hc",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyEnvYieldHc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_env_yield_hwc",
        translation_key="energy_env_yield_hwc",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyEnvYieldHwc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_electric_hc_outdoor",
        translation_key="energy_electric_hc_outdoor",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyElectricHc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="energy_electric_hwc_outdoor",
        translation_key="energy_electric_hwc_outdoor",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PrEnergyElectricHwc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_hmu_hours",
        translation_key="stats_hmu_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsHMUHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_compressor_hours",
        translation_key="stats_compressor_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsCompressorHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_compressor_starts",
        translation_key="stats_compressor_starts",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsCompressorStarts",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_hc_hours",
        translation_key="stats_hc_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsHcHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_hc_starts",
        translation_key="stats_hc_starts",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsHcStarts",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_hwc_hours",
        translation_key="stats_hwc_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsHwcHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_hwc_starts",
        translation_key="stats_hwc_starts",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsHwcStarts",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_building_cpump_hours",
        translation_key="stats_building_cpump_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsBuildingPumpHours",
        field="value",
        fallback_circuit=CIRCUIT_HMUX0,
        fallback_message="RunStatsBuildingCPumpHours",
        fallback_field="hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_building_cpump_starts",
        translation_key="stats_building_cpump_starts",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsBuildingCPumpStarts",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_4port_valve_hours",
        translation_key="stats_4port_valve_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStats4PortValveHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_4port_valve_switches",
        translation_key="stats_4port_valve_switches",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStats4PortValveSwitches",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_fan1_hours",
        translation_key="stats_fan1_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsFan1Hours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_fan2_hours",
        translation_key="stats_fan2_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsFan2Hours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
        entity_registry_enabled_default=False,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_deice_hours",
        translation_key="stats_deice_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsDeiceHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_immersion_heater_hours",
        translation_key="stats_immersion_heater_hours",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsImmersionHeaterHours",
        field="value",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
        entity_registry_enabled_default=False,
    ),
    SaunierGeniaSensorEntityDescription(
        key="stats_immersion_heater_starts",
        translation_key="stats_immersion_heater_starts",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="RunStatsImmersionHeaterStarts",
        field="value",
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
        entity_registry_enabled_default=False,
    ),
    # =========================================================================
    # C) Climate Controller Sensors (15.bass3 -> DEVICE_CLIMATE_CONTROLLER)
    # =========================================================================
    SaunierGeniaSensorEntityDescription(
        key="system_operating_state",
        translation_key="system_operating_state",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="SystemOperatingState",
        field="value",
        device_class=SensorDeviceClass.ENUM,
        options=SYSTEM_OPERATING_STATES,
    ),
    SaunierGeniaSensorEntityDescription(
        key="water_pressure",
        translation_key="water_pressure",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="WaterPressure",
        field="press",
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="displayed_outside_temp",
        translation_key="displayed_outside_temp",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="DisplayedOutsideTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="outside_temp_avg",
        translation_key="outside_temp_avg",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="OutsideTempAvg",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="z1_room_temp",
        translation_key="z1_room_temp",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1RoomTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="z1_actual_room_temp_desired",
        translation_key="z1_actual_room_temp_desired",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1ActualRoomTempDesired",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_get_z1_actual_desired_filtered,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hc1_flow_temp",
        translation_key="hc1_flow_temp",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Hc1FlowTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hc1_actual_flow_temp_desired",
        translation_key="hc1_actual_flow_temp_desired",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Hc1ActualFlowTempDesired",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hwc_storage_temp",
        translation_key="hwc_storage_temp",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HwcStorageTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hwc_flow_temp",
        translation_key="hwc_flow_temp",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HwcFlowTemp",
        field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="z1_status",
        translation_key="z1_status",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1Status",
        field="value",
        device_class=SensorDeviceClass.ENUM,
        options=Z1_STATUS_OPTIONS,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hwc_status",
        translation_key="hwc_status",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HwcStatus",
        field="value",
        device_class=SensorDeviceClass.ENUM,
        options=HWC_STATUS_OPTIONS,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hc1_pump_status",
        translation_key="hc1_pump_status",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Hc1PumpStatus",
        field="value",
        state_class=SensorStateClass.MEASUREMENT,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="hydraulic_scheme",
        translation_key="hydraulic_scheme",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HydraulicScheme",
        field="value",
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="cooling_start_date",
        translation_key="cooling_start_date",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="CoolingStartDate",
        field="day;month;year",
        value_fn=lambda coord: _format_bass3_date(coord, "CoolingStartDate"),
    ),
    SaunierGeniaSensorEntityDescription(
        key="cooling_end_date",
        translation_key="cooling_end_date",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="CoolingEndDate",
        field="day;month;year",
        value_fn=lambda coord: _format_bass3_date(coord, "CoolingEndDate"),
    ),
    SaunierGeniaSensorEntityDescription(
        key="holiday_start_date",
        translation_key="holiday_start_date",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HolidayStartDate",
        field="day;month;year",
        value_fn=lambda coord: _format_bass3_date(coord, "HolidayStartDate"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="holiday_end_date",
        translation_key="holiday_end_date",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HolidayEndDate",
        field="day;month;year",
        value_fn=lambda coord: _format_bass3_date(coord, "HolidayEndDate"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="holiday_duration_remaining",
        translation_key="holiday_duration_remaining",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="HolidayEndDate",
        field="day",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda coord: coord.get_holiday_remaining_days(),
        attr_fn=lambda coord: coord.get_holiday_remaining_attributes(),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="cooling_duration_remaining",
        translation_key="cooling_duration_remaining",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="CoolingEndDate",
        field="day",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda coord: coord.get_cooling_remaining_days(),
        attr_fn=lambda coord: coord.get_cooling_remaining_attributes(),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hc_this_month",
        translation_key="bass3_energy_hc_this_month",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHcThisMonth",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hc_last_month",
        translation_key="bass3_energy_hc_last_month",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHcLastMonth",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hc_total",
        translation_key="bass3_energy_hc_total",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHc",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hwc_this_month",
        translation_key="bass3_energy_hwc_this_month",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHwcThisMonth",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hwc_last_month",
        translation_key="bass3_energy_hwc_last_month",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHwcLastMonth",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="bass3_energy_hwc_total",
        translation_key="bass3_energy_hwc_total",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="PrEnergySumHwc",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="yield_total",
        translation_key="yield_total",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="YieldTotal",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="solar_yield_total",
        translation_key="solar_yield_total",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="SolarYieldTotal",
        field="value",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_integer=True,
        entity_registry_enabled_default=False,
    ),
    # =========================================================================
    # D) Hydraulic Interface (76.vwzio) & Wireless Thermostat (04 / Broadcast)
    # =========================================================================
    SaunierGeniaSensorEntityDescription(
        key="vwzio_secondary_circuit_status",
        translation_key="vwzio_secondary_circuit_status",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="SecondaryCircuitStatus",
        field="status",
        device_class=SensorDeviceClass.ENUM,
        options=VWZIO_SECONDARY_STATUS_OPTIONS,
        fallback_circuit=CIRCUIT_VWZIO,
        fallback_message="Status01",
        fallback_field="pumpstate",
        value_fn=_get_vwzio_secondary_status,
        attr_fn=_get_vwzio_secondary_attrs,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_secondary_circuit_hwc",
        translation_key="vwzio_secondary_circuit_hwc",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="SecondaryCircuitStatusHwc",
        field="status",
        device_class=SensorDeviceClass.ENUM,
        options=VWZIO_SECONDARY_HWC_OPTIONS,
        value_fn=_get_vwzio_secondary_hwc_status,
        attr_fn=_get_vwzio_secondary_hwc_attrs,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_current_error",
        translation_key="vwzio_current_error",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="Currenterror",
        field="error",
        value_fn=_get_vwzio_error,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_electric_power",
        translation_key="vwzio_electric_power",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="PowerStatus",
        field="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_energy_electric_hc",
        translation_key="vwzio_energy_electric_hc",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="PrEnergyElectricHc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_energy_electric_hwc",
        translation_key="vwzio_energy_electric_hwc",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="PrEnergyElectricHwc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_energy_thermal_hc",
        translation_key="vwzio_energy_thermal_hc",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="PrEnergyThermalHc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SaunierGeniaSensorEntityDescription(
        key="vwzio_energy_thermal_hwc",
        translation_key="vwzio_energy_thermal_hwc",
        device_key=DEVICE_HYDRAULIC_INTERFACE,
        circuit=CIRCUIT_VWZIO,
        message="PrEnergyThermalHwc",
        field="energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SaunierGeniaSensorEntityDescription(
        key="wireless_room_temp_dial",
        translation_key="wireless_room_temp_dial",
        device_key=DEVICE_WIRELESS_THERMOSTAT,
        circuit=CIRCUIT_NETX3,
        message="RoomTempDial",
        field="temp",
        fallback_circuit=CIRCUIT_NETX3_ALT,
        fallback_message="RoomTempDial",
        fallback_field="temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        requires_wireless_unit=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="wireless_room_target_temp",
        translation_key="wireless_room_target_temp",
        device_key=DEVICE_WIRELESS_THERMOSTAT,
        circuit=CIRCUIT_NETX3,
        message="RoomTargetTemp",
        field="temp",
        fallback_circuit=CIRCUIT_BASS3,
        fallback_message="Z1DayTemp",
        fallback_field="value",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        requires_wireless_unit=True,
    ),
    SaunierGeniaSensorEntityDescription(
        key="broadcast_outside_temp",
        translation_key="broadcast_outside_temp",
        device_key=DEVICE_WIRELESS_THERMOSTAT,
        circuit=CIRCUIT_BROADCAST,
        message="Outsidetemp",
        field="temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SaunierGeniaSensorEntityDescription(
        key="broadcast_datetime",
        translation_key="broadcast_datetime",
        device_key=DEVICE_WIRELESS_THERMOSTAT,
        circuit=CIRCUIT_BROADCAST,
        message="Vdatetime",
        field="date;time",
        fallback_circuit=CIRCUIT_BROADCAST,
        fallback_message="Datetime",
        fallback_field="date",
        value_fn=_get_broadcast_datetime,
    ),
)

WEEKLY_SCHEDULE_SENSORS: tuple[tuple[str, str], ...] = (
    ("z1_weekly_schedule_summary", "Z1Timer"),
    ("hwc_weekly_schedule_summary", "HwcTimer"),
    ("cooling_weekly_schedule_summary", "CoolingTimer"),
    ("circulation_weekly_schedule_summary", "CirculationTimer"),
)
