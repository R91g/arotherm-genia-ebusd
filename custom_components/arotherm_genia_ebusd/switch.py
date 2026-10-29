"""Switch platform for Saunier Duval MiPro Sense (DHW Boost, Cooling Lock 1, System Config)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CIRCUIT_BASS3, DEVICE_CLIMATE_CONTROLLER, DOMAIN
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaSwitchEntityDescription(SwitchEntityDescription):
    """Describe a standard Saunier Duval eBUSd Switch entity."""

    message: str
    circuit: str = CIRCUIT_BASS3
    field: str = "value"
    payload_on: str = "on"
    payload_off: str = "off"


STANDARD_SWITCH_DESCRIPTIONS: tuple[SaunierGeniaSwitchEntityDescription, ...] = (
    SaunierGeniaSwitchEntityDescription(
        key="adapt_heat_curve",
        translation_key="adapt_heat_curve",
        message="AdaptHeatCurve",
        field="value",
        payload_on="yes",
        payload_off="no",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaSwitchEntityDescription(
        key="hwc_parallel_loading",
        translation_key="hwc_parallel_loading",
        message="HwcParallelLoading",
        field="value",
        payload_on="on",
        payload_off="off",
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaSwitchEntityDescription(
        key="global_system_off",
        translation_key="global_system_off",
        message="GlobalSystemOff",
        field="value",
        payload_on="yes",
        payload_off="no",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval MiPro Sense Switch entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory:
    # 1. DHW Boost switch: orchestrates one-time tank loading with automatic hysteresis bypass.
    # 2. Cooling Season switch: manual control over Lock 1 (calendar start/end dates).
    # 3. Standard configuration switches (adaptive curve, parallel loading, global standby).
    entities: list[SwitchEntity] = [
        SaunierGeniaDhwBoostSwitch(coordinator),
        SaunierGeniaCoolingSeasonSwitch(coordinator),
        *(
            SaunierGeniaStandardSwitch(coordinator, description)
            for description in STANDARD_SWITCH_DESCRIPTIONS
        ),
    ]
    async_add_entities(entities)


class SaunierGeniaDhwBoostSwitch(SaunierGeniaEntity, SwitchEntity):
    """Switch for One-Time DHW Boost (ACS Puntual) with Smart Forced Hysteresis Bypass."""

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the DHW Boost switch."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="dhw_boost_switch",
            subscriptions=[
                (CIRCUIT_BASS3, "HwcSFMode"),
                (CIRCUIT_BASS3, "HwcStatus"),
                (CIRCUIT_BASS3, "HwcStorageTemp"),
                (CIRCUIT_BASS3, "HwcTempDesired"),
            ],
            unique_id_suffix="switch_bass3_hwcsfmode_boost",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if HwcSFMode is 'load'."""
        sf_mode = self.coordinator.get_str(CIRCUIT_BASS3, "HwcSFMode", "value")
        if sf_mode is None:
            return None
        return sf_mode.lower() == "load"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return boost diagnostic attributes."""
        return {
            "forced_boost_active": self.coordinator.dhw_boost_forced_active,
            "saved_pre_boost_target_temp": self.coordinator.saved_dhw_target_temp,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate One-Time DHW Boost using the Smart Forced Boost algorithm."""
        await self.coordinator.async_trigger_dhw_boost()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Cancel One-Time DHW Boost and restore original DHW target temperature."""
        await self.coordinator.async_cancel_dhw_boost()


class SaunierGeniaCoolingSeasonSwitch(SaunierGeniaEntity, SwitchEntity):
    """Switch for Cooling Season Authorization (Lock 1: CoolingStartDate / CoolingEndDate)."""

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Cooling Season Authorization (Lock 1) switch."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="cooling_season_authorization",
            subscriptions=[
                (CIRCUIT_BASS3, "CoolingReleaseStatus"),
                (CIRCUIT_BASS3, "CoolingStartDate"),
                (CIRCUIT_BASS3, "CoolingEndDate"),
                (CIRCUIT_BASS3, "Z1OpModeCooling"),
            ],
            unique_id_suffix="switch_bass3_coolinglock1_season",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if CoolingReleaseStatus is 'on' or CoolingEndDate year is 99."""
        release_status = self.coordinator.get_str(
            CIRCUIT_BASS3, "CoolingReleaseStatus", "value"
        )
        end_year = self.coordinator.get_int(
            CIRCUIT_BASS3, "CoolingEndDate", "year"
        )
        if release_status is None and end_year is None:
            return None
        return (
            release_status is not None and release_status.lower() == "on"
        ) or end_year == 99

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return start/end dates and release status for Lock 1."""
        start_msg = self.coordinator.get_message(
            CIRCUIT_BASS3, "CoolingStartDate"
        )
        end_msg = self.coordinator.get_message(CIRCUIT_BASS3, "CoolingEndDate")
        return {
            "cooling_release_status": self.coordinator.get_str(
                CIRCUIT_BASS3, "CoolingReleaseStatus", "value"
            ),
            "cooling_start_date": (
                f"{start_msg.get('day'):02d}/{start_msg.get('month'):02d}/20{start_msg.get('year'):02d}"
                if start_msg
                and all(
                    isinstance(start_msg.get(k), int)
                    for k in ("day", "month", "year")
                )
                else None
            ),
            "cooling_end_date": (
                f"{end_msg.get('day'):02d}/{end_msg.get('month'):02d}/20{end_msg.get('year'):02d}"
                if end_msg
                and all(
                    isinstance(end_msg.get(k), int)
                    for k in ("day", "month", "year")
                )
                else None
            ),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open Lock 1 indefinitely (CoolingStartDate=01;01;26, CoolingEndDate=01;01;99)."""
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", "01;01;26"
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", "01;01;99"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close Lock 1 to epoch 2019 (01;01;19) and set Z1OpModeCooling='off'."""
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", "01;01;19"
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", "01;01;19"
        )
        await asyncio.sleep(0.5)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "Z1OpModeCooling", "off"
        )


class SaunierGeniaStandardSwitch(SaunierGeniaEntity, SwitchEntity):
    """Standard single-register switch entity for MiPro Sense parameters."""

    entity_description: SaunierGeniaSwitchEntityDescription

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaSwitchEntityDescription,
    ) -> None:
        """Initialize the standard switch."""
        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"switch_{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key=description.translation_key or description.key,
            subscriptions=[(description.circuit, description.message)],
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the register matches payload_on."""
        val = self.coordinator.get_str(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.field,
        )
        if val is None:
            return None
        return val.lower() in (
            self.entity_description.payload_on.lower(),
            "1",
            "true",
            "on",
            "yes",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.async_write_parameter(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.payload_on,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.async_write_parameter(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.payload_off,
        )
