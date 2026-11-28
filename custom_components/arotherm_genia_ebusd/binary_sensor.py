"""Binary Sensor platform for Saunier Duval GeniaAir Max ES & MiPro Sense."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CALC_CIRCUIT,
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    CIRCUIT_VR70,
    CIRCUIT_VWZIO,
    CONTROLLER_CIRCUITS,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_MIXER_MODULE,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
    HMU_FAULT_STATUS_CODES,
    OUTDOOR_CIRCUITS,
    WATER_PRESSURE_HIGH_BAR,
    WATER_PRESSURE_LOW_BAR,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity
from .sensor_descriptions import (
    _get_controller_error,
    _get_outdoor_error,
    _get_vr70_error,
    _get_vwzio_error,
)


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Saunier Duval eBUSd Binary Sensor entity."""

    device_key: str
    circuit: str
    message: str
    field: str
    is_on_fn: Callable[[SaunierGeniaCoordinator], bool | None]
    attr_fn: Callable[[SaunierGeniaCoordinator], dict[str, Any]] | None = None
    requires_vr70: bool = False


def _check_compressor_active(coord: SaunierGeniaCoordinator) -> bool | None:
    state_bytes = coord.get_str(CIRCUIT_HMUX0, "StateCompressor", "state_bytes")
    if state_bytes:
        parts = state_bytes.strip().split()
        if len(parts) >= 4:
            try:
                b5 = int(parts[0], 16)
                b8 = int(parts[3], 16)
                return b5 == 0x09 or b8 > 0
            except ValueError:
                pass
    status = coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status")
    if status is not None:
        s_lower = status.lower().strip()
        if s_lower in (
            "heat_compressor_active",
            "hwc_compressor_active",
            "cool_compressor_active",
            "deicing",
            "deicing_active",
        ):
            return True
        if s_lower in (
            "standby",
            "frost_protect",
            "heat_prerun",
            "hwc_prerun",
            "cool_prerun",
            "heat_overrun",
            "hwc_overrun",
            "cool_overrun",
            "heat_compressor_shutdown",
            "heat_compressor_blocked",
            "hwc_compressor_blocked",
            "cool_compressor_shutdown",
            "cool_compressor_blocked",
        ):
            return False
    rps = coord.get_float(CIRCUIT_HMUX0, "RunDataCompressorSpeed", "value")
    if rps is not None:
        return rps > 0
    modulation = coord.get_float(CIRCUIT_HMUX0, "StateCompressor", "modulation")
    if modulation is not None:
        return modulation > 0
    return None


def _check_primary_pump(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_HMUX0, "StatusCirPump", "value")
    if val is None:
        return None
    return val.lower() in ("on", "100", "1", "true")


def _check_defrost_active(coord: SaunierGeniaCoordinator) -> bool | None:
    status = coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status")
    if status is None:
        return None
    return status.lower() in ("deicing", "deicing_active", "516")


def _check_energy_integration(coord: SaunierGeniaCoordinator) -> bool | None:
    status = coord.get_str(CIRCUIT_HMUX0, "PowerStatus", "status")
    if status is None:
        return None
    return status.lower() in (
        "active",
        "heating",
        "hwc",
        "cooling",
        "defrost",
        "1",
        "2",
        "3",
        "4",
    )


def _check_z1_heating_demand(coord: SaunierGeniaCoordinator) -> bool | None:
    status = coord.get_str(CIRCUIT_BASS3, "Z1HeatingState", "value")
    if status is None:
        return None
    return status.lower() in ("on", "1", "true")


def _check_cooling_release(coord: SaunierGeniaCoordinator) -> bool | None:
    """Check literal hardware cooling authorization from BASS3 CoolingReleaseStatus.

    Returns True (Authorized) ONLY when the heat pump firmware physically authorizes cooling
    (which requires both active calendar dates AND outdoor temperature >= 15 °C).
    Returns False (Blocked) if blocked by calendar dates or cold outdoor temperature.
    """
    status = coord.get_str(CIRCUIT_BASS3, "CoolingReleaseStatus", "value")
    if status is None:
        return None
    return status.lower() in ("on", "1", "true")


def _check_broadcast_cooling(coord: SaunierGeniaCoordinator) -> bool | None:
    status = coord.get_str(CIRCUIT_BROADCAST, "CoolingStatus", "status")
    if status is None:
        return None
    return status.lower() in ("on", "1", "true")


