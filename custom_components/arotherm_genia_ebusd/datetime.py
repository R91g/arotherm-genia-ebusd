"""DateTime platform for Saunier Duval MiPro Sense (Holiday / Away Mode & Manual Cooling Windows)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CIRCUIT_BASS3, DEVICE_CLIMATE_CONTROLLER, DOMAIN
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saunier Duval MiPro Sense DateTime entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[DateTimeEntity] = [
        SaunierGeniaHolidayStartDateTime(coordinator),
        SaunierGeniaHolidayEndDateTime(coordinator),
        SaunierGeniaCoolingStartDateTime(coordinator),
        SaunierGeniaCoolingEndDateTime(coordinator),
    ]
    async_add_entities(entities)


class SaunierGeniaHolidayStartDateTime(SaunierGeniaEntity, DateTimeEntity):
    """DateTime entity for Holiday / Away Mode Start Date and Time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Holiday Start DateTime entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="holiday_start_datetime",
            subscriptions=[
                (CIRCUIT_BASS3, "HolidayStartDate"),
                (CIRCUIT_BASS3, "HolidayStartTime"),
                (CIRCUIT_BASS3, "Z1Status"),
            ],
            unique_id_suffix="datetime_bass3_holiday_start",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the current holiday start datetime or preselected buffer."""
        date_msg = self.coordinator.get_message(CIRCUIT_BASS3, "HolidayStartDate")
        time_msg = self.coordinator.get_message(CIRCUIT_BASS3, "HolidayStartTime")

        if date_msg:
            day = date_msg.get("day")
            month = date_msg.get("month")
            year = date_msg.get("year")
            if (
                isinstance(day, int)
                and isinstance(month, int)
                and isinstance(year, int)
                and year != 15  # 2015 is reset sentinel
            ):
                h = time_msg.get("hours", 0) if time_msg else 0
                m = time_msg.get("minutes", 0) if time_msg else 0
                s = time_msg.get("seconds", 0) if time_msg else 0
                try:
                    tz = dt_util.get_default_time_zone()
                    return datetime(
                        2000 + year, month, day, int(h), int(m), int(s), tzinfo=tz
                    )
                except (ValueError, TypeError):
                    pass

        return self.coordinator.preselected_holiday_start_datetime

    async def async_set_value(self, value: datetime) -> None:
        """Set new holiday start date and time."""
        loc_val = dt_util.as_local(value) if value.tzinfo else value
        self.coordinator.preselected_holiday_start_datetime = loc_val

        date_str = f"{loc_val.day:02d};{loc_val.month:02d};{loc_val.year % 100:02d}"
        time_str = f"{loc_val.hour:02d};{loc_val.minute:02d};{loc_val.second:02d}"

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartDate", date_str
        )
        await asyncio.sleep(0.4)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HolidayStartTime", time_str
        )


class SaunierGeniaHolidayEndDateTime(SaunierGeniaEntity, DateTimeEntity):
    """DateTime entity for Holiday / Away Mode End Date and Time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-arrow-left"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Holiday End DateTime entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="holiday_end_datetime",
            subscriptions=[
                (CIRCUIT_BASS3, "HolidayEndDate"),
                (CIRCUIT_BASS3, "HolidayEndTime"),
                (CIRCUIT_BASS3, "Z1Status"),
            ],
            unique_id_suffix="datetime_bass3_holiday_end",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the current holiday end datetime or preselected buffer."""
        date_msg = self.coordinator.get_message(CIRCUIT_BASS3, "HolidayEndDate")
        time_msg = self.coordinator.get_message(CIRCUIT_BASS3, "HolidayEndTime")

        if date_msg:
            day = date_msg.get("day")
            month = date_msg.get("month")
            year = date_msg.get("year")
            if (
                isinstance(day, int)
                and isinstance(month, int)
                and isinstance(year, int)
                and year != 15  # 2015 is reset sentinel
            ):
                h = time_msg.get("hours", 23) if time_msg else 23
                m = time_msg.get("minutes", 59) if time_msg else 59
                s = time_msg.get("seconds", 59) if time_msg else 59
                try:
                    tz = dt_util.get_default_time_zone()
                    return datetime(
                        2000 + year, month, day, int(h), int(m), int(s), tzinfo=tz
                    )
                except (ValueError, TypeError):
                    pass

        return self.coordinator.preselected_holiday_end_datetime

    async def async_set_value(self, value: datetime) -> None:
        """Set new holiday end date and time."""
        loc_val = dt_util.as_local(value) if value.tzinfo else value
        self.coordinator.preselected_holiday_end_datetime = loc_val

        date_str = f"{loc_val.day:02d};{loc_val.month:02d};{loc_val.year % 100:02d}"
        time_str = f"{loc_val.hour:02d};{loc_val.minute:02d};{loc_val.second:02d}"

        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndDate", date_str
        )
        await asyncio.sleep(0.4)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "HolidayEndTime", time_str
        )


class SaunierGeniaCoolingStartDateTime(SaunierGeniaEntity, DateTimeEntity):
    """DateTime entity for Cooling Season Start Date (Lock 1)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake-check"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Cooling Start DateTime entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="cooling_start_datetime",
            subscriptions=[
                (CIRCUIT_BASS3, "CoolingStartDate"),
            ],
            unique_id_suffix="datetime_bass3_cooling_start",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the cooling start date (defaulting to 2019-01-01 when closed)."""
        date_msg = self.coordinator.get_message(CIRCUIT_BASS3, "CoolingStartDate")
        if date_msg:
            day = date_msg.get("day")
            month = date_msg.get("month")
            year = date_msg.get("year")
            if (
                isinstance(day, int)
                and isinstance(month, int)
                and isinstance(year, int)
            ):
                try:
                    tz = dt_util.get_default_time_zone()
                    return datetime(2000 + year, month, day, 0, 0, 0, tzinfo=tz)
                except (ValueError, TypeError):
                    pass

        return None

    async def async_set_value(self, value: datetime) -> None:
        """Set new cooling season start date."""
        loc_val = dt_util.as_local(value) if value.tzinfo else value
        date_str = f"{loc_val.day:02d};{loc_val.month:02d};{loc_val.year % 100:02d}"
        self.coordinator.set_custom_cooling_start_date(date_str)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingStartDate", date_str
        )


class SaunierGeniaCoolingEndDateTime(SaunierGeniaEntity, DateTimeEntity):
    """DateTime entity for Cooling Season End Date (Lock 1)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake-check"

    def __init__(self, coordinator: SaunierGeniaCoordinator) -> None:
        """Initialize the Cooling End DateTime entity."""
        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key="cooling_end_datetime",
            subscriptions=[
                (CIRCUIT_BASS3, "CoolingEndDate"),
            ],
            unique_id_suffix="datetime_bass3_cooling_end",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the cooling end date (2019 when closed, 2099 when indefinite)."""
        date_msg = self.coordinator.get_message(CIRCUIT_BASS3, "CoolingEndDate")
        if date_msg:
            day = date_msg.get("day")
            month = date_msg.get("month")
            year = date_msg.get("year")
            if (
                isinstance(day, int)
                and isinstance(month, int)
                and isinstance(year, int)
            ):
                try:
                    tz = dt_util.get_default_time_zone()
                    return datetime(2000 + year, month, day, 0, 0, 0, tzinfo=tz)
                except (ValueError, TypeError):
                    pass

        return None

    async def async_set_value(self, value: datetime) -> None:
        """Set new cooling season end date."""
        loc_val = dt_util.as_local(value) if value.tzinfo else value
        date_str = f"{loc_val.day:02d};{loc_val.month:02d};{loc_val.year % 100:02d}"
        self.coordinator.set_custom_cooling_end_date(date_str)
        await self.coordinator.async_write_parameter(
            CIRCUIT_BASS3, "CoolingEndDate", date_str
        )
