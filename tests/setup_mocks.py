"""Mock Home Assistant environment for running tests offline."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

MOCKED_MODULES = [
    "voluptuous",
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.climate",
    "homeassistant.components.datetime",
    "homeassistant.components.diagnostics",
    "homeassistant.components.mqtt",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.water_heater",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.selector",
    "homeassistant.util",
    "homeassistant.util.dt",
]

for mod_name in MOCKED_MODULES:
    if mod_name not in sys.modules:
        mock = MagicMock()
        mock.callback = lambda fn: fn
        sys.modules[mod_name] = mock


class MockEntity:
    """Mock base class for Home Assistant entities."""

    _attr_has_entity_name: bool = True
    _attr_should_poll: bool = False
    _attr_unique_id: str | None = None
    _attr_translation_key: str | None = None
    _attr_device_info: Any = None

    async def async_added_to_hass(self) -> None:
        """Mock async_added_to_hass."""

    def async_on_remove(self, func: Any) -> None:
        """Mock async_on_remove."""

    def async_write_ha_state(self) -> None:
        """Mock async_write_ha_state."""


class MockRestoreEntity:
    """Mock base class for restore state."""

    async def async_get_last_state(self) -> Any:
        return None


sys.modules["homeassistant.helpers.entity"].Entity = MockEntity
sys.modules["homeassistant.components.sensor"].SensorEntity = MockEntity
sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = MockEntity
sys.modules["homeassistant.components.number"].NumberEntity = MockEntity
sys.modules["homeassistant.components.select"].SelectEntity = MockEntity
sys.modules["homeassistant.components.switch"].SwitchEntity = MockEntity
sys.modules["homeassistant.components.climate"].ClimateEntity = MockEntity
sys.modules["homeassistant.components.water_heater"].WaterHeaterEntity = MockEntity
sys.modules["homeassistant.components.datetime"].DateTimeEntity = MockEntity
sys.modules["homeassistant.helpers.restore_state"].RestoreEntity = MockRestoreEntity


# Base entity description dataclass compatible with Python 3.10+ dataclass inheritance
@dataclass(frozen=True, kw_only=True)
class MockEntityDescription:
    """Mock base class for entity descriptions."""

    key: str = ""
    translation_key: str | None = None
    name: str | None = None
    icon: str | None = None
    device_class: Any = None
    state_class: Any = None
    entity_category: Any = None
    native_unit_of_measurement: str | None = None
    suggested_display_precision: int | None = None
    entity_registry_enabled_default: bool = True
    options: list[str] | None = None
    native_min_value: float | None = None
    native_max_value: float | None = None
    native_step: float | None = None
    mode: str = "box"


sys.modules[
    "homeassistant.components.sensor"
].SensorEntityDescription = MockEntityDescription
sys.modules[
    "homeassistant.components.binary_sensor"
].BinarySensorEntityDescription = MockEntityDescription
sys.modules[
    "homeassistant.components.number"
].NumberEntityDescription = MockEntityDescription
sys.modules[
    "homeassistant.components.select"
].SelectEntityDescription = MockEntityDescription
sys.modules[
    "homeassistant.components.switch"
].SwitchEntityDescription = MockEntityDescription
sys.modules[
    "homeassistant.components.datetime"
].DateTimeEntityDescription = MockEntityDescription

# Mock common string enums and constants
from datetime import UTC

sys.modules["homeassistant.util"].dt.get_default_time_zone.return_value = UTC
sys.modules["homeassistant.util.dt"].get_default_time_zone.return_value = UTC
sys.modules["homeassistant.util"].dt.as_local.side_effect = lambda dt: dt
sys.modules["homeassistant.util.dt"].as_local.side_effect = lambda dt: dt

sys.modules["homeassistant.const"].PERCENTAGE = "%"
sys.modules["homeassistant.const"].UnitOfTemperature = MagicMock(CELSIUS="°C")
sys.modules["homeassistant.const"].UnitOfPressure = MagicMock(BAR="bar")
sys.modules["homeassistant.const"].UnitOfPower = MagicMock(WATT="W", KILO_WATT="kW")
sys.modules["homeassistant.const"].UnitOfEnergy = MagicMock(
    KILO_WATT_HOUR="kWh", MEGA_WATT_HOUR="MWh"
)
sys.modules["homeassistant.const"].UnitOfVolumeFlowRate = MagicMock(
    CUBIC_METERS_PER_HOUR="m³/h"
)
sys.modules["homeassistant.const"].UnitOfTime = MagicMock(
    HOURS="h", MINUTES="min", SECONDS="s", DAYS="d"
)
