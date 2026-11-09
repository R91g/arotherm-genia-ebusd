"""Button platform for Saunier Duval & Vaillant (eBUSd daemon commands)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_OUTDOOR_UNIT, DOMAIN
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class SaunierGeniaButtonEntityDescription(ButtonEntityDescription):
    """Describe an eBUSd daemon action button."""

    action: Callable[[SaunierGeniaCoordinator], Coroutine[Any, Any, Any]]


BUTTON_DESCRIPTIONS: tuple[SaunierGeniaButtonEntityDescription, ...] = (
    SaunierGeniaButtonEntityDescription(
        key="ebusd_reload_csv",
        translation_key="ebusd_reload_csv",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        action=lambda coordinator: coordinator.async_ebusd_tcp_reload(),
    ),
    SaunierGeniaButtonEntityDescription(
        key="ebusd_restart_scan",
        translation_key="ebusd_restart_scan",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        action=lambda coordinator: coordinator.async_ebusd_tcp_scan(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval eBUSd Button entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [
        SaunierGeniaButton(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)


class SaunierGeniaButton(SaunierGeniaEntity, ButtonEntity):
    """Representation of an eBUSd daemon action button."""

    entity_description: SaunierGeniaButtonEntityDescription
    _gate_availability_on_ebus = False

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_OUTDOOR_UNIT,
            translation_key=description.translation_key,
            subscriptions=[],
            unique_id_suffix=f"button_{description.key}",
        )
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Button is available whenever eBUSd TCP connection is enabled."""
        return self.coordinator.is_ebusd_tcp_enabled

    async def async_press(self) -> None:
        """Handle button press."""
        await self.entity_description.action(self.coordinator)
