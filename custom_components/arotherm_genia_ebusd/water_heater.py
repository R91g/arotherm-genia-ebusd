"""Water Heater platform for Saunier Duval & Vaillant DHW (with Smart Forced Boost)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CIRCUIT_BASS3,
    DEFAULT_CYLINDER_HYST,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity

# Home Assistant standard WaterHeater operation modes (used internally for Lovelace card colors):
# - OP_ECO ("eco"): Maps to Saunier Duval "auto" -> Translated as "Time schedule" (Green color dial)
# - OP_PERFORMANCE ("performance"): Maps to Saunier Duval "day" -> Translated as "Continuous (24h)" (Orange color dial)
# - OP_BOOST ("boost"): Maps to Saunier Duval "load" -> Translated as "Boost" (Accent color dial)
# - OP_OFF ("off"): Maps to Saunier Duval "off" -> Translated as "Off" (Grey color dial)
OP_OFF = "off"
OP_ECO = "eco"
OP_PERFORMANCE = "performance"
OP_BOOST = "boost"

BASS3_TO_HA_OP_MAP: dict[str, str] = {
    "off": OP_OFF,
    "auto": OP_ECO,
    "day": OP_PERFORMANCE,
    "night": OP_ECO,
}

HA_TO_BASS3_OP_MAP: dict[str, str] = {
    OP_OFF: "off",
    OP_ECO: "auto",
    OP_PERFORMANCE: "day",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DHW Water Heater entity."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory: Instantiate the unified WaterHeater entity representing the domestic hot water cylinder.
    # Manages temperature setpoints, operational modes (auto/schedule, 24h continuous, boost, off),
    # and integrates directly with the smart forced boost algorithm in coordinator.py.
    async_add_entities([SaunierGeniaWaterHeater(coordinator)])


class SaunierGeniaWaterHeater(SaunierGeniaEntity, WaterHeaterEntity):
    """Representation of the DHW Water Heater with Smart Forced Boost."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 35.0
    _attr_max_temp = 68.0
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the DHW water heater entity."""
        self._attr_operation_list = [OP_OFF, OP_ECO, OP_PERFORMANCE, OP_BOOST]
        subscriptions = [
            (CIRCUIT_BASS3, "HwcStorageTemp"),
            (CIRCUIT_BASS3, "HwcTempDesired"),
            (CIRCUIT_BASS3, "HwcOpMode"),
            (CIRCUIT_BASS3, "HwcSFMode"),
            (CIRCUIT_BASS3, "HwcStatus"),
            (CIRCUIT_BASS3, "HwcFlowTemp"),
            (CIRCUIT_BASS3, "CylinderChargeHyst"),
            (CIRCUIT_BASS3, "SystemOperatingState"),
        ]
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="dhw_water_heater",
            subscriptions=subscriptions,
            unique_id_suffix="water_heater_dhw",
        )

    @property
    def current_temperature(self) -> float | None:
        """Return current DHW tank temperature (Probe SP1)."""
        temp = self.coordinator.get_float(CIRCUIT_BASS3, "HwcStorageTemp", "value")
        return round(temp, 2) if temp is not None else None

    @property
    def target_temperature(self) -> float | None:
        """Return target DHW tank setpoint."""
        return self.coordinator.get_float(CIRCUIT_BASS3, "HwcTempDesired", "value")

    @property
    def current_operation(self) -> str | None:
        """Return current operation mode (off, eco, performance, boost)."""
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "HwcSFMode", "value") or ""
        ).lower()
        hwc_status = (
            self.coordinator.get_str(CIRCUIT_BASS3, "HwcStatus", "value") or ""
        ).lower()
        if sf_mode == "load" or hwc_status == "load":
            return OP_BOOST

        op_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "HwcOpMode", "value") or ""
        ).lower()
        if not op_mode:
            return None
        return BASS3_TO_HA_OP_MAP.get(op_mode, OP_ECO)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extended DHW diagnostic attributes."""
        return {
            "hwc_flow_temp": self.coordinator.get_float(
                CIRCUIT_BASS3, "HwcFlowTemp", "value"
            ),
            "hwc_status": self.coordinator.get_str(CIRCUIT_BASS3, "HwcStatus", "value"),
            "cylinder_charge_hyst_k": self.coordinator.get_float(
                CIRCUIT_BASS3,
                "CylinderChargeHyst",
                "value",
                DEFAULT_CYLINDER_HYST,
            ),
            "forced_boost_active": self.coordinator.dhw_boost_forced_active,
            "saved_pre_boost_target_temp": self.coordinator.saved_dhw_target_temp,
        }

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new operation mode (implementing Smart Forced DHW Boost for 'boost')."""
        if operation_mode == OP_BOOST:
            await self.coordinator.async_trigger_dhw_boost()
            return

        # If cancelling boost while switching to another mode, restore setpoint and HwcSFMode=auto
        sf_mode = (
            self.coordinator.get_str(CIRCUIT_BASS3, "HwcSFMode", "value") or ""
        ).lower()
        if sf_mode == "load" or self.coordinator.dhw_boost_forced_active:
            await self.coordinator.async_cancel_dhw_boost()

        bass3_mode = HA_TO_BASS3_OP_MAP.get(operation_mode)
        if bass3_mode is not None:
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "HwcOpMode", bass3_mode
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature for the DHW cylinder."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temp_val = round(float(temperature) * 2.0) / 2.0
        # If boost was active, user manual setpoint overrides it
        if self.coordinator.dhw_boost_forced_active:
            self.coordinator.cancel_dhw_boost_tracking(temp_val)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HwcTempDesired", temp_val
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the water heater in scheduled solar eco mode (auto)."""
        await self.async_set_operation_mode(OP_ECO)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the water heater."""
        await self.async_set_operation_mode(OP_OFF)
