"""Number platform for Saunier Duval MiPro Sense (All controls strictly in NumberMode.BOX)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
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
    CIRCUIT_HMUX0,
    DEVICE_CLIMATE_CONTROLLER,
    DEVICE_OUTDOOR_UNIT,
    DOMAIN,
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
    device_key: str = DEVICE_CLIMATE_CONTROLLER
    mode: NumberMode = NumberMode.BOX


TEMP_DELTA_NUMBER_DEVICE_CLASS: NumberDeviceClass | None = getattr(
    NumberDeviceClass, "TEMPERATURE_DELTA", None
)


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
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
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
        key="z1_quick_veto_duration",
        translation_key="z1_quick_veto_duration",
        message="Z1QuickVetoDuration",
        field="value",
        native_min_value=0.5,
        native_max_value=12.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=NumberDeviceClass.DURATION,
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
        message="Z1CoolingManualTemp",
        field="value",
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
    ),
    SaunierGeniaNumberEntityDescription(
        key="holiday_temp",
        translation_key="holiday_temp",
        message="HolidayTemp",
        field="value",
        native_min_value=5.0,
        native_max_value=24.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
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
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
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
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="max_cylinder_charge_time",
        translation_key="max_cylinder_charge_time",
        message="MaxCylinderChargeTime",
        field="value",
        native_min_value=0,
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
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
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
    SaunierGeniaNumberEntityDescription(
        key="dew_point_offset",
        translation_key="dew_point_offset",
        message="DewPointOffset",
        field="value",
        native_min_value=-5.0,
        native_max_value=10.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="cooling_outside_temp_threshold",
        translation_key="cooling_outside_temp_threshold",
        message="CoolingOutsideTempThreshold",
        field="value",
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="offset_outside_temp",
        translation_key="offset_outside_temp",
        message="OffsetOutsideTemp",
        field="value",
        native_min_value=-5.0,
        native_max_value=5.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=TEMP_DELTA_NUMBER_DEVICE_CLASS,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="continuous_heating_threshold",
        translation_key="continuous_heating_threshold",
        message="ContinuosHeating",
        field="value",
        native_min_value=-26.0,
        native_max_value=10.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaNumberEntityDescription(
        key="frost_override_time",
        translation_key="frost_override_time",
        message="FrostOverRideTime",
        field="value",
        native_min_value=0,
        native_max_value=24,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        is_integer=True,
    ),
    SaunierGeniaNumberEntityDescription(
        key="compressor_silent_operation_level",
        translation_key="compressor_silent_operation_level",
        device_key=DEVICE_OUTDOOR_UNIT,
        circuit=CIRCUIT_HMUX0,
        message="CompressorSilentOperationLevel",
        field="value",
        native_min_value=30.0,
        native_max_value=60.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
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
    # Entity Factory: Instantiate writable configuration setpoints and outdoor unit controls.
    entities: list[NumberEntity] = [
        SaunierGeniaNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    ]
    entities.append(SaunierGeniaQuickVetoBoostDeltaNumber(coordinator))
    entities.append(SaunierGeniaCoolingQuickVetoBoostDeltaNumber(coordinator))
    async_add_entities(entities)


class SaunierGeniaNumber(SaunierGeniaEntity, NumberEntity):
    """Representation of a Saunier Duval eBUSd Number control."""

    entity_description: SaunierGeniaNumberEntityDescription
    _attr_mode = NumberMode.BOX
    _gate_availability_on_ebus = True

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
            device_key=description.device_key,
            translation_key=description.translation_key or description.key,
            subscriptions=[(description.circuit, description.message)],
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description
        self._attr_mode = description.mode

    @property
    def native_value(self) -> float | None:
        """Return the current number value."""
        val = self.coordinator.get_float(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.field,
        )
        if val is None:
            return None

        if self.entity_description.is_integer:
            return float(round(val))
        return round(val, 2)

    async def async_set_native_value(self, value: float) -> None:
        """Write the new numeric value to eBUSd."""
        payload_val: int | float = (
            round(value) if self.entity_description.is_integer else value
        )
        if self.entity_description.message == "HwcTempDesired" and (
            self.coordinator.dhw_boost_forced_active
            or self.coordinator.pending_dhw_boost_restore
        ):
            await self.coordinator.async_cancel_dhw_boost_tracking(float(payload_val))

        if (
            self.entity_description.message == "Z1QuickVetoDuration"
            and self.coordinator.cooling_quick_veto_active
        ):
            await self.coordinator.async_write_parameter(
                self.entity_description.circuit,
                self.entity_description.message,
                payload_val,
            )
            if self.coordinator.cooling_quick_veto_target_temp is not None:
                await self.coordinator.async_set_cooling_quick_veto(
                    temperature=self.coordinator.cooling_quick_veto_target_temp,
                    duration=float(payload_val),
                )
            else:
                await self.coordinator.async_refresh_cooling_veto_duration(
                    float(payload_val)
                )
            return

        await self.coordinator.async_write_parameter(
            self.entity_description.circuit,
            self.entity_description.message,
            payload_val,
        )
        if (
            self.entity_description.message == "Z1QuickVetoDuration"
            and await self.coordinator.async_confirm_heating_veto_active()
        ):
            await asyncio.sleep(0.3)
            await self.coordinator.async_write_parameter(
                CIRCUIT_BASS3, "Z1SFMode", "veto"
            )
            await self.coordinator.async_refresh_heating_veto_duration(
                float(payload_val)
            )


class _SaunierGeniaBoostDeltaNumber(SaunierGeniaEntity, RestoreNumber):
    """Shared base for HA-persisted Quick Veto boost temperature delta numbers."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.5
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = TEMP_DELTA_NUMBER_DEVICE_CLASS
    _attr_entity_category = EntityCategory.CONFIG
    _gate_availability_on_ebus = True
    _attr_native_max_value: float
    _coord_attr: str

    async def async_added_to_hass(self) -> None:
        """Restore last configured boost delta in native units on restart."""
        await super().async_added_to_hass()
        last_data = await self.async_get_last_number_data()
        if last_data is not None and last_data.native_value is not None:
            try:
                val = round(float(last_data.native_value), 1)
                max_val = self._attr_native_max_value
                if 0.5 <= val <= max_val:
                    setattr(self.coordinator, self._coord_attr, val)
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float:
        """Return the current configured boost delta."""
        return float(getattr(self.coordinator, self._coord_attr))

    async def async_set_native_value(self, value: float) -> None:
        """Update the configured boost delta."""
        setattr(self.coordinator, self._coord_attr, round(float(value), 1))
        self.async_write_ha_state()


class SaunierGeniaQuickVetoBoostDeltaNumber(_SaunierGeniaBoostDeltaNumber):
    """Number entity to configure the Quick Veto heating boost delta."""

    _attr_native_max_value = 10.0
    _coord_attr = "quick_veto_boost_delta"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the boost delta number entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="z1_quick_veto_boost_delta",
            subscriptions=[],
            unique_id_suffix="number_z1_quick_veto_boost_delta",
        )


class SaunierGeniaCoolingQuickVetoBoostDeltaNumber(_SaunierGeniaBoostDeltaNumber):
    """Number entity to configure the Quick Veto cooling boost delta."""

    _attr_native_max_value = 5.0
    _coord_attr = "cooling_quick_veto_boost_delta"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the cooling boost delta number entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="z1_cooling_quick_veto_boost_delta",
            subscriptions=[],
            unique_id_suffix="number_z1_cooling_quick_veto_boost_delta",
        )
