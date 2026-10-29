"""Diagnostics support for Saunier Duval GeniaAir Max ES & MiPro Sense (eBUSd)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SaunierGeniaCoordinator

TO_REDACT: list[str] = []


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Convert internal coordinator state (tuple keys) into a JSON-serializable hierarchical dict
    bus_state: dict[str, dict[str, Any]] = {}
    for (circuit, msg_name), values in coordinator._state.items():
        bus_state.setdefault(circuit, {})[msg_name] = values

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "mqtt_prefix": coordinator.mqtt_prefix,
            "outdoor_model": coordinator.outdoor_model,
            "indoor_model": coordinator.indoor_model,
            "has_wireless_room_unit": coordinator.has_wireless_room_unit,
            "has_migo_link": coordinator.has_migo_link,
            "force_dhw_boost": coordinator.force_dhw_boost,
            "dhw_boost_forced_active": coordinator.dhw_boost_forced_active,
            "saved_dhw_target_temp": coordinator.saved_dhw_target_temp,
            "last_active_cop": coordinator.last_active_cop,
            "active_listeners_count": sum(
                len(listeners) for listeners in coordinator._listeners.values()
            ),
        },
        "bus_state": bus_state,
    }

