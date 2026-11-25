"""Diagnostics support for Saunier Duval GeniaAir Max ES & MiPro Sense (eBUSd)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SaunierGeniaCoordinator

TO_REDACT: list[str] = [
    "serial_number",
    "serialnumber",
    "serial",
    "counter",
    "mac",
    "ebusd_tcp_host",
    "host",
    "ip",
    "ip_address",
    "password",
    "token",
    "secret",
]

_REDACT_PATTERN_SUBSTRINGS: tuple[str, ...] = (
    "serial",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "counter",
)
_REDACT_PATTERN_EXACT: frozenset[str] = frozenset(
    {
        "mac",
        "mac_address",
        "macaddress",
        "host",
        "ebusd_tcp_host",
        "ip",
        "ip_address",
        "username",
        "user",
    }
)


def _redact_sensitive_patterns(data: Any) -> Any:
    """Recursively redact sensitive keys matched by name or substring pattern."""
    if isinstance(data, dict):
        redacted: dict[Any, Any] = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if key_lower in _REDACT_PATTERN_EXACT or any(
                pat in key_lower for pat in _REDACT_PATTERN_SUBSTRINGS
            ):
                redacted[key] = "**REDACTED**"
            else:
                redacted[key] = _redact_sensitive_patterns(value)
        return redacted
    if isinstance(data, list):
        return [_redact_sensitive_patterns(item) for item in data]
    return data


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
            "data": _redact_sensitive_patterns(
                async_redact_data(dict(entry.data), TO_REDACT)
            ),
            "options": _redact_sensitive_patterns(
                async_redact_data(dict(entry.options), TO_REDACT)
            ),
        },
        "coordinator": {
            "mqtt_prefix": coordinator.mqtt_prefix,
            "outdoor_model": coordinator.outdoor_model,
            "indoor_model": coordinator.indoor_model,
            "has_wireless_room_unit": coordinator.has_wireless_room_unit,
            "has_migo_link": coordinator.has_migo_link,
            "force_dhw_boost": coordinator.force_dhw_boost,
            "dhw_boost_forced_active": coordinator.dhw_boost_forced_active,
            "active_controller_circuit": coordinator.active_controller_circuit,
            "active_outdoor_circuit": coordinator.active_outdoor_circuit,
            "saved_dhw_target_temp": coordinator.saved_dhw_target_temp,
            "last_active_cop": coordinator.last_active_cop,
            "active_repair_issues": sorted(coordinator._active_repair_issues),
            "ebusd_info": coordinator.sanitize_ebusd_info_lines(
                coordinator._last_ebusd_tcp_info_lines, anonymize=True
            ),
            "active_listeners_count": sum(
                len(listeners) for listeners in coordinator._listeners.values()
            ),
        },
        "bus_state": _redact_sensitive_patterns(
            async_redact_data(bus_state, TO_REDACT)
        ),
    }