def _check_ebusd_signal(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_GLOBAL, "signal", "value")
    if val is None:
        return None
    return val.lower() in ("true", "1", "on", "yes")


def _check_ebusd_running(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_GLOBAL, "running", "value")
    if val is None:
        return None
    return val.lower() in ("true", "1", "on", "yes")


def _check_maintenance_due(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_BASS3, "MaintenanceDue", "value")
    if val is None:
        return None
    return val.lower() in ("yes", "1", "on", "true")


def _check_app_session_status(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_BASS3, "AppSessionStatus", "status")
    if val is None:
        return None
    return val.lower() in ("connected", "1", "on", "true")


def _check_z1_time_slot_active(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_BASS3, "Z1TimeSlotActive", "value")
    if val is None:
        return None
    return val.lower() in ("yes", "1", "on", "true")


def _check_z1_cooling_time_slot_active(coord: SaunierGeniaCoordinator) -> bool | None:
    val = coord.get_str(CIRCUIT_BASS3, "Z1CoolingTimeSlotActive", "value")
    if val is None:
        return None
    return val.lower() in ("yes", "1", "on", "true")


def _get_hmu_fault_status(coord: SaunierGeniaCoordinator) -> str | None:
    """Return the active HMUStatusCode if it represents a fault/protection code, else None."""
    status = coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status")
    if status is None:
        return None
    s_lower = status.lower().strip()
    return s_lower if s_lower in HMU_FAULT_STATUS_CODES else None


def _get_system_water_pressure(coord: SaunierGeniaCoordinator) -> float | None:
    """Return hydraulic water pressure (bar) from controller WaterPressure or HMU FlowPressure."""
    pressure = coord.get_float(CIRCUIT_BASS3, "WaterPressure", "press")
    if pressure is None:
        pressure = coord.get_float(CIRCUIT_HMUX0, "FlowPressure", "value")
    return round(pressure, 2) if pressure is not None else None


def _check_vr70_mc1_pump(coord: SaunierGeniaCoordinator) -> bool | None:
    """Return True if VR 70 mixer circuit 1 pump is running."""
    val = coord.get_str(CIRCUIT_VR70, "Mc1Operation", "pump")
    if val is None:
        return None
    return val.lower() in ("on", "1", "true", "yes")


def _check_vr70_mc2_pump(coord: SaunierGeniaCoordinator) -> bool | None:
    """Return True if VR 70 mixer circuit 2 pump is running."""
    val = coord.get_str(CIRCUIT_VR70, "Mc2Operation", "pump")
    if val is None:
        return None
    return val.lower() in ("on", "1", "true", "yes")


def _check_active_fault(coord: SaunierGeniaCoordinator) -> bool | None:
    """Return True if any board reports Currenterror or HMUStatusCode is a fault code, False if OK, None if unhydrated."""
    statuses = (
        _get_outdoor_error(coord),
        _get_controller_error(coord),
        _get_vwzio_error(coord),
        _get_vr70_error(coord),
    )
    reported = [s for s in statuses if s is not None]
    hmu_status = coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status")
    if not reported and hmu_status is None:
        return None
    if any(s != "OK" for s in reported):
        return True
    return _get_hmu_fault_status(coord) is not None


def _get_active_fault_attrs(coord: SaunierGeniaCoordinator) -> dict[str, Any]:
    """Return per-board Currenterror and HMUStatusCode fault diagnostics for active_fault."""
    attrs: dict[str, Any] = {
        "outdoor_unit": _get_outdoor_error(coord),
        "climate_controller": _get_controller_error(coord),
        "hydraulic_interface": _get_vwzio_error(coord),
        "mixer_module": _get_vr70_error(coord),
        "hmu_fault_status": _get_hmu_fault_status(coord),
    }
    return {k: v for k, v in attrs.items() if v is not None}


