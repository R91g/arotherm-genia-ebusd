"""Mock Home Assistant environment for running tests offline."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock

MOCKED_MODULES = [
    "voluptuous",
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.button",
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
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.issue_registry",
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


class HomeAssistantError(Exception):
    """Base error for Home Assistant."""


class SupportsResponse(str, Enum):
    """Mock SupportsResponse enum."""

    NONE = "none"
    OPTIONAL = "optional"
    ONLY = "only"


class RegistryEntryDisabler(str, Enum):
    """Mock RegistryEntryDisabler enum."""

    INTEGRATION = "integration"
    USER = "user"


sys.modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
sys.modules["homeassistant.core"].SupportsResponse = SupportsResponse
sys.modules[
    "homeassistant.helpers.entity_registry"
].RegistryEntryDisabler = RegistryEntryDisabler
sys.modules["homeassistant.core"].ServiceResponse = dict[str, Any] | None
sys.modules["homeassistant.components.diagnostics"].async_redact_data = (
    lambda data, to_redact: data
)
sys.modules["homeassistant.components.mqtt"].async_subscribe = AsyncMock(
    return_value=MagicMock()
)
sys.modules["homeassistant.components.mqtt"].async_publish = AsyncMock()


class MockSchema:
    """Mock voluptuous.Schema."""

    def __init__(self, schema: Any = None) -> None:
        self.schema = schema or {}

    def __call__(self, val: Any) -> Any:
        return val


class MockMarker:
    """Mock voluptuous.Required and voluptuous.Optional."""

    def __init__(self, schema: Any, **kwargs: Any) -> None:
        self.schema = schema


sys.modules["voluptuous"].Schema = MockSchema
sys.modules["voluptuous"].Required = MockMarker
sys.modules["voluptuous"].Optional = MockMarker


class MockEntity:
    """Mock base class for Home Assistant entities."""

    _attr_has_entity_name: bool = True
    _attr_should_poll: bool = False
    _attr_unique_id: str | None = None
    _attr_translation_key: str | None = None
    _attr_device_info: Any = None
    _attr_available: bool = True
    _attr_mode: Any = "box"

    @property
    def unique_id(self) -> str | None:
        """Mock unique_id property."""
        return self._attr_unique_id

    @property
    def device_info(self) -> Any:
        """Mock device_info property."""
        return self._attr_device_info

    @property
    def available(self) -> bool:
        """Mock available property."""
        return self._attr_available

    @property
    def mode(self) -> Any:
        """Mock mode property for number entities."""
        return self._attr_mode

    @property
    def native_min_value(self) -> float:
        """Mock native_min_value delegating to entity_description."""
        if hasattr(self, "_attr_native_min_value"):
            return self._attr_native_min_value
        if hasattr(self, "entity_description") and (
            self.entity_description.native_min_value is not None
        ):
            return self.entity_description.native_min_value
        return 0.0

    @property
    def native_max_value(self) -> float:
        """Mock native_max_value delegating to entity_description."""
        if hasattr(self, "_attr_native_max_value"):
            return self._attr_native_max_value
        if hasattr(self, "entity_description") and (
            self.entity_description.native_max_value is not None
        ):
            return self.entity_description.native_max_value
        return 100.0

    @property
    def native_step(self) -> float | None:
        """Mock native_step delegating to entity_description."""
        if hasattr(self, "_attr_native_step"):
            return self._attr_native_step
        if hasattr(self, "entity_description"):
            return self.entity_description.native_step
        return None

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
sys.modules["homeassistant.helpers"].entity_registry = sys.modules[
    "homeassistant.helpers.entity_registry"
]
sys.modules["homeassistant.helpers"].device_registry = sys.modules[
    "homeassistant.helpers.device_registry"
]
sys.modules["homeassistant.helpers"].issue_registry = sys.modules[
    "homeassistant.helpers.issue_registry"
]
sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
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
sys.modules[
    "homeassistant.components.button"
].ButtonEntityDescription = MockEntityDescription


class MockButtonEntity(MockEntity):
    """Mock Button Entity."""

    def press(self) -> None:
        """Press the button."""

    async def async_press(self) -> None:
        """Press the button asynchronously."""


sys.modules["homeassistant.components.button"].ButtonEntity = MockButtonEntity


class MockRegistryEntryDisabler:
    """Mock RegistryEntryDisabler enum."""

    INTEGRATION = "integration"
    USER = "user"


sys.modules[
    "homeassistant.helpers.entity_registry"
].RegistryEntryDisabler = MockRegistryEntryDisabler


def mock_section(schema: Any, options: dict[str, Any] | None = None) -> Any:
    """Mock data_entry_flow.section helper."""
    return schema


sys.modules["homeassistant.data_entry_flow"].section = mock_section

# Mock common string enums and constants
from datetime import UTC, datetime

sys.modules["homeassistant.util"].dt.get_default_time_zone.return_value = UTC
sys.modules["homeassistant.util.dt"].get_default_time_zone.return_value = UTC
sys.modules["homeassistant.util"].dt.as_local.side_effect = lambda dt: dt
sys.modules["homeassistant.util.dt"].as_local.side_effect = lambda dt: dt
sys.modules["homeassistant.util"].dt.utcnow.side_effect = lambda: datetime.now(UTC)
sys.modules["homeassistant.util.dt"].utcnow.side_effect = lambda: datetime.now(UTC)

sys.modules["homeassistant.const"].PERCENTAGE = "%"
sys.modules["homeassistant.const"].UnitOfTemperature = MagicMock(CELSIUS="°C")
sys.modules["homeassistant.const"].UnitOfPressure = MagicMock(BAR="bar")
sys.modules["homeassistant.const"].UnitOfPower = MagicMock(WATT="W", KILO_WATT="kW")
sys.modules["homeassistant.const"].UnitOfEnergy = MagicMock(
    WATT_HOUR="Wh", KILO_WATT_HOUR="kWh", MEGA_WATT_HOUR="MWh"
)
sys.modules["homeassistant.const"].UnitOfVolumeFlowRate = MagicMock(
    LITERS_PER_HOUR="L/h", CUBIC_METERS_PER_HOUR="m³/h"
)
sys.modules["homeassistant.const"].UnitOfTime = MagicMock(
    HOURS="h", MINUTES="min", SECONDS="s", DAYS="d"
)
sys.modules["homeassistant.const"].Platform = MagicMock(
    CLIMATE="climate",
    WATER_HEATER="water_heater",
    SENSOR="sensor",
    BINARY_SENSOR="binary_sensor",
    NUMBER="number",
    SELECT="select",
    SWITCH="switch",
    DATETIME="datetime",
    BUTTON="button",
)


class MockOptionsFlow:
    """Mock OptionsFlow base class."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def async_show_form(
        self,
        step_id: str | None = None,
        data_schema: Any = None,
        errors: dict[str, str] | None = None,
        description_placeholders: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders,
        }

    def async_create_entry(self, title: str = "", data: Any = None) -> dict[str, Any]:
        return {
            "type": "create_entry",
            "title": title,
            "data": data or {},
        }


sys.modules["homeassistant.config_entries"].OptionsFlow = MockOptionsFlow
