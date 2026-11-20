"""Calendar platform for Saunier Duval / Vaillant eBUS weekly schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CIRCUIT_BASS3,
    CONF_ENABLE_SCHEDULE_CALENDARS,
    DAY_SHORT_KEYS,
    DEFAULT_ENABLE_SCHEDULE_CALENDARS,
    DEVICE_CLIMATE_CONTROLLER,
    DOMAIN,
    WEEKDAYS_LIST,
)
from .coordinator import SaunierGeniaCoordinator
from .entity import SaunierGeniaEntity


@dataclass(frozen=True, kw_only=True)
class ScheduleCalendarSpec:
    """Declarative specification for a read-only weekly schedule calendar."""

    translation_key: str
    timer_prefix: str
    default_summary: str
    enabled_default: bool = True


SCHEDULE_CALENDARS: tuple[ScheduleCalendarSpec, ...] = (
    ScheduleCalendarSpec(
        translation_key="z1_schedule_calendar",
        timer_prefix="Z1Timer",
        default_summary="Zone 1 Heating",
        enabled_default=True,
    ),
    ScheduleCalendarSpec(
        translation_key="hwc_schedule_calendar",
        timer_prefix="HwcTimer",
        default_summary="Domestic Hot Water (DHW)",
        enabled_default=True,
    ),
    ScheduleCalendarSpec(
        translation_key="cooling_schedule_calendar",
        timer_prefix="CoolingTimer",
        default_summary="Zone 1 Cooling",
        enabled_default=True,
    ),
    ScheduleCalendarSpec(
        translation_key="circulation_schedule_calendar",
        timer_prefix="CirculationTimer",
        default_summary="DHW Circulation",
        enabled_default=False,
    ),
    ScheduleCalendarSpec(
        translation_key="silent_mode_schedule_calendar",
        timer_prefix="SilentTimer",
        default_summary="Silent Mode",
        enabled_default=False,
    ),
)

DEFAULT_ENABLED_CALENDAR_SUFFIXES: tuple[str, ...] = tuple(
    f"_calendar_{spec.timer_prefix.lower()}"
    for spec in SCHEDULE_CALENDARS
    if spec.enabled_default
)
ALL_CALENDAR_SUFFIXES: tuple[str, ...] = tuple(
    f"_calendar_{spec.timer_prefix.lower()}" for spec in SCHEDULE_CALENDARS
)


def _parse_day_slot_count(
    slots_msg: dict[str, Any], day: str, *, default: int = 1
) -> int:
    """Parse active slot count (0..3) for a weekday, ignoring bools and invalid values."""
    short_key = DAY_SHORT_KEYS[day]
    raw_count = slots_msg.get(short_key)
    if raw_count is None or isinstance(raw_count, bool):
        return default
    try:
        parsed = int(float(raw_count)) if isinstance(raw_count, str) else int(raw_count)
    except (ValueError, TypeError):
        return default
    return parsed if 0 <= parsed <= 3 else default


def _parse_day_slot_windows(
    coordinator: SaunierGeniaCoordinator,
    timer_prefix: str,
    day: str,
) -> list[tuple[int, int, int, int, float | None]]:
    """Return active (from_h, from_m, to_h, to_m, temp) tuples for a weekday."""
    slots_msg = coordinator.get_message(CIRCUIT_BASS3, f"{timer_prefix}_Slots") or {}
    max_slots = _parse_day_slot_count(slots_msg, day)
    windows: list[tuple[int, int, int, int, float | None]] = []

    for slot_num in range(1, max_slots + 1):
        suffix = "" if slot_num == 1 else f"_Slot{slot_num}"
        msg = coordinator.get_message(CIRCUIT_BASS3, f"{timer_prefix}_{day}{suffix}")
        if not msg:
            continue

        fh = msg.get("from_hour")
        fm = msg.get("from_min")
        th = msg.get("to_hour")
        tm = msg.get("to_min")
        if fh is None or fm is None or th is None or tm is None:
            continue

        try:
            fh_i, fm_i, th_i, tm_i = int(fh), int(fm), int(th), int(tm)
        except (ValueError, TypeError):
            continue

        if (
            (fh_i == 0 and fm_i == 0 and th_i == 0 and tm_i == 0)
            or not (0 <= fh_i < 24 and 0 <= fm_i < 60)
            or not (0 <= th_i <= 24 and 0 <= tm_i < 60)
            or (th_i == 24 and tm_i != 0)
        ):
            continue

        start_total = fh_i * 60 + fm_i
        end_total = th_i * 60 + tm_i
        if end_total <= start_total:
            continue

        temp_val: float | None = None
        raw_temp = msg.get("cooling_temp", msg.get("temp"))
        if raw_temp is not None:
            try:
                temp_val = float(raw_temp)
            except (ValueError, TypeError):
                temp_val = None

        windows.append((fh_i, fm_i, th_i, tm_i, temp_val))

    return windows


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up read-only weekly schedule calendar entities."""
    coordinator: SaunierGeniaCoordinator = hass.data[DOMAIN][entry.entry_id]
    calendars_enabled = bool(
        entry.options.get(
            CONF_ENABLE_SCHEDULE_CALENDARS, DEFAULT_ENABLE_SCHEDULE_CALENDARS
        )
    )
    async_add_entities(
        SaunierGeniaScheduleCalendar(
            coordinator,
            spec,
            enabled_default=spec.enabled_default and calendars_enabled,
        )
        for spec in SCHEDULE_CALENDARS
    )


