"""Base Entity and 4-Device Hierarchy for Saunier Duval GeniaAir Max ES & MiPro Sense."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    CIRCUIT_BASV3,
    CIRCUIT_CTLV2,
    CIRCUIT_CTLV3,
    CIRCUIT_GLOBAL,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    DOMAIN,
    INDOOR_MODEL_SPECS,
    MANUFACTURER_VAILLANT,
    OUTDOOR_MODEL_SPECS,
)
from .coordinator import SaunierGeniaCoordinator


def build_device_info(
    coordinator: SaunierGeniaCoordinator,
    device_key: str,
) -> DeviceInfo:
    """Construct DeviceInfo for one of the 4 logical eBUS devices."""
    entry_id = coordinator.entry.entry_id
    outdoor_id = f"{entry_id}_{DEVICE_OUTDOOR_UNIT}"
    manufacturer = coordinator.manufacturer
    is_vaillant = manufacturer == MANUFACTURER_VAILLANT

    # Fallback: if wireless room unit is disabled, attach Broadcast entities to climate_controller
    if (
        device_key == DEVICE_WIRELESS_THERMOSTAT
        and not coordinator.has_wireless_room_unit
    ):
        device_key = DEVICE_CLIMATE_CONTROLLER

    sw_version = (
        coordinator.get_device_sw_version(device_key)
        if hasattr(coordinator, "get_device_sw_version")
        else None
    )
    hw_version = (
        coordinator.get_device_hw_version(device_key)
        if hasattr(coordinator, "get_device_hw_version")
        else None
    )
    serial_number = (
        coordinator.get_device_serial_number(device_key)
        if hasattr(coordinator, "get_device_serial_number")
        else None
    )
    outdoor_device_id = (
        coordinator.outdoor_device_id
        if hasattr(coordinator, "outdoor_device_id")
        else None
    )

    if device_key == DEVICE_OUTDOOR_UNIT:
        outdoor_model = coordinator.outdoor_model
        return DeviceInfo(
            identifiers={(DOMAIN, outdoor_id)},
            name=f"{outdoor_model} (Outdoor Unit)",
            manufacturer=manufacturer,
            model=OUTDOOR_MODEL_SPECS.get(outdoor_model, outdoor_model),
            sw_version=sw_version,
            hw_version=hw_version,
            serial_number=serial_number,
        )

    if device_key == DEVICE_CLIMATE_CONTROLLER:
        controller_name = (
            "sensoCOMFORT (Climate Controller)"
            if is_vaillant
            else "MiPro Sense (Climate Controller)"
        )
        active_circuit = getattr(coordinator, "active_controller_circuit", None)
        if active_circuit in (CIRCUIT_CTLV2, CIRCUIT_CTLV3):
            controller_model = f"sensoCOMFORT VRC 720 ({active_circuit.upper()})"
        elif is_vaillant or active_circuit == CIRCUIT_BASV3:
            controller_model = "sensoCOMFORT VRC 720/3 (BASV3)"
        else:
            controller_model = "MiPro Sense SRC 720/3 (BASS3)"
        info_kwargs: dict[str, Any] = {
            "identifiers": {(DOMAIN, f"{entry_id}_{DEVICE_CLIMATE_CONTROLLER}")},
            "name": controller_name,
            "manufacturer": manufacturer,
            "model": controller_model,
            "sw_version": sw_version,
            "hw_version": hw_version,
            "serial_number": serial_number,
        }
        if outdoor_device_id:
            info_kwargs["via_device_id"] = outdoor_device_id
        return DeviceInfo(**info_kwargs)

    if device_key == DEVICE_HYDRAULIC_INTERFACE:
        indoor_model = coordinator.indoor_model
        display_name = f"{indoor_model} (Hydraulic Interface)"
        info_kwargs = {
            "identifiers": {(DOMAIN, f"{entry_id}_{DEVICE_HYDRAULIC_INTERFACE}")},
            "name": display_name,
            "manufacturer": manufacturer,
            "model": INDOOR_MODEL_SPECS.get(indoor_model, indoor_model),
            "sw_version": sw_version,
            "hw_version": hw_version,
            "serial_number": serial_number,
        }
        if outdoor_device_id:
            info_kwargs["via_device_id"] = outdoor_device_id
        return DeviceInfo(**info_kwargs)

    # DEVICE_WIRELESS_THERMOSTAT
    thermostat_name = (
        "sensoCOMFORT Wireless Thermostat RF"
        if is_vaillant
        else "MiPro Sense Wireless Thermostat"
    )
    thermostat_model = (
        "Communication Gateway NETX3 (VR 940f / VR 921)"
        if is_vaillant
        else "Wireless Receiver NETX3 (0020260979)"
    )
    info_kwargs = {
        "identifiers": {(DOMAIN, f"{entry_id}_{DEVICE_WIRELESS_THERMOSTAT}")},
        "name": thermostat_name,
        "manufacturer": manufacturer,
        "model": thermostat_model,
        "sw_version": sw_version,
        "hw_version": hw_version,
        "serial_number": serial_number,
    }
    if outdoor_device_id:
        info_kwargs["via_device_id"] = outdoor_device_id
    return DeviceInfo(**info_kwargs)


class SaunierGeniaEntity(Entity):
    """Base entity class for all Saunier Duval GeniaAir Max ES & MiPro Sense entities.

    Key architectural design:
    - Fine-grained event subscriptions: Each entity only registers listener callbacks for its
      specific (circuit, message) eBUS dependencies via `coordinator.async_add_listener`.
    - Avoids waking up and re-rendering all 120+ entities when high-frequency telemetry
      (e.g. pump modulation or outdoor fan speed) arrives on MQTT.
    - Unique ID format: Strictly derived from {entry.entry_id}_{unique_id_suffix}
      where unique_id_suffix is based on {circuit}_{message}_{field} (e.g. hmux0_rundataflowrate_value),
      guaranteeing zero brand name dependencies so that changing manufacturer/model maintains history.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _gate_availability_on_ebus: bool = False

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        device_key: str,
        translation_key: str,
        subscriptions: list[tuple[str, str]],
        unique_id_suffix: str | None = None,
    ) -> None:
        """Initialize the base entity."""
        self.coordinator = coordinator
        self._device_key = device_key
        self._attr_translation_key = translation_key
        key_part = unique_id_suffix if unique_id_suffix is not None else translation_key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key_part}"
        self._attr_device_info = build_device_info(coordinator, device_key)
        self._subscriptions = subscriptions

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self._gate_availability_on_ebus and not self.coordinator.is_ebus_operational:
            return False
        return super().available

    async def async_added_to_hass(self) -> None:
        """Subscribe to relevant (circuit, message) updates when added to Home Assistant."""
        await super().async_added_to_hass()
        all_subs = list(self._subscriptions)
        if self._gate_availability_on_ebus:
            if (CIRCUIT_GLOBAL, "running") not in all_subs:
                all_subs.append((CIRCUIT_GLOBAL, "running"))
            if (CIRCUIT_GLOBAL, "signal") not in all_subs:
                all_subs.append((CIRCUIT_GLOBAL, "signal"))

        for circuit, message in all_subs:
            self.async_on_remove(
                self.coordinator.async_add_listener(
                    circuit, message, self._handle_coordinator_update
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the MQTT coordinator."""
        self.async_write_ha_state()
