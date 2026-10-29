"""Sensor platform for Saunier Duval GeniaAir Max ES & MiPro Sense (Telemetry, Energy, COP, Weekly Timers)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CIRCUIT_BASS3,
    DAY_SHORT_KEYS,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
    WEEKDAYS_LIST,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity
from .sensor_descriptions import (
    SENSOR_DESCRIPTIONS,
    WEEKLY_SCHEDULE_SENSORS,
    SaunierGeniaSensorEntityDescription,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval eBUSd Sensor entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Entity Factory: Iterate over declarative entity descriptions from sensor_descriptions.py.
    # Dynamically filter entities based on the user's hardware configuration:
    # - Skip wireless room thermostat telemetry if the physical unit is not installed.
    for description in SENSOR_DESCRIPTIONS:
        if (
            description.requires_wireless_unit
            and not coordinator.has_wireless_room_unit
        ):
            continue
        entities.append(SaunierGeniaSensor(coordinator, description))

    # Weekly schedule summary entities (aggregates the 7 daily time slots into weekly timetable sensors)
    for translation_key, timer_prefix in WEEKLY_SCHEDULE_SENSORS:
        entities.append(
            SaunierGeniaWeeklyScheduleSensor(
                coordinator, translation_key, timer_prefix
            )
        )

    async_add_entities(entities)


class SaunierGeniaSensor(SaunierGeniaEntity, SensorEntity):
    """Representation of a Saunier Duval eBUSd Telemetry or Energy Sensor."""

    entity_description: SaunierGeniaSensorEntityDescription

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        description: SaunierGeniaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor entity."""
        subs = [(description.circuit, description.message)]
        if description.fallback_circuit and description.fallback_message:
            subs.append(
                (description.fallback_circuit, description.fallback_message)
            )
        if description.key == "z1_actual_room_temp_desired":
            subs.extend(
                [
                    (CIRCUIT_BASS3, "Z1OpMode"),
                    (CIRCUIT_BASS3, "Z1DayTemp"),
                ]
            )

        c = description.circuit.lower()
        m = description.message.lower()
        f = description.field.lower()
        unique_id_suffix = f"{c}_{m}_{f}"

        super().__init__(
            coordinator=coordinator,
            device_key=description.device_key,
            translation_key=description.translation_key or description.key,
            subscriptions=subs,
            unique_id_suffix=unique_id_suffix,
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        desc = self.entity_description
        if desc.value_fn is not None:
            return desc.value_fn(self.coordinator)

        if desc.device_class == SensorDeviceClass.ENUM:
            val_str = self.coordinator.get_str(
                desc.circuit, desc.message, desc.field
            )
            if val_str is None:
                return None
            val_lower = val_str.lower()
            if desc.options and val_lower in desc.options:
                return val_lower
            return None

        if desc.is_integer:
            val_int = self.coordinator.get_int(
                desc.circuit, desc.message, desc.field
            )
            if (
                val_int is None
                and desc.fallback_circuit
                and desc.fallback_message
            ):
                val_int = self.coordinator.get_int(
                    desc.fallback_circuit,
                    desc.fallback_message,
                    desc.fallback_field or "value",
                )
            return val_int

        val_float = self.coordinator.get_float(
            desc.circuit, desc.message, desc.field
        )
        if (
            val_float is None
            and desc.fallback_circuit
            and desc.fallback_message
        ):
            val_float = self.coordinator.get_float(
                desc.fallback_circuit,
                desc.fallback_message,
                desc.fallback_field or "value",
            )
        if val_float is not None:
            return val_float

        return self.coordinator.get_field(
            desc.circuit, desc.message, desc.field
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return optional extra state attributes."""
        if self.entity_description.attr_fn is not None:
            return self.entity_description.attr_fn(self.coordinator)
        return None


class SaunierGeniaWeeklyScheduleSensor(SaunierGeniaEntity, SensorEntity):
    """Summary sensor for b5 55 Weekly Schedules (Heating Z1, DHW, Cooling, Circulation)."""

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        translation_key: str,
        timer_prefix: str,
    ) -> None:
        """Initialize the weekly schedule summary sensor."""
        subs: list[tuple[str, str]] = [
            (CIRCUIT_BASS3, f"{timer_prefix}_Slots")
        ]
        for day in WEEKDAYS_LIST:
            subs.append((CIRCUIT_BASS3, f"{timer_prefix}_{day}"))
            subs.append((CIRCUIT_BASS3, f"{timer_prefix}_{day}_Slot2"))
            subs.append((CIRCUIT_BASS3, f"{timer_prefix}_{day}_Slot3"))

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key=translation_key,
            subscriptions=subs,
            unique_id_suffix=f"bass3_{timer_prefix.lower()}_weekly_schedule",
        )
        self._timer_prefix = timer_prefix

    def _format_slot(self, day: str, slot_num: int) -> str | None:
        """Format a single slot (1, 2, or 3) for a given day as 'HH:MM - HH:MM'."""
        suffix = "" if slot_num == 1 else f"_Slot{slot_num}"
        msg = self.coordinator.get_message(
            CIRCUIT_BASS3, f"{self._timer_prefix}_{day}{suffix}"
        )
        if not msg:
            return None

        fh = msg.get("from_hour")
        fm = msg.get("from_min")
        th = msg.get("to_hour")
        tm = msg.get("to_min")
        if None in (fh, fm, th, tm):
            return None

        try:
            fh_i, fm_i, th_i, tm_i = int(fh), int(fm), int(th), int(tm)
        except (ValueError, TypeError):
            return None

        if (fh_i == 0 and fm_i == 0 and th_i == 0 and tm_i == 0) or (
            fh_i >= 24 or th_i > 24
        ):
            return None

        slot_str = f"{fh_i:02d}:{fm_i:02d} - {th_i:02d}:{tm_i:02d}"
        cooling_temp = msg.get("cooling_temp", msg.get("temp"))
        if cooling_temp is not None:
            try:
                slot_str = f"{slot_str} ({float(cooling_temp):.1f} °C)"
            except (ValueError, TypeError):
                pass
        return slot_str

    def _get_day_slots(self, day: str) -> list[str]:
        """Return list of formatted active slots for the given day."""
        slots_msg = (
            self.coordinator.get_message(
                CIRCUIT_BASS3, f"{self._timer_prefix}_Slots"
            )
            or {}
        )
        short_key = DAY_SHORT_KEYS[day]
        active_count = slots_msg.get(short_key)
        max_slots = 3
        if isinstance(active_count, (int, float)) and 0 <= int(active_count) <= 3:
            max_slots = int(active_count) if int(active_count) > 0 else 1

        formatted: list[str] = []
        for s_idx in range(1, max_slots + 1):
            s_val = self._format_slot(day, s_idx)
            if s_val:
                formatted.append(s_val)
        return formatted

    @property
    def native_value(self) -> str | None:
        """Return active schedule window(s) for today."""
        now_weekday = dt_util.now().weekday()  # 0 = Monday .. 6 = Sunday
        today_name = WEEKDAYS_LIST[now_weekday]
        today_slots = self._get_day_slots(today_name)
        if today_slots:
            # Strip temperature suffix from primary state string to keep it concise (e.g. "06:00 - 22:00")
            clean_slots = [s.split(" (")[0] for s in today_slots]
            return " / ".join(clean_slots)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return structured weekly schedule from Monday to Sunday with Slot 1..3 and active slot counts."""
        slots_msg = (
            self.coordinator.get_message(
                CIRCUIT_BASS3, f"{self._timer_prefix}_Slots"
            )
            or {}
        )
        schedule_dict: dict[str, dict[str, Any]] = {}
        for day in WEEKDAYS_LIST:
            short_key = DAY_SHORT_KEYS[day]
            schedule_dict[day] = {
                "active_slots": slots_msg.get(short_key, 1),
                "Slot 1": self._format_slot(day, 1),
                "Slot 2": self._format_slot(day, 2),
                "Slot 3": self._format_slot(day, 3),
            }
        return {
            "timer_prefix": self._timer_prefix,
            "weekly_schedule": schedule_dict,
        }