class SaunierGeniaScheduleCalendar(SaunierGeniaEntity, CalendarEntity):
    """Read-only calendar projecting a BASS3 b5 55 weekly schedule onto HA Calendar."""

    def __init__(
        self,
        coordinator: SaunierGeniaCoordinator,
        spec: ScheduleCalendarSpec,
        *,
        enabled_default: bool,
    ) -> None:
        """Initialize the weekly schedule calendar entity."""
        subs: list[tuple[str, str]] = [(CIRCUIT_BASS3, f"{spec.timer_prefix}_Slots")]
        for day in WEEKDAYS_LIST:
            subs.append((CIRCUIT_BASS3, f"{spec.timer_prefix}_{day}"))
            subs.append((CIRCUIT_BASS3, f"{spec.timer_prefix}_{day}_Slot2"))
            subs.append((CIRCUIT_BASS3, f"{spec.timer_prefix}_{day}_Slot3"))

        super().__init__(
            coordinator=coordinator,
            device_key=DEVICE_CLIMATE_CONTROLLER,
            translation_key=spec.translation_key,
            subscriptions=subs,
            unique_id_suffix=f"calendar_{spec.timer_prefix.lower()}",
        )
        self._spec = spec
        self._attr_entity_registry_enabled_default = enabled_default

    def _build_events_for_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Project recurring weekly slots onto [start_date, end_date)."""
        if end_date <= start_date:
            return []

        tz = dt_util.get_default_time_zone()
        start_local = dt_util.as_local(start_date)
        end_local = dt_util.as_local(end_date)

        base_summary = str(getattr(self, "name", None) or self._spec.default_summary)
        events: list[CalendarEvent] = []

        cursor_date = start_local.date() - timedelta(days=1)
        last_date = end_local.date() + timedelta(days=1)

        while cursor_date <= last_date:
            day_name = WEEKDAYS_LIST[cursor_date.weekday()]
            windows = _parse_day_slot_windows(
                self.coordinator, self._spec.timer_prefix, day_name
            )
            for fh_i, fm_i, th_i, tm_i, temp_val in windows:
                ev_start = datetime(
                    cursor_date.year,
                    cursor_date.month,
                    cursor_date.day,
                    fh_i,
                    fm_i,
                    tzinfo=tz,
                )
                if th_i == 24:
                    next_day = cursor_date + timedelta(days=1)
                    ev_end = datetime(
                        next_day.year,
                        next_day.month,
                        next_day.day,
                        0,
                        0,
                        tzinfo=tz,
                    )
                else:
                    ev_end = datetime(
                        cursor_date.year,
                        cursor_date.month,
                        cursor_date.day,
                        th_i,
                        tm_i,
                        tzinfo=tz,
                    )

                if ev_end > start_local and ev_start < end_local:
                    summary = (
                        f"{base_summary} ({temp_val:.1f} °C)"
                        if temp_val is not None
                        else base_summary
                    )
                    events.append(
                        CalendarEvent(
                            start=ev_start,
                            end=ev_end,
                            summary=summary,
                        )
                    )

            cursor_date += timedelta(days=1)

        events.sort(key=lambda ev: (ev.start, ev.end))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """Return the currently active slot or the next upcoming slot within 7 days."""
        now = dt_util.now()
        upcoming = self._build_events_for_range(now, now + timedelta(days=8))
        for ev in upcoming:
            if isinstance(ev.end, datetime) and ev.end > now:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within the requested datetime window."""
        return self._build_events_for_range(start_date, end_date)
