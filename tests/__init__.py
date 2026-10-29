"""Unit test suite for arotherm_genia_ebusd integration with mock Home Assistant modules."""

import sys
from unittest.mock import MagicMock

# Mock homeassistant and voluptuous packages if not installed in the current Python environment
for mod_name in [
    "voluptuous",
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.climate",
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
]:
    if mod_name not in sys.modules:
        mock = MagicMock()
        # Provide common decorators that return the function unchanged
        mock.callback = lambda fn: fn
        sys.modules[mod_name] = mock
