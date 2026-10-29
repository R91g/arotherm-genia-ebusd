"""Base Entity and 4-Device Hierarchy for Saunier Duval GeniaAir Max ES & MiPro Sense."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_HYDRAULIC_INTERFACE,
    DEVICE_OUTDOOR_UNIT,
    DEVICE_WIRELESS_THERMOSTAT,
    DOMAIN,
    INDOOR_MODEL_SPECS,
    MANUFACTURER,
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

    if device_key == DEVICE_OUTDOOR_UNIT:
        outdoor_model = coordinator.outdoor_model
        return DeviceInfo(
            identifiers={(DOMAIN, outdoor_id)},
            name=f"{outdoor_model} (Unidad Exterior)",
            manufacturer=manufacturer,
            model=OUTDOOR_MODEL_SPECS.get(outdoor_model, outdoor_model),
            sw_version="0407",
            hw_version="0504",
        )

    if device_key == DEVICE_CLIMATE_CONTROLLER:
        controller_name = (
            "sensoCOMFORT (Controlador de Clima)"
            if is_vaillant
            else "MiPro Sense (Controlador de Clima)"
        )
        controller_model = (
            "sensoCOMFORT VRC 720/3 (BASS3)"
            if is_vaillant
            else "MiPro Sense SRC 720/3 (BASS3)"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{DEVICE_CLIMATE_CONTROLLER}")},
            name=controller_name,
            manufacturer=manufacturer,
            model=controller_model,
            sw_version="0708",
            hw_version="4304",
            via_device=(DOMAIN, outdoor_id),
        )

    if device_key == DEVICE_HYDRAULIC_INTERFACE:
        indoor_model = coordinator.indoor_model
        display_name = f"Interfaz Hidráulica {indoor_model}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{DEVICE_HYDRAULIC_INTERFACE}")},
            name=display_name,
            manufacturer=manufacturer,
            model=INDOOR_MODEL_SPECS.get(indoor_model, indoor_model),
            sw_version="0500",
            hw_version="0504",
            via_device=(DOMAIN, outdoor_id),
        )

    # DEVICE_WIRELESS_THERMOSTAT
    thermostat_name = (
        "Termostato Inalámbrico sensoCOMFORT RF"
        if is_vaillant
        else "Termostato Inalámbrico MiPro Sense"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{DEVICE_WIRELESS_THERMOSTAT}")},
        name=thermostat_name,
        manufacturer=manufacturer,
        model="Receptor Radio NETX3 (0020260979)",
        sw_version="0708",
        hw_version="4304",
        via_device=(DOMAIN, outdoor_id),
    )


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

    async def async_added_to_hass(self) -> None:
        """Subscribe to relevant (circuit, message) updates when added to Home Assistant."""
        await super().async_added_to_hass()
        for circuit, message in self._subscriptions:
            self.async_on_remove(
                self.coordinator.async_add_listener(
                    circuit, message, self._handle_coordinator_update
                )
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the MQTT coordinator."""
        self.async_write_ha_state()
