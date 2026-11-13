"""Time platform for Saunier Duval / Vaillant Genia eBUS."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CIRCUIT_BASS3, DEVICE_CLIMATE_CONTROLLER, DOMAIN
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval eBUS Time entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([SaunierGeniaHwcLegionellaTime(coordinator)])


class SaunierGeniaHwcLegionellaTime(SaunierGeniaEntity, TimeEntity):
    """Time entity for Anti-Legionella disinfection execution time."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Legionella Time entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="hwc_legionella_time",
            subscriptions=[(CIRCUIT_BASS3, "HwcLegionellaTime")],
            unique_id_suffix="time_bass3_hwc_legionella_time",
        )

    @property
    def native_value(self) -> time | None:
        """Return the scheduled anti-legionella execution time."""
        raw_val = self.coordinator.get_str(CIRCUIT_BASS3, "HwcLegionellaTime", "time")

        if raw_val and ":" in raw_val:
            parts = raw_val.split(":")
            try:
                return time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass

        msg = self.coordinator.get_message(CIRCUIT_BASS3, "HwcLegionellaTime")
        if msg:
            h = msg.get("hours", msg.get("hour"))
            m = msg.get("minutes", msg.get("minute", 0))
            if h is not None and m is not None:
                try:
                    return time(int(h), int(m))
                except (ValueError, TypeError):
                    pass

        return None

    async def async_set_value(self, value: time) -> None:
        """Set scheduled anti-legionella execution time."""
        time_str = f"{value.hour:02d}:{value.minute:02d}"
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HwcLegionellaTime", time_str
        )