def _evaluate_system_health(
    coord: SaunierGeniaCoordinator,
) -> tuple[bool | None, dict[str, Any]]:
    """Evaluate aggregated heat-pump health alerts across faults, HMU status, pressure, and eBUS link."""
    outdoor_err = _get_outdoor_error(coord)
    controller_err = _get_controller_error(coord)
    hydraulic_err = _get_vwzio_error(coord)
    vr70_err = _get_vr70_error(coord)
    hmu_raw = coord.get_str(CIRCUIT_HMUX0, "HMUStatusCode", "status")
    hmu_fault = _get_hmu_fault_status(coord)
    pressure = _get_system_water_pressure(coord)
    ebus_known = (
        coord.get_str(CIRCUIT_GLOBAL, "running", "value") is not None
        or coord.get_str(CIRCUIT_GLOBAL, "signal", "value") is not None
        or coord._last_telemetry_time is not None
    )
    ebus_ok = coord.is_ebus_operational

    any_hydrated = (
        any(
            x is not None
            for x in (
                outdoor_err,
                controller_err,
                hydraulic_err,
                vr70_err,
                hmu_raw,
                pressure,
            )
        )
        or ebus_known
    )
    if not any_hydrated:
        return None, {}

    alerts: list[str] = []
    if outdoor_err is not None and outdoor_err != "OK":
        alerts.append("outdoor_fault")
    if controller_err is not None and controller_err != "OK":
        alerts.append("controller_fault")
    if hydraulic_err is not None and hydraulic_err != "OK":
        alerts.append("hydraulic_fault")
    if vr70_err is not None and vr70_err != "OK":
        alerts.append("mixer_module_fault")
    if hmu_fault is not None:
        alerts.append("hmu_status_fault")
    if pressure is not None:
        if pressure < WATER_PRESSURE_LOW_BAR:
            alerts.append("low_water_pressure")
        elif pressure > WATER_PRESSURE_HIGH_BAR:
            alerts.append("high_water_pressure")
    if ebus_known and coord.is_ebus_offline_alert_active:
        alerts.append("ebus_offline")

    attrs: dict[str, Any] = {
        "alerts": alerts,
        "alert_count": len(alerts),
        "ebus_operational": ebus_ok,
    }
    if pressure is not None:
        attrs["water_pressure_bar"] = pressure
    if outdoor_err is not None:
        attrs["outdoor_unit_error"] = outdoor_err
    if controller_err is not None:
        attrs["climate_controller_error"] = controller_err
    if hydraulic_err is not None:
        attrs["hydraulic_interface_error"] = hydraulic_err
    if vr70_err is not None:
        attrs["mixer_module_error"] = vr70_err
    if hmu_fault is not None:
        attrs["hmu_fault_status"] = hmu_fault

    return bool(alerts), attrs


def _check_system_health_alert(coord: SaunierGeniaCoordinator) -> bool | None:
    """Return True if any aggregated heat-pump health alert is active."""
    is_alert, _ = _evaluate_system_health(coord)
    return is_alert


def _get_system_health_alert_attrs(coord: SaunierGeniaCoordinator) -> dict[str, Any]:
    """Return structured health alert details for notifications and dashboards."""
    _, attrs = _evaluate_system_health(coord)
    return attrs


