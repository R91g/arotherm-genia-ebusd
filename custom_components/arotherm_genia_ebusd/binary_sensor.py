"""Binary Sensor platform for Saunier Duval GeniaAir Max ES & MiPro Sense."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CIRCUIT_BASS3,
    CIRCUIT_BROADCAST,
    CIRCUIT_GLOBAL,
    CIRCUIT_HMUX0,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Saunier Duval eBUSd Binary Sensor entity."""

    device_key: str
    circuit: str
    message: str
    field: str
    is_on_fn: Callable[[SaunierGeniaCoordinator], bool | None]


def _check_compressor_active(coord: SaunierGeniaCoordinator) -> bool | None:
    speed = coord.get_float(CIRCUIT_HMUX0, "StateCompressor", "comp_speed")
    if speed is not None:
        return speed > 0
    rps = coord.get_float(CIRCUIT_HMUX0, "RunDataCompressorSpeed", "value")
    if rps is not None:
        return rps > 0
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
    status = coord.get_str(CIRCUIT_HMUX0, "EnergyYieldPrecision", "status")
    if status is None:
        return None
    return status.lower() in ("active", "hwc", "heating", "2", "1")


def _check_z1_heating_demand(coord: SaunierGeniaCoordinator) -> bool | None:
    status = coord.get_str(CIRCUIT_BASS3, "Z1HeatingState", "value")
    if status is None:
        return None
    return status.lower() in ("on", "1", "true")


def _check_cooling_release(coord: SaunierGeniaCoordinator) -> bool | None:
    """Check literal hardware cooling authorization from BASS3 CoolingReleaseStatus.

    Returns True (Unlocked) ONLY when the heat pump firmware physically authorizes cooling
    (which requires both active calendar dates AND outdoor temperature >= 15 °C).
    Returns False (Locked) if blocked by calendar dates or cold outdoor temperature.
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


BINARY_SENSOR_DESCRIPTIONS: tuple[
    SaunierGeniaBinarySensorEntityDescription, ...
] = (
    SaunierGeniaBinarySensorEntityDescription(
        key="compressor_active",
        translation_key="compressor_active",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="StateCompressor",
        field="comp_speed",
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
        message="EnergyYieldPrecision",
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
        device_class=BinarySensorDeviceClass.LOCK,
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
        is_on_fn=_check_ebusd_signal,
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
    # heating demand, cooling lock release, and physical eBUS bus signal quality).
    async_add_entities(
        SaunierGeniaBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
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

        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"binary_{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=description.device_key,
            translation_key=description.translation_key or description.key,
            subscriptions=subs,
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is active."""
        return self.entity_description.is_on_fn(self.coordinator)
