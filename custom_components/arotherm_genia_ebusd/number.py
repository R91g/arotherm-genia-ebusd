"""Number platform for Saunier Duval MiPro Sense (All controls strictly in NumberMode.BOX)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CIRCUIT_BASS3,
    DEFAULT_COMFORT_TEMP,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
    SENTINEL_COOLING_THRESHOLD,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaNumberEntityDescription(NumberEntityDescription):
    """Describe a Saunier Duval eBUSd Number entity."""

    message: str
    circuit: str = CIRCUIT_BASS3
    field: str = "value"
    is_integer: bool = False
    filter_cooling_sentinel: bool = False


NUMBER_DESCRIPTIONS: tuple[SaunierGeniaNumberEntityDescription, ...] = (
    SaunierGeniaNumberEntityDescription(
        key="hc1_heat_curve",
        translation_key="hc1_heat_curve",
        message="Hc1HeatCurve",
        field="value",
        native_min_value=0.1,
        native_max_value=4.0,
        native_step=0.05,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hc1_excess_temp",
        translation_key="hc1_excess_temp",
        message="Hc1ExcessTemp",
        field="value",
        native_min_value=0.0,
        native_max_value=35.0,
        native_step=1.0,
        native_unit_of_measurement="K",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hc1_min_flow_temp_desired",
        translation_key="hc1_min_flow_temp_desired",
        message="Hc1MinFlowTempDesired",
        field="value",
        native_min_value=15.0,
        native_max_value=60.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hc1_max_flow_temp_desired",
        translation_key="hc1_max_flow_temp_desired",
        message="Hc1MaxFlowTempDesired",
        field="value",
        native_min_value=30.0,
        native_max_value=90.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hc1_summer_temp_limit",
        translation_key="hc1_summer_temp_limit",
        message="Hc1SummerTempLimit",
        field="value",
        native_min_value=10.0,
        native_max_value=35.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="cooling_flow_temp_desired_min",
        translation_key="cooling_flow_temp_desired_min",
        message="CoolingFlowTempDesiredMin",
        field="value",
        native_min_value=7.0,
        native_max_value=25.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="cooling_flow_temp_desired_max",
        translation_key="cooling_flow_temp_desired_max",
        message="CoolingFlowTempDesiredMax",
        field="value",
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_day_temp",
        translation_key="z1_day_temp",
        message="Z1DayTemp",
        field="value",
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_night_temp",
        translation_key="z1_night_temp",
        message="Z1NightTemp",
        field="value",
        native_min_value=5.0,
        native_max_value=25.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_manual_temp",
        translation_key="z1_manual_temp",
        message="Z1ManualTemp",
        field="value",
        native_min_value=5.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_quick_veto_temp",
        translation_key="z1_quick_veto_temp",
        message="Z1QuickVetoTemp",
        field="value",
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_cooling_temp_time_controlled",
        translation_key="z1_cooling_temp_time_controlled",
        message="Z1CoolingTemp",
        field="value",
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="z1_cooling_temp_manual",
        translation_key="z1_cooling_temp_manual",
        message="Z1CoolingTempDesired",
        field="value",
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        filter_cooling_sentinel=True,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hwc_temp_desired",
        translation_key="hwc_temp_desired",
        message="HwcTempDesired",
        field="value",
        native_min_value=35.0,
        native_max_value=68.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hwc_max_flow_temp_desired",
        translation_key="hwc_max_flow_temp_desired",
        message="HwcMaxFlowTempDesired",
        field="value",
        native_min_value=50.0,
        native_max_value=85.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="bivalence_point_hc",
        translation_key="bivalence_point_hc",
        message="BivalencePointHc",
        field="value",
        native_min_value=-30.0,
        native_max_value=20.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="bivalence_point_hwc",
        translation_key="bivalence_point_hwc",
        message="BivalencePointHwc",
        field="value",
        native_min_value=-30.0,
        native_max_value=20.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="alternative_point",
        translation_key="alternative_point",
        message="AlternativePoint",
        field="value",
        native_min_value=-30.0,
        native_max_value=20.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="cylinder_charge_hyst",
        translation_key="cylinder_charge_hyst",
        message="CylinderChargeHyst",
        field="value",
        native_min_value=2.0,
        native_max_value=15.0,
        native_step=0.5,
        native_unit_of_measurement="K",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="cylinder_charge_offset",
        translation_key="cylinder_charge_offset",
        message="CylinderChargeOffset",
        field="value",
        native_min_value=0.0,
        native_max_value=25.0,
        native_step=1.0,
        native_unit_of_measurement="K",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="max_cylinder_charge_time",
        translation_key="max_cylinder_charge_time",
        message="MaxCylinderChargeTime",
        field="value",
        native_min_value=20,
        native_max_value=180,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        is_integer=True,
    ),
    SaunierGeniaNumberEntityDescription(
        key="hwc_lock_time",
        translation_key="hwc_lock_time",
        message="HwcLockTime",
        field="value",
        native_min_value=0,
        native_max_value=120,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        is_integer=True,
    ),
    SaunierGeniaNumberEntityDescription(
        key="buffer_charge_offset",
        translation_key="buffer_charge_offset",
        message="BufferChargeOffset",
        field="value",
        native_min_value=0.0,
        native_max_value=20.0,
        native_step=1.0,
        native_unit_of_measurement="K",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="max_room_humidity",
        translation_key="max_room_humidity",
        message="MaxRoomHumidity",
        field="value",
        native_min_value=40.0,
        native_max_value=80.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.HUMIDITY,
        entity_category=EntityCategory.CONFIG,
        is_integer=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval MiPro Sense Number entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory: Instantiate writable configuration setpoints (heating curve, bivalence points,
    # flow temperature limits, and hysteresis) using strictly NumberMode.BOX to prevent accidental slider drags.
    async_add_entities(
        SaunierGeniaNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    )


class SaunierGeniaNumber(SaunierGeniaEntity, NumberEntity):
    """Representation of a Saunier Duval eBUSd Number control (strictly NumberMode.BOX)."""

    entity_description: SaunierGeniaNumberEntityDescription
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaNumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"number_{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key=description.translation_key or description.key,
            subscriptions=[(description.circuit, description.message)],
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description
        self._last_valid_cooling_value: float = DEFAULT_COMFORT_TEMP

    @property
    def native_value(self) -> float | None:
        """Return the current number value with anti-sentinel protection for Z1CoolingTempDesired."""
        val = self.coordinator.get_float(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.field,
        )
        if val is None:
            return None

        if self.entity_description.filter_cooling_sentinel:
            if val < SENTINEL_COOLING_THRESHOLD:
                self._last_valid_cooling_value = val
                return val
            return self._last_valid_cooling_value

        if self.entity_description.is_integer:
            return float(round(val))
        return round(val, 2)

    async def async_set_native_value(self, value: float) -> None:
        """Write the new numeric value to eBUSd."""
        if self.entity_description.filter_cooling_sentinel:
            self._last_valid_cooling_value = value

        payload_val: int | float = (
            round(value) if self.entity_description.is_integer else value
        )
        if (
            self.entity_description.message == "HwcTempDesired"
            and self.coordinator.dhw_boost_forced_active
        ):
            self.coordinator.cancel_dhw_boost_tracking(float(payload_val))

        await self.coordinator.async_write_parameter(
            self.entity_description.circuit,
            self.entity_description.message,
            payload_val,
        )