BINARY_SENSOR_DESCRIPTIONS: tuple[SaunierGeniaBinarySensorEntityDescription, ...] = (
    SaunierGeniaBinarySensorEntityDescription(
        key="compressor_active",
        translation_key="compressor_active",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="StateCompressor",
        field="modulation",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_check_compressor_active,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="primary_circulation_pump",
        translation_key="primary_circulation_pump",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="StatusCirPump",
        field="value",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_check_primary_pump,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="defrost_active",
        translation_key="defrost_active",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="HMUStatusCode",
        field="status",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_check_defrost_active,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="energy_integration_active",
        translation_key="energy_integration_active",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="PowerStatus",
        field="status",
        device_class=BinarySensorDeviceClass.POWER,
        is_on_fn=_check_energy_integration,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="z1_heating_demand",
        translation_key="z1_heating_demand",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1HeatingState",
        field="value",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=_check_z1_heating_demand,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="cooling_release_status",
        translation_key="cooling_release_status",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="CoolingReleaseStatus",
        field="value",
        is_on_fn=_check_cooling_release,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="broadcast_cooling_active",
        translation_key="broadcast_cooling_active",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BROADCAST,
        message="CoolingStatus",
        field="status",
        device_class=BinarySensorDeviceClass.COLD,
        is_on_fn=_check_broadcast_cooling,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="ebusd_signal",
        translation_key="ebusd_signal",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_GLOBAL,
        message="signal",
        field="value",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_ebusd_signal,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="ebusd_running",
        translation_key="ebusd_running",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_GLOBAL,
        message="running",
        field="value",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_ebusd_running,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="maintenance_due",
        translation_key="maintenance_due",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="MaintenanceDue",
        field="value",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_maintenance_due,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="app_session_status",
        translation_key="app_session_status",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="AppSessionStatus",
        field="status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_app_session_status,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="z1_time_slot_active",
        translation_key="z1_time_slot_active",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1TimeSlotActive",
        field="value",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_z1_time_slot_active,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="z1_cooling_time_slot_active",
        translation_key="z1_cooling_time_slot_active",
        device_key=DEVICE_CLIMATE_CONTROLLER,
        circuit=CIRCUIT_BASS3,
        message="Z1CoolingTimeSlotActive",
        field="value",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=_check_z1_cooling_time_slot_active,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="active_fault",
        translation_key="active_fault",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="Currenterror",
        field="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_active_fault,
        attr_fn=_get_active_fault_attrs,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="system_health_alert",
        translation_key="system_health_alert",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CALC_CIRCUIT,
        message="SystemHealthAlert",
        field="value",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_check_system_health_alert,
        attr_fn=_get_system_health_alert_attrs,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="vr70_mc1_pump",
        translation_key="vr70_mc1_pump",
        device_key=DEVICE_MIXER_MODULE,
        circuit=CIRCUIT_VR70,
        message="Mc1Operation",
        field="pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_check_vr70_mc1_pump,
        requires_vr70=True,
    ),
    SaunierGeniaBinarySensorEntityDescription(
        key="vr70_mc2_pump",
        translation_key="vr70_mc2_pump",
        device_key=DEVICE_MIXER_MODULE,
        circuit=CIRCUIT_VR70,
        message="Mc2Operation",
        field="pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        is_on_fn=_check_vr70_mc2_pump,
        requires_vr70=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval eBUSd Binary Sensor entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory: Instantiate diagnostic binary sensors (compressor state, primary pump,
    # heating demand, cooling lock release, physical eBUS bus signal quality, and optional VR 70 pumps).
    async_add_entities(
        SaunierGeniaBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
        if not (description.requires_vr70 and not coordinator.has_vr70)
    )


class SaunierGeniaBinarySensor(SaunierGeniaEntity, BinarySensorEntity):
    """Representation of a Saunier Duval eBUSd Binary Sensor."""

    entity_description: SaunierGeniaBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        subs = [(description.circuit, description.message)]
        if description.key == "compressor_active":
            subs.append((CIRCUIT_HMUX0, "RunDataCompressorSpeed"))
            subs.append((CIRCUIT_HMUX0, "HMUStatusCode"))
        elif description.key == "active_fault":
            subs.extend([(c, "Currenterror") for c in OUTDOOR_CIRCUITS])
            subs.extend([(c, "HMUStatusCode") for c in OUTDOOR_CIRCUITS])
            subs.extend([(c, "Currenterror") for c in CONTROLLER_CIRCUITS])
            subs.append((CIRCUIT_VWZIO, "Currenterror"))
            subs.append((CIRCUIT_VR70, "Currenterror"))
        elif description.key == "system_health_alert":
            subs.extend([(c, "Currenterror") for c in OUTDOOR_CIRCUITS])
            subs.extend([(c, "HMUStatusCode") for c in OUTDOOR_CIRCUITS])
            subs.extend([(c, "FlowPressure") for c in OUTDOOR_CIRCUITS])
            subs.extend([(c, "Currenterror") for c in CONTROLLER_CIRCUITS])
            subs.append((CIRCUIT_VWZIO, "Currenterror"))
            subs.append((CIRCUIT_VR70, "Currenterror"))
            subs.append((CIRCUIT_BASS3, "WaterPressure"))
            subs.append((CIRCUIT_GLOBAL, "running"))
            subs.append((CIRCUIT_GLOBAL, "signal"))

        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"binary_{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=description.device_key,
            translation_key=description.translation_key or description.key,
            subscriptions=list(dict.fromkeys(subs)),
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is active."""
        return self.entity_description.is_on_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional extra state attributes for the binary sensor."""
        if self.entity_description.attr_fn is not None:
            return self.entity_description.attr_fn(self.coordinator)
        return None
