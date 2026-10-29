"""Select platform for Saunier Duval MiPro Sense operational modes and settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CIRCUIT_BASS3, DEVICE_CLIMATE_CONTROLLER, DOMAIN
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaSelectEntityDescription(SelectEntityDescription):
    """Describe a Saunier Duval eBUSd Select entity."""

    message: str
    circuit: str = CIRCUIT_BASS3
    field: str = "value"


SELECT_DESCRIPTIONS: tuple[SaunierGeniaSelectEntityDescription, ...] = (
    SaunierGeniaSelectEntityDescription(
        key="z1_op_mode",
        translation_key="z1_op_mode",
        message="Z1OpMode",
        field="value",
        options=["off", "auto", "day", "night"],
    ),
    SaunierGeniaSelectEntityDescription(
        key="z1_op_mode_cooling",
        translation_key="z1_op_mode_cooling",
        message="Z1OpModeCooling",
        field="value",
        options=["off", "auto", "day"],
    ),
    SaunierGeniaSelectEntityDescription(
        key="hwc_op_mode",
        translation_key="hwc_op_mode",
        message="HwcOpMode",
        field="value",
        options=["off", "auto", "day", "night"],
    ),
    SaunierGeniaSelectEntityDescription(
        key="hc1_auto_off_mode",
        translation_key="hc1_auto_off_mode",
        message="Hc1AutoOffMode",
        field="value",
        options=["eco", "night", "off"],
        entity_category=EntityCategory.CONFIG,
    ),
    SaunierGeniaSelectEntityDescription(
        key="hc1_room_temp_switch_on",
        translation_key="hc1_room_temp_switch_on",
        message="Hc1RoomTempSwitchOn",
        field="value",
        options=["off", "modulating", "thermostat"],
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval MiPro Sense Select entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Entity Factory: Instantiate raw eBUS enum selectors (heating/cooling circuit operation modes,
    # night setback behaviors, and room temperature modulation feedback options).
    async_add_entities(
        SaunierGeniaSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    )


class SaunierGeniaSelect(SaunierGeniaEntity, SelectEntity):
    """Representation of a Saunier Duval eBUSd Select entity."""

    entity_description: SaunierGeniaSelectEntityDescription

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaSelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"select_{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key=description.translation_key or description.key,
            subscriptions=[(description.circuit, description.message)],
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        val = self.coordinator.get_str(
            self.entity_description.circuit,
            self.entity_description.message,
            self.entity_description.field,
        )
        if val is None:
            return None
        val_lower = val.lower()
        if self.options and val_lower in self.options:
            return val_lower
        return None

    async def async_select_option(self, option: str) -> None:
        """Write the selected option to eBUSd."""
        await self.coordinator.async_write_parameter(
            self.entity_description.circuit,
            self.entity_description.message,
            option,
        )
